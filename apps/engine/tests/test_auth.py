from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuthSession, User

GOOD = {"email": "Analyst@Example.com", "password": "correct-horse-battery"}


def test_register_login_logout_flow(client):
    r = client.post("/api/auth/register", json=GOOD)
    assert r.status_code == 201
    assert r.json()["email"] == "analyst@example.com"  # normalised
    assert "password" not in r.text
    assert client.get("/api/auth/me").status_code == 200  # registration signs the user in

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401

    r = client.post("/api/auth/login", json=GOOD)
    assert r.status_code == 200
    assert client.get("/api/auth/me").json()["email"] == "analyst@example.com"


def test_password_is_hashed_and_token_is_hashed(client, db_engine):
    client.post("/api/auth/register", json=GOOD)
    cookie = client.cookies.get("ql_session")
    with Session(db_engine) as db:
        user = db.scalar(select(User))
        assert user.password_hash.startswith("$argon2id$")
        assert GOOD["password"] not in user.password_hash
        stored = db.scalar(select(AuthSession))
        assert stored.token_hash != cookie and len(stored.token_hash) == 64


def test_session_cookie_flags(client):
    r = client.post("/api/auth/register", json=GOOD)
    header = r.headers["set-cookie"].lower()
    assert "httponly" in header and "samesite=lax" in header


def test_wrong_password_and_unknown_user_are_indistinguishable(client):
    client.post("/api/auth/register", json=GOOD)
    client.post("/api/auth/logout")
    wrong = client.post("/api/auth/login", json={**GOOD, "password": "wrong-password-123"})
    unknown = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-123"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_duplicate_registration_rejected(client):
    assert client.post("/api/auth/register", json=GOOD).status_code == 201
    assert client.post("/api/auth/register", json=GOOD).status_code == 409


def test_weak_and_invalid_input_rejected(client):
    assert client.post("/api/auth/register", json={**GOOD, "password": "short"}).status_code == 422
    assert client.post("/api/auth/register", json={**GOOD, "email": "not-an-email"}).status_code == 422
    assert client.post("/api/auth/register", json={**GOOD, "password": "x" * 500}).status_code == 422


def test_unauthenticated_access_rejected(client):
    assert client.get("/api/auth/me").status_code == 401


def test_forged_cookie_rejected(client):
    client.cookies.set("ql_session", "not-a-real-token")
    assert client.get("/api/auth/me").status_code == 401


def test_logout_invalidates_server_side(client):
    client.post("/api/auth/register", json=GOOD)
    stolen = client.cookies.get("ql_session")
    client.post("/api/auth/logout")
    client.cookies.set("ql_session", stolen)
    assert client.get("/api/auth/me").status_code == 401


def test_csrf_header_required_for_state_changes(client):
    del client.headers["X-Requested-With"]
    assert client.post("/api/auth/register", json=GOOD).status_code == 403


def test_login_rate_limited(client):
    client.post("/api/auth/register", json=GOOD)
    client.post("/api/auth/logout")
    codes = [client.post("/api/auth/login", json={**GOOD, "password": "wrong-password-123"}).status_code for _ in range(10)]
    assert codes[:8] == [401] * 8
    assert 429 in codes[8:]


def test_users_have_independent_sessions(client, make_client):
    client.post("/api/auth/register", json=GOOD)
    other = make_client()
    other.post("/api/auth/register", json={"email": "b@example.com", "password": "another-long-password"})
    assert client.get("/api/auth/me").json()["email"] == "analyst@example.com"
    assert other.get("/api/auth/me").json()["email"] == "b@example.com"


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
