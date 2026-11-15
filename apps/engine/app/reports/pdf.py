"""PDF report. Charts are drawn with reportlab's own vector graphics from the stored chart data."""

from __future__ import annotations

import io
import textwrap
from typing import Any
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.lineplots import ScatterPlot
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Group, Line, Rect, String
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle

from app.reports.common import FINDING_KIND, ReportContext, clean_text, fmt_number, referenced_result_ids

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN
INK = colors.HexColor("#1f2430")
MUTED = colors.HexColor("#5f6673")
RULE = colors.HexColor("#d9dbe0")
BRAND = colors.HexColor("#2a7f86")
PALETTE = [colors.HexColor(c) for c in ("#2a7f86", "#6c82b5", "#c79a3b", "#b5584f", "#7a8591", "#5b9a68", "#a2639b", "#b88e5e")]
STATUS_COLOUR = {"verified": "#2e7d4f", "failed": "#b3261e", "unverified": "#5f6673", "warning": "#9a6b00", "partially_verified": "#9a6b00", "not_validated": "#5f6673"}
MAX_TABLE_ROWS = 15
MAX_RESULT_TABLES = 6


def t(value: Any, limit: int = 20000) -> str:
    """Text for the standard PDF fonts (Windows-1252). Unsupported characters become '?' instead of broken boxes."""
    return clean_text(value, limit).encode("cp1252", "replace").decode("cp1252")


def para_text(value: Any) -> str:
    return escape(t(value))


def compact(v: Any) -> str:
    if not isinstance(v, (int, float)):
        return str(v)
    a = abs(v)
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if a >= div:
            return f"{v / div:.3g}{suffix}"
    return f"{v:.4g}" if a < 1 and a != 0 else f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    def mk(name: str, **kw: Any) -> ParagraphStyle:
        return ParagraphStyle(name, parent=base, fontName=kw.pop("fontName", "Helvetica"), textColor=kw.pop("textColor", INK), **kw)
    return {
        "title": mk("title", fontName="Helvetica-Bold", fontSize=20, leading=24, spaceAfter=4),
        "h2": mk("h2", fontName="Helvetica-Bold", fontSize=11.5, leading=14, spaceBefore=14, spaceAfter=5, textColor=BRAND),
        "h3": mk("h3", fontName="Helvetica-Bold", fontSize=9.5, leading=12, spaceBefore=6, spaceAfter=2),
        "body": mk("body", fontSize=9.5, leading=13.5, spaceAfter=3),
        "small": mk("small", fontSize=8, leading=10.5, textColor=MUTED),
        "cell": mk("cell", fontSize=8, leading=10),
        "cellb": mk("cellb", fontName="Helvetica-Bold", fontSize=8, leading=10),
        "code": ParagraphStyle("code", fontName="Courier", fontSize=7.4, leading=9.2, textColor=INK, backColor=colors.HexColor("#f3f4f6"), borderPadding=5, spaceBefore=2, spaceAfter=6, leftIndent=4, rightIndent=4),
        "bullet": mk("bullet", fontSize=9.5, leading=13.5, leftIndent=11, bulletIndent=2, spaceAfter=2),
    }


# ── charts ─────────────────────────────────────────────────────────────────

def _num(v: Any) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def _frame(spec: dict[str, Any], w: float, h: float) -> Drawing:
    d = Drawing(w, h)
    d.add(String(0, h - 9, t(spec["title"], 110), fontName="Helvetica-Bold", fontSize=9.5, fillColor=INK))
    return d


def _axis_titles(d: Drawing, spec: dict[str, Any], w: float, h: float) -> None:
    if spec.get("x_label"):
        d.add(String(w / 2, 2, t(spec["x_label"], 60), fontName="Helvetica", fontSize=7.5, fillColor=MUTED, textAnchor="middle"))
    if spec.get("y_label"):
        g = Group(String(0, 0, t(spec["y_label"], 50), fontName="Helvetica", fontSize=7.5, fillColor=MUTED, textAnchor="middle"))
        g.translate(8, h / 2)
        g.rotate(90)
        d.add(g)


def _style_axes(c: Any) -> None:
    c.valueAxis.labelTextFormat = compact
    c.valueAxis.labels.fontSize = 7
    c.categoryAxis.labels.fontSize = 7
    c.valueAxis.strokeColor = RULE
    c.categoryAxis.strokeColor = RULE
    c.valueAxis.gridStrokeColor = RULE
    c.valueAxis.visibleGrid = 1


def _legend(d: Drawing, names: list[str], x: float, y: float) -> None:
    lg = Legend()
    lg.x, lg.y, lg.fontSize, lg.fontName = x, y, 7, "Helvetica"
    lg.alignment, lg.columnMaximum, lg.dxTextSpace, lg.boxAnchor = "right", 10, 4, "nw"
    lg.colorNamePairs = [(PALETTE[i % len(PALETTE)], t(n, 24)) for i, n in enumerate(names[:10])]
    d.add(lg)


def cartesian(spec: dict[str, Any], w: float, h: float) -> Drawing:
    d = _frame(spec, w, h)
    data = spec["data"]
    keys = spec["y_keys"]
    names = [t(r.get("label", r.get("x", "")), 16) for r in data]
    series = [[_num(r.get(k)) for r in data] for k in keys]
    legend_w = 90 if len(keys) > 1 else 0
    kind = spec["type"]
    if kind == "hbar":
        c = HorizontalBarChart()
        c.x, c.y, c.width, c.height = 78, 22, w - 78 - 20 - legend_w, h - 44
    elif kind in ("line", "area"):
        c = HorizontalLineChart()
        c.x, c.y, c.width, c.height = 44, 34, w - 56 - legend_w, h - 56
    else:
        c = VerticalBarChart()
        c.x, c.y, c.width, c.height = 44, 34, w - 56 - legend_w, h - 56
    c.data = series
    c.categoryAxis.categoryNames = names
    _style_axes(c)
    if kind not in ("hbar",) and len(names) > 6:
        c.categoryAxis.labels.angle = 35
        c.categoryAxis.labels.boxAnchor = "ne"
        c.categoryAxis.labels.dy = -2
        c.y += 14
        c.height -= 14
    if kind in ("line", "area"):
        for i in range(len(series)):
            c.lines[i].strokeColor = PALETTE[i % len(PALETTE)]
            c.lines[i].strokeWidth = 1.6
            if len(names) <= 24:
                c.lines[i].symbol = makeMarker("FilledCircle", size=3, fillColor=PALETTE[i % len(PALETTE)])
    else:
        c.barSpacing = 1
        c.groupSpacing = 0 if kind == "histogram" else 6
        for i in range(len(series)):
            c.bars[i].fillColor = PALETTE[i % len(PALETTE)]
            c.bars[i].strokeColor = None
        if len(names) <= 12 and len(series) == 1:
            c.barLabelFormat = compact
            c.barLabels.fontSize = 6.5
            c.barLabels.nudge = 6 if kind != "hbar" else -2
            c.barLabels.dx = 0 if kind != "hbar" else 14
    d.add(c)
    if legend_w:
        _legend(d, keys, w - legend_w + 6, h - 24)
    # On a horizontal bar chart the categories run down the page, so the two axis titles trade places.
    _axis_titles(d, {**spec, "x_label": spec.get("y_label", ""), "y_label": spec.get("x_label", "")} if kind == "hbar" else spec, w, h)
    return d


def pie(spec: dict[str, Any], w: float, h: float) -> Drawing:
    d = _frame(spec, w, h)
    rows = spec["data"]
    total = sum(_num(r.get("value")) for r in rows) or 1
    p = Pie()
    size = min(h - 40, w * 0.42)
    p.x, p.y, p.width, p.height = 30, 14, size, size
    p.data = [_num(r.get("value")) for r in rows]
    p.labels = None
    p.slices.strokeColor = colors.white
    p.slices.strokeWidth = 0.8
    for i in range(len(rows)):
        p.slices[i].fillColor = PALETTE[i % len(PALETTE)]
    if spec["type"] == "donut" and hasattr(p, "innerRadiusFraction"):
        p.innerRadiusFraction = 0.55
    d.add(p)
    lg = Legend()
    lg.x, lg.y, lg.fontSize, lg.fontName, lg.alignment = size + 60, h - 30, 7.5, "Helvetica", "right"
    lg.columnMaximum, lg.dxTextSpace, lg.boxAnchor = 10, 5, "nw"
    lg.colorNamePairs = [(PALETTE[i % len(PALETTE)], f"{t(r.get('name'), 22)}  {_num(r.get('value')) / total * 100:.1f}%  ({compact(_num(r.get('value')))})") for i, r in enumerate(rows)]
    d.add(lg)
    return d


def scatter(spec: dict[str, Any], w: float, h: float) -> Drawing:
    d = _frame(spec, w, h)
    groups = spec.get("series_values") or [None]
    sp = ScatterPlot()
    sp.x, sp.y, sp.width, sp.height = 44, 34, w - 60 - (80 if len(groups) > 1 else 0), h - 58
    sp.data = [[(_num(r["x"]), _num(r["y"])) for r in spec["data"] if g is None or r.get("series") == g] or [(0, 0)] for g in groups]
    sp.joinedLines = 0
    for i in range(len(groups)):
        sp.lines[i].strokeColor = None
        sp.lines[i].symbol = makeMarker("FilledCircle", size=3, fillColor=PALETTE[i % len(PALETTE)])
    for ax in (sp.xValueAxis, sp.yValueAxis):
        ax.labelTextFormat = compact
        ax.labels.fontSize = 7
        ax.strokeColor = RULE
        ax.gridStrokeColor = RULE
        ax.visibleGrid = 1
    d.add(sp)
    if len(groups) > 1:
        _legend(d, [str(g) for g in groups], w - 76, h - 24)
    _axis_titles(d, spec, w, h)
    return d


def box(spec: dict[str, Any], w: float, h: float) -> Drawing:
    d = _frame(spec, w, h)
    rows = spec["data"]
    vals = [_num(r[k]) for r in rows for k in ("min", "max")] + [_num(o) for r in rows for o in r.get("outliers", [])]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo or 1) * 0.05
    L, B, T, R = 46, 30, 26, 14
    ph = h - T - B
    y = lambda v: B + ph * (_num(v) - (lo - pad)) / (hi - lo + 2 * pad)  # noqa: E731
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        d.add(Line(L, y(v), w - R, y(v), strokeColor=RULE, strokeWidth=0.4))
        d.add(String(L - 4, y(v) - 2.5, compact(v), fontName="Helvetica", fontSize=7, fillColor=MUTED, textAnchor="end"))
    slot = (w - L - R) / len(rows)
    bw = min(34, slot * 0.5)
    for i, r in enumerate(rows):
        cx = L + slot * (i + 0.5)
        col = PALETTE[i % len(PALETTE)]
        d.add(Line(cx, y(r["min"]), cx, y(r["q1"]), strokeColor=col, strokeWidth=1))
        d.add(Line(cx, y(r["q3"]), cx, y(r["max"]), strokeColor=col, strokeWidth=1))
        d.add(Rect(cx - bw / 2, y(r["q1"]), bw, max(1, y(r["q3"]) - y(r["q1"])), fillColor=colors.Color(col.red, col.green, col.blue, alpha=0.25), strokeColor=col, strokeWidth=1))
        d.add(Line(cx - bw / 2, y(r["median"]), cx + bw / 2, y(r["median"]), strokeColor=INK, strokeWidth=1.6))
        for o in r.get("outliers", []):
            d.add(Rect(cx - 1.2, y(o) - 1.2, 2.4, 2.4, fillColor=None, strokeColor=col, strokeWidth=0.6))
        d.add(String(cx, 18, t(r["group"], 16), fontName="Helvetica", fontSize=7, fillColor=INK, textAnchor="middle"))
        d.add(String(cx, 9, f"n={r['n']}", fontName="Helvetica", fontSize=6.5, fillColor=MUTED, textAnchor="middle"))
    _axis_titles(d, {"x_label": "", "y_label": spec.get("y_label", "")}, w, h)
    return d


def heat(spec: dict[str, Any], w: float, h: float) -> Drawing:
    xs, ys = spec.get("x_values", []), spec.get("y_values", [])
    cell = {(r["x"], r["y"]): r["value"] for r in spec["data"]}
    corr = spec["type"] == "correlation"
    mx = max([abs(_num(v)) for v in cell.values()] + [1e-9])
    cw = min(52, (w - 100) / max(len(xs), 1))
    ch = min(20, (h - 60) / max(len(ys), 1))
    d = Drawing(w, 44 + ch * len(ys) + 8)
    H = d.height
    d.add(String(0, H - 9, t(spec["title"], 110), fontName="Helvetica-Bold", fontSize=9.5, fillColor=INK))
    for i, x in enumerate(xs):
        d.add(String(90 + cw * i + cw / 2, H - 28, t(x, 10), fontName="Helvetica", fontSize=6.8, fillColor=MUTED, textAnchor="middle"))
    for j, yv in enumerate(ys):
        top = H - 36 - ch * (j + 1)
        d.add(String(84, top + ch / 2 - 2.5, t(yv, 16), fontName="Helvetica", fontSize=6.8, fillColor=MUTED, textAnchor="end"))
        for i, xv in enumerate(xs):
            v = cell.get((xv, yv))
            if v is None:
                fill = colors.white
            elif corr:
                a = min(1.0, abs(_num(v)))
                base = BRAND if _num(v) >= 0 else PALETTE[3]
                fill = colors.Color(1 - (1 - base.red) * a, 1 - (1 - base.green) * a, 1 - (1 - base.blue) * a)
            else:
                a = _num(v) / mx
                fill = colors.Color(1 - (1 - BRAND.red) * a, 1 - (1 - BRAND.green) * a, 1 - (1 - BRAND.blue) * a)
            d.add(Rect(90 + cw * i, top, cw - 1.5, ch - 1.5, fillColor=fill, strokeColor=RULE, strokeWidth=0.3))
            if v is not None:
                d.add(String(90 + cw * i + (cw - 1.5) / 2, top + ch / 2 - 2.5, f"{_num(v):.2f}" if corr else compact(_num(v)), fontName="Helvetica", fontSize=6.5, fillColor=INK, textAnchor="middle"))
    return d


def chart_drawing(spec: dict[str, Any], w: float = CONTENT_W, h: float = 200) -> Drawing:
    kind = spec["type"]
    if kind in ("pie", "donut"):
        return pie(spec, w, h)
    if kind == "scatter":
        return scatter(spec, w, h)
    if kind == "box":
        return box(spec, w, h)
    if kind in ("heatmap", "correlation"):
        return heat(spec, w, h)
    return cartesian(spec, w, h)


# ── document ───────────────────────────────────────────────────────────────

def _bullets(items: list[str], st: dict[str, ParagraphStyle]) -> list[Any]:
    return [Paragraph(para_text(i), st["bullet"], bulletText="\u2022") for i in items]


def _table(data: list[list[Any]], widths: list[float], header: bool = True) -> Table:
    tb = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    cmds = [
        ("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, RULE), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        cmds += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef0f3")), ("LINEBELOW", (0, 0), (-1, 0), 0.6, MUTED)]
    tb.setStyle(TableStyle(cmds))
    return tb


def _code(code: str, st: dict[str, ParagraphStyle], width: int = 100) -> Preformatted:
    lines: list[str] = []
    for line in t(code).replace("\t", "    ").splitlines() or [""]:
        lines.extend(textwrap.wrap(line, width, replace_whitespace=False, drop_whitespace=False, break_long_words=True) or [""])
    return Preformatted("\n".join(lines[:200]), st["code"])


def _footer(ctx: ReportContext):
    def draw(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, 10 * mm, t(f"QuantaLens AI  |  {ctx.title}", 90))
        canvas.drawRightString(PAGE_W - MARGIN, 10 * mm, f"Page {doc.page}")
        canvas.setStrokeColor(RULE)
        canvas.line(MARGIN, 14 * mm, PAGE_W - MARGIN, 14 * mm)
        canvas.restoreState()
    return draw


def build_pdf(ctx: ReportContext) -> bytes:
    st = styles()
    p, a, v = ctx.payload, ctx.answer, ctx.validation
    story: list[Any] = []
    story.append(Paragraph(para_text(ctx.title), st["title"]))
    ds = p.get("dataset") or {}
    meta = [
        ["Dataset", para_text(ctx.dataset_name)],
        ["Data analysed", para_text(f"{'Cleaned' if ds.get('version') == 'cleaned' else 'Original (uncleaned)'} version, {ds.get('rows', 0):,} rows")],
        ["Generated", ctx.generated_at.strftime("%d %b %Y, %H:%M UTC")],
        ["Analysis", para_text(f"{(p.get('duration_ms') or 0) / 1000:.1f} s, model {p.get('model') or 'n/a'}")],
        ["Validation", f'<font color="{STATUS_COLOUR.get(v["status"], "#5f6673")}"><b>{para_text(ctx.validation_label)}</b></font>'],
    ]
    story.append(_table([[Paragraph(k, st["cellb"]), Paragraph(val, st["cell"])] for k, val in meta], [30 * mm, CONTENT_W - 30 * mm], header=False))
    story += [Paragraph("Question", st["h2"]), Paragraph(para_text(ctx.question), st["body"])]
    if v["status"] in ("failed", "unverified", "not_validated", "partially_verified"):
        msg = {
            "failed": "An independent recalculation disagreed with a reported figure. Do not rely on these numbers until this is resolved.",
            "unverified": "No figure in this analysis could be independently confirmed. Treat the numbers as unchecked.",
            "not_validated": "No independent checks were run for this analysis.",
            "partially_verified": "Some figures were independently confirmed and others were not. See the Validation section.",
        }[v["status"]]
        story.append(Paragraph(f'<font color="{STATUS_COLOUR[v["status"]]}"><b>Validation notice.</b></font> {para_text(msg)}', st["body"]))

    story += [Paragraph("Executive summary", st["h2"]), Paragraph(para_text(a["executive_summary"]), st["body"])]
    story.append(Paragraph("Key findings", st["h2"]))
    for f in a["key_findings"]:
        kind = FINDING_KIND.get(f["kind"], "Observed")
        block = [Paragraph(f'<font color="#2a7f86"><b>{kind}.</b></font> {para_text(f["finding"])}', st["body"])]
        if f.get("evidence"):
            block.append(Paragraph("Evidence: " + para_text(f["evidence"]), st["small"]))
        story.append(KeepTogether(block + [Spacer(1, 3)]))

    shown = [c for c in p["charts"] if c["id"] in a.get("chart_ids", [c["id"] for c in p["charts"]])]
    if shown:
        story.append(Paragraph("Visualisations", st["h2"]))
        for c in shown:
            h = 230 if c["type"] in ("scatter", "box", "line", "area", "bar", "hbar", "histogram") else 190
            note = f"Source: result {c['result_id']}" + (". Shown as lines." if c["type"] == "area" else "") + (f". {' '.join(c['notes'])}" if c["notes"] else "")
            story.append(KeepTogether([chart_drawing(c, CONTENT_W, h), Paragraph(para_text(note), st["small"]), Spacer(1, 8)]))

    story.append(Paragraph("Supporting calculations", st["h2"]))
    ids = referenced_result_ids(ctx)[:MAX_RESULT_TABLES]
    if not ids:
        story.append(Paragraph("No stored results.", st["small"]))
    for rid in ids:
        r = ctx.result(rid)
        cols = r["columns"][:8]
        width = CONTENT_W / len(cols)
        data = [[Paragraph(para_text(c), st["cellb"]) for c in cols]]
        for row in r["rows"][:MAX_TABLE_ROWS]:
            data.append([Paragraph(para_text(fmt_number(x)), st["cell"]) for x in row[:8]])
        story.append(Paragraph(f"Result {rid}: {para_text(r['label'])}", st["h3"]))
        story.append(_table(data, [width] * len(cols)))
        shown_rows = min(MAX_TABLE_ROWS, len(r["rows"]))
        more = f" ({'truncated at the query row limit' if r['truncated'] else 'complete result'})"
        story.append(Paragraph(f"{r['source'].upper()} result, showing {shown_rows} of {r['row_count']:,} rows{more}.", st["small"]))
        story.append(Spacer(1, 4))

    for title, items in (("Business implications", a.get("business_implications")), ("Recommendations", a.get("recommendations"))):
        if items:
            story += [Paragraph(title, st["h2"]), *_bullets(items, st)]
    lim = list(a.get("limitations", [])) + [f"Assumption: {x}" for x in a.get("assumptions", [])]
    if lim:
        story += [Paragraph("Limitations and assumptions", st["h2"]), *_bullets(lim, st)]

    story.append(Paragraph("Validation results", st["h2"]))
    story.append(Paragraph(f'Overall: <font color="{STATUS_COLOUR.get(v["status"], "#5f6673")}"><b>{para_text(ctx.validation_label)}</b></font>. Each check recalculates a figure by a separate route.', st["body"]))
    if v["checks"]:
        rows = [[Paragraph(h, st["cellb"]) for h in ("Check", "Status", "Reported", "Recalculated", "Detail")]]
        for c in v["checks"]:
            rows.append([Paragraph(para_text(c["label"]), st["cell"]), Paragraph(f'<font color="{STATUS_COLOUR.get(c["status"], "#5f6673")}"><b>{para_text(c["status"].capitalize())}</b></font>', st["cell"]),
                         Paragraph(para_text(fmt_number(c["claimed"])), st["cell"]), Paragraph(para_text(fmt_number(c["recomputed"])), st["cell"]), Paragraph(para_text(c["detail"]), st["cell"])])
        story.append(_table(rows, [38 * mm, 20 * mm, 24 * mm, 26 * mm, CONTENT_W - 108 * mm]))
    for w in v.get("warnings", []):
        story.append(Paragraph(f'<font color="#9a6b00"><b>Warning.</b></font> {para_text(w["label"])}. {para_text(w["detail"])}', st["small"]))

    if p.get("plan"):
        story.append(Paragraph("Analysis plan", st["h2"]))
        story += [Paragraph(f"{i}. {para_text(s)}", st["body"]) for i, s in enumerate(p["plan"]["steps"], 1)]
    if p["sql"]:
        story.append(Paragraph("SQL used", st["h2"]))
        for q in p["sql"]:
            story.append(Paragraph(f"Query {q['index']} ({q['status']}): {para_text(q.get('purpose') or '')}", st["h3"]))
            story.append(_code(q["sql"], st))
            if q.get("executed_sql"):
                story += [Paragraph("Executed as:", st["small"]), _code(q["executed_sql"], st)]
    if p["python"]:
        story.append(Paragraph("Python used", st["h2"]))
        for q in p["python"]:
            story.append(Paragraph(f"Analysis {q['index']} ({q['status']}): {para_text(q.get('purpose') or '')}", st["h3"]))
            story.append(_code(q["code"], st))
    story += [Spacer(1, 10), Paragraph("Generated by QuantaLens AI from the stored results of this analysis. Figures are exactly those the queries and calculations returned. The AI's written interpretation should be read together with the validation status above.", st["small"])]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=16 * mm, bottomMargin=20 * mm,
                            title=t(ctx.title, 120), author="QuantaLens AI", subject="Analysis report")
    doc.build(story, onFirstPage=_footer(ctx), onLaterPages=_footer(ctx))
    return buf.getvalue()
