import json
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.datasets import get_owned
from app.config import get_settings
from app.core.auth import CurrentUser, DbSession, require_csrf_header
from app.core.rate_limit import limiter
from app.models import Conversation, Dataset, Message
from app.models.base import utcnow
from app.services import analyst

router = APIRouter(tags=["analyst"], dependencies=[Depends(require_csrf_header)])


class ConversationOut(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    title: str
    updated_at: datetime
    created_at: datetime
    message_count: int = 0


def _out(c: Conversation, count: int = 0) -> ConversationOut:
    return ConversationOut(id=c.id, dataset_id=c.dataset_id, title=c.title, updated_at=c.updated_at, created_at=c.created_at, message_count=count)


def get_owned_conversation(db, user, conversation_id: uuid.UUID) -> Conversation:
    c = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user.id))
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")
    return c


@router.get("/analyst/status")
def analyst_status(user: CurrentUser) -> dict[str, Any]:
    s = get_settings()
    return {"ai_configured": s.ai_configured, "model": s.ai_model if s.ai_configured else None}


class CreateConversation(BaseModel):
    dataset_id: uuid.UUID
    title: str | None = Field(default=None, max_length=200)


@router.post("/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(body: CreateConversation, user: CurrentUser, db: DbSession) -> ConversationOut:
    limiter.check(f"newconv:{user.id}", limit=60, window_seconds=3600)
    dataset = get_owned(db, user, body.dataset_id)
    c = Conversation(user_id=user.id, dataset_id=dataset.id, title=(body.title or "").strip() or analyst.DEFAULT_TITLE, updated_at=utcnow())
    db.add(c)
    db.commit()
    return _out(c)


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(user: CurrentUser, db: DbSession, dataset_id: uuid.UUID | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 100) -> list[ConversationOut]:
    q = select(Conversation, func.count(Message.id)).outerjoin(Message, Message.conversation_id == Conversation.id).where(Conversation.user_id == user.id)
    if dataset_id:
        q = q.where(Conversation.dataset_id == dataset_id)
    rows = db.execute(q.group_by(Conversation.id).order_by(Conversation.updated_at.desc()).limit(limit)).all()
    return [_out(c, n) for c, n in rows]


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    c = get_owned_conversation(db, user, conversation_id)
    messages = db.scalars(select(Message).where(Message.conversation_id == c.id).order_by(Message.created_at, Message.role.desc()))
    dataset = db.get(Dataset, c.dataset_id)
    return {
        "conversation": _out(c).model_dump(mode="json"),
        "dataset": {"id": str(dataset.id), "name": dataset.name, "status": dataset.status, "has_cleaned": dataset.cleaned_table is not None} if dataset else None,
        "messages": [analyst.message_dict(m) for m in messages],
        "running": c.id in analyst._active,
    }


class RenameBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
def rename_conversation(conversation_id: uuid.UUID, body: RenameBody, user: CurrentUser, db: DbSession) -> ConversationOut:
    c = get_owned_conversation(db, user, conversation_id)
    title = body.title.strip()
    if not title:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The title cannot be blank.")
    c.title = title
    db.commit()
    return _out(c)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    c = get_owned_conversation(db, user, conversation_id)
    if c.id in analyst._active:
        raise HTTPException(status.HTTP_409_CONFLICT, "An analysis is still running in this conversation.")
    db.delete(c)
    db.commit()


class AskBody(BaseModel):
    content: str = Field(min_length=1, max_length=analyst.MAX_QUESTION_CHARS)


@router.post("/conversations/{conversation_id}/messages")
def ask(conversation_id: uuid.UUID, body: AskBody, user: CurrentUser, db: DbSession) -> StreamingResponse:
    """Stream the analysis as newline-delimited JSON events. Every event reports work that actually happened."""
    c = get_owned_conversation(db, user, conversation_id)
    question = body.content.strip()
    if not question:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Ask a question.")
    if not get_settings().ai_configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The AI analyst is not configured on this server. Set AI_PROVIDER_API_KEY on the engine.")
    dataset = db.get(Dataset, c.dataset_id)
    if dataset is None or dataset.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "The dataset is not ready for analysis yet.")
    limiter.check(f"ask:{user.id}", limit=30, window_seconds=3600)
    if not analyst.try_acquire(c.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "An analysis is already running in this conversation.")
    try:
        events = analyst.start_stream(c.id, question)
    except Exception:
        analyst.release(c.id)
        raise

    def stream():
        for event in events:
            yield json.dumps(event, default=str) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})
