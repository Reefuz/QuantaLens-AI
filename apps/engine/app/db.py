"""Database engine and session management."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    url = settings.sqlalchemy_url
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("postgresql"):
        # Neon's pooled endpoint runs PgBouncer in transaction mode, which does not
        # support server-side prepared statements.
        kwargs["connect_args"] = {"prepare_threshold": None, "connect_timeout": 15}
        kwargs.update(pool_size=5, max_overflow=5, pool_recycle=300)
    return create_engine(url, **kwargs)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one transaction-scoped session per request."""
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()
