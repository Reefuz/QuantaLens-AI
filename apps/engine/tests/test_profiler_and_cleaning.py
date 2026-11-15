"""The profiler is tested against the synthetic sample, whose injected mess is known exactly."""

import io

import pandas as pd
import pytest

from app.data import cleaning as C
from app.data import parsing as P
from app.data.naming import sanitise_columns
from app.data.profiler import profile_dataframe
from app.data.sample import generate_sample


def to_frame(csv_text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(csv_text), dtype=str, keep_default_na=False)
    df = df.replace("", None).astype(object).where(lambda d: d.notna(), None)
    df.insert(0, C.ROW_ID, range(1, len(df) + 1))
    return df


@pytest.fixture(scope="module")
def sample():
    r = generate_sample()
    return r.manifest, to_frame(r.csv_text)


@pytest.fixture(scope="module")
def report(sample):
    _, df = sample
    names = {c: c for c in df.columns if c != C.ROW_ID}
    return profile_dataframe(df, names)


@pytest.fixture(scope="module")
def deduped_report(sample):
    _, df = sample
    deduped = C.remove_duplicate_rows(df).frame
    names = {c: c for c in df.columns if c != C.ROW_ID}
    return profile_dataframe(deduped, names), deduped


def issues_by(report, type_, column=None):
    found = [i for i in report[0]["issues"] if i["type"] == type_ and (column is None or i["column"] == column)]
    assert len(found) == 1, f"expected one {type_}/{column}, got {len(found)}"
    return found[0]


def col(report, name):
    return next(c for c in report[1] if c["name"] == name)


# ── detection vs ground truth ──────────────────────────────────────────────

def test_row_and_column_counts(sample, report):
    manifest, _ = sample
    assert report[0]["summary"]["rows"] == manifest["total_rows"]
    assert report[0]["summary"]["columns"] == len(manifest["columns"])


def test_exact_duplicate_rows(sample, report):
    manifest, _ = sample
    assert issues_by(report, "duplicate_rows")["affected_rows"] == manifest["exact_duplicate_rows_injected"]


def test_missing_values_and_placeholders(sample, deduped_report):
    m, _ = sample
    rep, _ = deduped_report
    assert col(rep, "customer_id")["missing_count"] == m["missing_customer_ids"]
    age = col(rep, "customer_age")
    assert age["missing_count"] == m["missing_ages"] + m["unknown_age_tokens"]
    assert age["placeholder_count"] == m["unknown_age_tokens"]
    inc = col(rep, "monthly_income")
    assert inc["missing_count"] == m["missing_incomes"] + m["na_income_tokens"]
    assert inc["placeholder_count"] == m["na_income_tokens"]
    assert issues_by(rep, "missing_values", "customer_id")["fix"] is None  # nothing safe to fix: no placeholders
    assert issues_by(rep, "missing_values", "customer_age")["fix"]["operation"] == "standardise_missing"


def test_date_formats_match_injected_counts(sample, deduped_report):
    m, _ = sample
    rep, _ = deduped_report
    issue = issues_by(rep, "inconsistent_dates", "transaction_date")
    f, expect = issue["formats"], m["date_format_counts"]
    assert f["iso"] == expect["iso"]
    assert f["nn/nn/yyyy"] == expect["dmy_slash"]
    assert f["dd Mon yyyy"] == expect["dd_mon_yyyy"]
    assert f["Mon dd, yyyy"] == expect["mon_d_yyyy"]
    assert issue["fix"]["params"]["dayfirst"] is True and not issue["ambiguous_dates"]


def test_invalid_and_formatted_numbers(sample, deduped_report):
    m, _ = sample
    rep, _ = deduped_report
    assert issues_by(rep, "mixed_types", "transaction_amount")["affected_rows"] == m["invalid_amounts"]
    assert issues_by(rep, "currency_format", "transaction_amount")["affected_rows"] == m["formatted_amounts"]
    assert issues_by(rep, "currency_format", "monthly_income")["affected_rows"] == m["formatted_incomes"]
    assert col(rep, "transaction_amount")["kind"] == "numeric"


def test_injected_outliers_are_found(sample, deduped_report):
    m, _ = sample
    rep, _ = deduped_report
    out = issues_by(rep, "outliers", "transaction_amount")
    # 40 values were inflated 150-400x. Judged globally, so a modest inflation of a tiny student amount can stay inside the fence; require most.
    assert out["affected_rows"] >= 0.7 * m["injected_amount_outliers"]
    assert out["fix"]["operation"] == "flag_outliers"  # flag, never delete
    assert issues_by(rep, "outliers", "customer_age")["affected_rows"] >= 1  # 230 / 999 ages


def test_category_variants_found_and_merge_to_canonical(sample, deduped_report):
    rep, df = deduped_report
    for column, expected in [("customer_segment", 4), ("transaction_status", 3), ("payment_method", 4)]:
        issue = issues_by(rep, "inconsistent_categories", column)
        assert issue["affected_rows"] > 0
        cleaned = C.apply_operation(C.trim_whitespace(df, column).frame, "standardise_categories", column).frame
        assert cleaned[column].nunique() == expected, column


def test_whitespace(sample, deduped_report):
    m, _ = sample
    rep, _ = deduped_report
    assert issues_by(rep, "whitespace", "branch")["affected_rows"] == m["branch_whitespace_rows"]


def test_unnecessary_columns(deduped_report):
    rep, _ = deduped_report
    assert issues_by(rep, "empty_column", "internal_notes")["fix"]["operation"] == "drop_column"
    assert issues_by(rep, "constant_column", "batch_source")["severity"] == "low"


def test_duplicate_identifiers_distinct_from_duplicate_rows(sample, deduped_report):
    m, _ = sample
    rep, _ = deduped_report
    assert issues_by(rep, "duplicate_identifiers", "transaction_id")["affected_rows"] == m["reused_transaction_ids_injected"]
    assert issues_by(rep, "duplicate_identifiers", "transaction_id")["fix"] is None  # needs a human decision


def test_identifier_and_kinds(deduped_report):
    rep, _ = deduped_report
    assert col(rep, "transaction_id")["is_identifier"]
    assert col(rep, "transaction_date")["kind"] == "date"
    assert col(rep, "customer_segment")["kind"] == "categorical"


def test_every_fixable_issue_has_a_real_preview(report):
    for issue in report[0]["issues"]:
        if issue["fix"]:
            assert issue["preview"] is not None, issue["id"]
            assert issue["preview"]["affected"] > 0, issue["id"]
            assert issue["preview"]["rows"], issue["id"]
        else:
            assert issue["preview"] is None


def test_issues_sorted_by_severity(report):
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    ranks = [order[i["severity"]] for i in report[0]["issues"]]
    assert ranks == sorted(ranks)


# ── cleaning correctness ───────────────────────────────────────────────────

def test_originals_not_mutated_by_operations(sample):
    _, df = sample
    snapshot = df.copy(deep=True)
    for op, column in [("trim_whitespace", "branch"), ("parse_numbers", "transaction_amount"), ("parse_dates", "transaction_date"), ("remove_duplicate_rows", None)]:
        C.apply_operation(df, op, column)
    pd.testing.assert_frame_equal(df, snapshot)


def test_parse_numbers_values(sample):
    _, df = sample
    res = C.apply_operation(df, "parse_numbers", "transaction_amount")
    new = res.frame["transaction_amount"]
    assert res.details["invalid_set_to_null"] > 0
    nums = pd.to_numeric(new.dropna())
    assert len(nums) == df["transaction_amount"].notna().sum() - res.details["invalid_set_to_null"] - (
        P.missing_mask(df["transaction_amount"]) & df["transaction_amount"].notna()
    ).sum()
    for raw, cleaned in zip(df["transaction_amount"], new):
        if raw and raw.startswith("£"):
            assert float(cleaned) == float(raw.replace("£", "").replace(",", ""))
            break


def test_parse_dates_all_iso_and_counts_preserved(sample, deduped_report):
    m, _ = sample
    _, df = deduped_report
    res = C.apply_operation(df, "parse_dates", "transaction_date", {"dayfirst": True})
    out = res.frame["transaction_date"].dropna()
    assert out.str.match(r"^\d{4}-\d{2}-\d{2}$").all()
    assert len(out) == len(df) - m["missing_dates"]
    assert res.details["invalid_set_to_null"] == 0
    # range matches the generator's window
    assert out.min() >= "2024-01-01" and out.max() <= "2025-06-30"


def test_dedupe_keeps_first_and_matches_manifest(sample):
    m, df = sample
    res = C.apply_operation(df, "remove_duplicate_rows", None)
    assert len(res.frame) == m["total_rows"] - m["exact_duplicate_rows_injected"] == len(df) - res.affected
    assert res.frame[C.ROW_ID].is_monotonic_increasing


def test_flag_outliers_adds_column_and_removes_nothing(sample):
    _, df = sample
    res = C.apply_operation(df, "flag_outliers", "transaction_amount")
    assert len(res.frame) == len(df)
    assert "transaction_amount_is_outlier" in res.frame.columns
    assert int(res.frame["transaction_amount_is_outlier"].fillna(False).sum()) == res.affected


def test_full_cleaning_pipeline_types_and_totals(sample):
    m, df = sample
    ordered = ["trim_whitespace", "standardise_missing", "parse_numbers", "parse_dates", "standardise_categories", "drop_column", "remove_duplicate_rows"]
    plan = [
        ("trim_whitespace", c) for c in ("branch", "customer_segment", "transaction_status")
    ] + [
        ("standardise_missing", "customer_age"), ("standardise_missing", "monthly_income"),
        ("parse_numbers", "transaction_amount"), ("parse_numbers", "monthly_income"), ("parse_numbers", "customer_age"),
        ("parse_dates", "transaction_date"),
        ("standardise_categories", "customer_segment"), ("standardise_categories", "transaction_status"), ("standardise_categories", "payment_method"),
        ("drop_column", "internal_notes"), ("remove_duplicate_rows", None),
    ]
    plan.sort(key=lambda p: C.order_key(p[0]))
    assert [p[0] for p in plan] == sorted([p[0] for p in plan], key=ordered.index)
    out = df
    for op, column in plan:
        out = C.apply_operation(out, op, column).frame
    schema = C.infer_schema(out)
    assert schema["transaction_amount"] == "double precision"
    assert schema["transaction_date"] == "date"
    assert schema["customer_age"] == "bigint"
    assert schema["customer_segment"] == "text" and schema["customer_id"] == "text"
    assert "internal_notes" not in out.columns
    assert out["customer_segment"].nunique() == 4
    assert len(out) == m["total_rows"] - m["exact_duplicate_rows_injected"]
    # An independent recalculation of the total from the raw text agrees with the cleaned column.
    raw = P.to_number(C.remove_duplicate_rows(df).frame["transaction_amount"])
    assert float(pd.to_numeric(out["transaction_amount"]).sum()) == pytest.approx(float(raw.sum()))


def test_natural_skew_is_not_flagged_but_real_outliers_are():
    import numpy as np

    rng = np.random.default_rng(1)
    values = rng.lognormal(4, 1.2, 5000).round(2)
    s = pd.Series([str(v) for v in values], dtype=object)
    mask, _ = C.outlier_mask(s)
    assert mask.mean() < 0.02  # a lognormal tail is not "unusual" (Tukey on a normal flags ~0.7%)
    s2 = pd.concat([s, pd.Series(["5000000", "9000000"], dtype=object)], ignore_index=True)
    mask2, fences = C.outlier_mask(s2)
    assert mask2.iloc[-2:].all() and fences[0] > 0
    assert "log scale" in C.outlier_method(P.to_number(s2))


def test_symmetric_data_uses_linear_fences():
    s = pd.Series([str(v) for v in [-2, 1, 0, 2, -1, 1, 0, -2, 2, -1, 1, 60]], dtype=object)
    mask, _ = C.outlier_mask(s)
    assert mask.tolist() == [False] * 11 + [True]
    assert "log" not in C.outlier_method(P.to_number(s))


def test_schema_inference_is_conservative():
    df = pd.DataFrame({
        "zip": ["07123", "01234"], "n": ["1", "2"], "f": ["1.5", "2"], "d": ["2024-01-05", "2024-02-30"],
        "t": ["2024-01-05 10:00:00", None], "mixed": ["1", "x"], "empty": [None, None], "_row_id": [1, 2],
    }, dtype=object)
    s = C.infer_schema(df)
    assert s == {"zip": "text", "n": "bigint", "f": "double precision", "d": "text", "t": "timestamp", "mixed": "text", "empty": "text", "_row_id": "bigint"}


def test_sanitised_names_roundtrip_with_sample():
    names = sanitise_columns(["Transaction ID", "customerID", "Amount (GBP)"])
    assert names == ["transaction_id", "customer_id", "amount_gbp"]
