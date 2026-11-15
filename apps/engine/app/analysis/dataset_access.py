"""What the analyst can see of a dataset, and how to load it for Python."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data import storage as S
from app.db import get_engine
from app.models import Dataset, DatasetMetadata

_CACHE_TTL = 600
_CACHE_MAX = 2
_cache: dict[tuple[str, int], tuple[float, pd.DataFrame]] = {}
_lock = threading.Lock()


@dataclass
class DatasetHandle:
    dataset_id: str
    name: str
    version: str  # "cleaned" | "original"
    table: str  # physical table in schema qdata
    schema: dict[str, str]  # data columns only, name -> postgres type
    columns: list[dict[str, Any]]
    row_count: int
    open_issues: list[dict[str, Any]] = field(default_factory=list)
    duplicate_rows: int = 0
    original_row_count: int = 0

    @property
    def is_text_only(self) -> bool:
        return all(t == "text" for t in self.schema.values())

    @property
    def column_names(self) -> list[str]:
        return list(self.schema)


def resolve_dataset(db: Session, dataset: Dataset) -> DatasetHandle:
    """Use the cleaned table when the user generated one, otherwise the untouched original."""
    meta = db.scalar(select(DatasetMetadata).where(DatasetMetadata.dataset_id == dataset.id))
    if meta is None or dataset.status not in ("ready", "cleaning") or not dataset.original_table:
        raise ValueError("This dataset is not ready for analysis yet.")
    report = meta.quality_report or {}
    cleaned = report.get("cleaned")
    if dataset.cleaned_table and cleaned:
        schema = {c: t for c, t in cleaned["schema"].items() if c != S.ROW_ID}
        columns = cleaned["columns"]
        issues = cleaned.get("issues", [])
        row_count = cleaned["summary"]["rows_after"]
        table, version = dataset.cleaned_table, "cleaned"
    else:
        schema = {c["name"]: "text" for c in meta.columns}
        columns = meta.columns
        issues = report.get("issues", [])
        row_count = dataset.row_count
        table, version = dataset.original_table, "original"
    dup = next((i["affected_rows"] for i in issues if i["type"] == "duplicate_rows"), 0)
    open_issues = [
        {"title": i["title"], "affected_rows": i["affected_rows"], "severity": i["severity"]}
        for i in issues if i["severity"] in ("high", "medium")
    ][:8]
    return DatasetHandle(
        dataset_id=str(dataset.id), name=dataset.name, version=version, table=table, schema=schema, columns=columns,
        row_count=row_count, open_issues=open_issues, duplicate_rows=dup, original_row_count=dataset.row_count,
    )


def _typed(frame: pd.DataFrame, schema: dict[str, str]) -> pd.DataFrame:
    out = pd.DataFrame(index=frame.index)
    for col, pgtype in schema.items():
        s = frame[col]
        if pgtype == "bigint":
            out[col] = pd.to_numeric(s, errors="coerce").astype("Int64")
        elif pgtype == "double precision":
            out[col] = pd.to_numeric(s, errors="coerce").astype("float64")
        elif pgtype in ("date", "timestamp"):
            out[col] = pd.to_datetime(s, errors="coerce")
        elif pgtype == "boolean":
            out[col] = s.astype("boolean")
        else:
            out[col] = s.astype(object).where(s.notna(), None)
    return out


def load_dataframe(handle: DatasetHandle) -> pd.DataFrame:
    """Typed DataFrame of the dataset (cached briefly; the cleaned table is rebuilt under a new size)."""
    engine = get_engine()
    size = S.table_size_bytes(engine, handle.table)
    key = (handle.table, size)
    now = time.time()
    with _lock:
        for k in [k for k, (ts, _) in _cache.items() if now - ts > _CACHE_TTL]:
            _cache.pop(k, None)
        if key in _cache:
            return _cache[key][1].copy()
    frame = S.fetch_frame(engine, handle.table, [S.ROW_ID, *handle.schema])
    typed = _typed(frame, handle.schema)
    with _lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]), None)
        _cache[key] = (now, typed)
    return typed.copy()
