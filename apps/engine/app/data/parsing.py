"""Parsing primitives shared by profiling and cleaning.

All functions take and return pandas Series of strings (object dtype, None for NULL).
Keeping detection and correction on the same code means a previewed fix is the fix that gets applied.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

# Values that mean "no value" once whitespace and case are ignored.
NA_TOKENS = frozenset(
    {"", "na", "n/a", "n.a.", "#n/a", "nan", "null", "none", "nil", "-", "--", "?", "unknown", "missing"}
)


def as_text(s: pd.Series) -> pd.Series:
    return s.astype(object).where(s.notna(), None)


def missing_mask(s: pd.Series) -> pd.Series:
    """True where the value is NULL or a placeholder such as 'N/A'."""
    stripped = s.astype(object).where(s.notna(), "").astype(str).str.strip().str.lower()
    return stripped.isin(NA_TOKENS)


def token_missing_mask(s: pd.Series) -> pd.Series:
    """True where the value is a non-NULL placeholder (e.g. 'N/A', '-')."""
    return missing_mask(s) & s.notna() & (s.astype(object).where(s.notna(), "").astype(str).str.strip() != "")


def whitespace_mask(s: pd.Series) -> pd.Series:
    t = s.astype(object).where(s.notna(), "").astype(str)
    return s.notna() & (t != t.str.strip())


# ── numbers ────────────────────────────────────────────────────────────────

_CURRENCY_WORDS = re.compile(r"(?i)\b(?:gbp|usd|eur|jpy|cad|aud|chf)\b")
_CURRENCY_SYMBOLS = re.compile(r"[£$€¥]")
_THOUSANDS = re.compile(r"^-?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_PLAIN_NUMBER = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


def has_currency_marker(s: pd.Series) -> pd.Series:
    t = s.astype(object).where(s.notna(), "").astype(str)
    return t.str.contains(_CURRENCY_SYMBOLS) | t.str.contains(_CURRENCY_WORDS)


def has_thousands_separator(s: pd.Series) -> pd.Series:
    t = s.astype(object).where(s.notna(), "").astype(str)
    cleaned = t.str.replace(_CURRENCY_SYMBOLS, "", regex=True).str.replace(_CURRENCY_WORDS, "", regex=True).str.strip()
    return cleaned.str.match(_THOUSANDS)


def to_number(s: pd.Series) -> pd.Series:
    """Parse numbers, tolerating currency symbols/codes, thousands separators and (accounting) negatives.

    Returns float64 with NaN where the value is missing or not a number.
    """
    t = s.astype(object).where(s.notna(), None).astype("string").str.strip()
    negative = t.str.match(r"^\(.*\)$").fillna(False).astype(bool)
    t = t.str.replace(r"^\((.*)\)$", r"\1", regex=True)
    t = t.str.replace(_CURRENCY_WORDS.pattern, "", regex=True)
    t = t.str.replace(_CURRENCY_SYMBOLS.pattern, "", regex=True)
    t = t.str.replace(r"\s+", "", regex=True)
    thousands = t.str.match(_THOUSANDS.pattern).fillna(False).astype(bool)
    t = t.where(~thousands, t.str.replace(",", "", regex=False))
    plain = t.str.match(_PLAIN_NUMBER.pattern).fillna(False).astype(bool)
    num = pd.to_numeric(t.where(plain), errors="coerce").astype("float64")
    num = num.where(~negative, -num)
    num = num.where(np.isfinite(num))
    num.index = s.index
    return num


def format_number(x: float) -> str | None:
    if x is None or not np.isfinite(x):
        return None
    if float(x).is_integer() and abs(x) < 1e15:
        return str(int(x))
    return np.format_float_positional(float(x), trim="-")


# ── dates ──────────────────────────────────────────────────────────────────

DATE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("iso", re.compile(r"^\d{4}-\d{1,2}-\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$")),
    ("yyyy/mm/dd", re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$")),
    ("nn/nn/yyyy", re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")),
    ("nn-nn-yyyy", re.compile(r"^\d{1,2}-\d{1,2}-\d{4}$")),
    ("nn.nn.yyyy", re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$")),
    ("dd Mon yyyy", re.compile(r"^\d{1,2}[ -][A-Za-z]{3,9}\.?,?[ -]\d{2,4}$")),
    ("Mon dd, yyyy", re.compile(r"^[A-Za-z]{3,9}\.? \d{1,2},? \d{4}$")),
]
_NUMERIC_DMY = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$")
AMBIGUOUS_LABELS = {"nn/nn/yyyy", "nn-nn-yyyy", "nn.nn.yyyy"}


def date_format_labels(s: pd.Series) -> pd.Series:
    """Label each value with the first date pattern it matches (None if none do or value is missing)."""
    t = s.astype(object).where(s.notna(), None).astype("string").str.strip()
    labels = pd.Series([None] * len(s), index=s.index, dtype=object)
    for name, pattern in reversed(DATE_PATTERNS):  # earlier patterns take precedence
        hit = t.str.match(pattern.pattern).fillna(False).astype(bool)
        labels = labels.mask(hit, name)
    return labels


def infer_dayfirst(s: pd.Series, labels: pd.Series) -> bool | None:
    """Decide day-first vs month-first from the values themselves. None if the data cannot tell."""
    sub = s[labels.isin(AMBIGUOUS_LABELS)].astype(str).str.strip()
    if sub.empty:
        return None
    parts = sub.str.extract(_NUMERIC_DMY).astype(float)
    if (parts[0] > 12).any() and not (parts[1] > 12).any():
        return True
    if (parts[1] > 12).any() and not (parts[0] > 12).any():
        return False
    return None


def parse_dates(s: pd.Series, dayfirst: bool | None = None) -> tuple[pd.Series, dict[str, Any]]:
    """Parse mixed-format dates to datetime64. Returns (series, info).

    info = {formats: {label: count}, dayfirst: bool, ambiguous: bool, unparsed: int}
    `ambiguous` is True when numeric d/m/y values cannot be resolved from the data and a default was assumed.
    """
    labels = date_format_labels(s)
    inferred = infer_dayfirst(s, labels) if dayfirst is None else dayfirst
    has_numeric = labels.isin(AMBIGUOUS_LABELS).any()
    ambiguous = bool(has_numeric and inferred is None and dayfirst is None)
    use_dayfirst = True if inferred is None else inferred

    result = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    text = s.astype(object).where(s.notna(), None)
    for label in labels.dropna().unique():
        idx = labels.index[labels == label]
        sub = text.loc[idx].astype(str).str.strip()
        if label == "iso":
            parsed = pd.to_datetime(sub, errors="coerce", format="ISO8601", utc=True).dt.tz_localize(None)
        elif label == "yyyy/mm/dd":
            parsed = pd.to_datetime(sub.str.replace("/", "-"), errors="coerce", format="%Y-%m-%d")
        elif label in AMBIGUOUS_LABELS:
            parts = sub.str.extract(_NUMERIC_DMY).astype(float)
            a, b, y = parts[0], parts[1], parts[2]
            y = y.where(y >= 100, np.where(y < 70, 2000 + y, 1900 + y))
            day, month = (a, b) if use_dayfirst else (b, a)
            parsed = pd.to_datetime(pd.DataFrame({"year": y, "month": month, "day": day}), errors="coerce")
        else:
            parsed = pd.to_datetime(sub, errors="coerce", format="mixed", dayfirst=True)
        result.loc[idx] = parsed.astype("datetime64[ns]")
    info = {
        "formats": {str(k): int(v) for k, v in labels.value_counts().items()},
        "dayfirst": bool(use_dayfirst),
        "ambiguous": ambiguous,
        "unparsed": int((labels.notna() & result.isna()).sum()),
    }
    return result, info


def format_dates(dt: pd.Series) -> pd.Series:
    """ISO-8601 date strings (date only when no time component exists anywhere)."""
    has_time = (dt.dropna().dt.normalize() != dt.dropna()).any()
    fmt = "%Y-%m-%d %H:%M:%S" if has_time else "%Y-%m-%d"
    out = dt.dt.strftime(fmt)
    return out.astype(object).where(dt.notna(), None)


# ── categories ─────────────────────────────────────────────────────────────

def category_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def category_groups(s: pd.Series) -> dict[str, dict[str, int]]:
    """Group raw values by normalised key: {key: {raw_value: count}}. Missing placeholders are ignored."""
    valid = s[~missing_mask(s)].astype(str)
    groups: dict[str, dict[str, int]] = {}
    for raw, n in valid.value_counts().items():
        groups.setdefault(category_key(raw), {})[raw] = int(n)
    return groups


def canonical_category(variants: dict[str, int]) -> str:
    """Most frequent variant after trimming; ties broken by preferring Title-style over lower/UPPER."""
    trimmed: dict[str, int] = {}
    for raw, n in variants.items():
        trimmed[raw.strip()] = trimmed.get(raw.strip(), 0) + n

    def rank(item: tuple[str, int]) -> tuple[int, int, str]:
        value, n = item
        styled = int(value != value.lower() and value != value.upper())
        return (-n, -styled, value)

    return sorted(trimmed.items(), key=rank)[0][0]
