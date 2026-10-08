from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from core import alerts as al
from core import analytics as an
from core import bot, charts, db
from core.config import inr, today

# colour, icon, short label
LEVELS = {
    "error": ("#EF4444", "🔻", "attention"),
    "warning": ("#F59E0B", "⚠️", "heads-up"),
    "success": ("#10B981", "✅", "good"),
    "info": ("#3B82F6", "💡", "insight"),
}


def _delta(d: float) -> str:
    return f"{'+' if d >= 0 else '-'}{inr(abs(d))} vs last month"


def _blank(x) -> bool:
    return x is None or pd.isna(x) or not str(x).strip()


# ---------------------------------------------------------------- notification bell
def _chip(color: str, text: str) -> str:
    return f'<span style="background:{color};color:#fff;border-radius:999px;padding:2px 10px;font-size:12px;font-weight:600;margin-right:6px">{html.escape(text)}</span>'


def _card(a: al.Alert) -> str:
    color, icon, _ = LEVELS[a.level]
    return (
        f'<div style="border-left:4px solid {color};background:{color}1F;border-radius:8px;padding:8px 12px;margin:6px 0">'
        f'<div style="font-weight:600">{icon} {html.escape(a.title)}</div>'
        f'<div style="font-size:0.88rem;opacity:0.85">{html.escape(a.message)}</div></div>'
    )


def _bell(items: list[al.Alert], advice_prompt: str) -> None:
    levels = [a.level for a in items]
    dot = "🔴" if "error" in levels else "🟠" if "warning" in levels else "🟢"
    with st.popover(f"🔔 {len(items)} {dot}", help="Alerts & advice"):
        counts = {lvl: levels.count(lvl) for lvl in LEVELS}
        st.markdown("".join(_chip(LEVELS[lvl][0], f"{c} {LEVELS[lvl][2]}") for lvl, c in counts.items() if c), unsafe_allow_html=True)
        st.markdown("".join(_card(a) for a in items), unsafe_allow_html=True)
        if st.button("✨ AI advice", help="Uses one Gemini request"):
            with st.spinner("Thinking..."):
                st.session_state["ai_advice"] = bot.advise(advice_prompt)
        if st.session_state.get("ai_advice"):
            st.markdown(
                f'<div style="border-left:4px solid #8B5CF6;background:#8B5CF61F;border-radius:8px;padding:8px 12px;margin:6px 0">'
                f'<div style="font-weight:600">🤖 AI advice</div></div>',
                unsafe_allow_html=True,
            )
            st.markdown(st.session_state["ai_advice"])


# ---------------------------------------------------------------- add entries
def _save(rows: list[dict]) -> None:
    if not rows:
        st.error("Add at least one entry.")
        return
    n, errors = db.add_many(rows)
    if errors:
        for e in errors[:10]:
            st.error(e)
        st.caption("Nothing was saved. Fix the rows above and press Save again.")
        return
    total = sum(float(r["amount"]) for r in rows)
    st.session_state["add_ver"] = st.session_state.get("add_ver", 0) + 1  # new widget keys = empty tables
    st.session_state["flash"] = f"Saved {n} entr{'y' if n == 1 else 'ies'}, total {inr(total)}"
    st.rerun()


def _add_panel(t) -> None:
    ver = st.session_state.setdefault("add_ver", 0)
    cats, bnks = db.category_names(), db.bank_names()
    amount_col = st.column_config.NumberColumn("Amount (₹)", min_value=0.01, format="%.2f")
    details_col = st.column_config.TextColumn("Details", width="large", max_chars=500)
    tab1, tab2 = st.tabs(["Same date, bank & category", "Different entries"])

    with tab1:
        st.caption("Choose the date, bank and category once, then list every amount with its details. Use the + row at the bottom of the table for more lines.")
        with st.form(f"add_same_{ver}", border=False):
            c1, c2, c3 = st.columns(3)
            d = c1.date_input("Date", t)
            bank = c2.selectbox("Bank", bnks, index=None, accept_new_options=True, placeholder="Select or type a bank")
            cat = c3.selectbox("Category", cats, index=None, placeholder="Select a category")
            base = pd.DataFrame({"amount": pd.Series([None] * 5, dtype="float64"), "details": pd.Series([""] * 5, dtype="object")})
            grid = st.data_editor(
                base,
                key=f"grid_same_{ver}",
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
                column_config={"amount": amount_col, "details": details_col},
            )
            go_same = st.form_submit_button("Save entries", type="primary")
        if go_same:
            if not cat:
                st.error("Choose a category.")
            else:
                rows = [
                    {"_row": i + 1, "date": d, "bank": bank or "", "category": cat, "amount": r.amount, "details": r.details}
                    for i, r in enumerate(grid.itertuples())
                    if not (pd.isna(r.amount) and _blank(r.details))
                ]
                _save(rows)

    with tab2:
        st.caption("Every row has its own date, bank, category, amount and details. Empty rows are ignored; a missing date means today.")
        with st.form(f"add_mixed_{ver}", border=False):
            base2 = pd.DataFrame(
                {
                    "date": [t] * 4,
                    "bank": pd.Series([None] * 4, dtype="object"),
                    "category": pd.Series([None] * 4, dtype="object"),
                    "amount": pd.Series([None] * 4, dtype="float64"),
                    "details": pd.Series([""] * 4, dtype="object"),
                }
            )
            grid2 = st.data_editor(
                base2,
                key=f"grid_mixed_{ver}",
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
                column_config={
                    "date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
                    "bank": st.column_config.SelectboxColumn("Bank", options=bnks),
                    "category": st.column_config.SelectboxColumn("Category", options=cats),
                    "amount": amount_col,
                    "details": details_col,
                },
            )
            go_mixed = st.form_submit_button("Save entries", type="primary")
        if go_mixed:
            rows = [
                {
                    "_row": i + 1,
                    "date": t if _blank(r.date) else r.date,
                    "bank": "" if _blank(r.bank) else r.bank,
                    "category": r.category,
                    "amount": r.amount,
                    "details": r.details,
                }
                for i, r in enumerate(grid2.itertuples())
                if not (pd.isna(r.amount) and _blank(r.details) and _blank(r.bank) and _blank(r.category))
            ]
            _save(rows)
    st.caption("Need a new bank or category? Type a new bank in the first tab, or manage both lists under Settings.")


# ---------------------------------------------------------------- page
def render():
    if st.session_state.get("flash"):
        st.toast(st.session_state.pop("flash"), icon="✅")

    t = today()
    df = db.get_expenses()
    m0 = t.replace(day=1)
    ps, pe = an.prev_range(m0, t, "Previous month")
    cur, prev = an.slice_df(df, m0, t), an.slice_df(df, ps, pe)
    ct, pt = an.totals(cur), an.totals(prev)
    items = al.compute_alerts(df, db.get_budgets(), t)

    lines = [f"Month to date ({m0:%d %b}-{t:%d %b}) vs same days last month:"]
    lines += [f"- {c}: {inr(ct['by_cat'][c])} (last month {inr(pt['by_cat'][c])})" for c in db.CATEGORIES]
    lines += [f"Alerts: {a.title} - {a.message}" for a in items]

    head, bell = st.columns([6, 1.4], vertical_alignment="center")
    head.title("🏠 Dashboard")
    with bell:
        _bell(items, "\n".join(lines))

    with st.expander("➕ Add entries", expanded=df.empty):
        _add_panel(t)

    st.subheader(f"{t:%B %Y} so far")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total outflow", inr(ct["total"]), _delta(ct["total"] - pt["total"]), delta_color="off")
    k2.metric("Spending (Home + Extra)", inr(ct["spending"]), _delta(ct["spending"] - pt["spending"]), delta_color="inverse")
    k3.metric("Invested (SIP + Stocks)", inr(ct["invested"]), _delta(ct["invested"] - pt["invested"]))
    k4.metric("Entries", ct["entries"], f"{ct['entries'] - pt['entries']:+d} vs last month", delta_color="off")

    if not cur.empty:
        c1, c2 = st.columns([1, 1.4])
        c1.plotly_chart(charts.donut(ct["by_cat"], "This month by group"), width="stretch")
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
