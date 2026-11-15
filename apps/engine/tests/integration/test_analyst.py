"""The analyst against the real database. The model is scripted (deterministic); SQL, validation and storage are real.
Live-model tests are in test_analyst_live.py."""

import json
import time

import pytest
from sqlalchemy import select

from app.analysis import agent
from app.analysis.dataset_access import resolve_dataset
from app.analysis.sql_exec import SqlExecutionError, execute_readonly
from app.analysis.sql_guard import SqlRejected, guard_sql
from app.db import get_sessionmaker
from app.models import Dataset
from app.services import analyst
from tests.analysis_helpers import tool_call_message
from tests.integration.conftest import wait_for
from tests.test_agent_and_llm import ANSWER, ScriptedLLM

pytestmark = pytest.mark.integration

ROWS = [("Retail", 100.0, "Completed"), ("Retail", 50.5, "Completed"), ("Retail", 25.0, "Failed"), ("Business", 400.0, "Completed"),
        ("Business", 100.25, "Completed"), ("Student", 10.0, "Completed"), ("Student", 5.0, "Pending")]
CSV = "customer_segment,transaction_amount,transaction_status\n" + "\n".join(f"{a},{b},{c}" for a, b, c in ROWS) + "\n"
TOTALS = {"Retail": 175.5, "Business": 500.25, "Student": 15.0}


def make_dataset(client, wait, csv=CSV, name="Mini"):
    r = client.post("/api/datasets", files={"file": ("mini.csv", csv.encode(), "text/csv")}, data={"name": name})
    did = r.json()["id"]
    wait(client, did)
    client.post(f"/api/datasets/{did}/cleaning/apply")  # typed cleaned table (no operations approved)
    wait(client, did)
    return did


def handle_for(did):
    import uuid

    with get_sessionmaker()() as db:
        return resolve_dataset(db, db.get(Dataset, uuid.UUID(did)))


@pytest.fixture()
def mini(make_user, wait):
    client = make_user()
    did = make_dataset(client, wait)
    return client, did, handle_for(did)


def run(h, llm, question="Which segment is biggest?"):
    events = []
    return agent.run_agent(handle=h, question=question, history=[], llm=llm, emit=events.append), events


def test_real_sql_and_independent_validation(mini):
    _, did, h = mini
    assert h.version == "cleaned" and h.schema["transaction_amount"] == "double precision"
    sql = "SELECT customer_segment, SUM(transaction_amount) AS total FROM data GROUP BY 1 ORDER BY total DESC"
    checks = [
        {"type": "total_reconciliation", "label": "Segments add up", "result_id": "r1", "value_column": "total", "measure": "transaction_amount"},
        {"type": "ranking", "label": "Business is highest", "result_id": "r1", "label_column": "customer_segment", "value_column": "total", "claimed_label": "Business", "direction": "highest"},
        {"type": "value_recalculation", "label": "Business total", "aggregate": "sum", "measure": "transaction_amount", "claimed_value": 500.25,
         "filters": [{"column": "customer_segment", "op": "=", "value": "Business"}]},
        {"type": "value_recalculation", "label": "Completed row count", "aggregate": "count", "claimed_value": 5, "filters": [{"column": "transaction_status", "op": "=", "value": "Completed"}]},
        {"type": "null_exposure", "label": "Missing amounts", "column": "transaction_amount"},
    ]
    p, _ = run(h, ScriptedLLM([tool_call_message(("execute_sql", {"sql": sql, "purpose": "totals"})), tool_call_message(("validate_results", {"checks": checks})),
                               tool_call_message(("explain_results", {**ANSWER, "executive_summary": "Business has the highest total (500.25)."}))]))
    assert p["type"] == "answer"
    got = {r[0]: r[1] for r in p["results"][0]["rows"]}
    assert got == pytest.approx(TOTALS)  # real database figures
    v = {c["label"]: c for c in p["validation"]["checks"]}
    assert all(v[k]["status"] == "verified" for k in ("Segments add up", "Business is highest", "Business total", "Completed row count", "Missing amounts")), v
    assert p["validation"]["status"] == "verified" and v["Segments add up"]["recomputed"] == pytest.approx(690.75)
    assert p["sql"][0]["executed_sql"].count(f"ds_{did.replace('-', '')}_clean") == 1


def test_wrong_claims_are_caught_by_real_recalculation(mini):
    _, _, h = mini
    sql = "SELECT customer_segment, SUM(transaction_amount) AS total FROM data GROUP BY 1"
    checks = [
        {"type": "value_recalculation", "label": "Wrong total", "aggregate": "sum", "measure": "transaction_amount", "claimed_value": 999.0, "filters": [{"column": "customer_segment", "op": "=", "value": "Retail"}]},
        {"type": "ranking", "label": "Wrong winner", "result_id": "r1", "label_column": "customer_segment", "value_column": "total", "claimed_label": "Retail", "direction": "highest"},
        {"type": "total_reconciliation", "label": "Filtered differently", "result_id": "r1", "value_column": "total", "measure": "transaction_amount",
         "filters": [{"column": "transaction_status", "op": "=", "value": "Completed"}]},
    ]
    p, _ = run(h, ScriptedLLM([tool_call_message(("execute_sql", {"sql": sql, "purpose": "t"})), tool_call_message(("validate_results", {"checks": checks})), tool_call_message(("explain_results", ANSWER))]))
    v = {c["label"]: c["status"] for c in p["validation"]["checks"]}
    assert v == {"Wrong total": "failed", "Wrong winner": "failed", "Filtered differently": "failed"} and p["validation"]["status"] == "failed"


def test_filter_values_cannot_inject_sql_through_validation(mini):
    _, _, h = mini
    sql = "SELECT COUNT(*) AS n FROM data"
    evil = [{"type": "value_recalculation", "label": "inj", "aggregate": "count", "claimed_value": 0, "filters": [{"column": "transaction_status", "op": "=", "value": "x' OR '1'='1"}]},
            {"type": "value_recalculation", "label": "inj2", "aggregate": "count", "claimed_value": 0, "filters": [{"column": "transaction_status; DROP TABLE users", "op": "="}]}]
    p, _ = run(h, ScriptedLLM([tool_call_message(("execute_sql", {"sql": sql, "purpose": "t"})), tool_call_message(("validate_results", {"checks": evil})), tool_call_message(("explain_results", ANSWER))]))
    v = {c["label"]: c for c in p["validation"]["checks"]}
    assert v["inj"]["status"] == "verified" and v["inj"]["recomputed"] == 0  # the quote was a literal, matched nothing
    assert v["inj2"]["status"] == "unverified" and "does not exist" in v["inj2"]["detail"]


def test_python_on_real_data_matches_pandas(mini):
    _, _, h = mini
    code = "g = df.groupby('customer_segment')['transaction_amount'].sum().reset_index()\nresult = g"
    p, _ = run(h, ScriptedLLM([tool_call_message(("execute_python", {"code": code, "purpose": "totals"})),
                                tool_call_message(("validate_results", {"checks": [{"type": "total_reconciliation", "label": "t", "result_id": "r1", "value_column": "transaction_amount", "measure": "transaction_amount"}]})),
                                tool_call_message(("explain_results", ANSWER))]))
    assert p["python"][0]["status"] == "success" and {r[0]: r[1] for r in p["results"][0]["rows"]} == pytest.approx(TOTALS)
    assert p["validation"]["status"] == "verified"  # Python result reconciled against an independent SQL total


def test_untouched_original_data_is_labelled_and_text_totals_are_unverified(make_user, wait):
    client = make_user()
    r = client.post("/api/datasets", files={"file": ("m.csv", CSV.encode(), "text/csv")})
    did = r.json()["id"]
    wait(client, did)
    h = handle_for(did)
    assert h.version == "original" and set(h.schema.values()) == {"text"}
    sql = "SELECT customer_segment, SUM(CAST(transaction_amount AS double precision)) AS total FROM data GROUP BY 1"
    check = {"type": "total_reconciliation", "label": "t", "result_id": "r1", "value_column": "total", "measure": "transaction_amount"}
    p, _ = run(h, ScriptedLLM([tool_call_message(("execute_sql", {"sql": sql, "purpose": "t"})), tool_call_message(("validate_results", {"checks": [check]})), tool_call_message(("explain_results", ANSWER))]))
    assert p["validation"]["checks"][0]["status"] == "unverified" and "stored as text" in p["validation"]["checks"][0]["detail"]
    assert p["validation"]["status"] == "unverified" and any(w["id"] == "w-version" for w in p["validation"]["warnings"])


# ── isolation and database-level defences ──────────────────────────────────

def test_one_users_query_can_never_reach_another_users_table(make_user, wait, readonly_db):
    a, b = make_user(), make_user()
    a_id = make_dataset(a, wait, "customer_segment,transaction_amount,transaction_status\nSECRET-A,111,Completed\nSECRET-A,222,Completed\n", "A")
    b_id = make_dataset(b, wait, CSV, "B")
    ha, hb = handle_for(a_id), handle_for(b_id)

    # Documenting the design: the database role itself is NOT per-user. It could read A's table.
    assert readonly_db.execute(f'SELECT count(*) FROM qdata."{ha.table}"').fetchone()[0] == 2
    # So the SQL guard is the boundary, and from B's dataset it cannot name A's table.
    for sql in (f"SELECT * FROM qdata.{ha.table}", f"SELECT * FROM {ha.table}", f"SELECT * FROM data UNION SELECT * FROM qdata.{ha.table}",
                f"SELECT (SELECT count(*) FROM qdata.{ha.table})", f'WITH x AS (SELECT * FROM "qdata"."{ha.table}") SELECT * FROM x',
                f"SELECT query_to_xml('select * from qdata.{ha.table}', true, false, '')", "SELECT * FROM pg_catalog.pg_tables"):
        with pytest.raises(SqlRejected):
            guard_sql(sql, hb.table, hb.column_names)
    rows = execute_readonly(guard_sql("SELECT customer_segment FROM data", hb.table).executed).rows
    assert len(rows) == len(ROWS) and not any("SECRET" in str(r) for r in rows)
    # And through the agent, the model "obeying" a hostile instruction gets nothing.
    hostile = f"SELECT * FROM qdata.{ha.table}"
    p, _ = run(hb, ScriptedLLM([tool_call_message(("execute_sql", {"sql": hostile, "purpose": "as asked"})), tool_call_message(("explain_results", ANSWER))]))
    assert p["sql"][0]["status"] == "rejected" and "SECRET" not in json.dumps(p)


def test_database_denies_writes_and_runaway_queries_even_if_the_guard_were_bypassed(mini):
    _, _, h = mini
    for stmt in (f'DELETE FROM qdata."{h.table}"', f'DROP TABLE qdata."{h.table}"', f'UPDATE qdata."{h.table}" SET transaction_amount = 0',
                 "SELECT * FROM public.users", "CREATE TABLE qdata.evil (a int)", "SELECT * FROM public.auth_sessions"):
        with pytest.raises(SqlExecutionError):
            execute_readonly(stmt)
    started = time.time()
    with pytest.raises(SqlExecutionError, match="longer than 10 seconds"):
        execute_readonly("SELECT count(*) FROM generate_series(1, 100000000000)")
    assert time.time() - started < 25
    assert execute_readonly(f'SELECT count(*) FROM qdata."{h.table}"').rows[0][0] == len(ROWS)  # data intact


def test_row_limit_and_truncation_are_enforced(make_user, wait):
    client = make_user()
    csv = "n\n" + "\n".join(str(i) for i in range(1500)) + "\n"
    did = make_dataset(client, wait, csv)
    h = handle_for(did)
    res = execute_readonly(guard_sql("SELECT n FROM data", h.table).executed)
    assert res.row_count == 1000 and res.truncated
    p, _ = run(h, ScriptedLLM([tool_call_message(("execute_sql", {"sql": "SELECT n FROM data", "purpose": "all"})),
                               tool_call_message(("validate_results", {"checks": [{"type": "total_reconciliation", "label": "t", "result_id": "r1", "value_column": "n", "measure": "n"}]})),
                               tool_call_message(("explain_results", ANSWER))]))
    assert p["sql"][0]["truncated"] and p["validation"]["checks"][0]["status"] == "unverified" and any("truncated" in w["label"] for w in p["validation"]["warnings"])


# ── full HTTP flow with real storage ───────────────────────────────────────

def test_http_flow_persists_logs_and_survives_reload(make_user, wait, monkeypatch):
    client = make_user()
    did = make_dataset(client, wait)
    cid = client.post("/api/conversations", json={"dataset_id": did}).json()["id"]
    sql = "SELECT customer_segment, SUM(transaction_amount) AS total FROM data GROUP BY 1 ORDER BY 2 DESC"
    script = [tool_call_message(("inspect_dataset", {})), tool_call_message(("execute_sql", {"sql": sql, "purpose": "totals"})),
              tool_call_message(("generate_chart", {"result_id": "r1", "chart_type": "bar", "title": "Totals", "x": "customer_segment", "y": ["total"]})),
              tool_call_message(("validate_results", {"checks": [{"type": "total_reconciliation", "label": "t", "result_id": "r1", "value_column": "total", "measure": "transaction_amount"}]})),
              tool_call_message(("explain_results", ANSWER))]
    monkeypatch.setattr(analyst, "LLM_FACTORY", lambda: ScriptedLLM(script))
    from app.config import get_settings

    monkeypatch.setenv("AI_PROVIDER_API_KEY", get_settings().ai_provider_api_key.get_secret_value() or "x")
    get_settings.cache_clear()
    with client.stream("POST", f"/api/conversations/{cid}/messages", json={"content": "Which segment is biggest?"}) as r:
        assert r.status_code == 200
        events = [json.loads(line) for line in r.iter_lines() if line]
    assert events[-1]["type"] == "end" and any(e["type"] == "final" for e in events)

    detail = client.get(f"/api/conversations/{cid}").json()
    payload = detail["messages"][1]["payload"]
    assert payload["validation"]["status"] == "verified" and payload["charts"][0]["data"][0]["x"] == "Business"
    assert client.get("/api/overview").json()["analysis_count"] == 1

    from app.models import SqlExecutionLog

    with get_sessionmaker()() as db:
        log = db.scalar(select(SqlExecutionLog))
        assert log.status == "success" and "Business" not in (log.sql_text or "") and log.executed_sql and log.row_count == 3
    assert client.delete(f"/api/conversations/{cid}").status_code == 204
    with get_sessionmaker()() as db:
        assert db.scalar(select(SqlExecutionLog.id)) is None  # logs cascade with the conversation
