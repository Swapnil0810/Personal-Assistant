from __future__ import annotations

import datetime as dt
import os
import re
from zoneinfo import ZoneInfo


def get_secret(name: str, default: str = "") -> str:
    """Read from Streamlit secrets first, then environment variables."""
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.environ.get(name, default)


def today() -> dt.date:
    return dt.datetime.now(ZoneInfo(get_secret("APP_TIMEZONE", "Asia/Kolkata"))).date()


def inr(x: float) -> str:
    """Format as rupees with Indian digit grouping, e.g. ₹1,23,456."""
    n = int(round(float(x)))
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = f"{head},{tail}"
    return f"{'-' if n < 0 else ''}₹{s}"
