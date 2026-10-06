from __future__ import annotations

import datetime as dt

import streamlit as st

from core import analytics as an
from core import charts, db
from core.config import inr, today

PRESETS = [p for p in an.PRESETS if p != "All time"]


def _range_input(label: str, default: tuple, key: str):
    r = st.date_input(label, value=default, key=key)
    if not isinstance(r, tuple) or len(r) != 2:
        st.info(f"Pick an end date for '{label}'.")
        st.stop()
    return r


def _kpi(col, label, cur, prev, inverse=False, off=False):
    delta = None
    if prev is not None:
        d = cur - prev
        delta = f"{'+' if d >= 0 else '-'}{inr(abs(d))}"
    col.metric(label, inr(cur), delta, delta_color="off" if off else ("inverse" if inverse else "normal"))


def render():
    st.title("📊 Expense Analytics")
    df = db.get_expenses()
    if df.empty:
        st.info("No data yet. Add entries from the Dashboard, the Ledger or the Bot.")
        return
    t = today()

    c1, c2, c3 = st.columns([1.2, 1.6, 1.2])
    with c1:
        preset = st.selectbox("Period", PRESETS)
        if preset == "Custom":
            start, end = _range_input("Date range", (t.replace(day=1), t), "an_range")
        else:
            start, end = an.preset_range_dates(preset, t)
            st.caption(f"{start:%d %b %Y} to {end:%d %b %Y}")
    with c2:
        cats = st.multiselect("Categories", db.CATEGORIES, default=db.CATEGORIES)
    with c3:
        mode = st.selectbox("Compare with", an.COMPARE_MODES)
    if not cats:
        st.warning("Select at least one category.")
        return

    prev_df, pstart, pend = None, None, None
    if mode == "Custom range":
        ds, de = an.prev_range(start, end, "Previous period")
        pstart, pend = _range_input("Comparison range", (ds, de), "an_prange")
    elif mode != "None":
        pstart, pend = an.prev_range(start, end, mode)
    if pstart:
        prev_df = an.slice_df(df, pstart, pend, cats)
        st.caption(f"Comparing with {pstart:%d %b %Y} to {pend:%d %b %Y}")

    cur = an.slice_df(df, start, end, cats)
    ct = an.totals(cur)
    pt = an.totals(prev_df) if prev_df is not None else None
    days = (end - start).days + 1

    k = st.columns(4)
    _kpi(k[0], "Total outflow", ct["total"], pt and pt["total"], off=True)
    _kpi(k[1], "Spending (Home + Extra)", ct["spending"], pt and pt["spending"], inverse=True)
    _kpi(k[2], "Invested (SIP + Stocks)", ct["invested"], pt and pt["invested"])
    _kpi(k[3], "Avg per day", ct["total"] / days, pt and pt["total"] / ((pend - pstart).days + 1), off=True)

    if cur.empty:
        st.info("No entries in this period for the selected categories.")
        return

    tab1, tab2, tab3 = st.tabs(["Overview", "Trends", "Details"])
    table = an.category_table(cur, prev_df)

    with tab1:
        a, b = st.columns(2)
        a.plotly_chart(charts.donut(ct["by_cat"]), width="stretch")
        b.plotly_chart(charts.compare_bars(table, "Selected period", "Comparison"), width="stretch")
        cfg = {c: st.column_config.NumberColumn(format="₹ %.0f") for c in ("Current", "Previous", "Change")}
        cfg["Change %"] = st.column_config.NumberColumn(format="%.1f%%")
        st.dataframe(table, hide_index=True, width="stretch", column_config=cfg)

    with tab2:
        st.plotly_chart(charts.trend(cur, start, end), width="stretch")
        cum_prev = an.cumulative(prev_df, pstart, pend, cats) if prev_df is not None else None
        st.plotly_chart(
            charts.cumulative(an.cumulative(cur, start, end, cats), cum_prev, "Selected period", "Comparison"),
            width="stretch",
        )

    with tab3:
        a, b = st.columns([1, 1.3])
        a.plotly_chart(charts.banks(cur), width="stretch")
        top = cur.nlargest(10, "amount").assign(date=lambda x: x["date"].dt.strftime("%d %b %Y"))
        b.markdown("**Top 10 entries**")
        b.dataframe(
            top[["date", "bank", "category", "amount", "details"]],
            hide_index=True,
            width="stretch",
            column_config={"amount": st.column_config.NumberColumn("Amount", format="₹ %.2f")},
        )
