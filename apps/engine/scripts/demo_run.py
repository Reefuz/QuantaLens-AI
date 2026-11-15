"""Developer tool: run real questions through the real stack (Neon + the configured LLM) and print what happened.

    python -m scripts.demo_run "Which segment has the highest total transaction_amount?" [--original] [--keep]

Creates a throwaway user and the sample dataset (cleaned unless --original), asks each question in one conversation,
prints the execution timeline, the SQL/Python that ran, validation and the answer. Cleans up unless --keep.
"""

import json
import sys
import time
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import get_sessionmaker
from app.main import create_app
from app.models import Dataset, User
from app.services import datasets as svc

H = {"X-Requested-With": "QuantaLens"}


def wait_ready(c: TestClient, did: str) -> None:
    for _ in range(240):
        d = c.get(f"/api/datasets/{did}").json()
        if d["status"] == "ready":
            return
        if d["status"] == "failed":
            raise SystemExit(f"dataset failed: {d['error']}")
        time.sleep(1)
    raise SystemExit("timed out")


def show(payload: dict) -> None:
    print(f"\n=== {payload['type'].upper()}  ({payload['duration_ms'] / 1000:.1f}s, model {payload['model']}, data {payload['dataset']['version'] if payload['dataset'] else '-'})")
    for s in payload["timeline"]:
        print(f"  [{s['status']:5}] {s['title']:28} {s['detail'][:90]}  {'' if s['ms'] is None else str(s['ms']) + 'ms'}")
    for r in payload["sql"]:
        print(f"\n  SQL #{r['index']} [{r['status']}] {r['purpose']}\n    {r['sql'][:400]}" + (f"\n    ERROR: {r['error']}" if r.get("error") else ""))
    for r in payload["python"]:
        print(f"\n  PYTHON #{r['index']} [{r['status']}] {r['purpose']}\n    " + r["code"][:400].replace("\n", "\n    ") + (f"\n    ERROR: {r['error']}" if r.get("error") else ""))
    for r in payload["results"]:
        print(f"\n  RESULT {r['id']} ({r['source']}) {r['row_count']} rows: {r['columns']}  first: {r['rows'][:3]}")
    for c in payload["charts"]:
        print(f"  CHART {c['id']} {c['type']} '{c['title']}' {len(c['data'])} points from {c['result_id']}")
    v = payload["validation"]
    print(f"\n  VALIDATION: {v['status']}")
    for chk in v["checks"]:
        print(f"    {chk['status']:10} {chk['label']}  claimed={chk['claimed']} recomputed={chk['recomputed']}  {chk['detail'][:110]}")
    for w in v["warnings"]:
        print(f"    warning    {w['label']}")
    a = payload.get("answer")
    if a:
        print(f"\n  SUMMARY: {a['executive_summary']}")
        for f in a["key_findings"]:
            print(f"   - [{f['kind']}] {f['finding']}  ({f['evidence']})")
        for k in ("business_implications", "recommendations", "limitations", "assumptions"):
            for x in a[k]:
                print(f"   {k[:5]}: {x}")
    if payload["type"] == "clarification":
        print("  QUESTION:", payload["question"], payload.get("options"))
    if payload["type"] == "error":
        print("  ERROR:", payload["error"])


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    original, keep = "--original" in sys.argv, "--keep" in sys.argv
    questions = args or ["Which customer segment has the highest total transaction_amount?"]
    email = f"demo-{uuid.uuid4().hex[:8]}@example.com"
    c = TestClient(create_app())
    c.headers.update(H)
    assert c.post("/api/auth/register", json={"email": email, "password": "a-demo-password-123"}).status_code == 201
    try:
        did = c.post("/api/datasets/sample").json()["id"]
        wait_ready(c, did)
        if not original:
            c.post(f"/api/datasets/{did}/cleaning/status", json={"status": "approved"})
            c.post(f"/api/datasets/{did}/cleaning/apply")
            time.sleep(1)
            wait_ready(c, did)
        cid = c.post("/api/conversations", json={"dataset_id": did}).json()["id"]
        for q in questions:
            print(f"\n>>> {q}")
            with c.stream("POST", f"/api/conversations/{cid}/messages", json={"content": q}) as r:
                if r.status_code != 200:
                    print("HTTP", r.status_code, r.read().decode()[:300])
                    continue
                for line in r.iter_lines():
                    e = json.loads(line) if line else {}
                    if e.get("type") == "notice":
                        print("  notice:", e["message"])
                    if e.get("type") == "final":
                        show(e["message"]["payload"])
    finally:
        if not keep:
            with get_sessionmaker()() as db:
                user = db.scalar(select(User).where(User.email == email))
                for d in db.scalars(select(Dataset).where(Dataset.user_id == user.id)).all():
                    svc.delete_dataset(db, d)
                db.execute(delete(User).where(User.id == user.id))
                db.commit()


if __name__ == "__main__":
    main()
