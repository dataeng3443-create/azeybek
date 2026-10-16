from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from models import DashboardComponent, DashboardSpec
from plotly_renderer import chart


def _format(value: object, metric: str) -> str:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return str(value)
    if "%" in metric or "Return" in metric:
        return f"{float(value):.2%}"
    if abs(float(value)) >= 1_000_000:
        return f"{float(value) / 1_000_000:.1f}M"
    return f"{float(value):,.0f}"


def _metric_value(frame: pd.DataFrame, metric: str | None) -> tuple[str, object]:
    numeric = frame.select_dtypes("number").columns.tolist()
    selected = metric if metric in frame.columns else (numeric[0] if numeric else None)
    if not selected:
        return "Value", "—"
    if len(frame) == 1:
        return selected, frame[selected].iloc[0]
    # Averages and percentages must not be summed across rows.
    is_average = "%" in selected or selected.startswith("Average") or "Return" in selected
    return selected, frame[selected].mean() if is_average else frame[selected].sum()


def render(spec: DashboardSpec, frame: pd.DataFrame) -> None:
    st.markdown(f"<div class='dashboard-title'><h2>{spec.title}</h2><p>{spec.subtitle} <span>• Synthetic Data</span></p></div>", unsafe_allow_html=True)
    kpis = spec.kpis()
    if kpis:
        columns = st.columns(min(len(kpis), 4))
        for column, component in zip(columns, kpis):
            label, value = _metric_value(frame, component.metric)
            with column:
                st.markdown(f"<div class='kpi-card'><div class='kpi-label'>{component.title or label}</div><div class='kpi-value'>{_format(value, label)}</div><div class='kpi-note'>Selected synthetic scope</div></div>", unsafe_allow_html=True)
    visuals = [component for component in spec.components if component.type in {"line", "bar", "stacked_bar", "pie", "scatter"}]
    tables = [component for component in spec.components if component.type == "table"]
    insights = [component for component in spec.components if component.type == "insight"]
    if len(visuals) >= 2:
        left, right = st.columns([1.55, 1])
        for column, component in zip((left, right), visuals[:2]):
            with column:
                _render_visual(component, frame)
        for component in visuals[2:]:
            _render_visual(component, frame)
    else:
        for component in visuals:
            _render_visual(component, frame)
    for component in insights:
        st.markdown(f"<div class='insight-card'><b>AI insight</b><br>{component.text}</div>", unsafe_allow_html=True)
    for _component in tables:
        st.dataframe(frame, use_container_width=True, hide_index=True)


def _render_visual(component: DashboardComponent, frame: pd.DataFrame) -> None:
    numeric = frame.select_dtypes("number").columns.tolist()
    y = component.y if component.y in frame.columns else (numeric[0] if numeric else None)
    x = component.x if component.x in frame.columns else next((column for column in frame.columns if column != y), None)
    if not x or not y or frame.empty:
        st.info("Bu sonuç için grafik çizilemedi; değerleri aşağıdaki tabloda görebilirsin.")
        return
    if x and y:
        st.plotly_chart(chart(frame, component.type, x, y, component.title or y, component.color if component.color in frame.columns else None), use_container_width=True, config={"displayModeBar": False}, theme=None)
