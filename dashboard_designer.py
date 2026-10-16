from __future__ import annotations

from typing import Any

import pandas as pd

from ai_provider import AIProvider
from models import DashboardComponent, DashboardFilter, DashboardSpec, QueryPlan
from semantic_fields import requested_chart

VISUAL_TYPES = {"line", "bar", "stacked_bar", "pie", "scatter"}
COMPONENT_TYPES = VISUAL_TYPES | {"kpi", "table", "insight", "text"}
TYPE_ALIASES = {"bar_chart": "bar", "column": "bar", "column_chart": "bar", "line_chart": "line", "area": "line",
                "pie_chart": "pie", "donut": "pie", "doughnut": "pie", "scatter_plot": "scatter", "stacked": "stacked_bar",
                "stacked_bar_chart": "stacked_bar", "card": "kpi", "metric": "kpi", "kpi_card": "kpi", "grid": "table"}


def _pick_chart(plan: QueryPlan, frame: pd.DataFrame) -> str:
    requested = (plan.requested_visualization or "").lower()
    if requested in VISUAL_TYPES:
        return requested
    if plan.intent == "time_series" or "YearMonth" in frame.columns:
        return "line"
    if plan.intent == "single_metric" or len(frame) <= 1:
        return "kpi"
    return "bar"


def _columns(frame: pd.DataFrame) -> tuple[list[str], list[str]]:
    numeric = [column for column in frame.columns if pd.api.types.is_numeric_dtype(frame[column])]
    return numeric, [column for column in frame.columns if column not in numeric]


def _resolve(name: Any, frame: pd.DataFrame) -> str | None:
    """Map 'Fund.FundName', 'Fund[FundName]' or 'fundname' onto an actual result column."""
    if not name:
        return None
    text = str(name).strip()
    if text in frame.columns:
        return text
    text = text.split(".")[-1].split("[")[-1].strip("[]'\" ")
    return next((column for column in frame.columns if str(column).lower() == text.lower()), None)


class DashboardDesigner:
    def __init__(self, ai: AIProvider | None, max_kpis: int = 4):
        self.ai, self.max_kpis = ai, max_kpis

    def design(self, question: str, plan: QueryPlan, frame: pd.DataFrame, use_ai: bool) -> tuple[DashboardSpec, bool]:
        fallback = self._deterministic(question, plan, frame)
        if not self.ai or not use_ai or frame.empty:
            return fallback, False
        numeric, dimensions = _columns(frame)
        prompt = ("Act as an analytics dashboard designer. Return one JSON DashboardSpec object, not code. Shape:\n"
                  '{"title": "...", "subtitle": "...", "components": ['
                  '{"id": "kpi1", "type": "kpi", "metric": "<numeric column>", "title": "...", "priority": 1}, '
                  '{"id": "chart1", "type": "bar", "x": "<dimension column>", "y": "<numeric column>", "title": "...", "priority": 1}, '
                  '{"id": "insight1", "type": "insight", "text": "one sentence insight from the sample data", "priority": 3}]}\n'
                  "Component types: kpi, line, bar, stacked_bar, pie, scatter, table, insight. At most four KPIs. "
                  "Include at least one chart. x and y must be exact column names from the result.\n"
                  f"Dimension columns: {dimensions}. Numeric columns: {numeric}. Rows: {len(frame)}. "
                  f"Preferred chart type: {_pick_chart(plan, frame)}.\n"
                  f"Question: {question}. Sample data: {frame.head(5).to_dict(orient='records')}")
        try:
            candidate = self._sanitize(self.ai.generate_json(prompt), plan, frame, fallback, requested_chart(question))
            return (candidate, True) if candidate else (fallback, False)
        except (ValueError, RuntimeError, TypeError):
            return fallback, False

    def _sanitize(self, raw: dict[str, Any], plan: QueryPlan, frame: pd.DataFrame, fallback: DashboardSpec, explicit_chart: str | None = None) -> DashboardSpec | None:
        """Repair common LLM deviations and guarantee the result shows a chart when one makes sense."""
        if isinstance(raw.get("dashboard"), dict):
            raw = raw["dashboard"]
        items = raw.get("components")
        if not isinstance(items, list):
            return None
        numeric, dimensions = _columns(frame)
        requested = explicit_chart or ""
        components: list[DashboardComponent] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type", "")).lower().replace(" ", "_")
            kind = TYPE_ALIASES.get(kind, kind)
            if kind not in COMPONENT_TYPES:
                continue
            if kind == "text":
                kind = "insight"
            try:
                priority = min(max(int(item.get("priority") or 2), 1), 4)
            except (TypeError, ValueError):
                priority = 2
            component = {"id": str(item.get("id") or f"{kind}_{index}"), "type": kind, "title": item.get("title"), "priority": priority}
            if kind == "kpi":
                metric = _resolve(item.get("metric") or item.get("y"), frame)
                if not metric:
                    continue
                component["metric"] = metric
            elif kind in VISUAL_TYPES:
                x, y = _resolve(item.get("x"), frame), _resolve(item.get("y"), frame)
                x = x if x in dimensions else (dimensions[0] if dimensions else None)
                y = y if y in numeric else (numeric[0] if numeric else None)
                if not x or not y:
                    continue
                color = _resolve(item.get("color"), frame)
                component.update(x=x, y=y, color=color if color in dimensions and color != x else None)
            elif kind == "insight":
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                component["text"] = text
            components.append(DashboardComponent(**component))
        kpis = [component for component in components if component.type == "kpi"][: self.max_kpis]
        others = [component for component in components if component.type != "kpi"]
        components = kpis + others
        primary_fallback = next((component for component in fallback.components if component.type in VISUAL_TYPES | {"table"}), None)
        visuals = [component for component in components if component.type in VISUAL_TYPES | {"table"}]
        if primary_fallback and not visuals:
            components.insert(len(kpis), primary_fallback)
        elif visuals and requested in VISUAL_TYPES | {"table"} and visuals[0].type != requested:
            # The user explicitly asked for a chart type; honour it on the main visual.
            index = components.index(visuals[0])
            components[index] = primary_fallback or visuals[0].model_copy(update={"type": requested})
        if not components:
            return None
        if not any(component.type == "insight" for component in components):
            components.extend(component for component in fallback.components if component.type == "insight")
        try:
            return DashboardSpec(title=str(raw.get("title") or fallback.title), subtitle=str(raw.get("subtitle") or fallback.subtitle),
                                 layout=fallback.layout, complexity=fallback.complexity, filters=fallback.filters, components=components[:10])
        except ValueError:
            return None

    def _deterministic(self, question: str, plan: QueryPlan, frame: pd.DataFrame) -> DashboardSpec:
        numeric, dimensions = _columns(frame)
        metric = plan.measures[0] if plan.measures and plan.measures[0] in frame.columns else (numeric[0] if numeric else "Total Allocation")
        dimension = dimensions[0] if dimensions else None
        color = dimensions[1] if len(dimensions) > 1 else None
        chart = _pick_chart(plan, frame)
        components = [DashboardComponent(id="primary_kpi", type="kpi", metric=metric, title=metric, priority=1)]
        if chart != "kpi" and dimension and metric in frame:
            if chart == "pie" and color:  # a pie cannot show two dimensions; aggregate first
                chart = "stacked_bar"
            components.append(DashboardComponent(id="primary_chart", type=chart, title=f"{metric} by {dimension}" + (f" and {color}" if color else ""), x=dimension, y=metric, color=color, priority=1))
            if (plan.requested_visualization or "").lower() == "table":
                components.append(DashboardComponent(id="primary_table", type="table", title="Result table", priority=2))
        if plan.intent == "overview" and dimension and metric in frame:
            components.append(DashboardComponent(id="comparison", type="pie", title=f"Share of {metric}", x=dimension, y=metric, priority=2))
        components.append(DashboardComponent(id="insight", type="insight", text=self._insight(frame, metric, dimension), priority=3))
        return DashboardSpec(title="Fund Allocation Analytics", subtitle="Synthetic Model • AI-assisted analysis", complexity="low" if plan.intent == "single_metric" else "medium", layout="single" if chart == "kpi" else "kpi_main_two_column", filters=[DashboardFilter(field="FundType"), DashboardFilter(field="RiskLevel")] if plan.intent in {"overview", "comparison"} else [], components=components)

    @staticmethod
    def _insight(frame: pd.DataFrame, metric: str, dimension: str | None) -> str:
        if frame.empty or metric not in frame:
            return "No data is available for the selected filters."
        if dimension and dimension in frame and len(frame) > 1:
            top = frame.loc[frame[metric].idxmax()]
            return f"{top[dimension]} has the highest {metric.lower()} in this synthetic result."
        value = frame.iloc[0][metric]
        formatted = f"{value:.2%}" if "%" in metric else f"{value:,.2f}"
        return f"The selected synthetic data returns {formatted} for {metric}."
