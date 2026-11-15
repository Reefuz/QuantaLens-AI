"""Validation and rewriting of model-generated SQL.

The read-only database role can read every user's tables in schema `qdata`, so *this module* is what
confines a query to one dataset. It is deliberately strict:

* exactly one statement, and it must be a SELECT (optionally with CTEs, or a UNION of SELECTs)
* the only relation it may read is the virtual table `data` (or CTEs defined in the same query)
* functions are allowlisted, because functions like query_to_xml() execute arbitrary SQL text
* no INTO, no locking clauses, no data-modifying CTEs, no catalog or `reg*` casts
* a row limit is always enforced

The statement that is executed is regenerated from the validated syntax tree, so comments and
parser tricks in the original text cannot reach the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

VIRTUAL_TABLE = "data"
MAX_ROWS = 1000
MAX_SQL_CHARS = 8000
MAX_NODES = 3000
SCHEMA = "qdata"

# Typed sqlglot functions (SUM, AVG, COUNT, COALESCE ...) are all standard SQL and safe.
# Anything sqlglot does not know arrives as exp.Anonymous and must be on this list.
ALLOWED_FUNCTIONS = frozenset(
    """
    abs ceil ceiling floor round trunc sqrt cbrt power exp ln log log10 sign mod div greatest least
    coalesce nullif lower upper trim ltrim rtrim btrim length char_length character_length octet_length
    substr substring replace split_part concat concat_ws left right lpad rpad initcap repeat reverse
    regexp_replace regexp_matches regexp_count position strpos starts_with translate to_char to_date
    to_number to_timestamp date_trunc date_part extract age make_date make_timestamp now current_date
    current_timestamp justify_days isfinite
    percentile_cont percentile_disc mode corr covar_pop covar_samp regr_slope regr_intercept regr_r2
    regr_count regr_avgx regr_avgy stddev stddev_pop stddev_samp variance var_pop var_samp
    string_agg array_agg bool_and bool_or every
    row_number rank dense_rank percent_rank cume_dist ntile lag lead first_value last_value nth_value
    width_bucket cardinality array_length unnest generate_subscripts
    """.split()
)

_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    getattr(exp, name)
    for name in (
        "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "AlterTable", "Command", "Copy",
        "Into", "Lock", "Set", "Use", "Commit", "Rollback", "Transaction", "TruncateTable", "Grant", "Revoke",
        "Analyze", "Pragma", "LoadData", "Kill", "Declare", "Execute", "Describe", "Show", "Refresh", "Comment",
        "Attach", "Detach", "Cache", "Uncache", "Return",
        # Session and server details are not analytical data.
        "CurrentUser", "SessionUser", "CurrentSchema", "CurrentSchemas", "CurrentCatalog", "CurrentDatabase", "Version", "CurrentVersion",
    )
    if hasattr(exp, name)
)

_ALLOWED_CTE_BODIES = (exp.Select, exp.Union, exp.Subquery, exp.Paren)
_CATALOG_SCHEMAS = {"pg_catalog", "information_schema", "pg_temp", "pg_toast"}


class SqlRejected(ValueError):
    """The query is not permitted. The message is safe to show to the user and the model."""


@dataclass
class GuardedSql:
    original: str  # exactly what the model wrote
    executed: str  # exactly what is sent to the database
    tables: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _reject(msg: str) -> SqlRejected:
    return SqlRejected(msg)


def _parse_single(sql: str) -> exp.Expression:
    if not sql or not sql.strip():
        raise _reject("The query is empty.")
    if len(sql) > MAX_SQL_CHARS:
        raise _reject(f"The query is too long (limit {MAX_SQL_CHARS} characters).")
    try:
        statements = [s for s in sqlglot.parse(sql, dialect="postgres") if s is not None]
    except (ParseError, TokenError) as exc:
        raise _reject(f"The query could not be parsed as PostgreSQL: {str(exc).splitlines()[0][:160]}") from exc
    if len(statements) != 1:
        raise _reject("Only a single SELECT statement is allowed.")
    return statements[0]


def _check_structure(tree: exp.Expression) -> None:
    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery)):
        raise _reject("Only SELECT queries are allowed. Writes, DDL and administrative commands are blocked.")
    nodes = 0
    for node in tree.walk():
        nodes += 1
        if nodes > MAX_NODES:
            raise _reject("The query is too complex.")
        if isinstance(node, _FORBIDDEN_NODES):
            raise _reject(f"{type(node).__name__.upper()} is not allowed. Only read-only SELECT queries can run.")
        if isinstance(node, exp.Select) and (node.args.get("into") or node.args.get("locks")):
            raise _reject("SELECT ... INTO and locking clauses are not allowed.")
        if isinstance(node, exp.DataType):
            kind = node.sql(dialect="postgres").lower()
            if kind.startswith("reg") or kind == "oid":
                raise _reject("Casting to system object types is not allowed.")
        if isinstance(node, exp.Anonymous):
            name = str(node.name).lower()
            if name not in ALLOWED_FUNCTIONS:
                raise _reject(f"The function {name}() is not allowed.")
        if isinstance(node, exp.Table) and not isinstance(node.this, exp.Identifier):
            raise _reject("Table-valued functions are not allowed. Query the table `data`.")
        if isinstance(node, exp.Pseudocolumn):
            raise _reject("System columns are not allowed.")
    for cte in tree.find_all(exp.CTE):
        body = cte.this
        if not isinstance(body, _ALLOWED_CTE_BODIES):
            raise _reject("Common table expressions must contain SELECT queries only.")


def _cte_names(tree: exp.Expression) -> set[str]:
    return {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}


def _resolve_tables(tree: exp.Expression, physical: str) -> None:
    """Allow only `data`, this dataset's own physical table, and CTEs. Rewrite `data` to the physical table."""
    ctes = _cte_names(tree)
    if VIRTUAL_TABLE in ctes:
        raise _reject("`data` is reserved for the dataset. Use a different name for the CTE.")
    for table in list(tree.find_all(exp.Table)):
        name = table.name.lower()
        schema = (table.db or "").lower()
        catalog = (table.catalog or "").lower()
        if schema in _CATALOG_SCHEMAS or name.startswith("pg_") or catalog:
            raise _reject("System catalogs are not accessible.")
        if not schema and name in ctes:
            continue
        is_virtual = not schema and name == VIRTUAL_TABLE
        is_own_physical = schema == SCHEMA and name == physical.lower()
        if not (is_virtual or is_own_physical):
            raise _reject(f"The table `{table.sql(dialect='postgres')}` is not available. Query the table `data`.")
        # Keep the model's alias, or alias to `data` so that `data.column` references still resolve.
        replacement = exp.Table(this=exp.to_identifier(physical), db=exp.to_identifier(SCHEMA))
        replacement.set("alias", exp.TableAlias(this=exp.to_identifier(table.alias or VIRTUAL_TABLE)))
        table.replace(replacement)


def _enforce_limit(tree: exp.Expression, notes: list[str]) -> exp.Expression:
    """Always fetch at most MAX_ROWS + 1 rows (the extra row reveals truncation)."""
    cap = MAX_ROWS + 1
    root = tree.this if isinstance(tree, exp.Subquery) else tree
    if isinstance(root, exp.Select):
        limit = root.args.get("limit")
        current = None
        if limit is not None and isinstance(limit.expression, exp.Literal) and limit.expression.is_int:
            current = int(limit.expression.this)
        if limit is None:
            root.set("limit", exp.Limit(expression=exp.Literal.number(cap)))
            notes.append(f"A row limit of {MAX_ROWS:,} was applied.")
        elif current is None or current > cap:
            root.set("limit", exp.Limit(expression=exp.Literal.number(cap)))
            notes.append(f"The row limit was lowered to {MAX_ROWS:,}.")
        return tree
    wrapped = exp.select("*").from_(tree.subquery("_q")).limit(cap)
    notes.append(f"A row limit of {MAX_ROWS:,} was applied.")
    return wrapped


def guard_sql(sql: str, physical_table: str, dataset_columns: list[str] | None = None) -> GuardedSql:
    """Validate `sql` and return the statement to execute. Raises SqlRejected."""
    tree = _parse_single(sql.strip().rstrip(";"))
    for node in tree.walk():
        node.comments = None  # comments are never executed or shown as part of the query
    _check_structure(tree)
    notes: list[str] = []
    referenced_tables = sorted({t.name for t in tree.find_all(exp.Table) if t.name.lower() not in _cte_names(tree)})
    referenced_columns = sorted({c.name for c in tree.find_all(exp.Column)})
    _resolve_tables(tree, physical_table)
    tree = _enforce_limit(tree, notes)
    executed = tree.sql(dialect="postgres")
    if dataset_columns is not None:
        known = {c.lower() for c in dataset_columns}
        referenced_columns = [c for c in referenced_columns if c.lower() in known]
    return GuardedSql(original=sql.strip(), executed=executed, tables=[t for t in referenced_tables], columns=referenced_columns, notes=notes)
