"""Dataset lifecycle: ingest, profile, store, clean.

The heavy jobs (`process_new_dataset`, `apply_cleaning_job`) run in the background with their own
database sessions. They never log row contents; failures are recorded as a short, safe message.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data import cleaning as C
from app.data import storage as S
from app.data.naming import sanitise_columns
from app.data.profiler import profile_dataframe
from app.db import get_engine, get_sessionmaker
from app.models import CleaningOperation, Dataset, DatasetMetadata
from app.models.base import utcnow

logger = logging.getLogger("quantalens.datasets")
ROW_ID = C.ROW_ID
STALE_AFTER = timedelta(minutes=20)
USABLE_OP_STATUSES = ("approved", "applied")


def set_status(ds: Dataset, status: str, error: str | None = None) -> None:
    ds.status, ds.error, ds.status_changed_at = status, error, utcnow()


def _without_previews(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in i.items() if k != "preview"} for i in issues]


METADATA_KEYS = {"issue_ids", "_preview", "note"}


def op_params(op: CleaningOperation) -> dict[str, Any]:
    """Parameters passed to the operation itself (without our bookkeeping keys)."""
    return {k: v for k, v in (op.parameters or {}).items() if k not in METADATA_KEYS}


def create_operations(db: Session, dataset_id: uuid.UUID, issues: list[dict[str, Any]]) -> None:
    """One proposed operation per (operation, column). Issues that share a fix are merged."""
    merged: dict[tuple[str, str | None], dict[str, Any]] = {}
    for issue in issues:
        fix = issue.get("fix")
        if not fix:
            continue
        key = (fix["operation"], fix["column"])
        if key in merged:
            merged[key]["issue_ids"].append(issue["id"])
        else:
            merged[key] = {"fix": fix, "issue_ids": [issue["id"]], "affected": (issue.get("preview") or {}).get("affected", issue["affected_rows"])}
    ordered = sorted(merged.values(), key=lambda m: (C.order_key(m["fix"]["operation"]), m["fix"]["column"] or ""))
    for seq, m in enumerate(ordered, start=1):
        fix = m["fix"]
        db.add(
            CleaningOperation(
                dataset_id=dataset_id, sequence=seq, operation=fix["operation"], column_name=fix["column"],
                parameters={**fix["params"], "issue_ids": m["issue_ids"]}, affected_rows=int(m["affected"]), status="proposed",
            )
        )


def process_new_dataset(
    dataset_id: uuid.UUID, frame: pd.DataFrame, original_headers: list[str], info: dict[str, Any]
) -> None:
    """Profile `frame`, store it untouched as the original table, and propose cleaning operations."""
    engine, Session_ = get_engine(), get_sessionmaker()
    table = S.table_name(dataset_id)
    try:
        names = sanitise_columns(original_headers)
        df = frame.copy()
        df.columns = names
        df.insert(0, ROW_ID, range(1, len(df) + 1))
        report, columns = profile_dataframe(df, dict(zip(names, original_headers)))
        types = {c: "text" for c in names} | {ROW_ID: "bigint"}
        S.create_table_from_frame(engine, table, df, types)
        size = S.table_size_bytes(engine, table)
        for c in columns:
            c["db_type"] = "text"
        with Session_() as db:
            ds = db.get(Dataset, dataset_id)
            if ds is None:  # deleted while processing
                S.drop_table(engine, table)
                return
            ds.original_table, ds.row_count, ds.column_count = table, len(df), len(names)
            ds.size_bytes = size
            set_status(ds, "ready")
            db.add(
                DatasetMetadata(
                    dataset_id=dataset_id,
                    columns=columns,
                    quality_report={**report, "warnings": info.get("warnings", []), "encoding": info.get("encoding"), "delimiter": info.get("delimiter")},
                )
            )
            create_operations(db, dataset_id, report["issues"])
            db.commit()
    except Exception as exc:  # noqa: BLE001 - record and move on; the type only, never row data
        logger.error("Processing failed for dataset %s: %s", dataset_id, type(exc).__name__)
        try:
            S.drop_table(engine, table)
        except Exception:  # noqa: BLE001
            pass
        with Session_() as db:
            ds = db.get(Dataset, dataset_id)
            if ds is not None:
                set_status(ds, "failed", "The file could not be processed. Check that it is a valid CSV and try again.")
                db.commit()


def apply_cleaning_job(dataset_id: uuid.UUID) -> None:
    """Rebuild the cleaned table from the immutable original using all approved operations."""
    engine, Session_ = get_engine(), get_sessionmaker()
    cleaned_table = S.table_name(dataset_id, cleaned=True)
    try:
        with Session_() as db:
            ds = db.get(Dataset, dataset_id)
            meta = db.scalar(select(DatasetMetadata).where(DatasetMetadata.dataset_id == dataset_id))
            ops = list(
                db.scalars(
                    select(CleaningOperation)
                    .where(CleaningOperation.dataset_id == dataset_id, CleaningOperation.status.in_(USABLE_OP_STATUSES))
                )
            )
            original_table = ds.original_table
            columns = [c["name"] for c in meta.columns]
            original_names = {c["name"]: c["original_name"] for c in meta.columns}
            op_specs = [(o.id, o.operation, o.column_name, op_params(o)) for o in ops]
        op_specs.sort(key=lambda s: C.order_key(s[1]))

        df = S.fetch_frame(engine, original_table, [ROW_ID, *columns])
        rows_before, results = len(df), []
        for op_id, operation, column, params in op_specs:
            if column is not None and column not in df.columns:
                results.append((op_id, None, "skipped: column no longer present"))
                continue
            res = C.apply_operation(df, operation, column, params)
            df = res.frame
            results.append((op_id, res.affected, None))

        schema = C.infer_schema(df)
        S.drop_table(engine, cleaned_table)
        S.create_table_from_frame(engine, cleaned_table, df, schema)
        size = S.table_size_bytes(engine, cleaned_table) + S.table_size_bytes(engine, original_table)
        after_report, after_columns = profile_dataframe(df, {c: original_names.get(c, c) for c in df.columns if c != ROW_ID})
        for c in after_columns:
            c["db_type"] = schema.get(c["name"], "text")

        with Session_() as db:
            ds = db.get(Dataset, dataset_id)
            if ds is None:
                S.drop_table(engine, cleaned_table)
                return
            meta = db.scalar(select(DatasetMetadata).where(DatasetMetadata.dataset_id == dataset_id))
            now = utcnow()
            for op_id, affected, note in results:
                op = db.get(CleaningOperation, op_id)
                if affected is not None:
                    op.status, op.applied_at, op.affected_rows = "applied", now, affected
                else:
                    op.parameters = {**(op.parameters or {}), "note": note}
            meta.quality_report = {
                **meta.quality_report,
                "cleaned": {
                    "schema": schema,
                    "columns": after_columns,
                    "summary": {**after_report["summary"], "rows_before": rows_before, "rows_after": len(df)},
                    "issues": _without_previews(after_report["issues"]),
                    "generated_at": now.isoformat(),
                },
            }
            ds.cleaned_table, ds.size_bytes = cleaned_table, size
            set_status(ds, "ready")
            db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.error("Cleaning failed for dataset %s: %s", dataset_id, type(exc).__name__)
        with Session_() as db:
            ds = db.get(Dataset, dataset_id)
            if ds is not None:
                set_status(ds, "ready", "Generating the cleaned version failed. Your original data is unchanged.")
                db.commit()


def delete_dataset(db: Session, dataset: Dataset) -> None:
    """Drop the stored tables, then the metadata. Conversations and logs cascade."""
    engine = get_engine()
    for table in (dataset.original_table, dataset.cleaned_table, S.table_name(dataset.id), S.table_name(dataset.id, True)):
        if table:
            S.drop_table(engine, table)
    db.delete(dataset)
    db.commit()


def expire_stale(db: Session, datasets: list[Dataset]) -> None:
    """A job that died with the process would otherwise leave a dataset 'processing' or 'cleaning' forever."""
    now = utcnow()
    changed = False
    for d in datasets:
        since = d.status_changed_at if d.status_changed_at.tzinfo else d.status_changed_at.replace(tzinfo=now.tzinfo)
        if d.status in ("processing", "cleaning") and now - since > STALE_AFTER:
            if d.status == "processing":
                set_status(d, "failed", "Processing did not finish. Please upload the file again.")
            else:
                set_status(d, "ready", "Generating the cleaned version did not finish. Your original data is unchanged.")
            changed = True
    if changed:
        db.commit()