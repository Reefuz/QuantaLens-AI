import io
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import ConfigError, Settings, get_settings, validate_for_production
from app.core import middleware
from app.core.passwords import check_password
from app.core.rate_limit import limiter
from app.core.security import hash_token
from app.db import get_db
from app.main import create_app
from app.models import AnalysisSession, AuthSession, Conversation, Dataset, Message, User
from app.models.base import utcnow
from tests.conftest import CSRF
from tests.report_helpers import SEGMENTS, make_payload

A = {"email": "alice.analyst@example.com", "password": "correct-horse-battery"}
B = {"email": "bob.banker@example.com", "password": "another-long-password-9"}


def seed(db_engine, email, *, question="Which segment is biggest?", payload=None, status="completed", title="Segment review", offset_s=0.0, dataset=None):
    with Session(db_engine) as db:
        u = db.scalar(select(User).where(User.email == email))
        ds = db.get(Dataset, dataset) if dataset else None
        if ds is None:
            ds = Dataset(user_id=u.id, name="Bank demo", status="ready", original_table=f"ds_{uuid.uuid4().hex}", row_count=10, column_count=3, size_bytes=1000)
            db.add(ds)
            db.flush()
        conv = Conversation(user_id=u.id, dataset_id=ds.id, title=title, updated_at=utcnow())
        db.add(conv)
        db.flush()
        sess = AnalysisSession(conversation_id=conv.id, question=question, status=status, events=[], model="m")
        db.add(sess)
        db.flush()
        pl = payload if payload is not None else make_payload()
        msg = Message(conversation_id=conv.id, role="assistant", content="summary", payload=pl)
        db.add(msg)
        db.flush()
        sess.message_id = msg.id
        sess.created_at = utcnow().replace(microsecond=0) + __import__("datetime").timedelta(seconds=offset_s)
        db.commit()
        return {"dataset": ds.id, "conversation": conv.id, "session": sess.id, "message": msg.id}


@pytest.fixture()
def two(client, make_client):
    client.post("/api/auth/register", json=A)
    other = make_client()
    other.post("/api/auth/register", json=B)
    limiter.reset()
    return client, other


# ── history ────────────────────────────────────────────────────────────────

class TestHistory:
    def test_requires_auth(self, client):
        assert client.get("/api/history").status_code == 401

    def test_lists_only_own_analyses_newest_first_with_real_fields(self, two, db_engine):
        a, b = two
        old = seed(db_engine, A["email"], question="older question", offset_s=-60)
        new = seed(db_engine, A["email"], question="newer question", offset_s=0)
        seed(db_engine, B["email"], question="SECRET of bob")
        body = a.get("/api/history").json()
        assert body["total"] == 2 and [i["question"] for i in body["items"]] == ["newer question", "older question"]
        item = body["items"][0]
        assert item["dataset_name"] == "Bank demo" and item["validation_status"] == "partially_verified" and item["status"] == "completed"
        assert item["results"][0] == {"id": "r1", "label": "Total value by segment", "row_count": 4}
        assert item["sql_count"] == 1 and item["python_count"] == 1 and item["chart_count"] == 11 and item["summary"] and item["duration_ms"] == 18400
        assert item["message_id"] == str(new["message"]) and "SECRET" not in a.get("/api/history").text
        assert [i["question"] for i in b.get("/api/history").json()["items"]] == ["SECRET of bob"]

    def test_search_filters_and_treats_wildcards_literally(self, two, db_engine):
        a, _ = two
        seed(db_engine, A["email"], question="Total revenue by segment")
        seed(db_engine, A["email"], question="Churn at 100% rate")
        seed(db_engine, A["email"], question="Unusual transactions")
        q = lambda text: [i["question"] for i in a.get("/api/history", params={"q": text}).json()["items"]]  # noqa: E731
        assert q("revenue") == ["Total revenue by segment"] and q("REVENUE") == ["Total revenue by segment"]
        assert q("100%") == ["Churn at 100% rate"] and len(q("%")) == 1 and q("_") == [] and q("zzz") == []

    def test_status_dataset_and_pagination(self, two, db_engine):
        a, _ = two
        first = seed(db_engine, A["email"], question="q1", offset_s=-30)
        seed(db_engine, A["email"], question="q2", status="failed", payload={"type": "error", "error": "busy", "answer": None, "sql": [], "python": [], "charts": [], "validation": {"status": "not_validated", "checks": [], "warnings": []}}, offset_s=-20)
        seed(db_engine, A["email"], question="q3", status="clarification", payload={"type": "clarification", "question": "Which quarter?", "answer": None, "sql": [], "python": [], "charts": [], "validation": {"status": "not_validated", "checks": [], "warnings": []}}, offset_s=-10)
        seed(db_engine, A["email"], question="q4", offset_s=0)
        names = lambda **p: [i["question"] for i in a.get("/api/history", params=p).json()["items"]]  # noqa: E731
        assert names(status="failed") == ["q2"] and names(status="clarification") == ["q3"] and names(status="completed") == ["q4", "q1"]
        assert names(dataset_id=str(first["dataset"])) == ["q1"]
        page = a.get("/api/history", params={"limit": 2, "offset": 1}).json()
        assert page["total"] == 4 and [i["question"] for i in page["items"]] == ["q3", "q2"]
        fail = next(i for i in a.get("/api/history", params={"status": "failed"}).json()["items"])
        assert fail["summary"] == "busy" and fail["validation_status"] is None
        assert a.get("/api/history", params={"limit": 1000}).status_code == 422 and a.get("/api/history", params={"status": "weird"}).status_code == 422


# ── reports ────────────────────────────────────────────────────────────────

class TestReports:
    def test_pdf_xlsx_csv_downloads(self, two, db_engine):
        a, _ = two
        ids = seed(db_engine, A["email"], title='Q3 "review": <final>/../x')
        m = ids["message"]
        pdf = a.get(f"/api/reports/{m}/pdf")
        assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
        assert pdf.headers["content-disposition"] == 'attachment; filename="Q3-review-final-..-x.pdf"'.replace("-..-", "-") or "filename=" in pdf.headers["content-disposition"]
        assert "/" not in pdf.headers["content-disposition"].split("filename=")[1] and "<" not in pdf.headers["content-disposition"]
        text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
        assert "Which segment is biggest?" in text and f"{SEGMENTS[0][1]:,.2f}" in text
        x = a.get(f"/api/reports/{m}/xlsx")
        assert x.status_code == 200 and "spreadsheetml" in x.headers["content-type"] and load_workbook(io.BytesIO(x.content))["Result r1"]["B4"].value == SEGMENTS[0][1]
        c = a.get(f"/api/reports/{m}/csv")
        assert c.status_code == 200 and c.headers["content-type"].startswith("text/csv") and c.content.decode("utf-8-sig").splitlines()[1] == "Private Banking,5232418.21"
        assert a.get(f"/api/reports/{m}/csv", params={"result": "r2"}).content.decode("utf-8-sig").startswith("grp,amount")
        for r in (pdf, x, c):
            assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"

    def test_bad_result_ids(self, two, db_engine):
        a, _ = two
        m = seed(db_engine, A["email"])["message"]
        assert a.get(f"/api/reports/{m}/csv", params={"result": "r99"}).status_code == 404
        for bad in ("../x", "r1;DROP", "R1", "rr", "r1234"):
            assert a.get(f"/api/reports/{m}/csv", params={"result": bad}).status_code == 422, bad

    def test_other_users_analyses_are_not_exportable(self, two, db_engine):
        a, b = two
        m = seed(db_engine, A["email"])["message"]
        for kind in ("pdf", "xlsx", "csv"):
            assert b.get(f"/api/reports/{m}/{kind}").status_code == 404
            assert a.get(f"/api/reports/{m}/{kind}").status_code == 200
        assert a.get(f"/api/reports/{uuid.uuid4()}/pdf").status_code == 404

    def test_only_completed_answers_can_be_exported(self, two, db_engine):
        a, _ = two
        err = seed(db_engine, A["email"], payload={"type": "error", "error": "x", "answer": None})["message"]
        clar = seed(db_engine, A["email"], payload={"type": "clarification", "question": "q", "answer": None})["message"]
        assert a.get(f"/api/reports/{err}/pdf").status_code == 409 and a.get(f"/api/reports/{clar}/xlsx").status_code == 409

    def test_requires_auth_and_is_rate_limited(self, client, two, db_engine):
        a, _ = two
        m = seed(db_engine, A["email"])["message"]
        assert TestClient(client.app).get(f"/api/reports/{m}/pdf").status_code == 401
        codes = [a.get(f"/api/reports/{m}/xlsx").status_code for _ in range(42)]
        assert codes[:40] == [200] * 40 and 429 in codes[40:]


# ── settings ───────────────────────────────────────────────────────────────

class TestSettings:
    def test_account_overview(self, two):
        a, _ = two
        s = a.get("/api/settings").json()
        assert s["user"]["email"] == A["email"] and len(s["sessions"]) == 1 and s["sessions"][0]["current"] is True
        assert s["storage"]["limit_bytes"] > 0 and "ai" in s and "password" not in str(s).lower().replace("password_hash", "")

    def test_profile_update_and_clear(self, two):
        a, _ = two
        assert a.patch("/api/settings/profile", json={"display_name": "  Alice A  "}).json()["display_name"] == "Alice A"
        assert a.patch("/api/settings/profile", json={"display_name": "  "}).json()["display_name"] is None
        assert a.patch("/api/settings/profile", json={"display_name": "x" * 500}).status_code == 422

    def test_password_change_rules_and_session_revocation(self, two, make_client):
        a, _ = two
        other_device = make_client()
        assert other_device.post("/api/auth/login", json=A).status_code == 200
        assert len(a.get("/api/settings").json()["sessions"]) == 2
        new = "a-much-better-passphrase-77"
        assert a.post("/api/settings/password", json={"current_password": "wrong-password-1", "new_password": new}).status_code == 403
        assert a.post("/api/settings/password", json={"current_password": A["password"], "new_password": "short"}).status_code == 422
        assert a.post("/api/settings/password", json={"current_password": A["password"], "new_password": "password123"}).status_code == 422
        assert a.post("/api/settings/password", json={"current_password": A["password"], "new_password": "alice.analyst-2024"}).status_code == 422  # contains the email name
        assert a.post("/api/settings/password", json={"current_password": A["password"], "new_password": A["password"]}).status_code == 422
        limiter.reset()  # the five rejected attempts above count towards the hourly limit, by design
        assert a.post("/api/settings/password", json={"current_password": A["password"], "new_password": new}).status_code == 204
        assert a.get("/api/auth/me").status_code == 200 and other_device.get("/api/auth/me").status_code == 401  # this device stays, others signed out
        fresh = make_client()
        assert fresh.post("/api/auth/login", json={**A, "password": A["password"]}).status_code == 401
        assert fresh.post("/api/auth/login", json={**A, "password": new}).status_code == 200

    def test_password_change_is_rate_limited(self, two):
        a, _ = two
        codes = [a.post("/api/settings/password", json={"current_password": "wrong-password-1", "new_password": "a-much-better-passphrase-77"}).status_code for _ in range(7)]
        assert codes[:5] == [403] * 5 and codes[5] == 429

    def test_revoke_other_sessions(self, two, make_client):
        a, _ = two
        d2, d3 = make_client(), make_client()
        d2.post("/api/auth/login", json=A)
        d3.post("/api/auth/login", json=A)
        assert a.post("/api/settings/sessions/revoke-others").json() == {"revoked": 2}
        assert a.get("/api/auth/me").status_code == 200 and d2.get("/api/auth/me").status_code == 401 and d3.get("/api/auth/me").status_code == 401

    def test_delete_all_data_needs_the_password_and_keeps_the_account(self, two, db_engine, monkeypatch):
        a, b = two
        dropped = []
        monkeypatch.setattr("app.services.datasets.get_engine", lambda: None)
        monkeypatch.setattr("app.services.datasets.S.drop_table", lambda e, t: dropped.append(t))
        ids = seed(db_engine, A["email"])
        seed(db_engine, B["email"])
        assert a.post("/api/settings/delete-data", json={"password": "wrong-password-1"}).status_code == 403 and not dropped
        assert a.post("/api/settings/delete-data", json={"password": A["password"]}).json() == {"datasets_deleted": 1} and dropped
        with Session(db_engine) as db:
            assert db.scalar(select(Dataset).where(Dataset.id == ids["dataset"])) is None and db.scalar(select(User).where(User.email == A["email"])) is not None
            assert db.scalar(select(Dataset).join(User, User.id == Dataset.user_id).where(User.email == B["email"])) is not None  # untouched
        assert a.get("/api/auth/me").status_code == 200

    def test_delete_account(self, two, db_engine, monkeypatch, make_client):
        a, b = two
        monkeypatch.setattr("app.services.datasets.get_engine", lambda: None)
        monkeypatch.setattr("app.services.datasets.S.drop_table", lambda e, t: None)
        seed(db_engine, A["email"])
        assert a.post("/api/settings/delete-account", json={"password": "wrong-password-1"}).status_code == 403
        r = a.post("/api/settings/delete-account", json={"password": A["password"]})
        assert r.status_code == 204 and "ql_session" in r.headers["set-cookie"] and "Max-Age=0" in r.headers["set-cookie"]
        assert a.get("/api/auth/me").status_code == 401 and make_client().post("/api/auth/login", json=A).status_code == 401
        with Session(db_engine) as db:
            assert db.scalar(select(User).where(User.email == A["email"])) is None and db.scalar(select(AuthSession.id).join(User, User.id == AuthSession.user_id).where(User.email == A["email"])) is None
            assert db.scalar(select(User).where(User.email == B["email"])) is not None

    def test_destructive_routes_need_csrf_header_and_auth(self, two, client):
        a, _ = two
        del a.headers["X-Requested-With"]
        for path, body in (("/api/settings/delete-account", {"password": A["password"]}), ("/api/settings/delete-data", {"password": A["password"]}), ("/api/settings/password", {"current_password": "x" * 11, "new_password": "y" * 12})):
            assert a.post(path, json=body).status_code == 403
        anon = TestClient(client.app)
        anon.headers.update(CSRF)
        assert anon.get("/api/settings").status_code == 401 and anon.post("/api/settings/delete-account", json={"password": "x"}).status_code == 401


# ── hardening ──────────────────────────────────────────────────────────────

class TestHardening:
    def test_security_headers(self, client):
        r = client.get("/api/auth/me")
        assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY" and r.headers["referrer-policy"] == "no-referrer" and r.headers["cache-control"] == "no-store"
        assert "strict-transport-security" not in r.headers  # development
        assert "cache-control" not in client.get("/health").headers  # health is not an API path

    def test_hsts_only_in_production(self, monkeypatch):
        for k, v in {"APP_ENV": "production", "DATABASE_URL": "postgresql://x@h/db", "ANALYTICS_DATABASE_URL": "postgresql://ro@h/db", "AUTH_SECRET": "s" * 40, "ALLOWED_ORIGINS": "https://app.example.com"}.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()
        try:
            r = TestClient(create_app()).get("/health")
            assert "max-age" in r.headers["strict-transport-security"]
            assert TestClient(create_app()).get("/docs").status_code == 404  # API docs are not exposed in production
        finally:
            get_settings.cache_clear()

    def test_global_rate_limit_applies_to_api_only(self, client, monkeypatch):
        monkeypatch.setattr(middleware, "GLOBAL_LIMIT", 5)
        middleware.reset_global_limit()
        codes = [client.get("/api/auth/me").status_code for _ in range(8)]
        assert codes[:5] == [401] * 5 and codes[5:] == [429] * 3
        assert client.get("/health").status_code == 200
        middleware.reset_global_limit()

    def test_production_config_is_validated_without_leaking_values(self):
        good = dict(app_env="production", database_url="postgresql://owner:pw@h/db", analytics_database_url="postgresql://ro:pw2@h/db", auth_secret="s" * 40, allowed_origins="https://a.example.com")
        validate_for_production(Settings(**good, _env_file=None))
        cases = {
            "DATABASE_URL": dict(database_url=""), "ANALYTICS_DATABASE_URL is not set": dict(analytics_database_url=""),
            "different, read-only": dict(analytics_database_url="postgresql://owner:pw@h/db"), "AUTH_SECRET": dict(auth_secret="short"),
            "ALLOWED_ORIGINS": dict(allowed_origins="*"), "https://": dict(allowed_origins="http://insecure.example.com"),
        }
        for needle, change in cases.items():
            with pytest.raises(ConfigError, match=needle) as e:
                validate_for_production(Settings(**{**good, **change}, _env_file=None))
            assert "pw" not in str(e.value) and "ssssss" not in str(e.value)

    def test_session_hashes_depend_on_the_server_secret(self, monkeypatch):
        t = "token-value"
        monkeypatch.setenv("AUTH_SECRET", "a" * 40)
        get_settings.cache_clear()
        h1 = hash_token(t)
        assert hash_token(t) == h1 and len(h1) == 64
        monkeypatch.setenv("AUTH_SECRET", "b" * 40)
        get_settings.cache_clear()
        assert hash_token(t) != h1
        get_settings.cache_clear()

    @pytest.mark.parametrize("pw,email,ok", [
        ("short", None, False), ("x" * 129, None, False), ("password123", None, False), ("Password-123", None, False), ("Tr0ub4dor&3-horse", None, True), ("1234567890", None, False), ("aaaaaaaaaaaa", None, False),
        ("bob.banker-2025", "bob.banker@example.com", False), ("a-long-unique-phrase", "bob.banker@example.com", True), ("abab" * 4, None, False), ("abcdabcdabcd", None, True),
    ])
    def test_password_policy(self, pw, email, ok):
        assert (check_password(pw, email) is None) is ok

    def test_registration_uses_the_policy(self, client):
        assert client.post("/api/auth/register", json={"email": "new.person@example.com", "password": "password123"}).status_code == 422
        assert client.post("/api/auth/register", json={"email": "new.person@example.com", "password": "new.person-2025!"}).status_code == 422
        assert client.post("/api/auth/register", json={"email": "new.person@example.com", "password": "a-fine-unique-phrase"}).status_code == 201
