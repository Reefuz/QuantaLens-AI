import io

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from app.reports import pdf as pdfmod
from app.reports.common import neutralise_formula, safe_filename
from app.reports.csv_export import result_csv
from app.reports.pdf import build_pdf, chart_drawing
from app.reports.xlsx import build_xlsx, sheet_name
from tests.report_helpers import SEGMENTS, make_context, make_payload, with_text

ALL_TYPES = ["bar", "hbar", "line", "area", "pie", "donut", "scatter", "histogram", "box", "heatmap", "correlation"]


def pdf_text(data: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


# ── PDF ────────────────────────────────────────────────────────────────────

class TestPdf:
    def test_every_section_and_real_figures_are_present(self):
        data = build_pdf(make_context())
        assert data.startswith(b"%PDF")
        reader = PdfReader(io.BytesIO(data))
        text = pdf_text(data)
        assert len(reader.pages) >= 3 and reader.metadata.title == "Segment value review"
        for needle in ["Segment value review", "Bank demo", "Cleaned version, 11,131 rows", "Which segment contributes the most?", "Executive summary", "Key findings",
                       "Visualisations", "Supporting calculations", "Business implications", "Recommendations", "Limitations and assumptions", "Validation results",
                       "SQL used", "Python used", "Analysis plan", "Partially verified", "Observed.", "Statistical.", "Possible explanation."]:
            assert needle in text, needle

    def test_numbers_in_tables_are_the_stored_results(self):
        text = pdf_text(build_pdf(make_context()))
        for name, value in SEGMENTS:
            assert name in text and f"{value:,.2f}" in text

    def test_sql_python_and_validation_are_included(self):
        text = pdf_text(build_pdf(make_context()))
        assert "SUM(transaction_amount) AS total" in text and "stats.pearsonr" in text and "Executed as" in text
        assert "Segments add up" in text and "12,140,067.64" in text and "Duplicates may be double counted" in text

    def test_an_unverified_analysis_is_labelled_as_such(self):
        p = make_payload()
        p["validation"] = {"status": "failed", "checks": [], "warnings": []}
        text = pdf_text(build_pdf(make_context(payload=p)))
        assert "Verification failed" in text and "disagreed with a reported figure" in text
        p["validation"]["status"] = "not_validated"
        assert "No independent checks were run" in pdf_text(build_pdf(make_context(payload=p)))

    @pytest.mark.parametrize("kind", ALL_TYPES)
    def test_each_chart_type_draws(self, kind):
        spec = next(c for c in make_payload()["charts"] if c["type"] == kind)
        d = chart_drawing(spec)
        assert d.width > 100 and d.height > 60 and d.getContents()

    def test_markup_in_data_is_text_not_formatting(self):
        hostile = '<b>bold</b> <img src="http://evil/x.png"/> <font color="red">red</font> & <script>alert(1)</script>'
        text = pdf_text(build_pdf(make_context(payload=with_text(make_payload(), hostile), title="<i>Title</i> & co")))
        assert "<b>bold</b>" in text and "<script>alert(1)</script>" in text and "<i>Title</i> & co" in text

    def test_characters_outside_the_pdf_font_do_not_crash(self):
        weird = "Revenue \u2192 up \u2265 5% \u2014 \u201csmart\u201d \u20ac \u4e2d\u6587 \U0001f600 \u0000 end"
        text = pdf_text(build_pdf(make_context(payload=with_text(make_payload(), weird))))
        assert "Revenue" in text and "smart" in text and "end" in text

    def test_very_long_unbroken_text_and_many_rows(self):
        p = make_payload()
        p["answer"]["executive_summary"] = "x" * 3000 + " " + "word " * 2000
        p["results"][0]["rows"] = [[f"Segment {i}", float(i)] for i in range(300)]
        p["results"][0]["row_count"] = 300
        data = build_pdf(make_context(payload=p))
        assert data.startswith(b"%PDF") and "showing 15 of 300 rows" in pdf_text(data)

    def test_a_report_with_no_charts_or_python(self):
        p = make_payload()
        p["charts"], p["python"], p["sql"], p["plan"] = [], [], [], None
        p["answer"]["chart_ids"] = []
        text = pdf_text(build_pdf(make_context(payload=p)))
        assert "Visualisations" not in text and "Python used" not in text and "Executive summary" in text

    def test_cp1252_helper(self):
        assert pdfmod.t("£5 \u2192 \u4e2d") == "£5 ? ?"


# ── Excel ──────────────────────────────────────────────────────────────────

class TestExcel:
    def book(self, ctx=None):
        return load_workbook(io.BytesIO(build_xlsx(ctx or make_context())))

    def test_sheets_and_summary(self):
        wb = self.book()
        assert wb.sheetnames[:3] == ["Summary", "Validation", "Queries"] and "Charts" in wb.sheetnames and "Result r1" in wb.sheetnames
        ws = wb["Summary"]
        assert ws["A1"].value == "Segment value review"
        values = [c.value for row in ws.iter_rows() for c in row if c.value]
        assert "Which segment contributes the most?" in values and "Private Banking contributes the most transaction value." in values and "Partially verified" in values

    def test_result_sheet_holds_the_exact_numbers_as_numbers(self):
        ws = self.book()["Result r1"]
        assert [c.value for c in ws[3]] == ["customer_segment", "total"]
        rows = [(r[0].value, r[1].value) for r in ws.iter_rows(min_row=4, max_row=7)]
        assert rows == SEGMENTS and all(isinstance(v, float) for _, v in rows)

    def test_sql_python_validation_sheets(self):
        wb = self.book()
        q = [[c.value for c in r] for r in wb["Queries"].iter_rows(min_row=2)]
        assert q[0][0] == "SQL" and "SUM(transaction_amount)" in q[0][6] and "LIMIT 1001" in q[0][7] and q[1][0] == "Python" and "pearsonr" in q[1][6]
        v = [[c.value for c in r] for r in wb["Validation"].iter_rows(min_row=4)]
        assert v[0][0] == "Segments add up" and v[0][2] == "verified" and v[0][3] == 12140067.64

    def test_native_charts_are_embedded(self):
        assert len(self.book()["Charts"]._charts) >= 7  # bar, hbar, line, area, pie, donut, scatter, histogram

    def test_formulas_from_uploaded_data_are_stored_as_text_not_executed(self):
        evil = '=HYPERLINK("http://evil.example/steal","click")'
        p = with_text(make_payload(), evil)
        wb = self.book(make_context(payload=p, title="+cmd|' /C calc'!A0"))
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and c.value[:1] in "=+@" and not c.value.lstrip("+-").replace(".", "").isdigit():
                        assert c.data_type == "s", f"{ws.title}!{c.coordinate} would run as a formula"
        assert wb["Result r1"]["A4"].value == evil and wb["Result r1"]["A4"].data_type == "s"
        assert wb["Summary"]["A1"].data_type == "s"

    def test_illegal_control_characters_and_long_text_are_survived(self):
        p = with_text(make_payload(), "bad\x00\x01\x02 text " + "y" * 40000)
        wb = self.book(make_context(payload=p))
        assert "bad" in wb["Result r1"]["A4"].value and len(wb["Result r1"]["A4"].value) <= 32000

    def test_sheet_names_are_valid_and_unique(self):
        taken: set[str] = set()
        names = [sheet_name(n, taken) for n in ["Summary", "summary", "A/B:C*D?[x]", "x" * 50, "x" * 50]]
        assert len(set(n.lower() for n in names)) == 5 and all(len(n) <= 31 and not set(n) & set("[]:*?/\\") for n in names)


# ── CSV ────────────────────────────────────────────────────────────────────

class TestCsv:
    def test_exports_exactly_the_stored_result(self):
        raw = result_csv(make_context(), "r1")
        assert raw.startswith(b"\xef\xbb\xbf")
        lines = raw.decode("utf-8-sig").splitlines()
        assert lines[0] == "customer_segment,total" and lines[1] == "Private Banking,5232418.21" and len(lines) == 5

    def test_formula_cells_are_defused_but_numbers_are_not(self):
        p = make_payload()
        p["results"][0]["rows"] = [["=SUM(1+1)", -5.5], ["+cmd", 3], ["@x", None], ["-3", 1], ["plain", 2], ["-danger", 1]]
        lines = result_csv(make_context(payload=p), "r1").decode("utf-8-sig").splitlines()
        assert lines[1].startswith("'=SUM(1+1)") and lines[2].startswith("'+cmd") and lines[3].startswith("'@x") and lines[4].startswith("-3,") and lines[6].startswith("'-danger")
        assert ",-5.5" in lines[1] and lines[3].endswith(",")

    def test_commas_quotes_and_newlines_are_escaped(self):
        p = make_payload()
        p["results"][0]["rows"] = [['a "quoted", name\nwith newline', 1]]
        import csv

        rows = list(csv.reader(io.StringIO(result_csv(make_context(payload=p), "r1").decode("utf-8-sig"))))
        assert rows[1][0] == 'a "quoted", name\nwith newline'

    def test_unknown_result(self):
        with pytest.raises(KeyError):
            result_csv(make_context(), "r99")


def test_helpers():
    assert neutralise_formula("=1+1") == "'=1+1" and neutralise_formula("-12.5") == "-12.5" and neutralise_formula("hello") == "hello"
    assert safe_filename('../../Q3 review: "final"?') == "Q3-review-final" and safe_filename("***") == "analysis"
