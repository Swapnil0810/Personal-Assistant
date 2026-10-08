from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from core import db
from core import logger as applog
from core.config import get_secret
from core.export import to_excel
from core.logger import get_logger

log = get_logger("settings")


def _save_lists(fn, orig: pd.DataFrame, edited: pd.DataFrame, label: str) -> None:
    try:
        stats, errors = fn(orig, edited)
    except Exception as e:  # e.g. a unique-name clash reported by the database
        log.exception("%s not saved", label)
        st.error(f"{label} not saved: {type(e).__name__}: {e}")
        return
    if errors:
        for e in errors:
            st.error(e)
        return
    st.session_state["lists_msgs"] = [("success", f"{label} saved: {stats['added']} added, {stats['updated']} changed, {stats['removed']} removed")]
    st.session_state["lists_ver"] = st.session_state.get("lists_ver", 0) + 1
    st.rerun()


def render():
    st.title("⚙️ Settings")

    with st.expander("🪵 Logs: errors, Gemini calls, tool calls"):
        st.caption(f"File: {os.path.abspath(applog.log_path())} (rotates at 1 MB, keeps 3 old files). Newest lines are at the bottom.")
        st.code(applog.tail(150) or "(log is empty)", language=None)
        st.download_button("⬇️ Download log", applog.tail(5000) or "(log is empty)", "app.log", mime="text/plain")

    for kind, msg in st.session_state.pop("lists_msgs", []):
        getattr(st, kind)(msg)

    st.subheader("Dropdown lists: banks & categories")
    st.caption(
        "These feed every Bank and Category dropdown. Add rows at the bottom, edit cells, or select a row and press Delete, then Save. "
        "Each category you add belongs to one of the four groups, which drive analytics, budgets and alerts. "
        "The four core categories cannot be renamed or removed. Renaming updates existing entries; a category that entries use cannot be removed."
    )
    ver = st.session_state.setdefault("lists_ver", 0)
    bdf, cdf = db.list_banks(), db.list_categories()
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Banks**")
        b_ed = st.data_editor(
            bdf,
            key=f"banks_{ver}",
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            column_config={"id": None, "name": st.column_config.TextColumn("Bank", required=True, max_chars=80)},
        )
        if st.button("Save banks"):
            _save_lists(db.save_banks, bdf, b_ed, "Banks")
    with c2:
        st.markdown("**Categories**")
        c_ed = st.data_editor(
            cdf,
            key=f"cats_{ver}",
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            column_config={
                "id": None,
                "name": st.column_config.TextColumn("Category", required=True, max_chars=32),
                "grp": st.column_config.SelectboxColumn("Group", options=db.CATEGORIES, required=True),
            },
        )
        if st.button("Save categories"):
            _save_lists(db.save_categories, cdf, c_ed, "Categories")

    st.subheader("Monthly budgets & investment targets")
    st.caption("Spending categories alert at 80% and 100% of the budget. Investment categories alert when the target is missed late in the month. Set 0 to disable.")
    cur = db.get_budgets()
    with st.form("budgets"):
        cols = st.columns(4)
        vals = {c: col.number_input(c, min_value=0.0, step=500.0, value=float(cur.get(c, 0.0)), format="%.0f") for c, col in zip(db.CATEGORIES, cols)}
        if st.form_submit_button("Save", type="primary"):
            for c, v in vals.items():
                db.set_budget(c, v)
            st.toast("Budgets saved", icon="✅")
            st.rerun()

    st.subheader("Import from Excel / CSV")
    st.caption("Columns: Date, Bank, Category, Amount, Details. Dates like 2026-10-05 or 05/10/2026 (day first).")
    up = st.file_uploader("File", type=["xlsx", "csv"])
    if up is not None:
        raw = pd.read_csv(up) if up.name.lower().endswith(".csv") else pd.read_excel(up)
        st.dataframe(raw.head(10), hide_index=True, width="stretch")
        if st.button(f"Import {len(raw)} rows"):
            n, errors = db.bulk_insert(raw)
            st.success(f"Imported {n} rows")
            for e in errors[:20]:
                st.error(e)

    st.subheader("Backup")
    st.download_button("⬇️ Download all data (Excel)", to_excel(db.get_expenses()), "finance_backup.xlsx")

    st.subheader("System")
    try:
        backend = db.backend_name()
        n = len(db.get_expenses())
        st.success(f"Database connected ({backend}), {n} entries")
    except Exception as e:
        st.error(f"Database connection failed: {type(e).__name__}: {e}")
        st.caption("Check DATABASE_URL in your secrets (use the pooled Neon/Supabase string; keep ?sslmode=require).")
        return
    st.write(f"Storage: **{backend}**")
    if backend == "sqlite":
        st.warning("SQLite is a local file. On free hosts (Streamlit Cloud, HF Spaces) the disk resets on restart. Set DATABASE_URL to a free Postgres (Neon / Supabase) for persistence.")
    st.write(f"Gemini key configured: **{'yes' if get_secret('GEMINI_API_KEY') else 'no'}**")
