"""Check that figures in the written answer exist in the computed results.

The model writes the prose, so it can mis-copy or invent a number. This scan finds every figure in the answer text and
looks for it among the stored result cells, validation values and dataset counts. Figures it cannot match are reported
as a warning. The scan cannot catch a wrong *comparison* between real numbers (use the `ranking` check for those),
and it can flag legitimate arithmetic the model did itself. Either way the user is told, and nothing is hidden.
"""

from __future__ import annotations

import re
from typing import Any

from app.analysis.state import RunState

_NUMBER = re.compile(r"(?<![A-Za-z_\d])[£$€]?\s?(\d+(?:\.\d+)?[eE][-+]?\d+|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(%|k|m|bn|b|million|billion|thousand)?(?![A-Za-z_\d])", re.I)
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
MAX_REPORTED = 8


def _numbers(text: str) -> list[tuple[str, float, float]]:
    """(as written, value, tolerance) for each figure in the text."""
    out = []
    for m in _NUMBER.finditer(text):
        raw = m.group(1).replace(",", "")
        if "e" in raw.lower():  # scientific notation, e.g. a p-value of 2.02e-36
            out.append((m.group(0).strip(), float(raw), abs(float(raw)) * 0.01 + 1e-300))
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        suffix = (m.group(2) or "").lower()
        scale = _SCALE.get(suffix, 1.0)
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        tol = 0.5 * 10 ** (-decimals) * scale + 1e-9
        is_year = suffix == "" and "." not in raw and "," not in m.group(1) and 1900 <= value <= 2100
        if is_year or (value <= 12 and "." not in raw and not suffix):  # small counts, ordinals, months, "top 3"
            continue
        out.append((m.group(0).strip(), value * scale, max(tol, abs(value * scale) * 1e-4)))
    return out


def _known_numbers(state: RunState) -> list[float]:
    known: list[float] = []
    for r in state.results.values():
        known.append(float(r.row_count))
        for row in r.rows:
            for v in row:
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    known.append(float(v))
                elif isinstance(v, str):
                    try:
                        known.append(float(v.replace(",", "")))
                    except ValueError:
                        pass
    for c in state.validations:
        for k in ("claimed", "recomputed"):
            if isinstance(c.get(k), (int, float)):
                known.append(float(c[k]))
    h = state.handle
    known += [float(h.row_count), float(h.original_row_count), float(len(h.schema)), float(h.duplicate_rows)]
    for run in state.sql_runs + state.python_runs:
        if run.get("row_count") is not None:
            known.append(float(run["row_count"]))
    for ch in state.charts:
        known.append(float(ch.get("source_rows") or 0))
        for k, v in (ch.get("stats") or {}).items():
            if isinstance(v, (int, float)):
                known.append(float(v))
    return known


def ungrounded_figures(texts: list[str], state: RunState) -> list[str]:
    known = _known_numbers(state)
    missing: list[str] = []
    for text in texts:
        for written, value, tol in _numbers(text):
            # A percentage may have been computed from two result cells; accept its fraction form too.
            candidates = (value, value / 100 if written.endswith("%") else value)
            if not any(abs(k - c) <= max(tol, abs(k) * 1e-4) or abs(abs(k) - abs(c)) <= tol for k in known for c in candidates):
                if written not in missing:
                    missing.append(written)
    return missing[:MAX_REPORTED]


def answer_texts(answer: dict[str, Any]) -> list[str]:
    texts = [answer.get("executive_summary", "")]
    for f in answer.get("key_findings", []):
        texts.append(f.get("finding", ""))
    for k in ("business_implications", "recommendations"):
        texts.extend(answer.get(k, []))
    return [t for t in texts if t]


def grounding_warning(answer: dict[str, Any], state: RunState) -> dict[str, Any] | None:
    if not state.results:
        return None
    missing = ungrounded_figures(answer_texts(answer), state)
    if not missing:
        return None
    return {
        "id": "w-grounding", "status": "warning",
        "label": f"{len(missing)} figure{'s' if len(missing) != 1 else ''} in the written answer could not be matched to a result",
        "detail": "Not found in any query or analysis output: " + ", ".join(missing) + ". They may be arithmetic the AI did itself, or mistakes. Check them against the results before relying on them.",
    }
