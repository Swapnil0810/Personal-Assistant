from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from core.db import CATEGORIES, INVESTMENTS, SPENDING

PRESETS = ["This month", "Last month", "Last 7 days", "Last 30 days", "Last 90 days", "This year", "All time", "Custom"]
COMPARE_MODES = ["Previous period", "Previous month", "Previous week", "Previous year", "Custom range", "None"]


def preset_range(name: str, t: dt.date) -> tuple[dt.date | None, dt.date | None]:
    m0 = t.replace(day=1)
    if name == "This month":
        return m0, t
    if name == "Last month":
        return m0 - pd.DateOffset(months=1), m0 - dt.timedelta(days=1)  # type: ignore[return-value]
    if name == "Last 7 days":
        return t - dt.timedelta(days=6), t
    if name == "Last 30 days":
        return t - dt.timedelta(days=29), t
    if name == "Last 90 days":
        return t - dt.timedelta(days=89), t
    if name == "This year":
        return t.replace(month=1, day=1), t
    return None, None


def _d(x) -> dt.date:
    return pd.Timestamp(x).date()


def preset_range_dates(name: str, t: dt.date):
    s, e = preset_range(name, t)
    return (_d(s) if s is not None else None, _d(e) if e is not None else None)


def prev_range(start: dt.date, end: dt.date, mode: str) -> tuple[dt.date, dt.date]:
    if mode == "Previous month":
        return _d(pd.Timestamp(start) - pd.DateOffset(months=1)), _d(pd.Timestamp(end) - pd.DateOffset(months=1))
    if mode == "Previous week":
        return start - dt.timedelta(days=7), end - dt.timedelta(days=7)
    if mode == "Previous year":
        return _d(pd.Timestamp(start) - pd.DateOffset(years=1)), _d(pd.Timestamp(end) - pd.DateOffset(years=1))
    days = (end - start).days + 1  # Previous period: same length, immediately before
    return start - dt.timedelta(days=days), start - dt.timedelta(days=1)


def slice_df(df: pd.DataFrame, start, end, cats=None) -> pd.DataFrame:
    m = (df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))
    if cats:
        m &= df["category"].isin(list(cats))
    return df[m]


def totals(df: pd.DataFrame) -> dict:
    by_cat = df.groupby("category")["amount"].sum().reindex(CATEGORIES).fillna(0.0)
    return {
        "by_cat": by_cat,
        "total": float(by_cat.sum()),
        "spending": float(by_cat[list(SPENDING)].sum()),
        "invested": float(by_cat[list(INVESTMENTS)].sum()),
        "entries": int(len(df)),
    }


def category_table(cur: pd.DataFrame, prev: pd.DataFrame | None) -> pd.DataFrame:
    c = totals(cur)["by_cat"]
    out = pd.DataFrame({"Category": CATEGORIES, "Current": c.values})
    if prev is not None:
        p = totals(prev)["by_cat"]
        out["Previous"] = p.values
        out["Change"] = out["Current"] - out["Previous"]
        out["Change %"] = np.where(out["Previous"] > 0, out["Change"] / out["Previous"].replace(0, np.nan) * 100, np.nan)
    return out


def trend_frame(df: pd.DataFrame, start, end) -> tuple[pd.DataFrame, str]:
    span = (end - start).days + 1
    if span <= 45:
        grouper, label = pd.Grouper(key="date", freq="D"), "Daily"
    elif span <= 180:
        grouper, label = pd.Grouper(key="date", freq="W-MON", label="left", closed="left"), "Weekly"
    else:
        grouper, label = pd.Grouper(key="date", freq="MS"), "Monthly"
    g = df.groupby([grouper, "category"])["amount"].sum().reset_index()
    return g, label


def cumulative(df: pd.DataFrame, start, end, cats=None) -> pd.Series:
    """Cumulative outflow by day index (1..N) so two periods can be overlaid."""
    days = pd.date_range(start, end, freq="D")
    d = df if cats is None else df[df["category"].isin(cats)]
    daily = d.groupby("date")["amount"].sum().reindex(days).fillna(0.0)
    s = daily.cumsum()
    s.index = range(1, len(days) + 1)
    return s
