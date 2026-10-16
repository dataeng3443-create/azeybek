from __future__ import annotations

from datetime import date

from ai_provider import AIProvider
from models import QueryPlan
from semantic_fields import SUPPORTED_MEASURES


def window_start(latest: date | None, months: int | None) -> date | None:
    """First day of the month that opens a trailing window of ``months`` months ending at ``latest``."""
    if not latest or not months:
        return None
    index = latest.year * 12 + (latest.month - 1) - (months - 1)
    return date(index // 12, index % 12 + 1, 1)


def deterministic_dax(plan: QueryPlan, start: date | None = None) -> str:
    measure = plan.measures[0] if plan.measures else "Total Allocation"
    date_filter = f"'Date'[Date] >= DATE({start.year}, {start.month}, {start.day})" if start else None
    if plan.intent == "single_metric":
        value = f"CALCULATE([{measure}], {date_filter})" if date_filter else f"[{measure}]"
        return f'EVALUATE ROW("{measure}", {value})'
    dimensions = plan.dimensions or ["Fund.FundName"]
    columns = ", ".join("'{}'[{}]".format(*dimension.split(".", 1)) for dimension in dimensions)
    column = dimensions[0].split(".", 1)[1]
    filter_arg = f", FILTER('Date', {date_filter})" if date_filter else ""
    base = f"SUMMARIZECOLUMNS({columns}{filter_arg}, \"{measure}\", [{measure}])"
    if plan.intent == "ranking":
        return f"EVALUATE TOPN({plan.top_n or 10}, {base}, [{measure}], DESC) ORDER BY [{measure}] DESC"
    if plan.intent == "time_series":
        return f"EVALUATE {base} ORDER BY [{column}] ASC"
    return f"EVALUATE {base} ORDER BY [{measure}] DESC"


class DaxGenerator:
    def __init__(self, ai: AIProvider | None = None):
        self.ai = ai

    def generate(self, plan: QueryPlan, context: dict[str, object], use_ai: bool, start: date | None = None) -> tuple[str, bool]:
        fallback = deterministic_dax(plan, start)
        if not self.ai or not use_ai:
            return fallback, False
        prompt = ("You are a read-only DAX query writer. Return JSON with exactly one property: {\"dax\": \"...\"}.\n"
                  "Rules: start with EVALUATE; use only SUMMARIZECOLUMNS, TOPN, FILTER, CALCULATE, ROW and DATE; "
                  "always write column references with quoted table names like 'Fund'[FundName]; "
                  f"use only these measures: {', '.join(SUPPORTED_MEASURES)}.\n"
                  "Example: EVALUATE SUMMARIZECOLUMNS('Fund'[RiskLevel], \"Total Allocation\", [Total Allocation]) ORDER BY [Total Allocation] DESC\n"
                  + (f"The query must include the date filter 'Date'[Date] >= DATE({start.year}, {start.month}, {start.day}).\n" if start else "")
                  + f"Plan: {plan.model_dump_json()}. Relevant schema: {context}.")
        try:
            response = self.ai.generate_json(prompt)
            return str(response.get("dax", fallback)), True
        except (ValueError, RuntimeError):
            return fallback, False
