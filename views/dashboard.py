from __future__ import annotations

import streamlit as st

from core import alerts as al
from core import analytics as an
from core import bot, charts, db
from core.config import inr, today

_LEVEL = {"error": (st.error, "🔻"), "warning": (st.warning, "⚠️"), "success": (st.success, "✅"), "info": (st.info, "💡")}


def _delta(d: float) -> str:
    return f"{'+' if d >= 0 else '-'}{inr(abs(d))} vs last month"


def _quick_add(t):
    with st.form("quick_add", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
        d = c1.date_input("Date", t)
        bank = c2.text_input("Bank")
        cat = c3.selectbox("Category", db.CATEGORIES)
        amt = c4.number_input("Amount (₹)", min_value=0.0, step=100.0, format="%.2f")
        det = st.text_input("Details")
        if st.form_submit_button("Add entry", type="primary"):
            try:
                db.add_expense(d, bank, cat, amt, det)
                st.toast("Entry added", icon="✅")
                st.rerun()
            except ValueError as e:
                st.error(str(e))


def render():
    st.title("🏠 Dashboard")
    t = today()
    df = db.get_expenses()
    m0 = t.replace(day=1)
    ps, pe = an.prev_range(m0, t, "Previous month")
    cur, prev = an.slice_df(df, m0, t), an.slice_df(df, ps, pe)
    ct, pt = an.totals(cur), an.totals(prev)

    with st.expander("➕ Quick add entry", expanded=df.empty):
        _quick_add(t)

    items = al.compute_alerts(df, db.get_budgets(), t)
    st.subheader("Alerts & advice")
    for a in items:
        fn, icon = _LEVEL[a.level]
        fn(f"**{a.title}**: {a.message}", icon=icon)

    if st.button("✨ Get AI advice", help="Uses one Gemini request"):
        lines = [f"Month to date ({m0:%d %b}-{t:%d %b}) vs same days last month:"]
        for cat in db.CATEGORIES:
            lines.append(f"- {cat}: {inr(ct['by_cat'][cat])} (last month {inr(pt['by_cat'][cat])})")
        lines += [f"Alerts: {a.title} - {a.message}" for a in items]
        with st.spinner("Thinking..."):
            st.session_state["ai_advice"] = bot.advise("\n".join(lines))
    if st.session_state.get("ai_advice"):
        st.info(st.session_state["ai_advice"], icon="🤖")

    st.subheader(f"{t:%B %Y} so far")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total outflow", inr(ct["total"]), _delta(ct["total"] - pt["total"]), delta_color="off")
    k2.metric("Spending (Home + Extra)", inr(ct["spending"]), _delta(ct["spending"] - pt["spending"]), delta_color="inverse")
    k3.metric("Invested (SIP + Stocks)", inr(ct["invested"]), _delta(ct["invested"] - pt["invested"]))
    k4.metric("Entries", ct["entries"], f"{ct['entries'] - pt['entries']:+d} vs last month", delta_color="off")

    if not cur.empty:
        c1, c2 = st.columns([1, 1.4])
        c1.plotly_chart(charts.donut(ct["by_cat"], "This month by category"), width="stretch")
        c2.plotly_chart(
            charts.cumulative(an.cumulative(df, m0, t), an.cumulative(df, ps, ps + (t - m0)), "This month", "Last month"),
            width="stretch",
        )

    st.subheader("Recent entries")
    recent = df.head(8).assign(date=lambda x: x["date"].dt.strftime("%d %b %Y"))
    st.dataframe(
        recent[["date", "bank", "category", "amount", "details"]],
        hide_index=True,
        width="stretch",
        column_config={"amount": st.column_config.NumberColumn("Amount", format="₹ %.2f")},
    )
