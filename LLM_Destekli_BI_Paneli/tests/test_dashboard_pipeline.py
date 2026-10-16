"""End-to-end checks that "Dashboard'u oluştur" always yields a chart-ready result."""
import pytest

from ai_agent import AnalyticsAgent
from ai_provider import AIProvider
from dax_validator import DaxValidator
from synthetic_provider import SyntheticProvider

VISUALS = {"line", "bar", "stacked_bar", "pie", "scatter"}


class ScriptedAI(AIProvider):
    """Returns planner, DAX and dashboard responses in order, like a local LLM would."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), 0

    def generate(self, prompt):
        return ""

    def health_check(self):
        return True, "ok"

    def generate_json(self, prompt):
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture(scope="module")
def provider():
    return SyntheticProvider()


def _visuals(result):
    return [component for component in result.dashboard.components if component.type in VISUALS]


@pytest.mark.parametrize("question, column", [
    ("Show total allocation by fund", "FundName"),
    ("Compare allocation by risk level", "RiskLevel"),
    ("Which investor segment has the highest allocation?", "Segment"),
    ("Varlık sınıfına göre pasta grafik", "AssetClass"),
    ("Bölgelere göre getiri", "Region"),
])
def test_breakdown_questions_produce_a_chart_without_ai(provider, question, column):
    result = AnalyticsAgent(provider, None, 2, 4).answer(question, {})
    assert column in result.result_columns and result.row_count > 1
    assert _visuals(result)


def test_total_question_is_a_single_kpi(provider):
    result = AnalyticsAgent(provider, None, 2, 4).answer("Toplam tahsis ne kadar?", {})
    assert result.plan.intent == "single_metric" and result.row_count == 1


def test_last_n_months_filters_the_trend(provider):
    result = AnalyticsAgent(provider, None, 2, 4).answer("Show allocation trend over the last 12 months", {})
    assert result.row_count == 12 and _visuals(result)[0].type == "line"


def test_requested_pie_chart_is_honoured(provider):
    result = AnalyticsAgent(provider, None, 2, 4).answer("Varlık sınıfına göre pasta grafik", {})
    assert _visuals(result)[0].type == "pie"


def test_unquoted_table_names_from_ai_still_group(provider):
    ai = ScriptedAI({"intent": "comparison", "dimensions": ["Fund.FundName"], "measures": ["Total Allocation"]},
                    {"dax": 'EVALUATE SUMMARIZECOLUMNS(Fund[FundName], "Total Allocation", [Total Allocation])'},
                    {"title": "t", "components": [{"id": "c", "type": "bar_chart", "x": "Fund.FundName", "y": "Total Allocation", "priority": 1}]})
    result = AnalyticsAgent(provider, ai, 2, 4).answer("Show total allocation by fund", {})
    assert result.row_count == 30 and _visuals(result)[0].x == "FundName"


def test_loosely_written_ai_plan_does_not_crash(provider):
    ai = ScriptedAI({"intent": "comparison", "dimensions": ["Fund[RiskLevel]"], "measures": ["Allocation.AllocationAmount"]},
                    {"dax": "not dax"}, ValueError("bad json"))
    result = AnalyticsAgent(provider, ai, 0, 4).answer("Compare allocation by risk level", {})
    assert "RiskLevel" in result.result_columns and _visuals(result)


def test_ai_dashboard_without_chart_gets_one(provider):
    ai = ScriptedAI({"intent": "comparison", "dimensions": ["Fund.RiskLevel"], "measures": ["Total Allocation"]},
                    {"dax": "EVALUATE SUMMARIZECOLUMNS('Fund'[RiskLevel], \"Total Allocation\", [Total Allocation])"},
                    {"title": "t", "components": [{"id": "k", "type": "kpi", "metric": "Total Allocation", "priority": 1}]})
    result = AnalyticsAgent(provider, ai, 2, 4).answer("Compare allocation by risk level", {})
    assert _visuals(result)


def test_ai_single_number_for_breakdown_question_is_corrected(provider):
    ai = ScriptedAI({"intent": "comparison", "dimensions": ["Fund.RiskLevel"], "measures": ["Total Allocation"]},
                    {"dax": 'EVALUATE ROW("Total Allocation", [Total Allocation])'}, ValueError("x"))
    result = AnalyticsAgent(provider, ai, 2, 4).answer("Compare allocation by risk level", {})
    assert "RiskLevel" in result.result_columns and result.warnings


def test_validator_checks_unquoted_table_references(provider):
    from dax_validator import DaxValidationError
    with pytest.raises(DaxValidationError):
        DaxValidator(provider.get_schema()).validate('EVALUATE SUMMARIZECOLUMNS(Fund[NotAField], "Total Allocation", [Total Allocation])')
