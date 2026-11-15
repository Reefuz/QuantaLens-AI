"""Excel workbook export: summary, validation, queries, one sheet per stored result, and chart data with native charts."""

from __future__ import annotations

import io
import re
from typing import Any

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.chart import AreaChart, BarChart, DoughnutChart, LineChart, PieChart, Reference, ScatterChart, Series
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.reports.common import FINDING_KIND, ReportContext

MAX_RESULT_SHEETS = 10
HEAD_FILL = PatternFill("solid", fgColor="E9EDF0")
_BAD_SHEET = re.compile(r"[\[\]:*?/\\]")
_FORMULA = re.compile(r"^[=+\-@\t\r]")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")


def sheet_name(name: str, taken: set[str]) -> str:
    base = _BAD_SHEET.sub(" ", name).strip()[:31] or "Sheet"
    candidate, n = base, 1
    while candidate.lower() in {t.lower() for t in taken}:
        n += 1
        candidate = f"{base[: 31 - len(str(n)) - 1]} {n}"
    taken.add(candidate)
    return candidate


def put(ws: Worksheet, row: int, col: int, value: Any, *, bold: bool = False, wrap: bool = False, fill: PatternFill | None = None):
    """Write a cell. Text is always stored as text: a cell such as =HYPERLINK(...) from an uploaded file must never run."""
    cell = ws.cell(row=row, column=col)
    if isinstance(value, str):
        text = ILLEGAL_CHARACTERS_RE.sub("", value)[:32000]
        cell.value = text
        if _FORMULA.match(text) and not _NUMBER.match(text):
            cell.data_type = "s"
        elif cell.data_type == "f":
            cell.data_type = "s"
    elif isinstance(value, (bool, int, float)) or value is None:
        cell.value = value
    else:
        cell.value = ILLEGAL_CHARACTERS_RE.sub("", str(value))[:32000]
    if bold:
        cell.font = Font(bold=True)
    if wrap:
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    if fill:
        cell.fill = fill
    return cell


def header(ws: Worksheet, row: int, labels: list[str]) -> None:
    for i, label in enumerate(labels, 1):
        put(ws, row, i, label, bold=True, fill=HEAD_FILL)


def widths(ws: Worksheet, spec: dict[int, float]) -> None:
    for col, w in spec.items():
        ws.column_dimensions[get_column_letter(col)].width = w


def _summary(wb: Workbook, ctx: ReportContext, taken: set[str]) -> None:
    ws = wb.active
    ws.title = sheet_name("Summary", taken)
    a, p = ctx.answer, ctx.payload
    ds = p.get("dataset") or {}
    put(ws, 1, 1, ctx.title, bold=True).font = Font(bold=True, size=14)
    rows = [
        ("Dataset", ctx.dataset_name), ("Data analysed", f"{'Cleaned' if ds.get('version') == 'cleaned' else 'Original (uncleaned)'} version, {ds.get('rows', 0):,} rows"),
        ("Generated", ctx.generated_at.strftime("%d %b %Y, %H:%M UTC")), ("Model", p.get("model") or ""), ("Validation", ctx.validation_label),
        ("Question", ctx.question), ("Executive summary", a["executive_summary"]),
    ]
    r = 3
    for k, val in rows:
        put(ws, r, 1, k, bold=True)
        put(ws, r, 2, val, wrap=True)
        r += 1
    r += 1
    put(ws, r, 1, "Key findings", bold=True)
    r += 1
    header(ws, r, ["Type", "Finding", "Evidence"])
    for f in a["key_findings"]:
        r += 1
        put(ws, r, 1, FINDING_KIND.get(f["kind"], "Observed"), wrap=True)
        put(ws, r, 2, f["finding"], wrap=True)
        put(ws, r, 3, f.get("evidence", ""), wrap=True)
    for title, items in (("Business implications", a.get("business_implications")), ("Recommendations", a.get("recommendations")),
                         ("Limitations", a.get("limitations")), ("Assumptions", a.get("assumptions"))):
        if items:
            r += 2
            put(ws, r, 1, title, bold=True)
            for item in items:
                r += 1
                put(ws, r, 2, item, wrap=True)
    widths(ws, {1: 22, 2: 90, 3: 50})


def _validation(wb: Workbook, ctx: ReportContext, taken: set[str]) -> None:
    ws = wb.create_sheet(sheet_name("Validation", taken))
    put(ws, 1, 1, f"Overall: {ctx.validation_label}", bold=True)
    header(ws, 3, ["Check", "Type", "Status", "Reported", "Recalculated", "Method", "Detail", "Independent SQL"])
    r = 3
    for c in ctx.validation["checks"]:
        r += 1
        for i, val in enumerate([c["label"], c["kind"], c["status"], c.get("claimed"), c.get("recomputed"), c["method"], c["detail"], c.get("sql") or ""], 1):
            put(ws, r, i, val, wrap=True)
    for w in ctx.validation.get("warnings", []):
        r += 1
        put(ws, r, 1, w["label"], wrap=True)
        put(ws, r, 2, "warning")
        put(ws, r, 7, w["detail"], wrap=True)
    widths(ws, {1: 38, 2: 20, 3: 12, 4: 16, 5: 16, 6: 50, 7: 70, 8: 50})


def _queries(wb: Workbook, ctx: ReportContext, taken: set[str]) -> None:
    ws = wb.create_sheet(sheet_name("Queries", taken))
    header(ws, 1, ["Kind", "#", "Purpose", "Status", "Rows", "Duration (ms)", "Code as written", "Executed statement"])
    r = 1
    for q in ctx.payload["sql"]:
        r += 1
        for i, val in enumerate(["SQL", q["index"], q.get("purpose") or "", q["status"], q.get("row_count"), q.get("duration_ms"), q["sql"], q.get("executed_sql") or ""], 1):
            put(ws, r, i, val, wrap=True)
    for q in ctx.payload["python"]:
        r += 1
        for i, val in enumerate(["Python", q["index"], q.get("purpose") or "", q["status"], None, q.get("duration_ms"), q["code"], ""], 1):
            put(ws, r, i, val, wrap=True)
    widths(ws, {1: 9, 2: 5, 3: 40, 4: 11, 5: 9, 6: 14, 7: 80, 8: 80})


def _result_sheets(wb: Workbook, ctx: ReportContext, taken: set[str]) -> None:
    for r in ctx.payload["results"][:MAX_RESULT_SHEETS]:
        ws = wb.create_sheet(sheet_name(f"Result {r['id']}", taken))
        put(ws, 1, 1, f"{r['label']} ({r['source'].upper()}). {len(r['rows']):,} of {r['row_count']:,} rows" + (" (query row limit reached)" if r["truncated"] else ""), bold=True)
        header(ws, 3, [str(c) for c in r["columns"]])
        for i, row in enumerate(r["rows"], 4):
            for j, val in enumerate(row, 1):
                put(ws, i, j, val)
        ws.freeze_panes = "A4"
        ws.auto_filter.ref = f"A3:{get_column_letter(max(len(r['columns']), 1))}{max(3 + len(r['rows']), 4)}"
        widths(ws, {j: min(40, max(12, len(str(c)) + 4)) for j, c in enumerate(r["columns"], 1)})


def _chart_block(spec: dict[str, Any]) -> tuple[list[str], list[list[Any]]]:
    d, kind = spec["data"], spec["type"]
    if kind in ("pie", "donut"):
        return ["name", "value"], [[r["name"], r["value"]] for r in d]
    if kind == "scatter":
        return (["x", "y", "series"], [[r["x"], r["y"], r.get("series", "")] for r in d])
    if kind == "box":
        cols = ["group", "min", "q1", "median", "q3", "max", "n"]
        return cols, [[r[c] for c in cols] for r in d]
    if kind in ("heatmap", "correlation"):
        return ["x", "y", "value"], [[r["x"], r["y"], r["value"]] for r in d]
    first = "label" if kind == "histogram" else "x"
    return [first, *spec["y_keys"]], [[r.get(first), *[r.get(k) for k in spec["y_keys"]]] for r in d]


def _charts(wb: Workbook, ctx: ReportContext, taken: set[str]) -> None:
    charts = ctx.payload["charts"]
    if not charts:
        return
    ws = wb.create_sheet(sheet_name("Charts", taken))
    row = 1
    for spec in charts:
        cols, rows = _chart_block(spec)
        put(ws, row, 1, f"{spec['id']}: {spec['title']} ({spec['type']}, from result {spec['result_id']})", bold=True)
        header(ws, row + 1, cols)
        for i, vals in enumerate(rows, row + 2):
            for j, val in enumerate(vals, 1):
                put(ws, i, j, val)
        n, first, last = len(rows), row + 2, row + 1 + len(rows)
        chart: Any = None
        if n and spec["type"] in ("bar", "hbar", "histogram"):
            chart = BarChart()
            chart.type = "bar" if spec["type"] == "hbar" else "col"
        elif n and spec["type"] == "line":
            chart = LineChart()
        elif n and spec["type"] == "area":
            chart = AreaChart()
        elif n and spec["type"] in ("pie", "donut"):
            chart = PieChart() if spec["type"] == "pie" else DoughnutChart()
        elif n and spec["type"] == "scatter":
            chart = ScatterChart()
            chart.style = 13
            s = Series(Reference(ws, min_col=2, min_row=first, max_row=last), Reference(ws, min_col=1, min_row=first, max_row=last), title=spec["y_label"] or "y")
            s.marker.symbol = "circle"
            s.graphicalProperties.line.noFill = True
            chart.series.append(s)
        if chart is not None:
            chart.title = spec["title"][:120]
            if spec["type"] not in ("scatter", "pie", "donut"):
                chart.add_data(Reference(ws, min_col=2, max_col=len(cols), min_row=row + 1, max_row=last), titles_from_data=True)
                chart.set_categories(Reference(ws, min_col=1, min_row=first, max_row=last))
            elif spec["type"] in ("pie", "donut"):
                chart.add_data(Reference(ws, min_col=2, min_row=row + 1, max_row=last), titles_from_data=True)
                chart.set_categories(Reference(ws, min_col=1, min_row=first, max_row=last))
            chart.height, chart.width = 8, 16
            ws.add_chart(chart, f"{get_column_letter(len(cols) + 2)}{row}")
        row = max(last, row + 18) + 2
    widths(ws, {1: 28, 2: 16, 3: 16})


def build_xlsx(ctx: ReportContext) -> bytes:
    wb = Workbook()
    taken: set[str] = set()
    _summary(wb, ctx, taken)
    _validation(wb, ctx, taken)
    _queries(wb, ctx, taken)
    _result_sheets(wb, ctx, taken)
    _charts(wb, ctx, taken)
    wb.properties.creator = "QuantaLens AI"
    wb.properties.title = ctx.title[:120]
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
