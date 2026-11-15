import pytest

from app.analysis import grounding
from tests.analysis_helpers import add_sql_result, state


@pytest.fixture()
def s():
    st = state()
    add_sql_result(st, ["customer_segment", "total", "share"], [["Private Banking", 5232418.209999995, 43.09805], ["Business", 4795591.17, 39.50002], ["Retail", 1990657.76, 16.39652]])
    st.validations.append({"claimed": 5232418.21, "recomputed": 5232418.21})
    return st


def check(s, *texts):
    return grounding.ungrounded_figures(list(texts), s)


class TestGrounding:
    def test_figures_from_results_match_in_any_reasonable_format(self, s):
        assert check(s, "Private Banking totals £5,232,418.21 (43.1% of volume).", "Business is 39.5%.", "About £5.2 million, or 5.23m.", "Retail: 1,990,658") == []

    def test_invented_or_miscopied_figures_are_reported(self, s):
        assert check(s, "Private Banking totals £5,432,418.21.") == ["£5,432,418.21"]
        assert "47.2%" in check(s, "Business accounts for 47.2% of volume.")

    def test_wrong_rounding_is_caught_but_correct_rounding_is_not(self, s):
        assert check(s, "Retail is 16.4%") == [] and check(s, "Retail is 16.9%") == ["16.9%"]

    def test_row_counts_and_dataset_sizes_are_known(self, s):
        assert check(s, "Across 1,000 rows and 5 columns, 3 segments appear.") == []

    def test_scientific_notation(self, s):
        add_sql_result(s, ["m", "v"], [["p_value", 2.0152582760758622e-36], ["r", 0.12326]])
        assert check(s, "The p-value is 2.02e-36 and r = 0.12.") == []
        assert check(s, "The p-value is 4.5e-12.") == ["4.5e-12"]

    def test_small_numbers_years_and_result_ids_are_ignored(self, s):
        assert check(s, "In 2024, the top 3 segments (see r1 and c2) in Q3 changed by 2 steps over 12 months.") == []

    def test_arithmetic_the_model_did_itself_is_flagged_not_trusted(self, s):
        out = check(s, "Private Banking exceeds Business by £436,827.04.")
        assert out == ["£436,827.04"]

    def test_duplicates_are_listed_once_and_capped(self, s):
        text = " ".join(f"{1000 + i * 7919}.5 and" for i in range(30)) + " 777777.7 777777.7"
        out = check(s, text)
        assert len(out) == grounding.MAX_REPORTED and len(set(out)) == len(out)

    def test_warning_shape(self, s):
        w = grounding.grounding_warning({"executive_summary": "Revenue was £999,999.99.", "key_findings": [{"finding": "Business is 39.5%", "evidence": ""}]}, s)
        assert w["status"] == "warning" and "1 figure" in w["label"] and "£999,999.99" in w["detail"] and "Check them" in w["detail"]
        assert grounding.grounding_warning({"executive_summary": "Business is 39.5%.", "key_findings": []}, s) is None

    def test_no_results_means_nothing_to_ground_against(self):
        assert grounding.grounding_warning({"executive_summary": "Revenue was £1,234.", "key_findings": []}, state()) is None

    def test_agent_adds_the_warning_to_the_payload(self, monkeypatch):
        from app.analysis import tools, validation
        from app.analysis.sql_exec import SqlResult
        from tests.analysis_helpers import tool_call_message
        from tests.test_agent_and_llm import ANSWER, SQL, ScriptedLLM, run

        monkeypatch.setattr(tools, "execute_readonly", lambda q: SqlResult(["customer_segment", "total"], [["Retail", 10.0], ["Student", 5.0]], 2, False, 3.0))
        monkeypatch.setattr(validation, "execute_trusted", lambda q, p=None: [(15.0,)])
        invented = {**ANSWER, "executive_summary": "Retail contributes £77,777.77, the most."}
        p, _ = run(ScriptedLLM([tool_call_message(SQL), tool_call_message(("validate_results", {"checks": [{"type": "null_exposure", "label": "n", "column": "transaction_amount"}]})), tool_call_message(("explain_results", invented))]))
        assert any(w["id"] == "w-grounding" and "£77,777.77" in w["detail"] for w in p["validation"]["warnings"])
