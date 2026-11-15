import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.auth import CurrentUser, DbSession
from app.models import AnalysisSession, Conversation, Dataset

router = APIRouter(tags=["overview"])


class DatasetBrief(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    row_count: int
    column_count: int
    is_sample: bool
    created_at: datetime


class ConversationBrief(BaseModel):
    id: uuid.UUID
    title: str
    dataset_id: uuid.UUID
    updated_at: datetime


class Overview(BaseModel):
    dataset_count: int
    analysis_count: int
    conversation_count: int
    storage_bytes: int
    storage_limit_bytes: int
    recent_datasets: list[DatasetBrief]
    recent_conversations: list[ConversationBrief]


# Per-user soft quota. Neon's free tier is 0.5 GB in total, shared by all users.
USER_STORAGE_LIMIT_BYTES = 100 * 1024 * 1024


@router.get("/overview", response_model=Overview)
def overview(user: CurrentUser, db: DbSession) -> Overview:
    dataset_count, storage = db.execute(
        select(func.count(Dataset.id), func.coalesce(func.sum(Dataset.size_bytes), 0)).where(Dataset.user_id == user.id)
    ).one()
    conversation_count = db.scalar(select(func.count(Conversation.id)).where(Conversation.user_id == user.id)) or 0
    analysis_count = (
        db.scalar(
            select(func.count(AnalysisSession.id))
            .join(Conversation, Conversation.id == AnalysisSession.conversation_id)
            .where(Conversation.user_id == user.id)
        )
        or 0
    )
    datasets = db.scalars(
        select(Dataset).where(Dataset.user_id == user.id).order_by(Dataset.created_at.desc()).limit(5)
    ).all()
    conversations = db.scalars(
        select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.updated_at.desc()).limit(5)
    ).all()
    return Overview(
        dataset_count=dataset_count,
        analysis_count=analysis_count,
        conversation_count=conversation_count,
        storage_bytes=int(storage),
        storage_limit_bytes=USER_STORAGE_LIMIT_BYTES,
        recent_datasets=[DatasetBrief.model_validate(d, from_attributes=True) for d in datasets],
        recent_conversations=[ConversationBrief.model_validate(c, from_attributes=True) for c in conversations],
    )
