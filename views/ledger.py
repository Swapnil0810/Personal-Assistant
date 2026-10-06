from __future__ import annotations

import streamlit as st

from core import analytics as an
from core import db
from core.config import inr, today
from core.export import to_excel
from core.logger import get_logger

log = get_logger("ledger")

GRID_COLS = ["id", "date", "bank", "category", "amount", "details"]


def render():
    st.title("📒 Ledger")
    for kind, msg in st.session_state.pop("ledger_msgs", []):
        getattr(st, kind)(msg)

    all_df = db.get_expenses()
    t = today()

    f1, f2, f3, f4 = st.columns([1.1, 1.4, 1.2, 1.4])
    with f1:
        preset = st.selectbox("Period", an.PRESETS, key="lg_preset")
        if preset == "Custom":
            r = st.date_input("Range", (t.replace(day=1), t), key="lg_range")
            start, end = (r if isinstance(r, tuple) and len(r) == 2 else (None, None))
        else:
            start, end = an.preset_range_dates(preset, t)
    cats = f2.multiselect("Category", db.CATEGORIES, key="lg_cats")
    banks = f3.multiselect("Bank", sorted(b for b in all_df["bank"].unique() if b), key="lg_banks")
    text = f4.text_input("Search details", key="lg_text")

    view = db.get_expenses(start, end, cats or None, None, text or None)
    if banks:
        view = view[view["bank"].isin(banks)]
    view = view.reset_index(drop=True)

    ver = st.session_state.setdefault("grid_ver", 0)
    key = f"grid_{ver}"
    show = view[GRID_COLS].copy()
    show["date"] = show["date"].dt.date

    st.caption(f"{len(view)} rows · total {inr(view['amount'].sum())} · edit cells, add rows at the bottom, select rows and press Delete, then Save.")
    edited = st.data_editor(
        show,
        key=key,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        height=520,
        disabled=["id"],
        column_config={
            "id": st.column_config.NumberColumn("ID", width="small"),
            "date": st.column_config.DateColumn("Date", format="DD MMM YYYY", required=True),
            "bank": st.column_config.TextColumn("Bank name"),
            "category": st.column_config.SelectboxColumn("Category", options=db.CATEGORIES, required=True),
            "amount": st.column_config.NumberColumn("Amount (₹)", format="%.2f", min_value=0.01, required=True),
            "details": st.column_config.TextColumn("Details", width="large"),
        },
    )

    state = st.session_state.get(key) or {}
    dirty = any(state.get(k) for k in ("edited_rows", "added_rows", "deleted_rows"))

    b1, b2, b3 = st.columns([1, 1, 3])
    if b1.button("💾 Save changes", type="primary", disabled=not dirty):
        stats, errors = db.apply_changes(view, edited)
        msgs = [("success", f"Saved: {stats['added']} added, {stats['updated']} updated, {stats['deleted']} deleted")]
        msgs += [("error", e) for e in errors]
        log.info("grid save: %s, %d row errors", stats, len(errors))
        for e in errors:
            log.warning("grid save rejected: %s", e)
        st.session_state["ledger_msgs"] = msgs
        st.session_state["grid_ver"] = ver + 1
        st.rerun()
    b2.download_button(
        "⬇️ Export Excel",
        data=to_excel(view),
        file_name=f"expenses_{t:%Y%m%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Exports the rows currently shown (respects filters)",
    )
    if dirty:
        b3.caption("⚠️ Unsaved changes")
