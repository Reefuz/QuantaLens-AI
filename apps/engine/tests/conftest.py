import os

# Must be set before app modules read settings.
os.environ.setdefault("APP_ENV", "test")
os.environ["DATABASE_URL"] = ""  # never touch the real database from unit tests

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.rate_limit import limiter
from app.db import get_db
from app.main import create_app
from app.models import Base

CSRF = {"X-Requested-With": "QuantaLens"}


@pytest.fixture()
def db_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def client(db_engine):
    limiter.reset()
    Session = sessionmaker(bind=db_engine, expire_on_commit=False)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        c.headers.update(CSRF)
        yield c


@pytest.fixture()
def make_client(db_engine):
    """Factory for additional independent clients (separate cookie jars) on the same database."""
    Session = sessionmaker(bind=db_engine, expire_on_commit=False)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    def factory() -> TestClient:
        app = create_app()
        app.dependency_overrides[get_db] = override_db
        c = TestClient(app)
        c.headers.update(CSRF)
        return c

    return factory
