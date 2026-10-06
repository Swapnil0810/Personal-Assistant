from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd

from core import analytics as an
from core.config import inr
from core.db import CATEGORIES, INVESTMENTS, SPENDING

_ORDER = {"error": 0, "warning": 1, "success": 2, "info": 3}


@dataclass
class Alert:
    level: str  # error | warning | success | info
    title: str
    message: str


def compute_alerts(df: pd.DataFrame, budgets: dict[str, float], t: dt.date) -> list[Alert]:
    """Rule-based alerts. Month-to-date is compared with the same days of last month."""
    if df.empty:
        return [Alert("info", "Welcome", "No entries yet. Add your first transaction from the Dashboard or ask the bot.")]

    out: list[Alert] = []
    gap = (t - df["date"].max().date()).days
    if gap >= 2:
        out.append(
            Alert("warning", "No new entries", f"Nothing logged for {gap} days (last entry {df['date'].max():%d %b}). Keep the ledger current.")
        )

    m0 = t.replace(day=1)
    ps, pe = an.prev_range(m0, t, "Previous month")
    cur_df, prev_df = an.slice_df(df, m0, t), an.slice_df(df, ps, pe)
    cur, prev = an.totals(cur_df)["by_cat"], an.totals(prev_df)["by_cat"]
    cmp_txt = "vs same days last month"

    for cat in CATEGORIES:
        c, p = float(cur[cat]), float(prev[cat])
        if p <= 0:
            if c > 0 and cat in INVESTMENTS:
                out.append(Alert("success", f"{cat} started", f"{inr(c)} invested this month, nothing in the same period last month. Keep it going."))
            continue
        pct = (c - p) / p * 100
        line = f"{inr(c)} {cmp_txt} ({inr(p)}, {pct:+.0f}%)."
        if cat in SPENDING:
            if pct > 5:
                out.append(Alert("error", f"{cat} spending is up", f"{line} Try to cut back."))
            elif pct < -5:
                out.append(Alert("success", f"{cat} spending is down", f"{line} Nice, keep it up."))
        else:
            if pct < -5:
                out.append(Alert("warning", f"Lower {cat} investment", f"{line} Try to maintain or increase it."))
            else:
                out.append(Alert("success", f"{cat} on track", f"{line} Great consistency."))

    # budgets (spending) and targets (investments), month to date
    for cat, limit in budgets.items():
        if cat not in CATEGORIES or limit <= 0:
            continue
        used = float(cur[cat])
        if cat in SPENDING:
            if used >= limit:
                out.append(Alert("error", f"{cat} budget exceeded", f"{inr(used)} spent of {inr(limit)} budget."))
            elif used >= 0.8 * limit:
                out.append(Alert("warning", f"{cat} budget at {used / limit:.0%}", f"{inr(used)} of {inr(limit)} used, {inr(limit - used)} left."))
        else:
            if used >= limit:
                out.append(Alert("success", f"{cat} target met", f"{inr(used)} invested, target {inr(limit)}."))
            elif t.day >= 25:
                out.append(Alert("warning", f"{cat} target not reached", f"{inr(used)} of {inr(limit)} target, month is nearly over."))

    extras = cur_df[cur_df["category"] == "Extra"]
    if not extras.empty:
        top = extras.loc[extras["amount"].idxmax()]
        out.append(Alert("info", "Biggest 'Extra' expense this month", f"{inr(top['amount'])} on {top['date']:%d %b}: {top['details'] or 'no details'}."))

    return sorted(out, key=lambda a: _ORDER[a.level])
