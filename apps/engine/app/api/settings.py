import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from app.api.auth import UserOut
from app.config import get_settings
from app.core.auth import SESSION_COOKIE, CurrentUser, DbSession, clear_session_cookie, require_csrf_header
from app.core.passwords import check_password
from app.core.rate_limit import limiter
from app.core.security import hash_password, hash_token, verify_password
from app.models import AuthSession, Conversation, Dataset, User
from app.models.base import utcnow
from app.services import datasets as dataset_service

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_csrf_header)])
USER_STORAGE_LIMIT_BYTES = 100 * 1024 * 1024


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    user_agent: str | None
    current: bool


@router.get("")
def get_account(request: Request, user: CurrentUser, db: DbSession) -> dict:
    current = hash_token(request.cookies.get(SESSION_COOKIE, ""))
    sessions = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id).order_by(AuthSession.last_seen_at.desc())).all()
    count, used = db.execute(select(func.count(Dataset.id), func.coalesce(func.sum(Dataset.size_bytes), 0)).where(Dataset.user_id == user.id)).one()
    s = get_settings()
    return {
        "user": {"id": str(user.id), "email": user.email, "display_name": user.display_name, "created_at": user.created_at.isoformat()},
        "sessions": [SessionOut(id=x.id, created_at=x.created_at, last_seen_at=x.last_seen_at, user_agent=x.user_agent, current=x.token_hash == current).model_dump(mode="json") for x in sessions],
        "storage": {"datasets": count, "used_bytes": int(used), "limit_bytes": USER_STORAGE_LIMIT_BYTES},
        "ai": {"configured": s.ai_configured, "model": s.ai_model if s.ai_configured else None, "fallback_model": s.ai_fallback_model if s.ai_configured else None},
        "limits": {"max_upload_mb": s.max_upload_mb},
    }


class ProfileBody(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)


@router.patch("/profile", response_model=UserOut)
def update_profile(body: ProfileBody, user: CurrentUser, db: DbSession) -> User:
    user.display_name = (body.display_name or "").strip() or None
    db.commit()
    return user


class PasswordBody(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: PasswordBody, request: Request, user: CurrentUser, db: DbSession) -> None:
    """Changing the password signs out every other device."""
    limiter.check(f"pwchange:{user.id}", limit=5, window_seconds=3600)
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your current password is incorrect.")
    problem = check_password(body.new_password, user.email)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    if body.new_password == body.current_password:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a password you have not used just now.")
    user.password_hash = hash_password(body.new_password)
    keep = hash_token(request.cookies.get(SESSION_COOKIE, ""))
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.token_hash != keep))
    db.commit()


@router.post("/sessions/revoke-others")
def revoke_other_sessions(request: Request, user: CurrentUser, db: DbSession) -> dict[str, int]:
    keep = hash_token(request.cookies.get(SESSION_COOKIE, ""))
    result = db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.token_hash != keep))
    db.commit()
    return {"revoked": result.rowcount or 0}


class ConfirmBody(BaseModel):
    password: str = Field(max_length=128)


def _require_password(user: User, password: str) -> None:
    if not verify_password(user.password_hash, password):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your password is incorrect.")


def _erase_data(db, user: User) -> int:
    """Drop every dataset table, then the metadata. Conversations, analyses, logs and charts cascade."""
    owned = db.scalars(select(Dataset).where(Dataset.user_id == user.id)).all()
    for d in owned:
        dataset_service.delete_dataset(db, d)
    db.execute(delete(Conversation).where(Conversation.user_id == user.id))
    db.commit()
    return len(owned)


@router.post("/delete-data")
def delete_all_data(body: ConfirmBody, user: CurrentUser, db: DbSession) -> dict[str, int]:
    limiter.check(f"erase:{user.id}", limit=5, window_seconds=3600)
    _require_password(user, body.password)
    return {"datasets_deleted": _erase_data(db, user)}


@router.post("/delete-account", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(body: ConfirmBody, response: Response, user: CurrentUser, db: DbSession) -> Response:
    limiter.check(f"erase:{user.id}", limit=5, window_seconds=3600)
    _require_password(user, body.password)
    _erase_data(db, user)
    db.execute(delete(User).where(User.id == user.id))  # sessions and settings cascade
    db.commit()
    clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
