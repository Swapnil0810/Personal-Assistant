from __future__ import annotations

import datetime as dt
import os
import re
from functools import lru_cache

import pandas as pd
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    func,
    insert,
    select,
    update,
)

from core.config import get_secret
from core.logger import get_logger

log = get_logger("db")

CATEGORIES = ["Home Essential", "SIP", "Stock Investment", "Extra"]
SPENDING = ("Home Essential", "Extra")
INVESTMENTS = ("SIP", "Stock Investment")
COLS = ["id", "date", "bank", "category", "amount", "details"]

meta = MetaData()
expenses = Table(
    "expenses",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("date", Date, nullable=False, index=True),
    Column("bank", String(80), nullable=False, default=""),
    Column("category", String(32), nullable=False),
    Column("amount", Float, nullable=False),
    Column("details", String(500), nullable=False, default=""),
    Column("created_at", DateTime, server_default=func.now()),
)
budgets = Table(
    "budgets",
    meta,
    Column("category", String(32), primary_key=True),
    Column("monthly_limit", Float, nullable=False),
)


@lru_cache(maxsize=1)
def engine():
    url = get_secret("DATABASE_URL", "sqlite:///data/finance.db")
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    if url.startswith("sqlite:///"):
        folder = os.path.dirname(url[len("sqlite:///"):])
        if folder:
            os.makedirs(folder, exist_ok=True)
    args = {"connect_timeout": 10} if url.startswith("postgresql") else {}
    try:
        eng = create_engine(url, pool_pre_ping=True, future=True, connect_args=args)
        meta.create_all(eng)
    except Exception:
        log.exception("Database init failed (backend=%s)", url.split(":", 1)[0])  # never log the URL: it holds the password
        raise
    log.info("Database ready (backend=%s)", eng.dialect.name)
    return eng


def backend_name() -> str:
    return engine().dialect.name


# ---------- validation helpers ----------
def normalize_category(value) -> str:
    v = re.sub(r"[_\-]+", " ", str(value or "")).strip().lower()
    for c in CATEGORIES:
        if v == c.lower():
            return c
    words = set(v.split())
    if "sip" in words or "mutual" in v:
        return "SIP"
    if any(k in v for k in ("stock", "equity", "share", "demat", "etf")):
        return "Stock Investment"
    if any(k in v for k in ("home", "essential", "household")):
        return "Home Essential"
    if any(k in v for k in ("extra", "other", "misc", "luxury")):
        return "Extra"
    raise ValueError(f"Unknown category '{value}'. Use one of: {', '.join(CATEGORIES)}")


def parse_date(value) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    s = str(value or "").strip()
    if not s:
        raise ValueError("Date is required")
    iso = bool(re.match(r"^\d{4}-\d{1,2}-\d{1,2}", s))
    ts = pd.to_datetime(s, dayfirst=not iso, errors="coerce")
    if pd.isna(ts):
        raise ValueError(f"Invalid date '{value}'")
    return ts.date()


def _clean(date, bank, category, amount, details) -> dict:
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid amount '{amount}'")
    if not amt > 0:
        raise ValueError("Amount must be greater than 0")
    return {
        "date": parse_date(date),
        "bank": ("" if pd.isna(bank) else str(bank)).strip()[:80],
        "category": normalize_category(category),
        "amount": round(amt, 2),
        "details": ("" if pd.isna(details) else str(details)).strip()[:500],
    }


# ---------- CRUD ----------
def add_expense(date, bank, category, amount, details) -> int:
    vals = _clean(date, bank, category, amount, details)
    with engine().begin() as c:
        return int(c.execute(insert(expenses).values(**vals)).inserted_primary_key[0])


def update_expense(expense_id: int, **fields) -> None:
    vals = {}
    if fields.get("date") not in (None, ""):
        vals["date"] = parse_date(fields["date"])
    if fields.get("bank") not in (None, ""):
        vals["bank"] = str(fields["bank"]).strip()[:80]
    if fields.get("category") not in (None, ""):
        vals["category"] = normalize_category(fields["category"])
    if fields.get("amount") not in (None, "", 0, 0.0):
        amt = float(fields["amount"])
        if not amt > 0:
            raise ValueError("Amount must be greater than 0")
        vals["amount"] = round(amt, 2)
    if fields.get("details") not in (None, ""):
        vals["details"] = str(fields["details"]).strip()[:500]
    if not vals:
        raise ValueError("Nothing to update")
    with engine().begin() as c:
        if c.execute(update(expenses).where(expenses.c.id == int(expense_id)).values(**vals)).rowcount == 0:
            raise ValueError(f"No entry with id {expense_id}")


def delete_expense(expense_id: int) -> None:
    with engine().begin() as c:
        if c.execute(delete(expenses).where(expenses.c.id == int(expense_id))).rowcount == 0:
            raise ValueError(f"No entry with id {expense_id}")


def get_expenses(start=None, end=None, categories=None, bank=None, text=None) -> pd.DataFrame:
    q = select(*[expenses.c[c] for c in COLS])
    if start:
        q = q.where(expenses.c.date >= start)
    if end:
        q = q.where(expenses.c.date <= end)
    if categories:
        q = q.where(expenses.c.category.in_(list(categories)))
    if bank:
        q = q.where(expenses.c.bank.ilike(f"%{bank}%"))
    for word in str(text or "").split():  # every word must appear in details
        q = q.where(expenses.c.details.ilike(f"%{word}%"))
    q = q.order_by(expenses.c.date.desc(), expenses.c.id.desc())
    with engine().connect() as c:
        rows = c.execute(q).all()
    df = pd.DataFrame(rows, columns=COLS)
    df["date"] = pd.to_datetime(df["date"])
    df["amount"] = df["amount"].astype(float)
    df["id"] = df["id"].astype(int)
    return df


def last_entry_date() -> dt.date | None:
    with engine().connect() as c:
        return c.execute(select(func.max(expenses.c.date))).scalar()


def apply_changes(orig: pd.DataFrame, edited: pd.DataFrame) -> tuple[dict, list[str]]:
    """Persist grid edits: new rows (no id), changed rows, and removed rows."""
    stats = {"added": 0, "updated": 0, "deleted": 0}
    errors: list[str] = []
    orig_by_id = {int(r["id"]): r for _, r in orig.iterrows()}
    kept: set[int] = set()
    with engine().begin() as c:
        for i, r in edited.iterrows():
            has_id = pd.notna(r.get("id"))
            if has_id:
                kept.add(int(r["id"]))
            elif r[["date", "amount"]].isna().all() and not str(r.get("details") or "").strip():
                continue  # blank row
            try:
                vals = _clean(r["date"], r["bank"], r["category"], r["amount"], r["details"])
            except ValueError as e:
                errors.append(f"Row {i + 1}: {e}")
                continue
            if has_id:
                o = orig_by_id[int(r["id"])]
                changed = (
                    vals["date"] != pd.Timestamp(o["date"]).date()
                    or vals["bank"] != o["bank"]
                    or vals["category"] != o["category"]
                    or abs(vals["amount"] - float(o["amount"])) > 0.005
                    or vals["details"] != o["details"]
                )
                if changed:
                    c.execute(update(expenses).where(expenses.c.id == int(r["id"])).values(**vals))
                    stats["updated"] += 1
            else:
                c.execute(insert(expenses).values(**vals))
                stats["added"] += 1
        for rid in set(orig_by_id) - kept:
            c.execute(delete(expenses).where(expenses.c.id == rid))
            stats["deleted"] += 1
    return stats, errors


def bulk_insert(df: pd.DataFrame) -> tuple[int, list[str]]:
    """Import rows from a DataFrame with Date/Bank/Category/Amount/Details columns."""
    df = df.rename(columns={c: str(c).strip().lower() for c in df.columns})
    missing = {"date", "category", "amount"} - set(df.columns)
    if missing:
        return 0, [f"Missing columns: {', '.join(sorted(missing))}"]
    rows, errors = [], []
    for i, r in df.iterrows():
        try:
            rows.append(_clean(r["date"], r.get("bank", ""), r["category"], r["amount"], r.get("details", "")))
        except ValueError as e:
            errors.append(f"Row {i + 2}: {e}")
    if rows:
        with engine().begin() as c:
            c.execute(insert(expenses), rows)
    return len(rows), errors


# ---------- budgets / targets ----------
def get_budgets() -> dict[str, float]:
    with engine().connect() as c:
        return {k: float(v) for k, v in c.execute(select(budgets.c.category, budgets.c.monthly_limit)).all()}


def set_budget(category: str, limit: float) -> None:
    with engine().begin() as c:
        c.execute(delete(budgets).where(budgets.c.category == category))
        if limit and limit > 0:
            c.execute(insert(budgets).values(category=category, monthly_limit=float(limit)))
