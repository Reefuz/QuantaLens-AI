"""Independent verification of analytical claims.

Every check recomputes a figure by a different route than the one the model used:

* totals and aggregates are recalculated with SQL that *this module* builds from structured filters
  (whitelisted columns, bound values), not SQL the model wrote
* percentages and growth rates are recomputed from cells read directly from stored results

A check is `verified` only if the independent figure matches. If a figure cannot be independently
recomputed, the check says `unverified` and why. Nothing is labelled verified by default.
"""

from __future__ import annotations

import math
from typing import Any

from psycopg import sql

from app.analysis.dataset_access import DatasetHandle
from app.analysis.sql_exec import SqlExecutionError, execute_trusted
from app.analysis.state import RunState
from app.data.storage import SCHEMA, _like_escape

NUMERIC_TYPES = {"bigint", "double precision"}
AGGREGATES = {"sum", "avg", "count", "min", "max", "median", "count_distinct"}
FILTER_OPS = {"=", "!=", ">", ">=", "<", "<=", "in", "is_null", "not_null", "contains"}
MAX_CHECKS = 12


class ValidationInputError(ValueError):
    """The check request itself is malformed. Message is for the model."""


def _close(a: float, b: float, rel: float = 1e-6, abs_: float = 0.01) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_)


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(str(v).replace(",", "")) if not isinstance(v, (int, float)) else float(v)
        return f if math.isfinite(f) else None
    except ValueError:
        return None


def build_where(handle: DatasetHandle, filters: list[dict[str, Any]] | None) -> tuple[sql.Composable, list[Any]]:
    clauses: list[sql.Composable] = []
    params: list[Any] = []
    for f in filters or []:
        col, op = f.get("column"), f.get("op", "=")
        if col not in handle.schema:
            raise ValidationInputError(f"Filter column '{col}' does not exist. Columns: {', '.join(handle.schema)}.")
        if op not in FILTER_OPS:
            raise ValidationInputError(f"Filter operator '{op}' is not supported. Use one of: {', '.join(sorted(FILTER_OPS))}.")
        ident, pgtype = sql.Identifier(col), handle.schema[col]
        if op == "is_null":
            clauses.append(sql.SQL("{} IS NULL").format(ident))
        elif op == "not_null":
            clauses.append(sql.SQL("{} IS NOT NULL").format(ident))
        elif op == "contains":
            clauses.append(sql.SQL("{}::text ILIKE %s").format(ident))
            params.append(f"%{_like_escape(str(f.get('value', '')))}%")
        elif op == "in":
            values = f.get("value")
            if not isinstance(values, list) or not values or len(values) > 100:
                raise ValidationInputError("The 'in' operator needs a non-empty list of up to 100 values.")
            clauses.append(sql.SQL("{} = ANY(CAST(%s AS {}[]))").format(ident, sql.SQL(pgtype)))
            params.append([str(v) for v in values])
        else:
            symbol = {"=": "=", "!=": "<>", ">": ">", ">=": ">=", "<": "<", "<=": "<="}[op]
            clauses.append(sql.SQL("{} {} CAST(%s AS {})").format(ident, sql.SQL(symbol), sql.SQL(pgtype)))
            params.append(str(f.get("value")))
    if not clauses:
        return sql.SQL(""), params
    return sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses), params


def _aggregate_query(handle: DatasetHandle, aggregate: str, measure: str | None, filters) -> tuple[sql.Composable, list[Any], str]:
    if aggregate not in AGGREGATES:
        raise ValidationInputError(f"aggregate must be one of: {', '.join(sorted(AGGREGATES))}.")
    table = sql.SQL("{}.{}").format(sql.Identifier(SCHEMA), sql.Identifier(handle.table))
    where, params = build_where(handle, filters)
    if aggregate == "count" and measure is None:
        expr = sql.SQL("count(*)")
    else:
        if measure not in handle.schema:
            raise ValidationInputError(f"Measure column '{measure}' does not exist. Columns: {', '.join(handle.schema)}.")
        col = sql.Identifier(measure)
        expr = {
            "count": sql.SQL("count({})").format(col),
            "count_distinct": sql.SQL("count(DISTINCT {})").format(col),
            "sum": sql.SQL("sum({})").format(col),
            "avg": sql.SQL("avg({})").format(col),
            "min": sql.SQL("min({})").format(col),
            "max": sql.SQL("max({})").format(col),
            "median": sql.SQL("percentile_cont(0.5) WITHIN GROUP (ORDER BY {})").format(col),
        }[aggregate]
    query = sql.SQL("SELECT ") + expr + sql.SQL(" FROM {}").format(table) + where
    shown = f"SELECT {aggregate}({measure or '*'}) FROM data" + (" WHERE " + " AND ".join(f"{f.get('column')} {f.get('op', '=')} {f.get('value', '')}".strip() for f in filters) if filters else "")
    return query, params, shown


def _cell(state: RunState, ref: dict[str, Any], what: str) -> float:
    r = state.get_result(str(ref.get("result_id", "")))
    col = ref.get("column")
    if col not in r.columns:
        raise ValidationInputError(f"{what}: column '{col}' is not in {r.id}. Columns: {', '.join(r.columns)}.")
    if ref.get("where_column"):
        wc = ref["where_column"]
        if wc not in r.columns:
            raise ValidationInputError(f"{what}: column '{wc}' is not in {r.id}.")
        matches = [row for row in r.rows if str(row[r.column_index(wc)]) == str(ref.get("where_value"))]
        if not matches:
            raise ValidationInputError(f"{what}: no row in {r.id} has {wc} = {ref.get('where_value')!r}.")
        row = matches[0]
    else:
        idx = ref.get("row")
        if not isinstance(idx, int) or not 0 <= idx < len(r.rows):
            raise ValidationInputError(f"{what}: row {idx!r} is out of range for {r.id} (0 to {len(r.rows) - 1}).")
        row = r.rows[idx]
    v = _num(row[r.column_index(col)])
    if v is None:
        raise ValidationInputError(f"{what}: the cell is not numeric.")
    return v


def _result(cid: str, kind: str, label: str, status: str, method: str, detail: str, claimed=None, recomputed=None, sql_text: str | None = None) -> dict[str, Any]:
    return {"id": cid, "kind": kind, "label": label, "status": status, "claimed": claimed, "recomputed": recomputed,
            "method": method, "detail": detail, "sql": sql_text}


def _typed_measure_ok(handle: DatasetHandle, measure: str | None, aggregate: str) -> str | None:
    """Reason a numeric aggregate cannot be independently recomputed, or None if it can."""
    if aggregate in ("count", "count_distinct") or measure is None:
        return None
    if handle.schema.get(measure) not in NUMERIC_TYPES and aggregate in ("sum", "avg", "median"):
        return (f"'{measure}' is stored as text in this version of the dataset, so it cannot be summed without parsing it. "
                "Generate the cleaned version for independent verification.")
    return None


def run_check(state: RunState, check: dict[str, Any], cid: str) -> dict[str, Any]:
    kind = check.get("type")
    label = str(check.get("label") or kind or "check")[:160]
    h = state.handle
    try:
        if kind == "total_reconciliation":
            r = state.get_result(str(check.get("result_id", "")))
            vc, aggregate, measure = check.get("value_column"), check.get("aggregate", "sum"), check.get("measure")
            if vc not in r.columns:
                raise ValidationInputError(f"value_column '{vc}' is not in {r.id}. Columns: {', '.join(r.columns)}.")
            if aggregate not in ("sum", "count"):
                raise ValidationInputError("total_reconciliation supports aggregate 'sum' or 'count'.")
            if r.truncated:
                return _result(cid, kind, label, "unverified", "Group totals vs independent total", f"{r.id} was truncated at {r.row_count:,} rows, so its total is incomplete.")
            why = _typed_measure_ok(h, measure, aggregate)
            if why:
                return _result(cid, kind, label, "unverified", "Group totals vs independent total", why)
            vals = [_num(v) for v in r.column(vc)]
            claimed = sum(v for v in vals if v is not None)
            q, params, shown = _aggregate_query(h, aggregate, measure, check.get("filters"))
            recomputed = float(execute_trusted(q, params)[0][0] or 0)
            ok = _close(claimed, recomputed)
            return _result(cid, kind, label, "verified" if ok else "failed", "The result's column total was compared with a separate aggregate over the whole table.",
                           "The parts add up to the independently calculated total." if ok else "The parts do not add up to the independent total. Rows may be missing, filtered differently, or double counted.",
                           claimed, recomputed, shown)
        if kind == "value_recalculation":
            aggregate, measure = check.get("aggregate"), check.get("measure")
            claimed = _num(check.get("claimed_value"))
            if claimed is None:
                raise ValidationInputError("claimed_value must be a number.")
            why = _typed_measure_ok(h, measure, aggregate)
            if why:
                return _result(cid, kind, label, "unverified", "Independent aggregate", why, claimed)
            q, params, shown = _aggregate_query(h, aggregate, measure, check.get("filters"))
            row = execute_trusted(q, params)[0][0]
            recomputed = _num(row)
            if recomputed is None:
                return _result(cid, kind, label, "unverified", "Independent aggregate", "The independent query returned no value (no matching rows or NULL).", claimed, None, shown)
            ok = _close(claimed, recomputed, rel=1e-4, abs_=0.01)
            return _result(cid, kind, label, "verified" if ok else "failed", "A separate aggregate query was run over the table with the same filters.",
                           "The reported value matches." if ok else "The reported value differs from the independent calculation.", claimed, recomputed, shown)
        if kind in ("percentage", "growth"):
            claimed = _num(check.get("claimed_pct"))
            if claimed is None:
                raise ValidationInputError("claimed_pct must be a number.")
            if kind == "percentage":
                part, total = _cell(state, check.get("part") or {}, "part"), _cell(state, check.get("total") or {}, "total")
                if total == 0:
                    return _result(cid, kind, label, "failed", "part / total x 100", "The denominator is zero, so no percentage exists.", claimed)
                recomputed, method = part / total * 100, "part / total x 100, with both values read from stored results"
            else:
                cur, prev = _cell(state, check.get("current") or {}, "current"), _cell(state, check.get("previous") or {}, "previous")
                if prev == 0:
                    return _result(cid, kind, label, "unverified", "(current - previous) / previous x 100", "The previous value is zero, so growth is undefined.", claimed)
                recomputed, method = (cur - prev) / abs(prev) * 100, "(current - previous) / |previous| x 100, with both values read from stored results"
            ok = abs(claimed - recomputed) <= 0.051
            return _result(cid, kind, label, "verified" if ok else "failed", method, "The percentage matches." if ok else "The percentage does not match the recalculation.", claimed, round(recomputed, 4))
        if kind == "ranking":
            r = state.get_result(str(check.get("result_id", "")))
            lc, vc, direction = check.get("label_column"), check.get("value_column"), check.get("direction", "highest")
            claimed_label, rank = str(check.get("claimed_label") or "").strip(), int(check.get("rank") or 1)
            if not claimed_label:
                raise ValidationInputError("claimed_label is required: the entry you claim is the highest or lowest.")
            for col, role in ((lc, "label_column"), (vc, "value_column")):
                if col not in r.columns:
                    raise ValidationInputError(f"{role} '{col}' is not in {r.id}. Columns: {', '.join(r.columns)}.")
            if direction not in ("highest", "lowest"):
                raise ValidationInputError("direction must be 'highest' or 'lowest'.")
            if r.truncated:
                return _result(cid, kind, label, "unverified", "Rank recomputed from the stored result", f"{r.id} was truncated, so the ranking may be incomplete.", claimed_label)
            pairs = [(str(row[r.column_index(lc)]), _num(row[r.column_index(vc)])) for row in r.rows]
            pairs = [(k, v) for k, v in pairs if v is not None]
            if len(pairs) < rank:
                raise ValidationInputError(f"{r.id} has only {len(pairs)} ranked rows.")
            ordered = sorted(pairs, key=lambda p: p[1], reverse=(direction == "highest"))
            actual, value = ordered[rank - 1]
            tied = [k for k, v in ordered if _close(v, value, rel=1e-9, abs_=1e-9)]
            if len(tied) > 1:
                return _result(cid, kind, label, "unverified", "Rank recomputed from the stored result", f"{len(tied)} entries tie for this position ({', '.join(tied[:4])}).", claimed_label, actual)
            ok = actual == claimed_label
            return _result(cid, kind, label, "verified" if ok else "failed", f"Sorted {r.id} by {vc} and read position {rank} ({direction}).",
                           f"{actual} is the {direction} ({value:,.2f})." if ok else f"The {direction} is {actual} ({value:,.2f}), not {claimed_label}.", claimed_label, actual)
        if kind == "null_exposure":
            column = check.get("column")
            if column not in h.schema:
                raise ValidationInputError(f"Column '{column}' does not exist. Columns: {', '.join(h.schema)}.")
            q, params, shown = _aggregate_query(h, "count", None, [{"column": column, "op": "is_null"}])
            nulls = int(execute_trusted(q, params)[0][0])
            total = h.row_count
            pct = round(100 * nulls / max(total, 1), 2)
            status = "verified" if nulls == 0 else "warning"
            return _result(cid, kind, label, status, "Count of NULL values in the column", f"{nulls:,} of {total:,} rows ({pct}%) have no value for '{column}'. Aggregates exclude them.", None, nulls, shown)
        raise ValidationInputError("type must be one of: total_reconciliation, value_recalculation, percentage, growth, ranking, null_exposure.")
    except (ValidationInputError, KeyError) as exc:
        return _result(cid, str(kind), label, "unverified", "Could not run this check", str(exc.args[0] if exc.args else exc))
    except SqlExecutionError as exc:
        return _result(cid, str(kind), label, "unverified", "Independent query failed", str(exc))


def automatic_warnings(state: RunState) -> list[dict[str, Any]]:
    h = state.handle
    out: list[dict[str, Any]] = []
    if h.version == "original":
        out.append({"id": "w-version", "label": "Analysed the original, uncleaned data", "status": "warning",
                    "detail": "Every column is text and values are messy. Figures that depend on parsing text are less reliable than on a cleaned dataset."})
    if h.duplicate_rows and h.version == "original":
        out.append({"id": "w-dup", "label": "Duplicate records may be double counted", "status": "warning",
                    "detail": f"The dataset has {h.duplicate_rows:,} exact duplicate rows that have not been removed."})
    for r in state.results.values():
        if r.truncated:
            out.append({"id": f"w-trunc-{r.id}", "label": f"Result {r.id} was truncated", "status": "warning",
                        "detail": f"Only the first {r.row_count:,} rows were returned. Totals over this result are incomplete."})
    return out


def overall_status(checks: list[dict[str, Any]]) -> str:
    real = [c for c in checks if c["status"] in ("verified", "failed", "unverified")]
    if not real:
        return "not_validated"
    if any(c["status"] == "failed" for c in real):
        return "failed"
    verified = sum(1 for c in real if c["status"] == "verified")
    if verified == len(real):
        return "verified"
    return "partially_verified" if verified else "unverified"


def run_checks(state: RunState, checks: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(checks, list) or not checks:
        raise ValidationInputError("Provide a non-empty list of checks.")
    if len(checks) > MAX_CHECKS:
        raise ValidationInputError(f"At most {MAX_CHECKS} checks per call.")
    base = len(state.validations)
    results = [run_check(state, c if isinstance(c, dict) else {}, f"v{base + i + 1}") for i, c in enumerate(checks)]
    # Re-running a check with the same label (for example after fixing a malformed request) replaces the earlier attempt,
    # so an abandoned mistake does not keep the overall status stuck at "unverified".
    for res in results:
        for i, old in enumerate(state.validations):
            if old["label"] == res["label"] and old["kind"] == res["kind"]:
                state.validations[i] = res
                break
        else:
            state.validations.append(res)
    state.validation_called = True
    hints = [c["detail"] for c in results if c["status"] == "unverified" and c["method"] == "Could not run this check"]
    out = {"checks": results, "status": overall_status(state.validations)}
    failed = [c for c in results if c["status"] == "failed"]
    if failed:
        out["a_check_failed"] = ("Decide whether your analysis or the check is wrong. If the check was set up incorrectly (wrong measure, filters or aggregate), correct it and call validate_results again with the same label. "
                                 "If the analysis was wrong, fix it. Do not present a failed figure as correct. Failed: " + " | ".join(f"{c['label']}: {c['detail']}" for c in failed[:3]))
    if hints:
        out["fix_and_rerun"] = "Some checks could not run because the request was malformed. Correct them and call validate_results again with the same labels: " + " | ".join(hints[:3])
    return out
