"""Shared pieces for report exports. Everything is read from the stored analysis payload, so a report can only contain
what the analysis actually produced."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

VALIDATION_LABEL = {
    "verified": "Verified", "partially_verified": "Partially verified", "unverified": "Unverified",
    "failed": "Verification failed", "not_validated": "Not validated",
}
FINDING_KIND = {"observed": "Observed", "statistical": "Statistical", "possible_explanation": "Possible explanation"}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_FORMULA_START = re.compile(r"^[=+\-@\t\r]")


@dataclass
class ReportContext:
    message_id: str
    title: str
    question: str
    dataset_name: str
    generated_at: datetime
    payload: dict[str, Any]

    @property
    def answer(self) -> dict[str, Any]:
        return self.payload["answer"]

    @property
    def validation(self) -> dict[str, Any]:
        return self.payload["validation"]

    @property
    def validation_label(self) -> str:
        return VALIDATION_LABEL.get(self.validation["status"], self.validation["status"])

    def result(self, result_id: str) -> dict[str, Any] | None:
        return next((r for r in self.payload["results"] if r["id"] == result_id), None)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def clean_text(value: Any, limit: int = 20000) -> str:
    return _CONTROL.sub("", "" if value is None else str(value))[:limit]


def neutralise_formula(text: str) -> str:
    """Spreadsheet programs run cells that start with = + - @ as formulas. Dataset text is untrusted, so defuse it
    (plain negative numbers are left alone)."""
    if _FORMULA_START.match(text) and not re.fullmatch(r"-?\d+(\.\d+)?([eE][-+]?\d+)?", text):
        return "'" + text
    return text


def safe_filename(text: str, fallback: str = "analysis") -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", text.strip()).strip("-.")[:60]
    return s or fallback


def fmt_number(v: Any) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.2f}" if abs(v) >= 1 or v == 0 else f"{v:.4g}"
    return str(v)


def referenced_result_ids(ctx: ReportContext) -> list[str]:
    """Results behind the charts and checks first, then the rest, so the supporting tables are the relevant ones."""
    ids: list[str] = []
    for c in ctx.payload["charts"]:
        ids.append(c["result_id"])
    ids += [r["id"] for r in ctx.payload["results"]]
    return list(dict.fromkeys(i for i in ids if ctx.result(i)))
