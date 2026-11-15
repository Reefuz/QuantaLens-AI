"""Integration tests run against the real Neon database configured in .env.

    RUN_INTEGRATION=1 python -m pytest tests/integration

Every test creates throwaway users and removes their datasets, tables and accounts afterwards.
"""

import os
import time
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.config import get_settings
from app.core.rate_limit import limiter
from app.db import get_sessionmaker
from app.main import create_app
from app.models import Dataset, User
from app.services import datasets as svc

CSRF = {"X-Requested-With": "QuantaLens"}
PASSWORD = "an-integration-password"


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_INTEGRATION") != "1":
        skip = pytest.mark.skip(reason="set RUN_INTEGRATION=1 to run against Neon")
        for item in items:
            if "integration" in str(item.fspath):
                item.add_marker(skip)


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture()
def admin_db(settings):
    """Direct owner-role connection, for verifying what is physically stored."""
    with psycopg.connect(settings.database_url_psycopg, autocommit=True) as conn:
        yield conn


@pytest.fixture()
def readonly_db(settings):
    with psycopg.connect(settings.analytics_database_url.get_secret_value(), prepare_threshold=None) as conn:
        yield conn


@pytest.fixture()
def make_user():
    """Returns a factory for logged-in clients; deletes their data afterwards."""
    emails: list[str] = []
    limiter.reset()

    def factory() -> TestClient:
        email = f"it-{uuid.uuid4().hex[:10]}@example.com"
        emails.append(email)
        client = TestClient(create_app())
        client.headers.update(CSRF)
        r = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
        assert r.status_code == 201, r.text
        client.email = email  # type: ignore[attr-defined]
        return client

    yield factory

    with get_sessionmaker()() as db:
        for email in emails:
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                continue
            for d in db.scalars(select(Dataset).where(Dataset.user_id == user.id)).all():
                svc.delete_dataset(db, d)
            db.execute(delete(User).where(User.id == user.id))
        db.commit()


def wait_for(client: TestClient, dataset_id: str, want: str = "ready", timeout: float = 180) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = client.get(f"/api/datasets/{dataset_id}").json()
        if d["status"] == want:
            return d
        if d["status"] == "failed":
            raise AssertionError(f"dataset failed: {d.get('error')}")
        time.sleep(0.5)
    raise AssertionError(f"timed out waiting for {want}")


@pytest.fixture()
def wait():
    return wait_for
