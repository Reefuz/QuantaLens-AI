"""Shared builders for analysis tests."""

import json
from typing import Any

from app.analysis.dataset_access import DatasetHandle
from app.analysis.state import RunState

PHYSICAL = "ds_" + "c" * 32


def handle(version: str = "cleaned", **over: Any) -> DatasetHandle:
    schema = {
        "customer_segment": "text", "transaction_amount": "double precision", "transaction_date": "date",
        "transaction_status": "text", "customer_age": "bigint",
    } if version == "cleaned" else {c: "text" for c in ["customer_segment", "transaction_amount", "transaction_date", "transaction_status", "customer_age"]}
    cols = [{"name": n, "original_name": n, "kind": "numeric" if t != "text" else "categorical", "missing_pct": 0.5, "distinct_count": 4,
             "samples": ["Retail", "Student"]} for n, t in schema.items()]
    base = dict(dataset_id="d1", name="Test dataset", version=version, table=PHYSICAL, schema=schema, columns=cols, row_count=1000,
                open_issues=[], duplicate_rows=0, original_row_count=1000)
    base.update(over)
    return DatasetHandle(**base)


def state(version: str = "cleaned", **over: Any) -> RunState:
    events: list[dict] = []
    s = RunState(handle=handle(version, **over), emit=events.append)
    s.events = events  # type: ignore[attr-defined]
    return s


def add_sql_result(s: RunState, columns, rows, label="test", truncated=False):
    return s.add_result(source="sql", label=label, columns=columns, rows=rows, row_count=len(rows), truncated=truncated)


def tool_call_message(*calls: tuple[str, dict], content: str | None = None) -> dict[str, Any]:
    return {
        "role": "assistant", "content": content,
        "tool_calls": [
            {"id": f"call_{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)},
             "extra_content": {"google": {"thought_signature": f"sig-{n}-{i}"}}}
            for i, (n, a) in enumerate(calls)
        ],
    }
