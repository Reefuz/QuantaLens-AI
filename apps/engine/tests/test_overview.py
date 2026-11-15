from sqlalchemy.orm import Session

from app.models import Conversation, Dataset, User
from app.models.base import utcnow

A = {"email": "a@example.com", "password": "a-long-password-1"}
B = {"email": "b@example.com", "password": "a-long-password-2"}


def test_overview_requires_auth(client):
    assert client.get("/api/overview").status_code == 401


def test_overview_empty_for_new_user(client):
    client.post("/api/auth/register", json=A)
    body = client.get("/api/overview").json()
    assert body["dataset_count"] == 0 and body["analysis_count"] == 0 and body["storage_bytes"] == 0
    assert body["recent_datasets"] == [] and body["recent_conversations"] == []


def test_overview_counts_only_own_data(client, make_client, db_engine):
    client.post("/api/auth/register", json=A)
    other = make_client()
    other.post("/api/auth/register", json=B)
    with Session(db_engine) as db:
        from sqlalchemy import select

        ua = db.scalar(select(User).where(User.email == A["email"]))
        ub = db.scalar(select(User).where(User.email == B["email"]))
        da = Dataset(user_id=ua.id, name="mine", status="ready", size_bytes=1000, row_count=5, column_count=2)
        db_ = Dataset(user_id=ub.id, name="theirs", status="ready", size_bytes=9999, row_count=1, column_count=1)
        db.add_all([da, db_])
        db.flush()
        db.add(Conversation(user_id=ub.id, dataset_id=db_.id, title="secret", updated_at=utcnow()))
        db.commit()
    mine = client.get("/api/overview").json()
    assert mine["dataset_count"] == 1 and mine["storage_bytes"] == 1000
    assert [d["name"] for d in mine["recent_datasets"]] == ["mine"]
    assert mine["conversation_count"] == 0
    theirs = other.get("/api/overview").json()
    assert theirs["dataset_count"] == 1 and theirs["storage_bytes"] == 9999 and theirs["conversation_count"] == 1
