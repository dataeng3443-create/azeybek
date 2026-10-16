from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

PALETTE = ["#4F46E5", "#16A34A", "#0EA5E9", "#F59E0B", "#EC4899", "#7C3AED"]


def apply_theme(fig: go.Figure) -> go.Figure:
    dark_text = "#111827"
    fig.update_layout(template="plotly_white", paper_bgcolor="#ffffff", plot_bgcolor="#ffffff", font={"family": "Inter, ui-sans-serif, system-ui", "color": dark_text}, margin={"l": 12, "r": 12, "t": 44, "b": 12}, legend_title_text="", legend={"font": {"color": dark_text, "size": 13}, "title": {"font": {"color": dark_text}}, "bgcolor": "rgba(255,255,255,.94)"}, hoverlabel={"bgcolor": "#18233A", "font_color": "white"})
    fig.update_xaxes(showgrid=False, linecolor="#E5E7EB", tickfont={"color": dark_text}, title_font={"color": dark_text})
    fig.update_yaxes(gridcolor="#EEF2F7", zeroline=False, tickfont={"color": dark_text}, title_font={"color": dark_text})
    # Pie/bar labels are trace text, not layout text; set them separately.
    fig.update_traces(textfont={"color": dark_text}, selector={"type": "pie"})
    fig.update_traces(textfont={"color": dark_text}, selector={"type": "bar"})
    return fig


def chart(frame: pd.DataFrame, visual_type: str, x: str, y: str, title: str, color: str | None = None) -> go.Figure:
    if visual_type == "line":
        fig = px.line(frame, x=x, y=y, color=color, markers=True, title=title, color_discrete_sequence=PALETTE)
    elif visual_type == "pie":
        fig = px.pie(frame.head(8), names=x, values=y, title=title, color_discrete_sequence=PALETTE)
    elif visual_type == "scatter":
        fig = px.scatter(frame, x=x, y=y, color=color, title=title, color_discrete_sequence=PALETTE)
    elif visual_type == "stacked_bar":
        fig = px.bar(frame, x=x, y=y, color=color, title=title, barmode="stack", color_discrete_sequence=PALETTE)
    else:
        fig = px.bar(frame.head(20), x=x, y=y, color=color, title=title, color_discrete_sequence=PALETTE)
    return apply_theme(fig)
