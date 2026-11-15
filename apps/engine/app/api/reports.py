import re
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from app.core.auth import CurrentUser, DbSession
from app.core.rate_limit import limiter
from app.models import AnalysisSession, Conversation, Dataset, Message
from app.reports.common import ReportContext, now_utc, safe_filename
from app.reports.csv_export import result_csv
from app.reports.pdf import build_pdf
from app.reports.xlsx import build_xlsx

router = APIRouter(prefix="/reports", tags=["reports"])
_RESULT_ID = re.compile(r"^r\d{1,3}$")


def load_context(db, user, message_id: uuid.UUID) -> ReportContext:
    """The analysis a report is built from. Other users' analyses are indistinguishable from missing ones."""
    row = db.execute(
        select(Message, Conversation, Dataset.name)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(Dataset, Dataset.id == Conversation.dataset_id)
        .where(Message.id == message_id, Conversation.user_id == user.id, Message.role == "assistant")
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found.")
    msg, conv, dataset_name = row
    payload = msg.payload or {}
    if payload.get("type") != "answer" or not payload.get("answer"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only completed analyses with an answer can be exported.")
    session = db.scalar(select(AnalysisSession).where(AnalysisSession.message_id == msg.id))
    return ReportContext(message_id=str(msg.id), title=conv.title, question=session.question if session else "", dataset_name=dataset_name,
                         generated_at=now_utc(), payload=payload)


def _download(data: bytes, media: str, name: str) -> Response:
    return Response(content=data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/{message_id}/pdf")
def pdf_report(message_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    limiter.check(f"report:{user.id}", limit=40, window_seconds=3600)
    ctx = load_context(db, user, message_id)
    return _download(build_pdf(ctx), "application/pdf", f"{safe_filename(ctx.title)}.pdf")


@router.get("/{message_id}/xlsx")
def excel_report(message_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    limiter.check(f"report:{user.id}", limit=40, window_seconds=3600)
    ctx = load_context(db, user, message_id)
    return _download(build_xlsx(ctx), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{safe_filename(ctx.title)}.xlsx")


@router.get("/{message_id}/csv")
def csv_report(message_id: uuid.UUID, user: CurrentUser, db: DbSession, result: Annotated[str, Query(max_length=8)] = "r1") -> Response:
    """One stored result as CSV."""
    if not _RESULT_ID.match(result):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid result id.")
    ctx = load_context(db, user, message_id)
    try:
        data = result_csv(ctx, result)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"This analysis has no result {result}.") from None
    return _download(data, "text/csv; charset=utf-8", f"{safe_filename(ctx.title)}-{result}.csv")
