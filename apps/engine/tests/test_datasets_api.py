"""Dataset API behaviour that does not need PostgreSQL storage: validation, auth, ownership, limits."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db import get_db
from app.main import create_app
from app.models import Dataset, User
from tests.conftest import CSRF

A = {"email": "a@example.com", "password": "a-long-password-1"}
B = {"email": "b@example.com", "password": "a-long-password-2"}


def csv_file(content: bytes | str, name="data.csv", mime="text/csv"):
    return {"file": (name, content if isinstance(content, bytes) else content.encode(), mime)}


@pytest.fixture()
def authed(client):
    client.post("/api/auth/register", json=A)
    return client


def test_all_dataset_routes_require_auth(client):
    some_id = uuid.uuid4()
    for method, path in [
        ("get", "/api/datasets"), ("post", "/api/datasets/sample"), ("get", f"/api/datasets/{some_id}"),
        ("patch", f"/api/datasets/{some_id}"), ("delete", f"/api/datasets/{some_id}"),
        ("get", f"/api/datasets/{some_id}/rows"), ("get", f"/api/datasets/{some_id}/quality"),
        ("get", f"/api/datasets/{some_id}/cleaning"), ("post", f"/api/datasets/{some_id}/cleaning/apply"),
    ]:
        assert getattr(client, method)(path).status_code == 401, (method, path)
    assert client.post("/api/datasets", files=csv_file("a\n1\n")).status_code == 401


def test_state_changing_routes_need_csrf_header(authed):
    del authed.headers["X-Requested-With"]
    assert authed.post("/api/datasets", files=csv_file("a\n1\n")).status_code == 403
    assert authed.delete(f"/api/datasets/{uuid.uuid4()}").status_code == 403


class TestUploadValidation:
    def test_wrong_extension(self, authed):
        r = authed.post("/api/datasets", files=csv_file("a,b\n1,2\n", name="data.xlsx"))
        assert r.status_code == 422 and ".csv" in r.json()["detail"]

    def test_double_extension_trick(self, authed):
        assert authed.post("/api/datasets", files=csv_file("a\n1\n", name="data.csv.exe")).status_code == 422

    def test_empty_file(self, authed):
        r = authed.post("/api/datasets", files=csv_file(""))
        assert r.status_code == 422 and "empty" in r.json()["detail"]

    def test_header_only(self, authed):
        r = authed.post("/api/datasets", files=csv_file("a,b,c\n"))
        assert r.status_code == 422 and "no data rows" in r.json()["detail"]

    def test_binary_content_with_csv_name(self, authed):
        r = authed.post("/api/datasets", files=csv_file(b"PK\x03\x04" + b"\x00" * 100, mime="text/csv"))
        assert r.status_code == 422 and "Excel" in r.json()["detail"]

    def test_failed_validation_creates_nothing(self, authed, db_engine):
        authed.post("/api/datasets", files=csv_file(""))
        authed.post("/api/datasets", files=csv_file("a,b,c\n"))
        with Session(db_engine) as db:
            assert db.scalar(select(Dataset.id)) is None

    def test_path_traversal_filename_is_harmless(self, authed):
        r = authed.post("/api/datasets", files=csv_file("", name="../../../etc/passwd.csv"))
        assert r.status_code == 422  # rejected for being empty, never touches that path

    def test_uploads_are_rate_limited(self, authed):
        codes = [authed.post("/api/datasets", files=csv_file("")).status_code for _ in range(22)]
        assert codes[:20] == [422] * 20 and 429 in codes[20:]


class TestSizeLimit:
    @pytest.fixture()
    def small_limit_client(self, db_engine, monkeypatch):
        monkeypatch.setenv("MAX_UPLOAD_MB", "1")
        get_settings.cache_clear()
        Session_ = sessionmaker(bind=db_engine, expire_on_commit=False)

        def override_db():
            db = Session_()
            try:
                yield db
            finally:
                db.close()

        app = create_app()
        app.dependency_overrides[get_db] = override_db
        c = TestClient(app)
        c.headers.update(CSRF)
        c.post("/api/auth/register", json=A)
        yield c
        get_settings.cache_clear()

    def test_oversized_upload_rejected_with_413(self, small_limit_client):
        big = b"a,b\n" + b"1,2\n" * (3 * 1024 * 1024 // 4)
        r = small_limit_client.post("/api/datasets", files=csv_file(big))
        assert r.status_code == 413

    def test_oversized_chunked_body_without_content_length(self, small_limit_client):
        def body():  # well-formed multipart, streamed with chunked transfer encoding (no Content-Length)
            yield b'--x\r\nContent-Disposition: form-data; name="file"; filename="a.csv"\r\nContent-Type: text/csv\r\n\r\n'
            for _ in range(40):
                yield b"a,b\n1,2\n" * 12_500  # 100 KB per chunk, 4 MB total
            yield b"\r\n--x--\r\n"

        r = small_limit_client.post("/api/datasets", content=body(), headers={"Content-Type": "multipart/form-data; boundary=x"})
        assert r.status_code == 413
        assert r.json()["detail"].startswith("The file is larger")


class TestOwnership:
    def _create_other_users_dataset(self, db_engine, client):
        client.post("/api/auth/register", json=A)
        other = TestClient(client.app)
        other.headers.update(CSRF)
        other.post("/api/auth/register", json=B)
        with Session(db_engine) as db:
            ub = db.scalar(select(User).where(User.email == B["email"]))
            d = Dataset(user_id=ub.id, name="secret", status="ready", original_table="ds_x", row_count=1, column_count=1)
            db.add(d)
            db.commit()
            return d.id

    def test_other_users_dataset_is_404_everywhere(self, client, db_engine):
        did = self._create_other_users_dataset(db_engine, client)
        for method, path in [
            ("get", f"/api/datasets/{did}"), ("get", f"/api/datasets/{did}/rows"), ("get", f"/api/datasets/{did}/quality"),
            ("get", f"/api/datasets/{did}/cleaning"), ("post", f"/api/datasets/{did}/cleaning/apply"),
        ]:
            assert getattr(client, method)(path).status_code == 404, path
        assert client.patch(f"/api/datasets/{did}", json={"name": "mine now"}).status_code == 404
        assert client.delete(f"/api/datasets/{did}").status_code == 404
        with Session(db_engine) as db:
            assert db.get(Dataset, did).name == "secret"  # untouched

    def test_list_only_shows_own(self, client, db_engine):
        self._create_other_users_dataset(db_engine, client)
        assert client.get("/api/datasets").json() == []

    def test_unknown_and_malformed_ids(self, authed):
        assert authed.get(f"/api/datasets/{uuid.uuid4()}").status_code == 404
        assert authed.get("/api/datasets/not-a-uuid").status_code == 422


def test_rows_param_validation(authed, db_engine):
    with Session(db_engine) as db:
        u = db.scalar(select(User))
        d = Dataset(user_id=u.id, name="mine", status="ready", original_table="ds_x", row_count=1, column_count=1)
        db.add(d)
        db.commit()
        did = d.id
    base = f"/api/datasets/{did}/rows"
    assert authed.get(base, params={"limit": 100000}).status_code == 422
    assert authed.get(base, params={"offset": -1}).status_code == 422
    assert authed.get(base, params={"filters": "not json"}).status_code == 422
    assert authed.get(base, params={"filters": '{"a":1}'}).status_code == 422
    assert authed.get(base, params={"version": "../etc"}).status_code == 422
    # no metadata row yet -> a clear conflict, not a crash
    assert authed.get(base).status_code == 409
