import hmac
from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).parent / "assets"

st.set_page_config(page_title="vriddhi-ai", page_icon=str(ASSETS / "vriddhi-icon.png"), layout="wide")

from core.config import get_secret  # noqa: E402
from core.logger import get_logger  # noqa: E402
from views import analytics, bot_chat, dashboard, ledger, settings  # noqa: E402

log = get_logger("app")

st.logo(str(ASSETS / "vriddhi-logo.svg"), icon_image=str(ASSETS / "vriddhi-icon.svg"), size="large")


def gate() -> None:
    pw = get_secret("APP_PASSWORD")
    if not pw:
        st.sidebar.warning("APP_PASSWORD is not set: anyone with the URL can open this app.")
        return
    if st.session_state.get("auth"):
        return
    left, mid, right = st.columns([1, 1.2, 1])
    with mid:
        st.image(str(ASSETS / "vriddhi-logo.svg"), width=260)
        st.caption("Your money, growing.")
        with st.form("login"):
            p = st.text_input("Password", type="password")
            if st.form_submit_button("Unlock", type="primary", width="stretch"):
                if hmac.compare_digest(p.encode(), pw.encode()):
                    st.session_state["auth"] = True
                    st.rerun()
                st.error("Wrong password")
    st.stop()


gate()

pages = [
    st.Page(dashboard.render, title="Dashboard", icon="🏠", url_path="dashboard", default=True),
    st.Page(bot_chat.render, title="Bot", icon="🤖", url_path="bot"),
    st.Page(analytics.render, title="Analytics", icon="📊", url_path="analytics"),
    st.Page(ledger.render, title="Ledger", icon="📒", url_path="ledger"),
    st.Page(settings.render, title="Settings", icon="⚙️", url_path="settings"),
]
try:
    st.navigation(pages).run()
except Exception:  # st.rerun()/st.stop() are BaseException subclasses, so they pass through untouched
    log.exception("Unhandled error while rendering a page")
    raise
