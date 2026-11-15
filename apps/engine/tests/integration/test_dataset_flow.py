import hashlib
import io
import json
import time

import pandas as pd
import psycopg
import pytest

from app.data import parsing as P
from app.data.csv_reader import read_csv_file
from app.data.sample import generate_sample
from tests.integration.conftest import wait_for

pytestmark = pytest.mark.integration


def table_digest(conn, table: str) -> tuple[int, str]:
    rows = conn.execute(f'SELECT * FROM qdata."{table}" ORDER BY _row_id').fetchall()
    return len(rows), hashlib.sha256(repr(rows).encode()).hexdigest()


@pytest.fixture()
def sample_dataset(make_user):
    client = make_user()
    r = client.post("/api/datasets/sample")
    assert r.status_code == 202, r.text
    dataset = wait_for(client, r.json()["id"])
    return client, dataset


def test_sample_ingest_is_faithful(sample_dataset, admin_db, tmp_path):
    client, d = sample_dataset
    gen = generate_sample()
    m = gen.manifest
    assert d["status"] == "ready" and d["is_sample"] and not d["has_cleaned"]
    assert d["row_count"] == m["total_rows"] and d["column_count"] == len(m["columns"])
    assert len(d["suggested_questions"]) == 7
    assert d["name"].startswith("Synthetic banking transactions")

    # The stored original equals the source CSV value-for-value (NULL for empty fields).
    csv_path = tmp_path / "s.csv"
    csv_path.write_text(gen.csv_text, encoding="utf-8")
    source = read_csv_file(csv_path).frame
    table = f"ds_{d['id'].replace('-', '')}"
    stored = pd.DataFrame(
        admin_db.execute(f'SELECT {", ".join(source.columns)} FROM qdata."{table}" ORDER BY _row_id').fetchall(),
        columns=source.columns, dtype=object,
    )
    pd.testing.assert_frame_equal(stored.reset_index(drop=True), source.reset_index(drop=True), check_dtype=False)
    types = {r[0] for r in admin_db.execute("SELECT data_type FROM information_schema.columns WHERE table_schema='qdata' AND table_name=%s AND column_name <> '_row_id'", (table,))}
    assert types == {"text"}  # original is never type-coerced


def test_quality_report_links_every_fix_to_an_operation(sample_dataset):
    client, d = sample_dataset
    q = client.get(f"/api/datasets/{d['id']}/quality").json()
    assert q["summary"]["rows"] == d["row_count"]
    fixable = [i for i in q["issues"] if i["fix"]]
    assert fixable and all(i["operation_id"] for i in fixable)
    assert all(i["operation_id"] is None for i in q["issues"] if not i["fix"])
    ops = client.get(f"/api/datasets/{d['id']}/cleaning").json()["operations"]
    assert {o["id"] for o in ops} >= {i["operation_id"] for i in fixable}
    assert all(o["status"] == "proposed" for o in ops)  # nothing is applied or approved automatically
    assert all(o["preview"] and o["preview"]["rows"] for o in ops)


def test_rows_pagination_sorting_search_filters(sample_dataset, admin_db):
    client, d = sample_dataset
    base = f"/api/datasets/{d['id']}/rows"
    table = f"ds_{d['id'].replace('-', '')}"
    p1 = client.get(base, params={"limit": 10}).json()
    p2 = client.get(base, params={"limit": 10, "offset": 10}).json()
    assert p1["total"] == d["row_count"] and len(p1["rows"]) == len(p2["rows"]) == 10
    assert p1["rows"][0]["_row_id"] == 1 and p2["rows"][0]["_row_id"] == 11
    assert [c["name"] for c in p1["columns"]][:2] == ["transaction_id", "customer_id"]
    assert "_row_id" not in [c["name"] for c in p1["columns"]]

    desc = client.get(base, params={"limit": 5, "sort": "transaction_id", "desc": True}).json()["rows"]
    ids = [r["transaction_id"] for r in desc]
    assert ids == sorted(ids, reverse=True)

    expected = admin_db.execute(f"SELECT count(*) FROM qdata.\"{table}\" WHERE customer_id IS NULL").fetchone()[0]
    nulls = client.get(base, params={"filters": json.dumps([{"column": "customer_id", "op": "is_null"}])}).json()
    assert nulls["total"] == expected > 0

    expected = admin_db.execute(f"SELECT count(*) FROM qdata.\"{table}\" WHERE branch = 'London'").fetchone()[0]
    eq = client.get(base, params={"filters": json.dumps([{"column": "branch", "op": "equals", "value": "London"}])}).json()
    assert eq["total"] == expected and all(r["branch"] == "London" for r in eq["rows"])

    found = client.get(base, params={"search": "txn-000007"}).json()
    assert found["total"] >= 1 and any(r["transaction_id"] == "TXN-000007" for r in found["rows"])
    combined = client.get(base, params={"search": "london", "filters": json.dumps([{"column": "transaction_status", "op": "contains", "value": "fail"}])}).json()
    assert all("london" in json.dumps(r).lower() for r in combined["rows"])


def test_sql_injection_attempts_are_inert(sample_dataset, admin_db):
    client, d = sample_dataset
    base = f"/api/datasets/{d['id']}/rows"
    table = f"ds_{d['id'].replace('-', '')}"
    before = table_digest(admin_db, table)
    attacks_sort = ['transaction_id; DROP TABLE users;--', '"', "x' OR '1'='1", "_row_id, (SELECT 1)", "transaction_id DESC; --"]
    for attack in attacks_sort:
        assert client.get(base, params={"sort": attack}).status_code == 422, attack
    for attack in ["'; DROP TABLE users; --", "' OR 1=1 --", "%", "_", "\\", "100%", '"; select pg_sleep(5); --']:
        r = client.get(base, params={"search": attack})
        assert r.status_code == 200, attack
    # % and _ are literals, not wildcards: searching "%" must not match everything
    assert client.get(base, params={"search": "%"}).json()["total"] < d["row_count"]
    bad_filters = [
        [{"column": 'branch" OR 1=1 --', "op": "equals", "value": "x"}],
        [{"column": "branch", "op": "equals; DROP", "value": "x"}],
        [{"column": "_row_id", "op": "equals", "value": "1"}],
        [{"column": "branch", "op": "gt", "value": "x"}],  # greater-than on a text column
    ]
    for f in bad_filters:
        assert client.get(base, params={"filters": json.dumps(f)}).status_code == 422, f
    # values are bound parameters
    r = client.get(base, params={"filters": json.dumps([{"column": "branch", "op": "equals", "value": "'; DROP TABLE users; --"}])})
    assert r.status_code == 200 and r.json()["total"] == 0
    assert table_digest(admin_db, table) == before
    assert admin_db.execute("SELECT to_regclass('public.users')").fetchone()[0] is not None


def test_cleaning_workflow_never_touches_the_original(sample_dataset, admin_db, readonly_db):
    client, d = sample_dataset
    did = d["id"]
    gen = generate_sample()
    original_table = f"ds_{did.replace('-', '')}"
    before = table_digest(admin_db, original_table)

    ops = client.get(f"/api/datasets/{did}/cleaning").json()["operations"]
    # reject one operation, approve the rest
    outlier_op = next(o for o in ops if o["operation"] == "flag_outliers" and o["column"] == "transaction_amount")
    assert client.post(f"/api/datasets/{did}/cleaning/status", json={"status": "approved"}).json()["updated"] == len(ops)
    rejected = client.patch(f"/api/datasets/{did}/cleaning/{outlier_op['id']}", json={"status": "rejected"}).json()
    assert rejected["status"] == "rejected"

    # day/month order override recomputes the preview from the real data
    date_op = next(o for o in ops if o["operation"] == "parse_dates")
    flipped = client.patch(f"/api/datasets/{did}/cleaning/{date_op['id']}", json={"dayfirst": False}).json()
    assert flipped["params"]["dayfirst"] is False
    assert client.patch(f"/api/datasets/{did}/cleaning/{date_op['id']}", json={"dayfirst": True}).json()["params"]["dayfirst"] is True
    assert client.patch(f"/api/datasets/{did}/cleaning/{outlier_op['id']}", json={"dayfirst": True}).status_code == 422

    # cannot view a cleaned version before one exists
    assert client.get(f"/api/datasets/{did}/rows", params={"version": "cleaned"}).status_code == 404

    r = client.post(f"/api/datasets/{did}/cleaning/apply")
    assert r.status_code == 202
    cleaned = wait_for(client, did)
    assert cleaned["has_cleaned"] and not cleaned.get("error")

    # 1. original is byte-for-byte unchanged
    assert table_digest(admin_db, original_table) == before

    # 2. the cleaned table has the expected shape
    m = gen.manifest
    assert cleaned["row_count"] == m["total_rows"]  # row_count describes the original
    rows = client.get(f"/api/datasets/{did}/rows", params={"version": "cleaned", "limit": 5}).json()
    assert rows["total"] == m["total_rows"] - m["exact_duplicate_rows_injected"]
    names = [c["name"] for c in rows["columns"]]
    assert "internal_notes" not in names and "batch_source" not in names
    assert "transaction_amount_is_outlier" not in names  # that op was rejected
    types = {c["name"]: c["db_type"] for c in rows["columns"]}
    assert types["transaction_amount"] == "double precision" and types["transaction_date"] == "date" and types["customer_age"] == "bigint"

    # 3. typed filtering works on the cleaned table, and a wrong-typed value is a clean 422
    flt = lambda v: json.dumps([{"column": "transaction_amount", "op": "gt", "value": v}])
    big = client.get(f"/api/datasets/{did}/rows", params={"version": "cleaned", "filters": flt("100000")}).json()
    assert big["total"] > 0 and all(r["transaction_amount"] > 100000 for r in big["rows"])
    assert client.get(f"/api/datasets/{did}/rows", params={"version": "cleaned", "filters": flt("abc")}).status_code == 422
    dated = client.get(f"/api/datasets/{did}/rows", params={"version": "cleaned", "sort": "transaction_date", "limit": 3}).json()["rows"]
    assert all(str(r["transaction_date"]).startswith("2024-01") for r in dated)

    # 4. totals agree with an independent recalculation from the raw text
    cleaned_table = f"{original_table}_clean"
    sql_total = admin_db.execute(f'SELECT sum(transaction_amount) FROM qdata."{cleaned_table}"').fetchone()[0]
    raw = pd.DataFrame(admin_db.execute(f'SELECT * FROM qdata."{original_table}" ORDER BY _row_id').fetchall(), columns=[c.name for c in admin_db.execute(f'SELECT * FROM qdata."{original_table}" LIMIT 0').description], dtype=object)
    raw = raw.drop_duplicates(subset=[c for c in raw.columns if c != "_row_id"])
    expected = float(P.to_number(raw["transaction_amount"]).sum())
    assert sql_total == pytest.approx(expected, rel=1e-9)
    # segment variants really merged
    segs = {r[0] for r in admin_db.execute(f'SELECT DISTINCT customer_segment FROM qdata."{cleaned_table}"')}
    assert segs == {"Retail", "Student", "Business", "Private Banking"}

    # 5. before/after report on the cleaned data
    q = client.get(f"/api/datasets/{did}/quality").json()
    assert q["cleaned"]["summary"]["rows_before"] == m["total_rows"] and q["cleaned"]["summary"]["rows_after"] == rows["total"]
    assert q["cleaned"]["summary"]["issue_counts"]["high"] < q["summary"]["issue_counts"]["high"]
    applied = client.get(f"/api/datasets/{did}/cleaning").json()["operations"]
    assert {o["status"] for o in applied} == {"applied", "rejected"}

    # 6. the read-only role can read both tables, and cannot write to either
    for t in (original_table, cleaned_table):
        assert readonly_db.execute(f'SELECT count(*) FROM qdata."{t}"').fetchone()[0] > 0
        with pytest.raises(psycopg.Error):
            readonly_db.execute(f'DELETE FROM qdata."{t}"')
        readonly_db.rollback()

    # 7. regenerating is idempotent and reflects later decisions
    assert client.patch(f"/api/datasets/{did}/cleaning/{outlier_op['id']}", json={"status": "approved"}).status_code == 200
    client.post(f"/api/datasets/{did}/cleaning/apply")
    wait_for(client, did)
    names2 = [c["name"] for c in client.get(f"/api/datasets/{did}/rows", params={"version": "cleaned", "limit": 1}).json()["columns"]]
    assert "transaction_amount_is_outlier" in names2
    assert table_digest(admin_db, original_table) == before


def test_rename_and_delete_remove_everything(sample_dataset, admin_db):
    client, d = sample_dataset
    did = d["id"]
    r = client.patch(f"/api/datasets/{did}", json={"name": "  Renamed  "})
    assert r.status_code == 200 and r.json()["name"] == "Renamed"
    assert client.patch(f"/api/datasets/{did}", json={"name": "   "}).status_code == 422
    client.post(f"/api/datasets/{did}/cleaning/apply")
    wait_for(client, did)
    t = f"ds_{did.replace('-', '')}"
    for suffix in ("", "_clean"):
        assert admin_db.execute("SELECT to_regclass(%s)", (f"qdata.{t}{suffix}",)).fetchone()[0] is not None  # present before delete
    assert client.delete(f"/api/datasets/{did}").status_code == 204
    assert admin_db.execute("SELECT to_regclass(%s)", (f"qdata.{t}",)).fetchone()[0] is None
    assert admin_db.execute("SELECT to_regclass(%s)", (f"qdata.{t}_clean",)).fetchone()[0] is None
    assert client.get(f"/api/datasets/{did}").status_code == 404
    assert client.get("/api/overview").json()["dataset_count"] == 0


def test_user_isolation(make_user, wait, readonly_db):
    a, b = make_user(), make_user()
    did = a.post("/api/datasets/sample").json()["id"]
    wait(a, did)
    for path in ["", "/rows", "/quality", "/cleaning"]:
        assert b.get(f"/api/datasets/{did}{path}").status_code == 404, path
    assert b.patch(f"/api/datasets/{did}", json={"name": "stolen"}).status_code == 404
    assert b.post(f"/api/datasets/{did}/cleaning/apply").status_code == 404
    assert b.post(f"/api/datasets/{did}/cleaning/status", json={"status": "approved"}).status_code == 404
    assert b.delete(f"/api/datasets/{did}").status_code == 404
    assert b.get("/api/datasets").json() == []
    assert b.get("/api/overview").json()["storage_bytes"] == 0
    assert a.get(f"/api/datasets/{did}").json()["name"] != "stolen"
    # app tables are unreachable from the analytics role
    with pytest.raises(psycopg.Error):
        readonly_db.execute("SELECT * FROM public.datasets")
    readonly_db.rollback()


def test_messy_custom_upload(make_user, wait):
    client = make_user()
    csv_text = (
        "Customer ID;Order Date;Amount (GBP);Region;customerID;\n"
        "1;05/01/2024;£1,200.50; north ;a;x\n"
        "2;13/02/2024;GBP 80;North;b;y\n"
        "2;13/02/2024;GBP 80;North;b;y\n"
        "3;2024-03-01;n/a;SOUTH;c\n"
        "4;Mar 5, 2024;TBC;south;d;z;extra\n"
    )
    r = client.post("/api/datasets", files={"file": ("Q1 Sales Export.csv", csv_text.encode(), "text/csv")}, data={"name": "Q1 sales"})
    assert r.status_code == 202
    d = wait(client, r.json()["id"])
    assert d["name"] == "Q1 sales" and d["row_count"] == 4  # one over-long row skipped
    assert [c["name"] for c in d["columns"]] == ["customer_id", "order_date", "amount_gbp", "region", "customer_id_2", "column_6"]
    assert any("more fields" in w for w in d["warnings"]) and any("fewer fields" in w for w in d["warnings"])
    q = client.get(f"/api/datasets/{d['id']}/quality").json()
    types = {i["type"] for i in q["issues"]}
    assert {"duplicate_rows", "inconsistent_dates", "inconsistent_categories", "currency_format"} <= types
    assert any(c["kind"] == "date" for c in d["columns"]) and any(c["kind"] == "numeric" for c in d["columns"])


def test_processing_failure_is_reported_and_cleaned_up(make_user, admin_db, monkeypatch):
    from app.data import storage

    def boom(*a, **k):
        raise RuntimeError("simulated storage failure with secret=hunter2")

    monkeypatch.setattr(storage, "create_table_from_frame", boom)
    client = make_user()
    r = client.post("/api/datasets", files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")})
    d = client.get(f"/api/datasets/{r.json()['id']}").json()
    assert d["status"] == "failed" and "hunter2" not in json.dumps(d)  # internal error text is not exposed
    assert admin_db.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='qdata' AND table_name = %s", (f"ds_{d['id'].replace('-', '')}",)).fetchone()[0] == 0
    assert client.get(f"/api/datasets/{d['id']}/rows").status_code == 409
    assert client.post(f"/api/datasets/{d['id']}/cleaning/apply").status_code == 409


def test_large_csv_100k_rows(make_user, wait, admin_db):
    n = 100_000
    rng = pd.Series(range(n))
    df = pd.DataFrame({
        "id": [f"R{i:07d}" for i in range(n)],
        "when": pd.to_datetime("2024-01-01") + pd.to_timedelta(rng % 500, unit="D"),
        "amount": (rng % 997) * 1.37,
        "segment": rng.map(lambda i: ["Retail", "retail", "Business", "Student"][i % 4]),
        "note": None,
    })
    df["when"] = df["when"].dt.strftime("%d/%m/%Y")
    payload = df.to_csv(index=False).encode()
    assert len(payload) > 3_000_000
    client = make_user()
    t0 = time.time()
    r = client.post("/api/datasets", files={"file": ("big.csv", payload, "text/csv")})
    d = wait(client, r.json()["id"], timeout=300)
    elapsed = time.time() - t0
    print(f"\n100k rows ({len(payload)/1e6:.1f} MB) ingested + profiled in {elapsed:.1f}s")
    assert d["row_count"] == n
    t = f"ds_{d['id'].replace('-', '')}"
    assert admin_db.execute(f'SELECT count(*) FROM qdata."{t}"').fetchone()[0] == n
    t1 = time.time()
    page = client.get(f"/api/datasets/{d['id']}/rows", params={"offset": 99_990, "limit": 10, "sort": "amount", "desc": True}).json()
    assert page["total"] == n and len(page["rows"]) == 10 and time.time() - t1 < 10
    q = client.get(f"/api/datasets/{d['id']}/quality").json()
    assert any(i["type"] == "empty_column" for i in q["issues"]) and any(i["type"] == "inconsistent_categories" for i in q["issues"])
    assert elapsed < 240
