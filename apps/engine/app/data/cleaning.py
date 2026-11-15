"""Cleaning operations. Pure functions on a DataFrame of text values (None = NULL).

The same function produces both the preview shown to the user and the cleaned table, so the
preview cannot drift from what is applied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.data import parsing as P

ROW_ID = "_row_id"

# Operations run in this order regardless of the order they were approved.
# Normalise values first so that duplicates and categories are judged on clean data.
OPERATION_ORDER = [
    "trim_whitespace",
    "standardise_missing",
    "parse_numbers",
    "parse_dates",
    "standardise_categories",
    "drop_column",
    "remove_duplicate_rows",
    "flag_outliers",
]

OPERATION_LABELS = {
    "trim_whitespace": "Trim whitespace",
    "standardise_missing": "Convert placeholders to NULL",
    "parse_numbers": "Convert to numbers",
    "parse_dates": "Standardise dates (ISO 8601)",
    "standardise_categories": "Merge inconsistent categories",
    "drop_column": "Remove column",
    "remove_duplicate_rows": "Remove duplicate rows",
    "flag_outliers": "Flag outliers (no rows removed)",
}

OUTLIER_IQR_MULTIPLIER = 1.5  # standard Tukey fence


@dataclass
class OpResult:
    frame: pd.DataFrame
    affected: int
    details: dict[str, Any] = field(default_factory=dict)


def _changed(before: pd.Series, after: pd.Series) -> pd.Series:
    b = before.astype(object).where(before.notna(), None)
    a = after.astype(object).where(after.notna(), None)
    return ~((b == a) | (b.isna() & a.isna()))


def _replace_column(df: pd.DataFrame, col: str, new: pd.Series) -> pd.DataFrame:
    out = df.copy()
    out[col] = new.astype(object).where(new.notna(), None)
    return out


def trim_whitespace(df: pd.DataFrame, col: str, **_: Any) -> OpResult:
    s = df[col]
    new = s.where(s.isna(), s.astype(object).where(s.notna(), "").astype(str).str.strip())
    return OpResult(_replace_column(df, col, new), int(_changed(s, new).sum()))


def standardise_missing(df: pd.DataFrame, col: str, **_: Any) -> OpResult:
    s = df[col]
    mask = P.token_missing_mask(s)
    new = s.mask(mask, None)
    return OpResult(_replace_column(df, col, new), int(mask.sum()))


def parse_numbers(df: pd.DataFrame, col: str, **_: Any) -> OpResult:
    s = df[col]
    num = P.to_number(s)
    placeholder = P.missing_mask(s)
    invalid = ~placeholder & num.isna()
    new = pd.Series([P.format_number(x) if np.isfinite(x) else None for x in num], index=s.index, dtype=object)
    return OpResult(
        _replace_column(df, col, new),
        int(_changed(s, new).sum()),
        {"invalid_set_to_null": int(invalid.sum())},
    )


def parse_dates(df: pd.DataFrame, col: str, dayfirst: bool | None = None, **_: Any) -> OpResult:
    s = df[col]
    parsed, info = P.parse_dates(s, dayfirst)
    new = P.format_dates(parsed)
    placeholder = P.missing_mask(s)
    invalid = ~placeholder & parsed.isna()
    return OpResult(
        _replace_column(df, col, new),
        int(_changed(s, new).sum()),
        {"invalid_set_to_null": int(invalid.sum()), **info},
    )


def standardise_categories(df: pd.DataFrame, col: str, **_: Any) -> OpResult:
    s = df[col]
    groups = P.category_groups(s)
    mapping: dict[str, str] = {}
    for variants in groups.values():
        canonical = P.canonical_category(variants)
        for raw in variants:
            mapping[raw] = canonical
    new = s.map(lambda v: mapping.get(v, v) if v is not None else None)
    merged = {k: sorted(v) for k, v in groups.items() if len({x.strip() for x in v}) > 1}
    return OpResult(_replace_column(df, col, new), int(_changed(s, new).sum()), {"merged_groups": len(merged)})


def drop_column(df: pd.DataFrame, col: str, **_: Any) -> OpResult:
    return OpResult(df.drop(columns=[col]), len(df))


def remove_duplicate_rows(df: pd.DataFrame, **_: Any) -> OpResult:
    subset = [c for c in df.columns if c != ROW_ID]
    dup = df.duplicated(subset=subset, keep="first")
    return OpResult(df.loc[~dup].reset_index(drop=True), int(dup.sum()))


def outlier_fences(num: pd.Series, multiplier: float = OUTLIER_IQR_MULTIPLIER) -> tuple[float, float] | None:
    """Tukey fences. Strictly positive, right-skewed data (money, counts) is judged on the log scale.

    On a linear scale the natural long tail of such data would be flagged wholesale, which is
    not "unusual", just how amounts are distributed.
    """
    clean = num.dropna()
    if len(clean) < 8:
        return None
    if (clean > 0).all() and clean.skew() > 1.0:
        logs = np.log(clean)
        q1, q3 = logs.quantile(0.25), logs.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            return None
        return float(np.exp(q1 - multiplier * iqr)), float(np.exp(q3 + multiplier * iqr))
    q1, q3 = clean.quantile(0.25), clean.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return None
    return float(q1 - multiplier * iqr), float(q3 + multiplier * iqr)


def outlier_method(num: pd.Series) -> str:
    clean = num.dropna()
    log = len(clean) >= 8 and bool((clean > 0).all()) and clean.skew() > 1.0
    return f"IQR x {OUTLIER_IQR_MULTIPLIER:g}" + (" on the log scale" if log else "")


def outlier_mask(s: pd.Series, multiplier: float = OUTLIER_IQR_MULTIPLIER) -> tuple[pd.Series, tuple[float, float] | None]:
    num = P.to_number(s)
    fences = outlier_fences(num, multiplier)
    if fences is None:
        return pd.Series(False, index=s.index), None
    return ((num < fences[0]) | (num > fences[1])).fillna(False), fences


def flag_outliers(df: pd.DataFrame, col: str, multiplier: float = OUTLIER_IQR_MULTIPLIER, **_: Any) -> OpResult:
    mask, fences = outlier_mask(df[col], multiplier)
    num = P.to_number(df[col])
    flag = pd.Series([bool(m) if np.isfinite(n) else None for m, n in zip(mask, num)], index=df.index, dtype=object)
    out = df.copy()
    out[f"{col}_is_outlier"] = flag
    details = {"method": outlier_method(num), "lower_fence": fences[0] if fences else None, "upper_fence": fences[1] if fences else None}
    return OpResult(out, int(mask.sum()), details)


OPERATIONS = {
    "trim_whitespace": trim_whitespace,
    "standardise_missing": standardise_missing,
    "parse_numbers": parse_numbers,
    "parse_dates": parse_dates,
    "standardise_categories": standardise_categories,
    "drop_column": drop_column,
    "remove_duplicate_rows": remove_duplicate_rows,
    "flag_outliers": flag_outliers,
}


def apply_operation(df: pd.DataFrame, operation: str, column: str | None, params: dict[str, Any] | None = None) -> OpResult:
    fn = OPERATIONS.get(operation)
    if fn is None:
        raise ValueError(f"Unknown cleaning operation: {operation}")
    kwargs = dict(params or {})
    if column is not None:
        if column not in df.columns:
            raise ValueError(f"Column '{column}' not found")
        return fn(df, column, **kwargs)
    return fn(df, **kwargs)


def order_key(operation: str) -> int:
    return OPERATION_ORDER.index(operation) if operation in OPERATION_ORDER else len(OPERATION_ORDER)


# ── previews ───────────────────────────────────────────────────────────────

def _evenly(indices: list[int], k: int) -> list[int]:
    if len(indices) <= k:
        return indices
    step = len(indices) / k
    return [indices[int(i * step)] for i in range(k)]


def _show(v: Any) -> str:
    return "NULL" if v is None or (isinstance(v, float) and np.isnan(v)) else repr(v) if isinstance(v, str) and v != v.strip() else str(v)


def preview_operation(df: pd.DataFrame, operation: str, column: str | None, params: dict[str, Any] | None = None, k: int = 5) -> dict[str, Any]:
    """Before/after examples produced by running the real operation."""
    result = apply_operation(df, operation, column, params)
    rows: list[dict[str, str]] = []
    ids = df[ROW_ID] if ROW_ID in df.columns else pd.Series(range(1, len(df) + 1), index=df.index)

    if operation == "remove_duplicate_rows":
        subset = [c for c in df.columns if c != ROW_ID]
        dup = df.duplicated(subset=subset, keep="first")
        shown = [c for c in subset[:4]]
        for i in _evenly(list(np.flatnonzero(dup.to_numpy())), k):
            rows.append({"row": str(ids.iloc[i]), "before": " | ".join(_show(df.iloc[i][c]) for c in shown), "after": "removed (duplicate)"})
    elif operation == "drop_column":
        non_empty = int((~P.missing_mask(df[column])).sum())
        rows.append({"row": "-", "before": f"{non_empty:,} non-empty values", "after": "column removed"})
    elif operation == "flag_outliers":
        mask, fences = outlier_mask(df[column])
        num = P.to_number(df[column])
        top = list(np.flatnonzero(mask.to_numpy()))
        top = sorted(top, key=lambda i: -abs(num.iloc[i]))[:k]
        for i in top:
            rows.append({"row": str(ids.iloc[i]), "before": _show(df.iloc[i][column]), "after": "flagged as outlier"})
    else:
        after = result.frame[column]
        # frames can differ in length only for dedupe, handled above
        changed = _changed(df[column], after)
        for i in _evenly(list(np.flatnonzero(changed.to_numpy())), k):
            rows.append({"row": str(ids.iloc[i]), "before": _show(df[column].iloc[i]), "after": _show(after.iloc[i])})

    note = None
    d = result.details
    if operation == "parse_dates" and d.get("ambiguous"):
        note = "Some dates like 03/04/2024 could be read either way. Day-first (UK) was assumed because the data does not say."
    elif operation == "parse_dates":
        note = "Read as " + ("day-first (dd/mm/yyyy)." if d.get("dayfirst") else "month-first (mm/dd/yyyy).")
    if d.get("invalid_set_to_null"):
        extra = f"{d['invalid_set_to_null']:,} values that are not valid will become NULL."
        note = f"{note} {extra}" if note else extra
    if operation == "flag_outliers" and d.get("upper_fence") is not None:
        note = f"Values outside {d['lower_fence']:,.2f} to {d['upper_fence']:,.2f} ({d['method']}). A new column is added; nothing is removed."
    return {"rows": rows, "affected": result.affected, "note": note, "details": {k_: v for k_, v in d.items() if isinstance(v, (int, float, str, bool, type(None)))}}


# ── typing the cleaned table ───────────────────────────────────────────────

_INT = re.compile(r"^-?(0|[1-9]\d{0,17})$")
_FLOAT = re.compile(r"^-?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def infer_pg_type(s: pd.Series) -> str:
    """Postgres type for a column of text values. Conservative: only types that every value satisfies."""
    values = s.dropna()
    if values.empty:
        return "text"
    if values.map(lambda v: isinstance(v, (bool, np.bool_))).all():
        return "boolean"
    text = values.astype(str)
    if text.map(lambda v: bool(_INT.match(v))).all():
        return "bigint"
    if text.map(lambda v: bool(_FLOAT.match(v))).all():
        return "double precision"
    if text.map(lambda v: bool(_DATE.match(v))).all() and pd.to_datetime(text, errors="coerce", format="%Y-%m-%d").notna().all():
        return "date"
    if text.map(lambda v: bool(_TIMESTAMP.match(v))).all() and pd.to_datetime(text, errors="coerce", format="%Y-%m-%d %H:%M:%S").notna().all():
        return "timestamp"
    return "text"


def infer_schema(df: pd.DataFrame) -> dict[str, str]:
    return {c: ("bigint" if c == ROW_ID else infer_pg_type(df[c])) for c in df.columns}
