from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from plotly_renderer import PALETTE, apply_theme
from relationship_diagram import relationship_svg, relationship_table
from synthetic_provider import SyntheticProvider


def _money(value: float) -> str:
    return f"{value / 1_000_000:,.1f}M" if abs(value) >= 1_000_000 else f"{value:,.0f}"


def render_workspace_overview(provider: SyntheticProvider, filters: dict[str, str] | None = None, compact: bool = False) -> None:
    model = provider.model
    facts = provider.dashboard_frame(filters).copy()
    if not compact:
        st.markdown("<div class='dashboard-title'><h2>Fund Allocation Command Center</h2><p>Portfolio, investor, asset and market intelligence <span>• Synthetic Data</span></p></div>", unsafe_allow_html=True)
    total = float(facts.AllocationAmount.sum())
    avg_return = float(facts.ReturnPercent.mean())
    net_flow = float(facts.NetFlow.sum())
    variance = float((facts.ActualAllocation.sum() - facts.TargetAllocation.sum()) / facts.TargetAllocation.sum())
    metrics = st.columns(4)
    for column, label, value, note in zip(metrics, ("Total allocation", "Average return", "Net flow", "Target variance"), (_money(total), f"{avg_return:.2%}", _money(net_flow), f"{variance:.2%}"), ("Across all positions", "Average monthly return", "Subscriptions less redemptions", "Actual versus target")):
        with column:
            st.markdown(f"<div class='kpi-card'><div class='kpi-label'>{label}</div><div class='kpi-value'>{value}</div><div class='kpi-note'>{note}</div></div>", unsafe_allow_html=True)

    monthly = facts.groupby("YearMonth", as_index=False).agg({"AllocationAmount": "sum", "NetFlow": "sum"})
    asset = facts.groupby("AssetClass", as_index=False).AllocationAmount.sum()
    fund_type = facts.groupby("FundType", as_index=False).agg(AllocationAmount=("AllocationAmount", "sum"), ReturnPercent=("ReturnPercent", "mean"))
    top_funds = facts.groupby("FundName", as_index=False).AllocationAmount.sum().nlargest(10, "AllocationAmount").sort_values("AllocationAmount")

    left, right = st.columns([1.65, 1])
    with left:
        trend = px.line(monthly, x="YearMonth", y="AllocationAmount", title="Allocation trend", markers=True, color_discrete_sequence=[PALETTE[0]])
        trend.update_traces(line={"width": 2, "shape": "spline", "smoothing": 0.6}, marker={"size": 6, "line": {"width": 1.5, "color": "#FFFFFF"}})
        st.plotly_chart(apply_theme(trend), use_container_width=True, config={"displayModeBar": False}, theme=None)
    with right:
        pie = px.pie(asset, names="AssetClass", values="AllocationAmount", title="Allocation by asset class", hole=.58, color_discrete_sequence=PALETTE)
        st.plotly_chart(apply_theme(pie), use_container_width=True, config={"displayModeBar": False}, theme=None)
    left, right = st.columns(2)
    with left:
        bar = px.bar(fund_type.sort_values("AllocationAmount"), x="FundType", y="AllocationAmount", color="FundType", title="Allocation by fund type", color_discrete_sequence=PALETTE)
        st.plotly_chart(apply_theme(bar), use_container_width=True, config={"displayModeBar": False}, theme=None)
    with right:
        ranking = px.bar(top_funds, x="AllocationAmount", y="FundName", orientation="h", title="Top 10 funds by allocation", color_discrete_sequence=[PALETTE[1]])
        st.plotly_chart(apply_theme(ranking), use_container_width=True, config={"displayModeBar": False}, theme=None)
    if not compact:
        st.markdown("<div class='insight-card'><b>Workspace overview</b><br>Explore a governed synthetic semantic model first, then use the question box to let the AI build a focused analytical view.</div>", unsafe_allow_html=True)


def render_model_explorer(provider: SyntheticProvider) -> None:
    model = provider.model
    st.markdown("<div class='section-label'>SYNTHETIC SEMANTIC MODEL EXPLORER</div>", unsafe_allow_html=True)
    tables, schema, relationships = st.tabs(["Data tables", "Schema & measures", "Relationships"])
    frames: dict[str, pd.DataFrame] = {"Fund": model.funds, "Date": model.dates, "Investor": model.investors, "Asset": model.assets, "Market": model.market, "Allocation": model.allocation}
    with tables:
        table_map: dict[str, pd.DataFrame] = {("Allocation (fact)" if name == "Allocation" else name): frame for name, frame in frames.items()}
        selected = st.selectbox("Inspect a synthetic table", list(table_map), key="model_table")
        frame = table_map[selected]
        info = st.columns(3)
        info[0].metric("Rows", f"{len(frame):,}")
        info[1].metric("Columns", len(frame.columns))
        info[2].metric("Data type", "Fact" if "Allocation" in selected else "Dimension")
        st.dataframe(frame.head(500), use_container_width=True, hide_index=True, height=310)
        st.caption("Preview is capped at 500 rows. Data is deterministic and synthetic; no company data is included.")
    with schema:
        fields = []
        for table in model.schema.tables:
            for column in table.columns:
                fields.append({"Table": table.name, "Field": column.name, "Type": column.data_type, "Kind": "Column"})
            for measure in table.measures:
                fields.append({"Table": table.name, "Field": measure.name, "Type": measure.expression, "Kind": "Measure"})
        st.dataframe(pd.DataFrame(fields), use_container_width=True, hide_index=True, height=330)
        st.caption("Relationships: " + " • ".join(f"{item.from_table}[{item.from_column}] → {item.to_table}[{item.to_column}]" for item in model.schema.relationships))
    with relationships:
        st.caption("Model view: dimension tables (1) filter the Allocation fact table (*). Highlighted rows are the key columns that join the tables.")
        st.markdown(f"<div style='overflow-x:auto'>{relationship_svg(model.schema, frames)}</div>", unsafe_allow_html=True)
        st.dataframe(relationship_table(model.schema, frames), use_container_width=True, hide_index=True)
