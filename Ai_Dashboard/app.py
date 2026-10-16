from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
import streamlit as st

from ai_agent import AnalyticsAgent
from config import Settings
from dashboard_renderer import render
from ollama_provider import OllamaProvider
from synthetic_provider import SyntheticProvider
from workspace_overview import render_model_explorer, render_workspace_overview

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
st.set_page_config(page_title="LLM-Powered BI Dashboard", page_icon="◈", layout="wide", initial_sidebar_state="expanded")

CSS = """
<style>
  .stApp { background: #F7F8FC; color: #18233A; }
  [data-testid='stSidebar'] { background: #111B32; } [data-testid='stSidebar'] * { color: #EEF2FF; }
  .brand { padding: .7rem .25rem 1.5rem; } .brand h1 { font-size: 1.45rem; margin:0; color:#fff; } .brand p { color:#A5B4D4; margin:.25rem 0; }
  .dashboard-title { margin: .3rem 0 1.1rem; } .dashboard-title h2 { margin:0; font-size:1.55rem; } .dashboard-title p { color:#65718A; margin:.25rem 0; } .dashboard-title span { color:#7C3AED; font-weight:600; }
  .kpi-card { background:#fff; border:1px solid #E7EAF1; border-radius:14px; padding:1rem 1.1rem; min-height:115px; box-shadow:0 4px 16px rgba(24,35,58,.04); }
  .kpi-label { font-size:.73rem; color:#64748B; text-transform:uppercase; letter-spacing:.06em; font-weight:700; } .kpi-value { font-size:1.65rem; font-weight:750; margin:.35rem 0; color:#172554; } .kpi-note { font-size:.72rem; color:#94A3B8; }
  .insight-card { border-left:4px solid #6D5CE7; background:#F1F0FF; border-radius:8px; padding:1rem 1.2rem; color:#312E81; margin-top:.8rem; }
  .sample { background:#1D2B4B; border:1px solid #344767; border-radius:8px; margin:.35rem 0; padding:.55rem .65rem; font-size:.82rem; }
  .section-label { color:#64748B; font-size:.72rem; font-weight:800; letter-spacing:.12em; margin:2rem 0 .6rem; }
  .answer-card { background:#FFFFFF; border:1px solid #DDE3EE; border-radius:12px; padding:1rem 1.15rem; margin:1rem 0; color:#172554; box-shadow:0 4px 16px rgba(24,35,58,.035); }
  /* Keep prompt controls readable even when Streamlit inherits a dark system theme. */
  [data-testid='stMain'] .stButton > button { background:#FFFFFF !important; color:#172554 !important; border:1px solid #CBD5E1 !important; }
  [data-testid='stMain'] .stButton > button:hover { background:#EEF2FF !important; border-color:#818CF8 !important; color:#1E1B4B !important; }
  [data-testid='stMain'] .stButton > button *, [data-testid='stMain'] .stButton > button p { color:#172554 !important; }
  [data-testid='stMain'] [data-testid='stFormSubmitButton'] > button { background:#FF4B4B !important; border-color:#FF4B4B !important; }
  [data-testid='stMain'] [data-testid='stFormSubmitButton'] > button *, [data-testid='stMain'] [data-testid='stFormSubmitButton'] > button p { color:#FFFFFF !important; }
  [data-testid='stMain'] [data-testid='stTextArea'] label, [data-testid='stMain'] [data-testid='stTextArea'] label * { color:#172554 !important; }
  [data-testid='stMain'] [data-testid='stTextArea'] textarea { background:#FFFFFF !important; color:#172554 !important; caret-color:#172554 !important; border:1px solid #94A3B8 !important; }
  [data-testid='stMain'] [data-testid='stTextArea'] textarea::placeholder { color:#64748B !important; opacity:1 !important; }
  /* Streamlit may inject its own Plotly dark-mode token after the figure JSON is sent.
     Override only chart chrome (not pie slice labels) so every label stays readable. */
  [data-testid='stPlotlyChart'] .main-svg .gtitle,
  [data-testid='stPlotlyChart'] .main-svg .xtitle,
  [data-testid='stPlotlyChart'] .main-svg .ytitle,
  [data-testid='stPlotlyChart'] .main-svg .xtick text,
  [data-testid='stPlotlyChart'] .main-svg .ytick text,
  [data-testid='stPlotlyChart'] .main-svg .legendtext,
  [data-testid='stPlotlyChart'] .main-svg .legendtitletext { fill:#172554 !important; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def _use_suggested_question(question: str) -> None:
    st.session_state.question_draft = question


@st.cache_resource(show_spinner=False)
def services() -> tuple[Settings, SyntheticProvider, OllamaProvider]:
    settings = Settings.from_env()
    return settings, SyntheticProvider(settings.synthetic_seed, settings.max_result_rows), OllamaProvider(settings.ollama_base_url, settings.ollama_model, settings.ollama_timeout_seconds, settings.ollama_temperature)


def main() -> None:
    settings, provider, ollama = services()
    filter_fields = ("FundType", "RiskLevel", "Region", "AssetClass")
    if "history" not in st.session_state:
        st.session_state.history = []
    if "question_draft" not in st.session_state:
        st.session_state.question_draft = "Show allocation trend over the last 12 months"
    if "applied_filters" not in st.session_state:
        st.session_state.applied_filters = {field: "All" for field in filter_fields}
    for field in filter_fields:
        st.session_state.setdefault(f"filter_draft_{field}", st.session_state.applied_filters.get(field, "All"))

    def apply_filters() -> None:
        st.session_state.applied_filters = {field: st.session_state[f"filter_draft_{field}"] for field in filter_fields}

    def clear_filters() -> None:
        st.session_state.applied_filters = {field: "All" for field in filter_fields}
        for field in filter_fields:
            st.session_state[f"filter_draft_{field}"] = "All"

    with st.sidebar:
        st.markdown("<div class='brand'><h1>LLM-Powered BI Dashboard</h1><p>Analytics Workspace</p></div>", unsafe_allow_html=True)
        available, status = ollama.health_check()
        st.success("● Synthetic Model")
        status_label = f"Connected ({ollama.model})" if available else status
        (st.success if available else st.warning)(f"● {status_label}")
        st.caption(f"{ollama.model} is used when available; deterministic, validated fallbacks keep the prototype usable offline.")
        st.divider()
        st.subheader("Global filters")
        # A form creates an explicit Power BI-style "choose, then apply" action.
        # It also prevents an unrelated Streamlit rerun from discarding draft choices.
        with st.form("global_filter_form", clear_on_submit=False):
            for field in filter_fields:
                options = ["All", *provider.filter_values(field)]
                st.selectbox(field, options, key=f"filter_draft_{field}")
            apply_clicked = st.form_submit_button("Filtreleri uygula", type="primary", use_container_width=True)
        if apply_clicked:
            apply_filters()
        st.button("Filtreleri temizle", use_container_width=True, on_click=clear_filters)
        filters = st.session_state.applied_filters
        active_filter_names = [f"{field}: {value}" for field, value in filters.items() if value != "All"]
        if active_filter_names:
            st.caption("Uygulanan: " + " · ".join(active_filter_names))
            st.caption(f"Dashboard scope: {len(provider.dashboard_frame(filters)):,} allocation records")
        else:
            st.caption("Henüz filtre uygulanmadı.")
        st.divider()
        st.subheader("Try a question")
        examples = ["Show total allocation by fund", "Show allocation trend over the last 12 months", "Compare allocation by risk level", "Show the top 10 funds", "Which investor segment has the highest allocation?"]
        for example in examples:
            st.button(example, use_container_width=True, key=f"example-{example}", on_click=_use_suggested_question, args=(example,))

    st.markdown("<div class='section-label'>QUESTION SUGGESTIONS</div>", unsafe_allow_html=True)
    quick_examples = ["Show total allocation by fund", "Show allocation trend over the last 12 months", "Compare allocation by risk level", "Show the top 10 funds", "Which investor segment has the highest allocation?"]
    quick_columns = st.columns(len(quick_examples))
    for column, example in zip(quick_columns, quick_examples):
        with column:
            st.button(example, key=f"quick-{example}", use_container_width=True, on_click=_use_suggested_question, args=(example,))
    with st.form("question_form", clear_on_submit=False):
        question = st.text_area("Kendi sorunu sor", key="question_draft", height=86, placeholder="Örn. Son 12 ayda hangi fon türü en yüksek net flow üretti?")
        run = st.form_submit_button("Dashboard’u oluştur", type="primary")
    with st.expander("Generated DAX", expanded=False):
        manual_dax = st.text_area("Edit DAX and run through the same validation pipeline", value=st.session_state.get("manual_dax", ""), height=130, key="manual_dax")
        run_manual = st.button("Run Query")
    if run or run_manual:
        agent = AnalyticsAgent(provider, ollama if available else None, settings.max_dax_repair_attempts, settings.max_dashboard_kpis)
        stages = st.status("Building your analytics workspace…", expanded=True)
        try:
            for label in ("Understanding question", "Selecting relevant model fields", "Generating and validating analytical query", "Running synthetic semantic model", "Designing dashboard"):
                stages.write(f"✓ {label}")
            result = agent.answer(question, filters, manual_dax if run_manual and manual_dax.strip() else None, prefer_ai=available)
            stages.update(label="Dashboard ready", state="complete", expanded=False)
            st.session_state.result = result
            st.session_state.history = ([{"question": question, "dax": result.dax, "dashboard_spec": result.dashboard.model_dump(), "timestamp": datetime.now().isoformat(timespec="seconds"), "status": "success"}] + st.session_state.history)[:settings.max_history_items]
        except Exception as error:  # User-safe error boundary; details remain in server logs.
            logging.exception("dashboard_generation_failed")
            stages.update(label="Could not build dashboard", state="error")
            st.error("Synthetic query execution failed. The query uses an unsupported analytical pattern or no data matches the selected filters.")
            st.caption(f"Error type: {type(error).__name__}")
    result = st.session_state.get("result")
    # Streamlit preserves session objects across hot reloads. Results created by
    # an older PipelineResult schema do not contain the newer answer_text field.
    if result is not None and not hasattr(result, "answer_text"):
        st.session_state.pop("result", None)
        result = None
        st.info("Uygulama güncellendi. Sorunu yeniden çalıştırarak güncel yanıt ve dashboard’u oluşturabilirsin.")
    if result:
        # Re-run only the stored, already validated query against current filters.
        # This makes sidebar changes immediate without another Ollama request.
        frame = provider.execute_dax(result.dax, filters)
        answer_text = AnalyticsAgent._answer_from_result(result.plan, frame)
        st.markdown(f"<div class='answer-card'><b>Yanıt</b><br>{answer_text}</div>", unsafe_allow_html=True)
        source = f"{settings.ollama_model} ile oluşturuldu" if result.used_ollama else "Kural tabanlı yedek mantıkla oluşturuldu (Ollama kullanılmadı)"
        st.caption(f"{source} • Soru tipi: {result.plan.intent}")
        if active_filter_names:
            st.caption("Bu AI dashboard’u, yukarıdaki uygulanan filtrelerle yeniden hesaplandı.")
        render(result.dashboard, frame)
        with st.expander("Kullanılan DAX sorgusu"):
            st.code(result.dax, language="sql")
        if result.warnings:
            with st.expander("Validation notes"):
                for warning in result.warnings:
                    st.warning(warning)
        with st.expander("View Data"):
            st.caption(f"{result.row_count:,} rows • capped by MAX_RESULT_ROWS")
            st.dataframe(frame.head(settings.max_result_rows), use_container_width=True, hide_index=True)
        st.divider()
        render_workspace_overview(provider, filters, compact=True)
    else:
        render_workspace_overview(provider, filters)
    render_model_explorer(provider)
    if st.session_state.history:
        with st.expander("Question History"):
            for item in st.session_state.history:
                st.write(f"**{item['question']}** — {item['timestamp']}")


if __name__ == "__main__":
    main()
