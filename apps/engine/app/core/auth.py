"""Session lifecycle and the current-user dependency."""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.security import hash_token, new_session_token
from app.db import get_db
from app.models import AuthSession, User
from app.models.base import utcnow

SESSION_COOKIE = "ql_session"
SESSION_TTL = timedelta(days=7)
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "QuantaLens"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def create_session(db: Session, user: User, request: Request, response: Response) -> None:
    token = new_session_token()
    now = utcnow()
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=now + SESSION_TTL,
            last_seen_at=now,
            user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        )
    )
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=get_settings().is_production,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def require_csrf_header(request: Request) -> None:
    """State-changing requests must carry a custom header, which cross-site forms cannot set."""
    if request.method not in _SAFE_METHODS and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing or invalid request header.")


def get_current_session(request: Request, db: Annotated[Session, Depends(get_db)]) -> AuthSession:
    token = request.cookies.get(SESSION_COOKIE)
    unauthorised = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")
    if not token:
        raise unauthorised
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if session is None:
        raise unauthorised
    now = utcnow()
    if _aware(session.expires_at) <= now:
        db.delete(session)
        db.commit()
        raise unauthorised
    # Sliding expiry, written at most once a minute to avoid a write on every request.
    if now - _aware(session.last_seen_at) > timedelta(minutes=1):
        session.last_seen_at = now
        session.expires_at = now + SESSION_TTL
        db.commit()
    return session


def get_current_user(
    session: Annotated[AuthSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]
