import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.core import upload_token as ut
from app.core.rate_limit import limiter
from app.db import get_db
from app.main import create_app
from tests.conftest import CSRF

A = {"email": "a.uploader@example.com", "password": "a-long-password-1"}
ORIGIN = "https://app.example.com"


@pytest.fixture(autouse=True)
def _fresh():
    ut.reset()
    yield
    ut.reset()


class TestToken:
    def test_valid_token_returns_its_user_once(self):
        uid = uuid.uuid4()
        t = ut.create_token(uid)
        assert ut.verify_token(t) == uid
        assert ut.verify_token(t) is None  # single use

    def test_expires(self):
        t = ut.create_token(uuid.uuid4(), now=1000.0)
        assert ut.verify_token(t, now=1000.0 + ut.TTL_SECONDS + 1, consume=False) is None
        assert ut.verify_token(t, now=1000.0 + ut.TTL_SECONDS - 1) is not None

    def test_tampering_is_detected(self):
        uid = uuid.uuid4()
        t = ut.create_token(uid)
        body, sig = t.split(".")
        other = ut.create_token(uuid.uuid4()).split(".")[0]
        for bad in (f"{other}.{sig}", f"{body}.{sig[:-2]}AA", f"{body}x.{sig}", body, "", "a.b", "....", f"{body}."):
            assert ut.verify_token(bad) is None, bad
        assert ut.verify_token(t) == uid  # the genuine token was not consumed by the failed attempts

    def test_signed_with_the_server_secret(self, monkeypatch):
        uid = uuid.uuid4()
        monkeypatch.setenv("AUTH_SECRET", "a" * 40)
        get_settings.cache_clear()
        t = ut.create_token(uid)
        monkeypatch.setenv("AUTH_SECRET", "b" * 40)
        get_settings.cache_clear()
        assert ut.verify_token(t) is None  # a token minted under another secret is worthless
        get_settings.cache_clear()

    def test_not_interchangeable_with_other_signed_values(self):
        import base64, hashlib, hmac, json

        key = get_settings().auth_secret.get_secret_value().encode()
        body = base64.urlsafe_b64encode(json.dumps({"u": str(uuid.uuid4()), "e": int(time.time()) + 100, "n": "x", "p": "upload"}).encode()).rstrip(b"=").decode()
        sig = base64.urlsafe_b64encode(hmac.new(key, body.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()  # no domain prefix
        assert ut.verify_token(f"{body}.{sig}") is None


@pytest.fixture()
def env(db_engine, monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", ORIGIN)
    get_settings.cache_clear()
    limiter.reset()
    ut.reset()
    Session_ = sessionmaker(bind=db_engine, expire_on_commit=False)

    def override_db():
        db = Session_()
        try:
            yield db
        finally:
            db.close()

    def client(headers=True):
        app = create_app()
        app.dependency_overrides[get_db] = override_db
        c = TestClient(app)
        if headers:
            c.headers.update(CSRF)
        return c

    yield client
    get_settings.cache_clear()


def csv_file(content: bytes | str = ""):
    return {"file": ("d.csv", content if isinstance(content, bytes) else content.encode(), "text/csv")}


class TestEndpoint:
    def test_issue_requires_login_and_csrf(self, env):
        anon = env()
        assert anon.post("/api/datasets/upload-token").status_code == 401
        c = env()
        c.post("/api/auth/register", json=A)
        del c.headers["X-Requested-With"]
        assert c.post("/api/datasets/upload-token").status_code == 403

    def test_issue_returns_token_and_limits(self, env):
        c = env()
        c.post("/api/auth/register", json=A)
        body = c.post("/api/datasets/upload-token").json()
        assert body["expires_in"] == 300 and body["max_bytes"] == 50 * 1024 * 1024 and len(body["token"]) > 40

    def test_bearer_token_authorises_an_upload_without_a_cookie(self, env):
        c = env()
        c.post("/api/auth/register", json=A)
        token = c.post("/api/datasets/upload-token").json()["token"]
        direct = env()  # a different client: no session cookie at all
        r = direct.post("/api/datasets", headers={"Authorization": f"Bearer {token}"}, files=csv_file(""))
        assert r.status_code == 422 and "empty" in r.json()["detail"]  # reached validation, so authentication passed

    def test_a_token_works_once(self, env):
        c = env()
        c.post("/api/auth/register", json=A)
        token = c.post("/api/datasets/upload-token").json()["token"]
        direct = env()
        h = {"Authorization": f"Bearer {token}"}
        assert direct.post("/api/datasets", headers=h, files=csv_file("")).status_code == 422
        assert direct.post("/api/datasets", headers=h, files=csv_file("")).status_code == 401

    @pytest.mark.parametrize("header", ["Bearer nonsense", "Bearer ", "Bearer a.b", "Basic abc", "bearer"])
    def test_bad_tokens_are_rejected(self, env, header):
        assert env().post("/api/datasets", headers={"Authorization": header}, files=csv_file("a\n1\n")).status_code == 401

    def test_an_upload_token_cannot_be_used_for_anything_else(self, env):
        c = env()
        c.post("/api/auth/register", json=A)
        token = c.post("/api/datasets/upload-token").json()["token"]
        direct = env()
        h = {"Authorization": f"Bearer {token}"}
        for method, path in [("get", "/api/datasets"), ("get", "/api/auth/me"), ("get", "/api/settings"), ("post", "/api/datasets/sample"), ("get", "/api/history"),
                             ("post", "/api/settings/delete-account"), ("post", "/api/conversations")]:
            assert getattr(direct, method)(path, headers=h).status_code in (401, 422), path
        assert direct.get("/api/datasets", headers=h).status_code == 401

    def test_the_csrf_header_is_still_required_on_the_direct_route(self, env):
        c = env()
        c.post("/api/auth/register", json=A)
        token = c.post("/api/datasets/upload-token").json()["token"]
        r = env(headers=False).post("/api/datasets", headers={"Authorization": f"Bearer {token}"}, files=csv_file("a\n1\n"))
        assert r.status_code == 403

    def test_issuing_is_rate_limited(self, env):
        c = env()
        c.post("/api/auth/register", json=A)
        codes = [c.post("/api/datasets/upload-token").status_code for _ in range(32)]
        assert codes[:30] == [200] * 30 and codes[30] == 429


class TestCors:
    """Direct upload is a cross-origin request, so the browser sends a preflight first."""

    def preflight(self, env, origin):
        return env().options("/api/datasets", headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,x-requested-with"})

    def test_the_configured_app_origin_is_allowed_with_the_needed_headers(self, env):
        r = self.preflight(env, ORIGIN)
        assert r.status_code == 200 and r.headers["access-control-allow-origin"] == ORIGIN
        allowed = r.headers["access-control-allow-headers"].lower()
        assert "authorization" in allowed and "x-requested-with" in allowed

    @pytest.mark.parametrize("origin", ["https://evil.example", "http://app.example.com", "https://app.example.com.evil.example", "null"])
    def test_other_origins_are_refused(self, env, origin):
        r = self.preflight(env, origin)
        assert r.status_code == 400 or "access-control-allow-origin" not in r.headers
