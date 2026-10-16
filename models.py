from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ColumnSchema(BaseModel):
    name: str
    data_type: Literal["string", "integer", "number", "date"]


class MeasureSchema(BaseModel):
    name: str
    expression: str
    description: str


class TableSchema(BaseModel):
    name: str
    columns: list[ColumnSchema]
    measures: list[MeasureSchema] = Field(default_factory=list)


class RelationshipSchema(BaseModel):
    from_table: str
    from_column: str
    to_table: str
    to_column: str


class SemanticSchema(BaseModel):
    model: str
    tables: list[TableSchema]
    relationships: list[RelationshipSchema]


class QueryPlan(BaseModel):
    intent: Literal["overview", "comparison", "time_series", "ranking", "single_metric"]
    dimensions: list[str] = Field(default_factory=list)
    measures: list[str] = Field(default_factory=lambda: ["Total Allocation"])
    filters: list[dict[str, str]] = Field(default_factory=list)
    time_analysis: str | None = None
    requested_visualization: str | None = None
    time_window_months: int | None = Field(default=None, ge=1, le=120)
    top_n: int | None = Field(default=None, ge=1, le=100)


ComponentType = Literal["kpi", "line", "bar", "stacked_bar", "pie", "scatter", "table", "insight", "text"]


class DashboardComponent(BaseModel):
    id: str
    type: ComponentType
    title: str | None = None
    metric: str | None = None
    x: str | None = None
    y: str | None = None
    color: str | None = None
    priority: int = Field(ge=1, le=4)
    text: str | None = None


class DashboardFilter(BaseModel):
    field: str
    type: Literal["select"] = "select"
    default: str = "All"


class DashboardSpec(BaseModel):
    dashboard_type: Literal["analytical", "summary"] = "analytical"
    title: str
    subtitle: str = "Synthetic Model"
    complexity: Literal["low", "medium", "high"] = "medium"
    layout: Literal["single", "kpi_main", "kpi_main_two_column", "overview"] = "kpi_main_two_column"
    filters: list[DashboardFilter] = Field(default_factory=list)
    components: list[DashboardComponent] = Field(min_length=1, max_length=10)

    def kpis(self) -> list[DashboardComponent]:
        return [component for component in self.components if component.type == "kpi"]


class PipelineResult(BaseModel):
    plan: QueryPlan
    dax: str
    dashboard: DashboardSpec
    result_columns: list[str]
    row_count: int
    used_ollama: bool = False
    answer_text: str = ""
    warnings: list[str] = Field(default_factory=list)
    data: list[dict[str, Any]] = Field(default_factory=list)
