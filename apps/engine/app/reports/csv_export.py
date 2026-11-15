import csv
import io

from app.reports.common import ReportContext, clean_text, neutralise_formula


def result_csv(ctx: ReportContext, result_id: str) -> bytes:
    """One stored result as CSV (UTF-8 with BOM so Excel reads accents). Cells that could run as formulas are defused."""
    r = ctx.result(result_id)
    if r is None:
        raise KeyError(result_id)
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([neutralise_formula(clean_text(c)) for c in r["columns"]])
    for row in r["rows"]:
        w.writerow(["" if v is None else neutralise_formula(clean_text(v)) if isinstance(v, str) else v for v in row])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")
