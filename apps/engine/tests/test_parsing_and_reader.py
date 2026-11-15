import numpy as np
import pandas as pd
import pytest

from app.data import parsing as P
from app.data.csv_reader import CsvError, detect_delimiter, read_csv_file, sanitise_filename
from app.data.naming import sanitise_columns


def S(*values):
    return pd.Series(list(values), dtype=object)


class TestNumbers:
    def test_plain_and_formatted(self):
        n = P.to_number(S("12", "12.50", "£1,234.50", "GBP 99.9", "$ 5", "(40.00)", "-3", "1e3", " 7 "))
        assert n.tolist() == [12, 12.5, 1234.5, 99.9, 5, -40, -3, 1000, 7]

    def test_invalid_and_missing_are_nan(self):
        n = P.to_number(S("TBC", "N/A", None, "", "1,2,3", "inf", "nan", "12abc", "--"))
        assert n.isna().all()

    def test_thousands_requires_valid_grouping(self):
        assert np.isnan(P.to_number(S("12,34"))[0])
        assert P.to_number(S("1,234"))[0] == 1234

    def test_currency_markers_detected(self):
        s = S("£5", "GBP 5", "5", "1,000", None)
        assert P.has_currency_marker(s).tolist() == [True, True, False, False, False]
        assert P.has_thousands_separator(s).tolist() == [False, False, False, True, False]


class TestMissing:
    def test_placeholders(self):
        s = S("a", None, "", " N/A ", "null", "-", "Unknown", "0")
        assert P.missing_mask(s).tolist() == [False, True, True, True, True, True, True, False]
        assert P.token_missing_mask(s).tolist() == [False, False, False, True, True, True, True, False]


class TestDates:
    def test_labels(self):
        s = S("2024-01-05", "05/01/2024", "05-Jan-2024", "Jan 5, 2024", "5 January 2024", "hello", None)
        assert P.date_format_labels(s).tolist() == [
            "iso", "nn/nn/yyyy", "dd Mon yyyy", "Mon dd, yyyy", "dd Mon yyyy", None, None,
        ]

    def test_dayfirst_inferred_from_data(self):
        parsed, info = P.parse_dates(S("25/12/2024", "01/02/2024"))
        assert info["dayfirst"] is True and not info["ambiguous"]
        assert parsed.tolist() == [pd.Timestamp("2024-12-25"), pd.Timestamp("2024-02-01")]

    def test_monthfirst_inferred_from_data(self):
        parsed, info = P.parse_dates(S("12/25/2024", "02/01/2024"))
        assert info["dayfirst"] is False
        assert parsed[1] == pd.Timestamp("2024-02-01")  # Feb 1st, month-first

    def test_ambiguous_is_flagged_not_silent(self):
        _, info = P.parse_dates(S("03/04/2024", "05/06/2024"))
        assert info["ambiguous"] is True and info["dayfirst"] is True

    def test_explicit_dayfirst_overrides(self):
        parsed, info = P.parse_dates(S("03/04/2024"), dayfirst=False)
        assert parsed[0] == pd.Timestamp("2024-03-04") and not info["ambiguous"]

    def test_mixed_formats_and_invalid(self):
        parsed, info = P.parse_dates(S("2024-01-05", "13/01/2024", "05-Jan-2024", "Jan 5, 2024", "31/02/2024"))
        assert parsed.iloc[0] == parsed.iloc[2] == parsed.iloc[3] == pd.Timestamp("2024-01-05")
        assert parsed.iloc[1] == pd.Timestamp("2024-01-13")
        assert pd.isna(parsed.iloc[4]) and info["unparsed"] == 1

    def test_format_dates_iso(self):
        out = P.format_dates(pd.Series(pd.to_datetime(["2024-01-05", None])))
        assert out.tolist() == ["2024-01-05", None]


class TestCategories:
    def test_grouping_and_canonical(self):
        s = S("Retail", "retail", "RETAIL ", "Retail", "Business", None, "N/A")
        groups = P.category_groups(s)
        assert set(groups) == {"retail", "business"}
        assert P.canonical_category(groups["retail"]) == "Retail"


class TestNaming:
    def test_snake_case_and_uniqueness(self):
        assert sanitise_columns(["Customer ID", "customerID", "Amount (GBP)", "2024 total", "", "Amount (GBP)", "_row_id"]) == [
            "customer_id", "customer_id_2", "amount_gbp", "col_2024_total", "column_5", "amount_gbp_2", "row_id",
        ]


def write(tmp_path, content: bytes | str, name="f.csv"):
    p = tmp_path / name
    p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return p


class TestCsvReader:
    def test_valid(self, tmp_path):
        r = read_csv_file(write(tmp_path, "a,b\n1,x\n2,\n"))
        assert r.frame.shape == (2, 2) and r.frame.iloc[1, 1] is None and r.delimiter == ","

    def test_semicolon_and_tab_delimiters(self, tmp_path):
        assert read_csv_file(write(tmp_path, "a;b;c\n1;2;3\n")).frame.shape == (1, 3)
        assert read_csv_file(write(tmp_path, "a\tb\n1\t2\n")).delimiter == "\t"

    def test_commas_inside_quotes_do_not_confuse(self, tmp_path):
        r = read_csv_file(write(tmp_path, 'name,amount\n"Smith, J",1\n"Lee, K",2\n'))
        assert r.frame.shape == (2, 2) and r.frame.iloc[0, 0] == "Smith, J"

    def test_empty_and_header_only(self, tmp_path):
        with pytest.raises(CsvError, match="empty"):
            read_csv_file(write(tmp_path, ""))
        with pytest.raises(CsvError, match="empty"):
            read_csv_file(write(tmp_path, "   \n\n"))
        with pytest.raises(CsvError, match="no data rows"):
            read_csv_file(write(tmp_path, "a,b,c\n"))

    @pytest.mark.parametrize("magic,hint", [(b"PK\x03\x04rest", "Excel"), (b"%PDF-1.7 x", "PDF"), (b"\x89PNG\r\n", "image"), (b"MZ\x90\x00", "executable")])
    def test_binary_formats_rejected_by_content(self, tmp_path, magic, hint):
        with pytest.raises(CsvError, match=hint):
            read_csv_file(write(tmp_path, magic, name="innocent.csv"))

    def test_nul_bytes_rejected(self, tmp_path):
        with pytest.raises(CsvError, match="binary"):
            read_csv_file(write(tmp_path, b"a,b\n1,\x002\n"))

    def test_ragged_rows_reported_not_hidden(self, tmp_path):
        r = read_csv_file(write(tmp_path, "a,b,c\n1,2,3\n4,5\n6,7,8,9\n\n10,11,12\n"))
        assert len(r.frame) == 3 and r.skipped_rows == 1
        assert any("more fields" in w for w in r.warnings) and any("fewer fields" in w for w in r.warnings)

    def test_encoding_fallback_is_reported(self, tmp_path):
        r = read_csv_file(write(tmp_path, "name\ncaf\xe9\n".encode("cp1252")))
        assert r.frame.iloc[0, 0] == "café" and any("Windows-1252" in w for w in r.warnings)

    def test_utf8_bom_stripped(self, tmp_path):
        r = read_csv_file(write(tmp_path, b"\xef\xbb\xbfa,b\n1,2\n"))
        assert list(r.frame.columns) == ["a", "b"]

    def test_duplicate_and_blank_headers(self, tmp_path):
        r = read_csv_file(write(tmp_path, "a,a,\n1,2,3\n"))
        assert list(r.frame.columns) == ["a", "a_2", "column_3"]

    def test_too_many_columns(self, tmp_path):
        with pytest.raises(CsvError, match="Too many columns"):
            read_csv_file(write(tmp_path, ",".join(f"c{i}" for i in range(250)) + "\n" + ",".join("1" for _ in range(250))))

    def test_formula_like_values_are_kept_as_plain_text(self, tmp_path):
        r = read_csv_file(write(tmp_path, "a\n=SUM(1+1)\n"))
        assert r.frame.iloc[0, 0] == "=SUM(1+1)"


def test_sanitise_filename():
    assert sanitise_filename("../../etc/passwd") == "passwd"
    assert sanitise_filename("C:\\x\\y.csv") == "y.csv"
    assert sanitise_filename("a\x00b\n.csv") == "ab.csv"
    assert sanitise_filename(None) == "upload.csv"
    assert len(sanitise_filename("x" * 999 + ".csv")) == 255


def test_delimiter_default():
    assert detect_delimiter("justonecolumn\nvalue\n") == ","
