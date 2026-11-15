import json
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.config import get_settings
from app.core import upload_token
from app.core.auth import CurrentUser, DbSession, get_current_session, get_current_user, require_csrf_header
from app.core.rate_limit import limiter
from app.data import cleaning as C
from app.data import storage as S
from app.data.csv_reader import CsvError, read_csv_file, sanitise_filename
from app.data.sample import SAMPLE_FILENAME, SAMPLE_NAME, SAMPLE_QUESTIONS, generate_sample
from app.db import get_engine
from app.models import CleaningOperation, Dataset, DatasetMetadata, User
from app.services import datasets as svc

router = APIRouter(prefix="/datasets", tags=["datasets"], dependencies=[Depends(require_csrf_header)])

USER_STORAGE_LIMIT_BYTES = 100 * 1024 * 1024
MAX_DATASETS_PER_USER = 20
_CHUNK = 1024 * 1024


class DatasetOut(BaseModel):
    id: uuid.UUID
    name: str
    original_filename: str | None
    status: str
    error: str | None
    is_sample: bool
    row_count: int
    column_count: int
    size_bytes: int
    has_cleaned: bool
    created_at: datetime


class DatasetDetail(DatasetOut):
    columns: list[dict[str, Any]]
    warnings: list[str]
    suggested_questions: list[str]
    cleaned_columns: list[dict[str, Any]] | None


def _out(d: Dataset) -> DatasetOut:
    return DatasetOut(
        id=d.id, name=d.name, original_filename=d.original_filename, status=d.status, error=d.error,
        is_sample=d.is_sample, row_count=d.row_count, column_count=d.column_count, size_bytes=d.size_bytes,
        has_cleaned=d.cleaned_table is not None, created_at=d.created_at,
    )


def get_owned(db, user, dataset_id: uuid.UUID) -> Dataset:
    """404 (not 403) for other users' datasets, so ids cannot be probed."""
    d = db.scalar(select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id))
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found.")
    return d


def _metadata(db, dataset: Dataset) -> DatasetMetadata:
    meta = db.scalar(select(DatasetMetadata).where(DatasetMetadata.dataset_id == dataset.id))
    if meta is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This dataset has not finished processing.")
    return meta


def _require_ready(dataset: Dataset) -> None:
    if dataset.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, f"The dataset is {dataset.status}. Try again when it is ready.")


# ── upload ─────────────────────────────────────────────────────────────────

def _spool_to_disk(upload: UploadFile, max_bytes: int) -> tuple[Path, int]:
    fd, name = tempfile.mkstemp(prefix="ql_upload_", suffix=".csv")
    path, size = Path(name), 0
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := upload.file.read(_CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"The file is larger than {max_bytes // (1024 * 1024)} MB.")
                out.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path, size


def _register(db, user, background: BackgroundTasks, path: Path, size: int, filename: str, name: str, is_sample: bool) -> Dataset:
    try:
        count, used = db.execute(
            select(func.count(Dataset.id), func.coalesce(func.sum(Dataset.size_bytes), 0)).where(Dataset.user_id == user.id)
        ).one()
        if count >= MAX_DATASETS_PER_USER:
            raise HTTPException(status.HTTP_409_CONFLICT, f"You can keep up to {MAX_DATASETS_PER_USER} datasets. Delete one to add another.")
        if used + size > USER_STORAGE_LIMIT_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "This upload would exceed your storage allowance. Delete a dataset first.")
        try:
            result = read_csv_file(path)
        except CsvError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    finally:
        path.unlink(missing_ok=True)

    dataset = Dataset(user_id=user.id, name=name[:200] or "Untitled dataset", original_filename=filename, source_type="csv", is_sample=is_sample, status="processing", size_bytes=size)
    db.add(dataset)
    db.commit()
    background.add_task(
        svc.process_new_dataset, dataset.id, result.frame, result.original_headers,
        {"warnings": result.warnings, "encoding": result.encoding, "delimiter": result.delimiter},
    )
    return dataset


def upload_user(request: Request, db: DbSession) -> User:
    """Who is uploading: a bearer upload token (direct-to-engine uploads) or the normal session cookie."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        user_id = upload_token.verify_token(header[7:].strip())
        user = db.get(User, user_id) if user_id else None
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "The upload link expired. Please try again.")
        return user
    return get_current_user(get_current_session(request, db), db)


UploadUser = Annotated[User, Depends(upload_user)]


@router.post("/upload-token")
def create_upload_token(user: CurrentUser) -> dict[str, Any]:
    """A five-minute, single-use token for uploading one file directly to the engine."""
    limiter.check(f"uptoken:{user.id}", limit=30, window_seconds=3600)
    return {"token": upload_token.create_token(user.id), "expires_in": upload_token.TTL_SECONDS, "max_bytes": get_settings().max_upload_mb * 1024 * 1024}

@router.post("", response_model=DatasetOut, status_code=status.HTTP_202_ACCEPTED)
def upload_dataset(
    background: BackgroundTasks, user: UploadUser, db: DbSession,
    file: Annotated[UploadFile, File()], name: Annotated[str | None, Form(max_length=200)] = None,
) -> DatasetOut:
    limiter.check(f"upload:{user.id}", limit=20, window_seconds=3600)
    filename = sanitise_filename(file.filename)
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Only .csv files are supported.")
    path, size = _spool_to_disk(file, get_settings().max_upload_mb * 1024 * 1024)
    display = (name or "").strip() or Path(filename).stem
    return _out(_register(db, user, background, path, size, filename, display, is_sample=False))


@router.post("/sample", response_model=DatasetOut, status_code=status.HTTP_202_ACCEPTED)
def create_sample_dataset(background: BackgroundTasks, user: CurrentUser, db: DbSession) -> DatasetOut:
    """Generate the synthetic banking dataset for this user and ingest it like any upload."""
    limiter.check(f"sample:{user.id}", limit=5, window_seconds=3600)
    text = generate_sample().csv_text
    fd, name = tempfile.mkstemp(prefix="ql_sample_", suffix=".csv")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as out:
        out.write(text)
    return _out(_register(db, user, background, Path(name), len(text.encode()), SAMPLE_FILENAME, SAMPLE_NAME, is_sample=True))


# ── read ───────────────────────────────────────────────────────────────────

@router.get("", response_model=list[DatasetOut])
def list_datasets(user: CurrentUser, db: DbSession) -> list[DatasetOut]:
    rows = list(db.scalars(select(Dataset).where(Dataset.user_id == user.id).order_by(Dataset.created_at.desc())))
    svc.expire_stale(db, rows)
    return [_out(d) for d in rows]


@router.get("/{dataset_id}", response_model=DatasetDetail)
def get_dataset(dataset_id: uuid.UUID, user: CurrentUser, db: DbSession) -> DatasetDetail:
    d = get_owned(db, user, dataset_id)
    svc.expire_stale(db, [d])
    meta = db.scalar(select(DatasetMetadata).where(DatasetMetadata.dataset_id == d.id))
    report = (meta.quality_report if meta else {}) or {}
    return DatasetDetail(
        **_out(d).model_dump(),
        columns=meta.columns if meta else [],
        warnings=report.get("warnings", []),
        suggested_questions=SAMPLE_QUESTIONS if d.is_sample else [],
        cleaned_columns=(report.get("cleaned") or {}).get("columns"),
    )


class RenameBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.patch("/{dataset_id}", response_model=DatasetOut)
def rename_dataset(dataset_id: uuid.UUID, body: RenameBody, user: CurrentUser, db: DbSession) -> DatasetOut:
    d = get_owned(db, user, dataset_id)
    d.name = body.name.strip()
    if not d.name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The name cannot be blank.")
    db.commit()
    return _out(d)


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(dataset_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    svc.delete_dataset(db, get_owned(db, user, dataset_id))


class RowsOut(BaseModel):
    columns: list[dict[str, str]]
    rows: list[dict[str, Any]]
    total: int
    offset: int
    limit: int
    version: str


def _schema_for(d: Dataset, meta: DatasetMetadata, version: str) -> tuple[str, dict[str, str], dict[str, str]]:
    names = {c["name"]: c["original_name"] for c in meta.columns}
    if version == "cleaned":
        cleaned = (meta.quality_report or {}).get("cleaned")
        if not d.cleaned_table or not cleaned:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no cleaned version yet.")
        return d.cleaned_table, cleaned["schema"], names
    if not d.original_table:
        raise HTTPException(status.HTTP_409_CONFLICT, "This dataset has not finished processing.")
    return d.original_table, {S.ROW_ID: "bigint", **{c["name"]: "text" for c in meta.columns}}, names


@router.get("/{dataset_id}/rows", response_model=RowsOut)
def dataset_rows(
    dataset_id: uuid.UUID, user: CurrentUser, db: DbSession,
    version: Literal["original", "cleaned"] = "original",
    offset: Annotated[int, Query(ge=0, le=10_000_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=S.MAX_PAGE_SIZE)] = 50,
    sort: Annotated[str | None, Query(max_length=80)] = None,
    desc: bool = False,
    search: Annotated[str | None, Query(max_length=200)] = None,
    filters: Annotated[str | None, Query(max_length=4000)] = None,
) -> RowsOut:
    parsed: list[dict[str, Any]] = []
    if filters:
        try:
            parsed = json.loads(filters)
            if not isinstance(parsed, list) or len(parsed) > 10 or not all(isinstance(f, dict) for f in parsed):
                raise ValueError
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid filters.") from exc
    d = get_owned(db, user, dataset_id)
    meta = _metadata(db, d)
    table, schema, names = _schema_for(d, meta, version)
    try:
        rows, total = S.query_rows(get_engine(), table, schema, offset=offset, limit=limit, sort=sort, descending=desc, search=search, filters=parsed)
    except S.QueryError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except S.TableMissing as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found.") from exc
    columns = [{"name": c, "original_name": names.get(c, c), "db_type": t} for c, t in schema.items() if c != S.ROW_ID]
    return RowsOut(columns=columns, rows=rows, total=total, offset=offset, limit=limit, version=version)


# ── quality report and cleaning ────────────────────────────────────────────

def _ops(db, dataset_id: uuid.UUID) -> list[CleaningOperation]:
    return list(db.scalars(select(CleaningOperation).where(CleaningOperation.dataset_id == dataset_id).order_by(CleaningOperation.sequence)))


def _op_out(op: CleaningOperation, issues: dict[str, dict[str, Any]]) -> dict[str, Any]:
    linked = [issues[i] for i in (op.parameters or {}).get("issue_ids", []) if i in issues]
    first = linked[0] if linked else {}
    preview = (op.parameters or {}).get("_preview") or first.get("preview")
    severities = ["high", "medium", "low", "info"]
    return {
        "id": str(op.id),
        "operation": op.operation,
        "label": C.OPERATION_LABELS.get(op.operation, op.operation),
        "column": op.column_name,
        "column_label": first.get("column_label") or op.column_name,
        "status": op.status,
        "affected_rows": op.affected_rows,
        "params": svc.op_params(op),
        "issue_ids": (op.parameters or {}).get("issue_ids", []),
        "issue_titles": [i["title"] for i in linked],
        "severity": min((i["severity"] for i in linked), key=severities.index) if linked else "low",
        "recommendation": first.get("recommendation"),
        "preview": preview,
        "applied_at": op.applied_at,
        "note": (op.parameters or {}).get("note"),
    }


@router.get("/{dataset_id}/quality")
def quality_report(dataset_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    d = get_owned(db, user, dataset_id)
    meta = _metadata(db, d)
    report = dict(meta.quality_report or {})
    op_by_issue = {i: op for op in _ops(db, d.id) for i in (op.parameters or {}).get("issue_ids", [])}
    issues = []
    for issue in report.get("issues", []):
        op = op_by_issue.get(issue["id"])
        issues.append({**issue, "operation_id": str(op.id) if op else None, "operation_status": op.status if op else None})
    report["issues"] = issues
    return report


@router.get("/{dataset_id}/cleaning")
def cleaning_operations(dataset_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    d = get_owned(db, user, dataset_id)
    meta = _metadata(db, d)
    names = {c["name"]: c["original_name"] for c in meta.columns}
    issues = {i["id"]: {**i, "column_label": names.get(i.get("column") or "", i.get("column"))} for i in (meta.quality_report or {}).get("issues", [])}
    return {"operations": [_op_out(o, issues) for o in _ops(db, d.id)], "has_cleaned": d.cleaned_table is not None, "status": d.status}


class OpUpdate(BaseModel):
    status: Literal["proposed", "approved", "rejected"] | None = None
    dayfirst: bool | None = None


def _get_op(db, d: Dataset, op_id: uuid.UUID) -> CleaningOperation:
    op = db.scalar(select(CleaningOperation).where(CleaningOperation.id == op_id, CleaningOperation.dataset_id == d.id))
    if op is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Operation not found.")
    return op


@router.patch("/{dataset_id}/cleaning/{op_id}")
def update_operation(dataset_id: uuid.UUID, op_id: uuid.UUID, body: OpUpdate, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    d = get_owned(db, user, dataset_id)
    _require_ready(d)
    meta = _metadata(db, d)
    op = _get_op(db, d, op_id)
    if body.dayfirst is not None:
        if op.operation != "parse_dates":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Only date operations have a day/month order.")
        frame = S.fetch_frame(get_engine(), d.original_table, [S.ROW_ID, op.column_name])
        params = {**svc.op_params(op), "dayfirst": body.dayfirst}
        preview = C.preview_operation(frame, op.operation, op.column_name, params)
        op.parameters = {**(op.parameters or {}), "dayfirst": body.dayfirst, "_preview": preview}
        op.affected_rows = preview["affected"]
    if body.status is not None:
        op.status = body.status
    db.commit()
    names = {c["name"]: c["original_name"] for c in meta.columns}
    issues = {i["id"]: {**i, "column_label": names.get(i.get("column") or "", i.get("column"))} for i in (meta.quality_report or {}).get("issues", [])}
    return _op_out(op, issues)


class BulkStatus(BaseModel):
    status: Literal["proposed", "approved", "rejected"]
    operation_ids: list[uuid.UUID] | None = None


@router.post("/{dataset_id}/cleaning/status")
def bulk_status(dataset_id: uuid.UUID, body: BulkStatus, user: CurrentUser, db: DbSession) -> dict[str, int]:
    d = get_owned(db, user, dataset_id)
    _require_ready(d)
    ops = _ops(db, d.id)
    if body.operation_ids is not None:
        wanted = set(body.operation_ids)
        ops = [o for o in ops if o.id in wanted]
    for op in ops:
        op.status = body.status
    db.commit()
    return {"updated": len(ops)}


@router.post("/{dataset_id}/cleaning/apply", response_model=DatasetOut, status_code=status.HTTP_202_ACCEPTED)
def apply_cleaning(dataset_id: uuid.UUID, background: BackgroundTasks, user: CurrentUser, db: DbSession) -> DatasetOut:
    """Build the cleaned table from the original using approved operations. The original is never modified."""
    limiter.check(f"clean:{user.id}", limit=30, window_seconds=3600)
    d = get_owned(db, user, dataset_id)
    _require_ready(d)
    svc.set_status(d, "cleaning")
    db.commit()
    background.add_task(svc.apply_cleaning_job, d.id)
    return _out(d)
