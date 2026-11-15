"""Data profiling and quality reporting.

Input: a DataFrame of text values with a `_row_id` column and SQL-safe column names.
Output: per-column profiles and a list of issues, each with severity, a recommendation,
an executable fix (when one is safe to propose) and a before/after preview.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from app.data import cleaning as C
from app.data import parsing as P

ROW_ID = C.ROW_ID
_ID_NAME = re.compile(r"(^|_)(id|ref|reference|code|key|uuid|number|no)$", re.I)
CATEGORY_MAX_DISTINCT = 200
DATE_FORMAT_EXAMPLES = {
    "iso": "2024-01-31",
    "yyyy/mm/dd": "2024/01/31",
    "nn/nn/yyyy": "31/01/2024 or 01/31/2024",
    "nn-nn-yyyy": "31-01-2024 or 01-31-2024",
    "nn.nn.yyyy": "31.01.2024 or 01.31.2024",
    "dd Mon yyyy": "31 Jan 2024",
    "Mon dd, yyyy": "Jan 31, 2024",
}


def _severity(pct: float, *, high: float = 0.10, medium: float = 0.01) -> str:
    return "high" if pct >= high else "medium" if pct >= medium else "low"


def _round(x: float | None, nd: int = 4) -> float | None:
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def profile_column(df: pd.DataFrame, name: str, original_name: str) -> dict[str, Any]:
    s = df[name]
    n = len(s)
    missing = P.missing_mask(s)
    present = s[~missing].astype(str).str.strip()
    token_missing = int(P.token_missing_mask(s).sum())
    prof: dict[str, Any] = {
        "name": name,
        "original_name": original_name,
        "missing_count": int(missing.sum()),
        "null_count": int(s.isna().sum()),
        "placeholder_count": token_missing,
        "missing_pct": _round(missing.mean() * 100, 2),
        "distinct_count": int(present.nunique()),
        "unique_ratio": _round(present.nunique() / max(len(present), 1)),
        "samples": [str(v) for v in present.value_counts().head(5).index],
        "kind": "empty",
        "is_identifier": False,
    }
    if present.empty:
        return prof

    num = P.to_number(present)
    labels = P.date_format_labels(present)
    numeric_ratio = float(num.notna().mean())
    date_ratio = float(labels.notna().mean())
    if date_ratio >= 0.8:
        prof["kind"] = "date"
        parsed, info = P.parse_dates(present)
        valid = parsed.dropna()
        prof["date_formats"] = info["formats"]
        if not valid.empty:
            prof["min"], prof["max"] = valid.min().strftime("%Y-%m-%d"), valid.max().strftime("%Y-%m-%d")
    elif numeric_ratio >= 0.8:
        prof["kind"] = "numeric"
        v = num.dropna()
        prof.update(
            min=_round(v.min()), max=_round(v.max()), mean=_round(v.mean()),
            median=_round(v.median()), std=_round(v.std()),
        )
    else:
        # Judge by normalised values, so 'North', ' north' and 'NORTH' count as one category.
        categories = int(present.map(P.category_key).nunique())
        prof["kind"] = "categorical" if categories <= CATEGORY_MAX_DISTINCT and categories / len(present) <= 0.5 else "text"

    prof["is_identifier"] = bool(
        _ID_NAME.search(name) and prof["kind"] in ("text", "categorical", "numeric") and prof["unique_ratio"] is not None
    )
    return prof


def _issue(
    type_: str, column: str | None, title: str, description: str, recommendation: str, affected: int, total: int,
    severity: str, fix: dict[str, Any] | None = None, extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"{type_}:{column or 'dataset'}",
        "type": type_,
        "column": column,
        "title": title,
        "description": description,
        "recommendation": recommendation,
        "affected_rows": int(affected),
        "affected_pct": _round(100 * affected / max(total, 1), 2),
        "severity": severity,
        "fix": fix,
        "preview": None,
        **(extra or {}),
    }


def _fix(operation: str, column: str | None, **params: Any) -> dict[str, Any]:
    return {"operation": operation, "column": column, "params": params, "label": C.OPERATION_LABELS[operation]}


def detect_issues(df: pd.DataFrame, columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    n = len(df)
    issues: list[dict[str, Any]] = []
    data_cols = [c["name"] for c in columns]

    # Whole-dataset: exact duplicate rows
    dup_count = int(df.duplicated(subset=data_cols, keep="first").sum())
    if dup_count:
        pct = dup_count / n
        issues.append(_issue(
            "duplicate_rows", None, "Duplicate records",
            f"{dup_count:,} rows are exact copies of an earlier row.",
            "Remove the repeated rows, keeping the first occurrence. Duplicates inflate counts and totals.",
            dup_count, n, "high" if pct >= 0.01 else "medium", _fix("remove_duplicate_rows", None),
        ))
    deduped = df.drop_duplicates(subset=data_cols, keep="first")

    for col in columns:
        name, kind = col["name"], col["kind"]
        s = df[name]
        label = col["original_name"]

        if kind == "empty":
            issues.append(_issue(
                "empty_column", name, f"Empty column: {label}", "Every value is missing.",
                "Remove the column. It carries no information.", n, n, "medium", _fix("drop_column", name),
            ))
            continue

        # Constant column (fully populated, one value)
        if col["distinct_count"] == 1 and col["missing_count"] == 0 and n > 1:
            issues.append(_issue(
                "constant_column", name, f"Constant column: {label}",
                f"Every row has the same value ({col['samples'][0]!r}).",
                "Remove the column unless it is needed for reference. It cannot explain any variation.",
                n, n, "low", _fix("drop_column", name),
            ))

        # Missing values
        missing, placeholders = col["missing_count"], col["placeholder_count"]
        if missing:
            parts = []
            if col["null_count"]:
                parts.append(f"{col['null_count']:,} empty")
            if placeholders:
                parts.append(f"{placeholders:,} placeholders such as 'N/A'")
            issues.append(_issue(
                "missing_values", name, f"Missing values: {label}",
                f"{missing:,} of {n:,} values are missing ({', '.join(parts)}).",
                "Placeholders can be converted to proper NULLs. Missing values are not filled in automatically, "
                "because any imputed value would be an assumption. Analyses will exclude them and say so."
                if placeholders else
                "Review why values are missing. They are not filled in automatically, because any imputed value "
                "would be an assumption. Analyses will exclude them and say so.",
                missing, n, _severity(missing / n),
                _fix("standardise_missing", name) if placeholders else None,
            ))

        # Whitespace
        ws = int(P.whitespace_mask(s).sum())
        if ws:
            issues.append(_issue(
                "whitespace", name, f"Leading or trailing spaces: {label}", f"{ws:,} values have extra spaces.",
                "Trim the spaces. Otherwise 'London' and ' London' are counted as different values.",
                ws, n, _severity(ws / n, high=0.25, medium=0.05), _fix("trim_whitespace", name),
            ))

        present_mask = ~P.missing_mask(s)
        present = s[present_mask]

        # Numbers
        if kind == "numeric":
            num = P.to_number(present)
            invalid = int(num.isna().sum())
            formatted = int((P.has_currency_marker(present) | P.has_thousands_separator(present)).sum())
            if invalid:
                examples = ", ".join(repr(v) for v in present[num.isna()].astype(str).value_counts().head(3).index)
                issues.append(_issue(
                    "mixed_types", name, f"Mixed data types: {label}",
                    f"{invalid:,} values in a numeric column are not numbers (e.g. {examples}).",
                    "Convert the column to numbers. Values that are not valid numbers become NULL and are listed in the preview.",
                    invalid, n, "high" if invalid / n >= 0.05 else "medium", _fix("parse_numbers", name),
                ))
            if formatted:
                issues.append(_issue(
                    "currency_format", name, f"Inconsistent number formatting: {label}",
                    f"{formatted:,} values contain currency symbols, currency codes or thousands separators.",
                    "Strip the symbols and separators and store plain numbers. No currency conversion is performed; "
                    "all values are assumed to be in the same currency.",
                    formatted, n, _severity(formatted / n), _fix("parse_numbers", name),
                ))
            mask, fences = C.outlier_mask(present)
            out = int(mask.sum())
            if out:
                issues.append(_issue(
                    "outliers", name, f"Potential outliers: {label}",
                    f"{out:,} values fall outside {fences[0]:,.2f} to {fences[1]:,.2f} ({C.outlier_method(P.to_number(present))}).",
                    "Review these before drawing conclusions. They are flagged in a new column, not removed, "
                    "because an extreme value can be a data error or a genuine event.",
                    out, n, "medium" if out / n >= 0.01 else "low", _fix("flag_outliers", name),
                    extra={"fences": [_round(fences[0]), _round(fences[1])]},
                ))

        # Dates
        if kind == "date":
            parsed, info = P.parse_dates(present)
            formats = info["formats"]
            unparsed = int(parsed.isna().sum())
            if len(formats) > 1 or unparsed:
                dominant = max(formats.values()) if formats else 0
                off_format = int(sum(formats.values()) - dominant)
                affected = off_format + unparsed
                shown = ", ".join(f"{DATE_FORMAT_EXAMPLES.get(k, k)} ({v:,})" for k, v in sorted(formats.items(), key=lambda kv: -kv[1]))
                issues.append(_issue(
                    "inconsistent_dates", name, f"Inconsistent date formats: {label}",
                    f"{len(formats)} different formats found: {shown}."
                    + (f" {unparsed:,} values could not be read as dates." if unparsed else ""),
                    "Convert every date to ISO 8601 (YYYY-MM-DD). "
                    + ("Some values like 03/04/2024 are ambiguous; the day-first reading is assumed unless the data shows otherwise." if info["ambiguous"] else ""),
                    affected, n, _severity(affected / n), _fix("parse_dates", name, dayfirst=info["dayfirst"]),
                    extra={"ambiguous_dates": info["ambiguous"], "formats": formats},
                ))

        # Categories
        if kind == "categorical":
            trimmed = s.where(s.isna(), s.astype(object).where(s.notna(), "").astype(str).str.strip())
            res = C.standardise_categories(pd.DataFrame({name: trimmed}), name)
            if res.affected:
                groups = {k: v for k, v in P.category_groups(trimmed).items() if len(v) > 1}
                shown = "; ".join(" / ".join(f"{r!r}" for r in sorted(v)) for v in list(groups.values())[:3])
                issues.append(_issue(
                    "inconsistent_categories", name, f"Inconsistent categories: {label}",
                    f"{len(groups)} categories appear under more than one spelling ({shown}). {res.affected:,} rows are affected.",
                    "Merge each group into its most common spelling so that groupings and totals are correct.",
                    res.affected, n, _severity(res.affected / n), _fix("standardise_categories", name),
                ))

        # Duplicate identifiers (not exact duplicate rows)
        if col["is_identifier"] and (col["unique_ratio"] or 0) >= 0.9:
            ids = deduped[name]
            ids = ids[~P.missing_mask(ids)]
            dup_ids = int(ids.duplicated(keep="first").sum())
            if dup_ids:
                issues.append(_issue(
                    "duplicate_identifiers", name, f"Duplicate identifiers: {label}",
                    f"{dup_ids:,} rows reuse an identifier that appears on a different record (the rows differ in other columns).",
                    "Decide which record is correct. No automatic fix is offered because the rows are not exact copies.",
                    dup_ids, n, "high" if dup_ids / n >= 0.01 else "medium",
                ))

        # Informational
        if col["is_identifier"]:
            issues.append(_issue(
                "potential_identifier", name, f"Potential identifier: {label}",
                f"{col['distinct_count']:,} distinct values. Likely an identifier rather than something to average or sum.",
                "Treat as a label. The analyst will group and count by it, not aggregate it.", 0, n, "info",
            ))
        elif kind == "text" and col["distinct_count"] / max(n - col["missing_count"], 1) > 0.5:
            issues.append(_issue(
                "high_cardinality", name, f"High cardinality: {label}",
                f"{col['distinct_count']:,} distinct values, mostly unique.",
                "Not suitable for grouping or charting by category.", 0, n, "info",
            ))
    return issues


def build_previews(df: pd.DataFrame, issues: list[dict[str, Any]]) -> None:
    for issue in issues:
        fix = issue.get("fix")
        if fix:
            issue["preview"] = C.preview_operation(df, fix["operation"], fix["column"], fix["params"])


def profile_dataframe(df: pd.DataFrame, original_names: dict[str, str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Profile a text DataFrame. `df` must contain `_row_id`; other columns are data columns."""
    data_cols = [c for c in df.columns if c != ROW_ID]
    columns = [profile_column(df, c, original_names.get(c, c)) for c in data_cols]
    issues = detect_issues(df, columns)
    build_previews(df, issues)
    severity_rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
    issues.sort(key=lambda i: (severity_rank[i["severity"]], -i["affected_rows"]))
    counts = {s: sum(1 for i in issues if i["severity"] == s) for s in severity_rank}
    summary = {
        "rows": int(len(df)),
        "columns": len(data_cols),
        "issue_counts": counts,
        "fixable_issues": sum(1 for i in issues if i["fix"]),
        "missing_cells": int(sum(c["missing_count"] for c in columns)),
    }
    return {"summary": summary, "issues": issues}, columns
