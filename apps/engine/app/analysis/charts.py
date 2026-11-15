"""Chart specifications built from stored results.

The model chooses the chart type and which columns to use. Every data point is then read from the stored
result by this module, and statistics (histogram bins, box-plot quartiles, correlations) are computed here,
so a chart can only show numbers that were actually produced by a query or analysis.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from app.analysis.state import RunState, StoredResult

CHART_TYPES = ["bar", "hbar", "line", "area", "pie", "donut", "scatter", "histogram", "box", "heatmap", "correlation"]
MAX_CATEGORIES = 60
MAX_SERIES = 12
MAX_LINE_POINTS = 600
MAX_SCATTER_POINTS = 1000
MAX_PIE_SLICES = 10


class ChartError(ValueError):
    """The chart request cannot be satisfied from the result. Message is for the model."""


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    try:
        f = float(str(v).replace(",", ""))
        return f if math.isfinite(f) else None
    except ValueError:
        return None


def _need_column(r: StoredResult, name: str | None, role: str) -> str:
    if not name:
        raise ChartError(f"'{role}' is required for this chart type.")
    if name not in r.columns:
        raise ChartError(f"Column '{name}' (for {role}) is not in result {r.id}. Its columns are: {', '.join(r.columns)}.")
    return name


def _numeric_values(r: StoredResult, col: str, role: str) -> list[float | None]:
    vals = [_num(v) for v in r.column(col)]
    if not any(v is not None for v in vals):
        raise ChartError(f"Column '{col}' (for {role}) has no numeric values in result {r.id}.")
    bad = sum(1 for raw, v in zip(r.column(col), vals) if raw is not None and v is None)
    if bad > len(vals) * 0.2:
        raise ChartError(f"Column '{col}' (for {role}) is mostly non-numeric in result {r.id}. Convert it to numbers in the query first.")
    return vals


def _label(v: Any) -> str:
    return "(missing)" if v is None else str(v)


def _clean(v: float | None) -> float | None:
    return None if v is None else (int(v) if float(v).is_integer() and abs(v) < 1e15 else round(v, 6))


def _sorted_idx(order: list[int], keys: list[Any], sort: str | None, vals: list[float | None]) -> list[int]:
    if sort == "y_desc":
        return sorted(order, key=lambda i: -(vals[i] if vals[i] is not None else -math.inf))
    if sort == "y_asc":
        return sorted(order, key=lambda i: (vals[i] if vals[i] is not None else math.inf))
    if sort == "x":
        return sorted(order, key=lambda i: (keys[i] is None, str(keys[i])))
    return order


def build_chart(state: RunState, args: dict[str, Any]) -> dict[str, Any]:
    ctype = args.get("chart_type")
    if ctype not in CHART_TYPES:
        raise ChartError(f"chart_type must be one of: {', '.join(CHART_TYPES)}.")
    r = state.get_result(str(args.get("result_id", "")))
    title = str(args.get("title") or "").strip()
    if not title:
        raise ChartError("A descriptive title is required.")
    x, series = args.get("x"), args.get("series")
    ys = args.get("y") or []
    ys = [ys] if isinstance(ys, str) else list(ys)
    sort, top_n = args.get("sort"), args.get("top_n")
    notes: list[str] = []
    if r.truncated:
        notes.append(f"The underlying result was truncated at {r.row_count:,} rows.")

    spec: dict[str, Any] = {"type": ctype, "title": title[:140], "result_id": r.id, "notes": notes, "source_rows": r.row_count}
    spec["x_label"] = str(args.get("x_label") or x or "")[:80]
    spec["y_label"] = str(args.get("y_label") or (ys[0] if ys else ""))[:80]

    if ctype in ("bar", "hbar", "line", "area"):
        _build_cartesian(r, spec, x, ys, series, sort, top_n, notes)
    elif ctype in ("pie", "donut"):
        _build_pie(r, spec, x, ys, sort, notes)
    elif ctype == "scatter":
        _build_scatter(r, spec, x, ys, series, notes)
    elif ctype == "histogram":
        _build_histogram(r, spec, x or (ys[0] if ys else None), int(args.get("bins") or 0), notes)
    elif ctype == "box":
        _build_box(r, spec, x, ys, notes)
    elif ctype == "heatmap":
        _build_heatmap(r, spec, x, series or args.get("y_category"), ys, notes)
    else:
        _build_correlation(r, spec, args.get("columns"), notes)
    spec["id"] = f"c{len(state.charts) + 1}"
    return spec


def _build_cartesian(r, spec, x, ys, series, sort, top_n, notes):
    xcol = _need_column(r, x, "x")
    if not ys:
        raise ChartError("'y' (one or more numeric columns) is required.")
    for y in ys:
        _need_column(r, y, "y")
    xs = r.column(xcol)
    if series:
        scol = _need_column(r, series, "series")
        if len(ys) != 1:
            raise ChartError("With 'series', provide exactly one y column.")
        yvals = _numeric_values(r, ys[0], "y")
        sv = r.column(scol)
        x_order: list[Any] = []
        series_order: list[Any] = []
        cell: dict[tuple[Any, Any], float | None] = {}
        for xv, s, v in zip(xs, sv, yvals):
            if xv not in x_order:
                x_order.append(xv)
            if s not in series_order:
                series_order.append(s)
            cell[(xv, s)] = (cell.get((xv, s)) or 0) + v if v is not None else cell.get((xv, s))
        if len(series_order) > MAX_SERIES:
            raise ChartError(f"'{series}' has {len(series_order)} distinct values. Limit it to {MAX_SERIES} (filter or aggregate in the query).")
        if len(x_order) > MAX_LINE_POINTS:
            raise ChartError(f"Too many x values ({len(x_order)}). Aggregate to fewer than {MAX_LINE_POINTS}.")
        keys = [_label(s) for s in series_order]
        data = [{"x": _label(xv), **{_label(s): _clean(cell.get((xv, s))) for s in series_order}} for xv in x_order]
        spec.update(x_key="x", y_keys=keys, data=data)
        spec["y_label"] = spec["y_label"] or ys[0]
        return
    ydata = {y: _numeric_values(r, y, "y") for y in ys}
    n = len(xs)
    limit = MAX_CATEGORIES if spec["type"] in ("bar", "hbar") else MAX_LINE_POINTS
    order = _sorted_idx(list(range(n)), xs, sort, ydata[ys[0]])
    if top_n:
        order = _sorted_idx(order, xs, "y_desc", ydata[ys[0]])[: int(top_n)]
        notes.append(f"Showing the top {int(top_n)} by {ys[0]}.")
    if len(order) > limit:
        raise ChartError(f"{len(order)} points is too many for a {spec['type']} chart (limit {limit}). Aggregate further, or pass top_n.")
    spec.update(x_key="x", y_keys=list(ys), data=[{"x": _label(xs[i]), **{y: _clean(ydata[y][i]) for y in ys}} for i in order])


def _build_pie(r, spec, x, ys, sort, notes):
    xcol = _need_column(r, x, "x (category)")
    if len(ys) != 1:
        raise ChartError("Provide exactly one y (value) column for a pie or donut chart.")
    vals = _numeric_values(r, _need_column(r, ys[0], "y"), "y")
    pairs = [(_label(k), v) for k, v in zip(r.column(xcol), vals) if v is not None]
    if any(v < 0 for _, v in pairs):
        raise ChartError("Pie charts cannot show negative values. Use a bar chart.")
    pairs.sort(key=lambda p: -p[1])
    if len(pairs) > MAX_PIE_SLICES:
        tail = sum(v for _, v in pairs[MAX_PIE_SLICES - 1:])
        pairs = pairs[: MAX_PIE_SLICES - 1] + [("Other", tail)]
        notes.append(f"Categories beyond the top {MAX_PIE_SLICES - 1} are grouped as 'Other'.")
    spec.update(x_key="name", y_keys=["value"], data=[{"name": k, "value": _clean(v)} for k, v in pairs])


def _build_scatter(r, spec, x, ys, series, notes):
    xcol = _need_column(r, x, "x")
    if len(ys) != 1:
        raise ChartError("Provide exactly one y column for a scatter plot.")
    xv, yv = _numeric_values(r, xcol, "x"), _numeric_values(r, _need_column(r, ys[0], "y"), "y")
    sv = r.column(_need_column(r, series, "series")) if series else [None] * len(xv)
    pts = [(a, b, s) for a, b, s in zip(xv, yv, sv) if a is not None and b is not None]
    if len(pts) > MAX_SCATTER_POINTS:
        raise ChartError(f"{len(pts)} points is too many. Sample or aggregate to at most {MAX_SCATTER_POINTS}.")
    dropped = len(xv) - len(pts)
    if dropped:
        notes.append(f"{dropped:,} rows with a missing x or y were left out.")
    groups = sorted({_label(s) for _, _, s in pts}) if series else []
    if len(groups) > MAX_SERIES:
        raise ChartError(f"'{series}' has {len(groups)} distinct values. Limit it to {MAX_SERIES}.")
    spec.update(x_key="x", y_keys=["y"], series_values=groups, data=[{"x": _clean(a), "y": _clean(b), **({"series": _label(s)} if series else {})} for a, b, s in pts])
    if len(pts) >= 3:
        c = float(np.corrcoef([p[0] for p in pts], [p[1] for p in pts])[0, 1])
        if math.isfinite(c):
            spec["stats"] = {"pearson_r": round(c, 4), "n": len(pts)}


def _build_histogram(r, spec, col, bins, notes):
    col = _need_column(r, col, "x (numeric column of raw values)")
    vals = [v for v in _numeric_values(r, col, "x") if v is not None]
    if len(vals) < 10:
        raise ChartError("A histogram needs at least 10 raw values. Query the individual values, not an aggregate.")
    arr = np.asarray(vals)
    k = bins if 3 <= bins <= 60 else int(min(40, max(8, math.ceil(math.log2(len(arr)) + 1))))
    counts, edges = np.histogram(arr, bins=k)
    spec.update(x_key="label", y_keys=["count"], y_label=spec["y_label"] or "Count", x_label=spec["x_label"] or col,
                data=[{"label": f"{edges[i]:,.4g} to {edges[i + 1]:,.4g}", "bin_start": float(edges[i]), "bin_end": float(edges[i + 1]), "count": int(counts[i])} for i in range(k)])
    spec["stats"] = {"n": int(arr.size), "mean": round(float(arr.mean()), 4), "median": round(float(np.median(arr)), 4)}
    if r.truncated:
        notes.append("The histogram covers only the rows returned, not the whole dataset.")


def _build_box(r, spec, x, ys, notes):
    if len(ys) != 1:
        raise ChartError("Provide exactly one numeric y column for a box plot.")
    yv = _numeric_values(r, _need_column(r, ys[0], "y"), "y")
    gv = r.column(_need_column(r, x, "x (group)")) if x else [None] * len(yv)
    groups: dict[str, list[float]] = {}
    for g, v in zip(gv, yv):
        if v is not None:
            groups.setdefault(_label(g) if x else "All", []).append(v)
    if len(groups) > 20:
        raise ChartError(f"{len(groups)} groups is too many for a box plot (limit 20).")
    data = []
    for g, vs in groups.items():
        a = np.asarray(vs)
        if a.size < 5:
            notes.append(f"Group '{g}' has fewer than 5 values and was left out.")
            continue
        q1, med, q3 = (float(np.percentile(a, p)) for p in (25, 50, 75))
        iqr = q3 - q1
        lo_fence, hi_fence = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        inside = a[(a >= lo_fence) & (a <= hi_fence)]
        outliers = a[(a < lo_fence) | (a > hi_fence)]
        data.append({"group": g, "min": _clean(float(inside.min())), "q1": _clean(q1), "median": _clean(med), "q3": _clean(q3),
                     "max": _clean(float(inside.max())), "n": int(a.size), "outlier_count": int(outliers.size), "outliers": [_clean(float(o)) for o in outliers[:50]]})
    if not data:
        raise ChartError("No group has enough values (at least 5) for a box plot.")
    spec.update(x_key="group", y_keys=["median"], data=data)
    notes.append("Whiskers extend to the most extreme value within 1.5 x IQR of the quartiles.")


def _build_heatmap(r, spec, x, y_cat, ys, notes):
    xcol = _need_column(r, x, "x")
    ycol = _need_column(r, y_cat, "series (the second category, rows of the heatmap)")
    if len(ys) != 1:
        raise ChartError("Provide exactly one numeric value column in 'y'.")
    vals = _numeric_values(r, _need_column(r, ys[0], "y"), "y")
    xs, yc = r.column(xcol), r.column(ycol)
    x_vals = list(dict.fromkeys(_label(v) for v in xs))
    y_vals = list(dict.fromkeys(_label(v) for v in yc))
    if len(x_vals) > 40 or len(y_vals) > 40:
        raise ChartError("A heatmap supports at most 40 x 40 categories. Aggregate further.")
    spec.update(x_key="x", y_keys=["value"], x_values=x_vals, y_values=y_vals,
                data=[{"x": _label(a), "y": _label(b), "value": _clean(v)} for a, b, v in zip(xs, yc, vals) if v is not None])


def _build_correlation(r, spec, columns, notes):
    cols = list(columns) if columns else [c for c in r.columns if sum(_num(v) is not None for v in r.column(c)) >= max(8, 0.8 * len(r.rows))]
    for c in cols:
        _need_column(r, c, "columns")
    if len(cols) < 2:
        raise ChartError("A correlation matrix needs at least two numeric columns in the result.")
    if len(cols) > 15:
        raise ChartError("A correlation matrix supports at most 15 columns.")
    if len(r.rows) < 8:
        raise ChartError("A correlation matrix needs at least 8 rows of raw values.")
    mat = np.array([[(_num(v) if _num(v) is not None else np.nan) for v in r.column(c)] for c in cols], dtype=float)
    n = len(cols)
    corr = np.full((n, n), np.nan)
    for i in range(n):
        for j in range(n):
            m = ~np.isnan(mat[i]) & ~np.isnan(mat[j])
            if m.sum() >= 3 and np.std(mat[i][m]) > 0 and np.std(mat[j][m]) > 0:
                corr[i, j] = np.corrcoef(mat[i][m], mat[j][m])[0, 1]
    spec.update(type="correlation", x_key="x", y_keys=["value"], x_values=cols, y_values=cols,
                data=[{"x": cols[j], "y": cols[i], "value": None if np.isnan(corr[i, j]) else round(float(corr[i, j]), 4)} for i in range(n) for j in range(n)])
    notes.append("Pearson correlation. Correlation does not show cause and effect.")
