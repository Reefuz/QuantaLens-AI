"""A realistic stored analysis, built with the real chart builder so reports are tested on real chart specs."""

import copy
from datetime import datetime, timezone
from typing import Any

import numpy as np

from app.analysis import charts
from app.reports.common import ReportContext
from tests.analysis_helpers import add_sql_result, state

SEGMENTS = [("Private Banking", 5232418.21), ("Business", 4795591.17), ("Retail", 1990657.76), ("Student", 121400.5)]


def make_payload(summary: str = "Private Banking contributes the most transaction value.", extra_finding: str | None = None) -> dict[str, Any]:
    s = state()
    rng = np.random.default_rng(5)
    add_sql_result(s, ["customer_segment", "total"], [[k, v] for k, v in SEGMENTS], label="Total value by segment")
    raw = [[g, float(v)] for g in ("A", "B", "C") for v in rng.normal({"A": 10, "B": 30, "C": 55}[g], 5, 60)]
    add_sql_result(s, ["grp", "amount"], raw, label="Raw amounts")
    add_sql_result(s, ["month", "segment", "v"], [[m, sg, 100 + i * 10 + j * 40] for i, m in enumerate(["2024-01", "2024-02", "2024-03", "2024-04"]) for j, sg in enumerate(["Retail", "Business"])], label="Monthly")
    add_sql_result(s, ["day", "hour", "n"], [[d, h, i * 3 + j] for i, d in enumerate(["Mon", "Tue", "Wed"]) for j, h in enumerate(["9", "12", "15"])], label="Heat")
    a = rng.normal(0, 1, 40)
    add_sql_result(s, ["a", "b", "c"], [[float(x), float(2 * x + rng.normal(0, 0.4)), float(rng.normal())] for x in a], label="Numeric matrix")
    add_sql_result(s, ["x", "y"], [[float(x), float(3 * x + rng.normal(0, 4))] for x in a], label="Pairs")
    specs = [
        dict(result_id="r1", chart_type="bar", title="Total value by segment", x="customer_segment", y=["total"], sort="y_desc"),
        dict(result_id="r1", chart_type="hbar", title="Horizontal bars", x="customer_segment", y=["total"]),
        dict(result_id="r3", chart_type="line", title="Monthly value", x="month", y=["v"], series="segment"),
        dict(result_id="r3", chart_type="area", title="Monthly area", x="month", y=["v"], series="segment"),
        dict(result_id="r1", chart_type="pie", title="Share (pie)", x="customer_segment", y=["total"]),
        dict(result_id="r1", chart_type="donut", title="Share (donut)", x="customer_segment", y=["total"]),
        dict(result_id="r6", chart_type="scatter", title="x against y", x="x", y=["y"]),
        dict(result_id="r2", chart_type="histogram", title="Amount distribution", x="amount", bins=10),
        dict(result_id="r2", chart_type="box", title="Amount spread", x="grp", y=["amount"]),
        dict(result_id="r4", chart_type="heatmap", title="Weekday by hour", x="day", series="hour", y=["n"]),
        dict(result_id="r5", chart_type="correlation", title="Correlation matrix"),
    ]
    for sp in specs:
        spec = charts.build_chart(s, sp)
        s.charts.append(spec)
    findings = [{"finding": "Private Banking leads with £5,232,418.21.", "evidence": "r1: Private Banking 5,232,418.21", "kind": "observed"},
                {"finding": "Amount and x are strongly related (r = 0.97).", "evidence": "r6", "kind": "statistical"},
                {"finding": "Concentration may reflect a few very large accounts.", "evidence": "Outliers in the box plot", "kind": "possible_explanation"}]
    if extra_finding:
        findings.append({"finding": extra_finding, "evidence": "", "kind": "observed"})
    return {
        "type": "answer", "plan": {"steps": ["Total by segment", "Check the distribution", "Verify totals"], "assumptions": ["All statuses included"]},
        "results": [r.to_record() | {"rows_in_payload": len(r.rows)} for r in s.results.values()], "charts": s.charts,
        "sql": [{"index": 1, "sql": "SELECT customer_segment, SUM(transaction_amount) AS total\nFROM data\nGROUP BY 1\nORDER BY total DESC", "purpose": "Total by segment", "status": "success",
                 "executed_sql": 'SELECT customer_segment, SUM(transaction_amount) AS total FROM "qdata"."ds_x" AS data GROUP BY 1 ORDER BY total DESC LIMIT 1001', "tables": ["Bank"], "columns": ["customer_segment"], "notes": [],
                 "duration_ms": 41.2, "row_count": 4, "result_id": "r1", "error": None}],
        "python": [{"index": 1, "code": "from scipy import stats\nresult = stats.pearsonr(df['a'], df['b'])", "purpose": "Correlation", "status": "success", "duration_ms": 220, "stdout": "", "error": None, "packages": ["scipy"], "result_id": "r6", "limits_enforced": True}],
        "validation": {"status": "partially_verified", "checks": [
            {"id": "v1", "kind": "total_reconciliation", "label": "Segments add up", "status": "verified", "claimed": 12140067.64, "recomputed": 12140067.64, "method": "Compared with a separate aggregate.", "detail": "The parts add up.", "sql": "SELECT sum(transaction_amount) FROM data"},
            {"id": "v2", "kind": "ranking", "label": "Highest segment", "status": "unverified", "claimed": None, "recomputed": None, "method": "m", "detail": "Could not verify.", "sql": None}],
            "warnings": [{"id": "w1", "label": "Duplicates may be double counted", "status": "warning", "detail": "166 duplicate rows remain."}]},
        "dataset": {"id": "d1", "name": "Bank", "version": "cleaned", "rows": 11131}, "timeline": [], "model": "gemini-3.1-flash-lite", "duration_ms": 18400,
        "answer": {"executive_summary": summary, "key_findings": findings, "business_implications": ["Revenue is concentrated."], "recommendations": ["Review concentration risk."],
                   "limitations": ["91 amounts are missing."], "assumptions": ["All statuses included."], "chart_ids": [c["id"] for c in s.charts], "follow_up_questions": []},
    }


def make_context(**kw: Any) -> ReportContext:
    return ReportContext(message_id="m1", title=kw.pop("title", "Segment value review"), question=kw.pop("question", "Which segment contributes the most?"),
                         dataset_name=kw.pop("dataset_name", "Bank demo"), generated_at=datetime(2025, 3, 4, 9, 30, tzinfo=timezone.utc), payload=kw.pop("payload", None) or make_payload())


def with_text(payload: dict[str, Any], text: str) -> dict[str, Any]:
    p = copy.deepcopy(payload)
    p["answer"]["executive_summary"] = text
    p["answer"]["key_findings"][0]["finding"] = text
    p["answer"]["recommendations"] = [text]
    p["results"][0]["rows"][0][0] = text
    return p
