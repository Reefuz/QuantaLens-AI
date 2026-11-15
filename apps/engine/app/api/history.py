import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.auth import CurrentUser, DbSession
from app.data.storage import _like_escape
from app.models import AnalysisSession, Conversation, Dataset, Message

router = APIRouter(tags=["history"])


class HistoryItem(BaseModel):
    session_id: uuid.UUID
    message_id: uuid.UUID | None
    conversation_id: uuid.UUID
    conversation_title: str
    dataset_id: uuid.UUID
    dataset_name: str
    question: str
    status: str  # completed | clarification | failed | running
    summary: str | None
    validation_status: str | None
    model: str | None
    duration_ms: int | None
    sql_count: int
    python_count: int
    chart_count: int
    results: list[dict[str, Any]] = []
    created_at: datetime


class HistoryPage(BaseModel):
    items: list[HistoryItem]
    total: int
    offset: int
    limit: int


@router.get("/history", response_model=HistoryPage)
def history(
    user: CurrentUser, db: DbSession,
    dataset_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: Literal["completed", "clarification", "failed", "running"] | None = None,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> HistoryPage:
    """Every analysis the user has run, newest first. Always scoped to the signed-in user."""
    where = [Conversation.user_id == user.id]
    if dataset_id:
        where.append(Conversation.dataset_id == dataset_id)
    if status:
        where.append(AnalysisSession.status == status)
    if q and q.strip():
        where.append(AnalysisSession.question.ilike(f"%{_like_escape(q.strip())}%", escape="\\"))
    base = select(AnalysisSession).join(Conversation, Conversation.id == AnalysisSession.conversation_id).where(*where)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(
        select(AnalysisSession, Conversation, Dataset.name, Message.payload)
        .join(Conversation, Conversation.id == AnalysisSession.conversation_id)
        .join(Dataset, Dataset.id == Conversation.dataset_id)
        .outerjoin(Message, Message.id == AnalysisSession.message_id)
        .where(*where).order_by(AnalysisSession.created_at.desc()).offset(offset).limit(limit)
    ).all()
    items = []
    for s, c, ds_name, payload in rows:
        p: dict[str, Any] = payload or {}
        answer = p.get("answer") or {}
        items.append(HistoryItem(
            session_id=s.id, message_id=s.message_id, conversation_id=c.id, conversation_title=c.title, dataset_id=c.dataset_id,
            dataset_name=ds_name, question=s.question, status=s.status, summary=(answer.get("executive_summary") or p.get("question") or p.get("error")),
            validation_status=(p.get("validation") or {}).get("status") if p.get("type") == "answer" else None, model=s.model,
            duration_ms=p.get("duration_ms"), sql_count=len(p.get("sql") or []), python_count=len(p.get("python") or []),
            chart_count=len(p.get("charts") or []), created_at=s.created_at,
            results=[{"id": r["id"], "label": r.get("label", ""), "row_count": r.get("row_count", 0)} for r in (p.get("results") or [])][:12],
        ))
    return HistoryPage(items=items, total=total, offset=offset, limit=limit)
