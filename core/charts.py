from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from core import analytics as an
from core.db import CATEGORIES

COLORS = {
    "Home Essential": "#3B82F6",
    "SIP": "#10B981",
    "Stock Investment": "#8B5CF6",
    "Extra": "#F59E0B",
}
CUR, PREV = "#3B82F6", "#9CA3AF"


def _style(fig: go.Figure, height: int = 340, title: str = "") -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0, font=dict(size=15)),
        height=height,
        margin=dict(l=8, r=8, t=44, b=8),
        legend=dict(orientation="h", y=-0.18),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def donut(by_cat: pd.Series, title: str = "Share by category") -> go.Figure:
    s = by_cat[by_cat > 0]
    fig = go.Figure(
        go.Pie(
            labels=list(s.index),
            values=list(s.values),
            hole=0.6,
            marker=dict(colors=[COLORS[c] for c in s.index]),
            textinfo="percent",
            hovertemplate="%{label}<br>₹%{value:,.0f} (%{percent})<extra></extra>",
        )
    )
    return _style(fig, title=title)


def compare_bars(table: pd.DataFrame, cur_label="Current", prev_label="Previous") -> go.Figure:
    fig = go.Figure()
    fig.add_bar(x=table["Category"], y=table["Current"], name=cur_label, marker_color=CUR)
    if "Previous" in table:
        fig.add_bar(x=table["Category"], y=table["Previous"], name=prev_label, marker_color=PREV)
    fig.update_layout(barmode="group")
    fig.update_yaxes(tickprefix="₹", gridcolor="rgba(128,128,128,0.2)")
    return _style(fig, title="Category comparison")


def trend(df: pd.DataFrame, start, end) -> go.Figure:
    g, label = an.trend_frame(df, start, end)
    fig = go.Figure()
    for cat in CATEGORIES:
        d = g[g["group"] == cat]
        if not d.empty:
            fig.add_bar(x=d["date"], y=d["amount"], name=cat, marker_color=COLORS[cat])
    fig.update_layout(barmode="stack")
    fig.update_yaxes(tickprefix="₹", gridcolor="rgba(128,128,128,0.2)")
    return _style(fig, title=f"{label} outflow by category")


def cumulative(cur: pd.Series, prev: pd.Series | None, cur_label="Current", prev_label="Previous") -> go.Figure:
    fig = go.Figure()
    if prev is not None:
        fig.add_scatter(x=prev.index, y=prev.values, name=prev_label, line=dict(color=PREV, width=2, dash="dot"))
    fig.add_scatter(x=cur.index, y=cur.values, name=cur_label, line=dict(color=CUR, width=3))
    fig.update_xaxes(title="Day of period")
    fig.update_yaxes(tickprefix="₹", gridcolor="rgba(128,128,128,0.2)")
    return _style(fig, title="Cumulative outflow, day by day")


def subcategories(df: pd.DataFrame) -> go.Figure:
    """Spend per category name, bar colored by the group it belongs to."""
    s = df.groupby(["category", "group"])["amount"].sum().reset_index().sort_values("amount").tail(12)
    fig = go.Figure(
        go.Bar(
            x=s["amount"],
            y=list(s["category"]),
            orientation="h",
            marker_color=[COLORS.get(g, CUR) for g in s["group"]],
            customdata=s["group"],
            hovertemplate="%{y} (%{customdata})<br>₹%{x:,.0f}<extra></extra>",
        )
    )
    fig.update_xaxes(tickprefix="₹", gridcolor="rgba(128,128,128,0.2)")
    return _style(fig, title="By category")


def banks(df: pd.DataFrame) -> go.Figure:
    s = df.groupby("bank")["amount"].sum().sort_values().tail(10)
    s.index = [b or "(none)" for b in s.index]
    fig = go.Figure(go.Bar(x=s.values, y=list(s.index), orientation="h", marker_color=CUR))
    fig.update_xaxes(tickprefix="₹", gridcolor="rgba(128,128,128,0.2)")
    return _style(fig, title="By bank")
