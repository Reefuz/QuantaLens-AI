"""Dataset tables in the `qdata` schema.

Table names derive from a dataset UUID and column names come from our own sanitiser, but every
identifier is still quoted with psycopg's `sql.Identifier` and every value is a bound parameter.
Column and sort names supplied by a client are checked against the stored schema before use.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pandas as pd
from psycopg import sql
from psycopg.errors import DataError, InvalidTextRepresentation, UndefinedTable
from sqlalchemy import Engine

SCHEMA = "qdata"
ROW_ID = "_row_id"
MAX_PAGE_SIZE = 200
FILTER_OPS = {"contains", "equals", "gt", "gte", "lt", "lte", "is_null", "not_null"}
_NUMERIC_TYPES = {"bigint", "double precision"}
_ORDERED_TYPES = _NUMERIC_TYPES | {"date", "timestamp"}


class QueryError(ValueError):
    """A bad client request (unknown column, bad filter value). Safe to show."""


class TableMissing(LookupError):
    """The dataset's table no longer exists (for example, it is being deleted)."""


@contextmanager
def raw_connection(engine: Engine) -> Iterator[Any]:
    """A psycopg connection with an explicit transaction.

    Statements run directly on the driver connection are invisible to SQLAlchemy's transaction
    tracking, so `Connection.commit()` would silently do nothing and the pool would roll the work back.
    """
    with engine.connect() as conn:
        raw = conn.connection.driver_connection
        try:
            yield raw
            raw.commit()
        except BaseException:
            raw.rollback()
            raise


def table_name(dataset_id: uuid.UUID, cleaned: bool = False) -> str:
    return f"ds_{dataset_id.hex}" + ("_clean" if cleaned else "")


def _qualified(table: str) -> sql.Composed:
    return sql.SQL("{}.{}").format(sql.Identifier(SCHEMA), sql.Identifier(table))


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def create_table_from_frame(engine: Engine, table: str, df: pd.DataFrame, pg_types: dict[str, str]) -> None:
    """Create the table and bulk-load `df` with COPY, in one transaction."""
    columns = list(df.columns)
    defs = [
        sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(pg_types[c]))  # type names come from a fixed whitelist
        for c in columns
    ]
    allowed = {"text", "bigint", "double precision", "date", "timestamp", "boolean"}
    if not set(pg_types.values()) <= allowed:
        raise ValueError("Unsupported column type")
    ddl = sql.SQL("CREATE TABLE {} ({}, PRIMARY KEY ({}))").format(
        _qualified(table), sql.SQL(", ").join(defs), sql.Identifier(ROW_ID)
    )
    copy_stmt = sql.SQL("COPY {} ({}) FROM STDIN").format(
        _qualified(table), sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    )
    rows = df.astype(object).where(df.notna(), None).itertuples(index=False, name=None)
    with raw_connection(engine) as raw:
        with raw.cursor() as cur:
            cur.execute(ddl)
            with cur.copy(copy_stmt) as copy:
                for row in rows:
                    copy.write_row(row)


def drop_table(engine: Engine, table: str) -> None:
    with raw_connection(engine) as raw:
        raw.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(_qualified(table)))


def table_size_bytes(engine: Engine, table: str) -> int:
    with raw_connection(engine) as raw:
        cur = raw.execute("SELECT pg_total_relation_size(to_regclass(%s))", (f"{SCHEMA}.{table}",))
        return int(cur.fetchone()[0] or 0)


def fetch_frame(engine: Engine, table: str, columns: list[str]) -> pd.DataFrame:
    """Load a whole dataset table as text-or-native values (None for NULL)."""
    query = sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
        sql.SQL(", ").join(sql.Identifier(c) for c in columns), _qualified(table), sql.Identifier(ROW_ID)
    )
    with raw_connection(engine) as raw:
        data = raw.execute(query).fetchall()
    return pd.DataFrame(data, columns=columns, dtype=object)


def _build_where(
    columns: dict[str, str], search: str | None, filters: list[dict[str, Any]]
) -> tuple[sql.Composable, list[Any]]:
    clauses: list[sql.Composable] = []
    params: list[Any] = []
    if search and search.strip():
        pattern = f"%{_like_escape(search.strip())}%"
        ors = [
            sql.SQL("{}::text ILIKE %s ESCAPE '\\'").format(sql.Identifier(c)) for c in columns if c != ROW_ID
        ]
        clauses.append(sql.SQL("(") + sql.SQL(" OR ").join(ors) + sql.SQL(")"))
        params.extend([pattern] * len(ors))
    for f in filters:
        col, op, value = f.get("column"), f.get("op"), f.get("value")
        if col not in columns or col == ROW_ID:
            raise QueryError(f"Unknown column: {col}")
        if op not in FILTER_OPS:
            raise QueryError(f"Unsupported filter: {op}")
        ident, pgtype = sql.Identifier(col), columns[col]
        if op == "is_null":
            clauses.append(sql.SQL("{} IS NULL").format(ident))
        elif op == "not_null":
            clauses.append(sql.SQL("{} IS NOT NULL").format(ident))
        elif op == "contains":
            clauses.append(sql.SQL("{}::text ILIKE %s ESCAPE '\\'").format(ident))
            params.append(f"%{_like_escape(str(value or ''))}%")
        elif op == "equals":
            clauses.append(sql.SQL("{}::text = %s").format(ident))
            params.append(str(value if value is not None else ""))
        else:
            if pgtype not in _ORDERED_TYPES:
                raise QueryError(f"'{col}' is text, so greater/less-than filters do not apply.")
            symbol = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
            clauses.append(sql.SQL("{} {} CAST(%s AS {})").format(ident, sql.SQL(symbol), sql.SQL(pgtype)))
            params.append(str(value))
    if not clauses:
        return sql.SQL(""), params
    return sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses), params


def query_rows(
    engine: Engine,
    table: str,
    schema: dict[str, str],
    *,
    offset: int = 0,
    limit: int = 50,
    sort: str | None = None,
    descending: bool = False,
    search: str | None = None,
    filters: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return (rows, total matching rows). `schema` maps column name to Postgres type."""
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    offset = max(0, offset)
    if sort is not None and sort not in schema:
        raise QueryError(f"Unknown column: {sort}")
    where, params = _build_where(schema, search, filters or [])
    order = sql.SQL(" ORDER BY ")
    if sort:
        order += sql.SQL("{} {} NULLS LAST, ").format(sql.Identifier(sort), sql.SQL("DESC" if descending else "ASC"))
    order += sql.Identifier(ROW_ID)
    cols = [c for c in schema]
    select = sql.SQL("SELECT {} FROM {}").format(sql.SQL(", ").join(sql.Identifier(c) for c in cols), _qualified(table))
    count = sql.SQL("SELECT count(*) FROM {}").format(_qualified(table))
    try:
        with raw_connection(engine) as raw:
            total = raw.execute(count + where, params).fetchone()[0]
            data = raw.execute(select + where + order + sql.SQL(" LIMIT %s OFFSET %s"), [*params, limit, offset]).fetchall()
    except UndefinedTable as exc:
        raise TableMissing from exc
    except (InvalidTextRepresentation, DataError) as exc:
        raise QueryError("That filter value does not match the column's type.") from exc
    out = []
    for row in data:
        out.append({c: (v.isoformat() if hasattr(v, "isoformat") else v) for c, v in zip(cols, row)})
    return out, int(total)
