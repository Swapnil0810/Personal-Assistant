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

# The four GROUPS. They drive analytics, alerts and budgets and can never be removed.
# Users can add their own categories (e.g. "Rent", "Groceries"); each one belongs to one of these groups.
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
banks = Table(
    "banks",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(80), nullable=False, unique=True),
)
categories = Table(
    "categories",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(32), nullable=False, unique=True),
    Column("grp", String(32), nullable=False),
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
        meta.create_all(eng)  # creates any missing tables; existing data is untouched
        _seed(eng)
    except Exception:
        log.exception("Database init failed (backend=%s)", url.split(":", 1)[0])  # never log the URL: it holds the password
        raise
    log.info("Database ready (backend=%s)", eng.dialect.name)
    return eng


def _seed(eng) -> None:
    """First run after the upgrade: create the four core categories and import banks already used in entries."""
    with eng.begin() as c:
        if not c.execute(select(func.count()).select_from(categories)).scalar():
            c.execute(insert(categories), [{"name": n, "grp": n} for n in CATEGORIES])
        if not c.execute(select(func.count()).select_from(banks)).scalar():
            seen, rows = set(), []
            for (b,) in c.execute(select(expenses.c.bank).distinct()).all():
                b = (b or "").strip()
                if b and b.lower() not in seen:
                    seen.add(b.lower())
                    rows.append({"name": b})
            if rows:
                c.execute(insert(banks), sorted(rows, key=lambda r: r["name"].lower()))


def backend_name() -> str:
    return engine().dialect.name


# ---------- dropdown lookups ----------
def _lookups(conn=None) -> tuple[dict[str, str], list[str]]:
    def run(c):
        cats = {n: g for n, g in c.execute(select(categories.c.name, categories.c.grp).order_by(categories.c.id)).all()}
        bnk = [n for (n,) in c.execute(select(banks.c.name).order_by(func.lower(banks.c.name))).all()]
        return cats, bnk

    if conn is not None:
        return run(conn)
    with engine().connect() as c:
        return run(c)


def group_map() -> dict[str, str]:
    """{category name: group}"""
    return _lookups()[0]


def category_names() -> list[str]:
    return list(_lookups()[0])


def bank_names(extra=()) -> list[str]:
    """Banks for dropdowns. `extra` adds values already present in data so existing rows still render."""
    names = _lookups()[1]
    low = {n.lower() for n in names}
    for b in extra:
        b = _s(b).strip()
        if b and b.lower() not in low:
            names.append(b)
            low.add(b.lower())
    return names


def list_categories() -> pd.DataFrame:
    with engine().connect() as c:
        rows = c.execute(select(categories.c.id, categories.c.name, categories.c.grp).order_by(categories.c.id)).all()
    return pd.DataFrame(rows, columns=["id", "name", "grp"])


def list_banks() -> pd.DataFrame:
    with engine().connect() as c:
        rows = c.execute(select(banks.c.id, banks.c.name).order_by(func.lower(banks.c.name))).all()
    return pd.DataFrame(rows, columns=["id", "name"])


# ---------- validation helpers ----------
def _s(x) -> str:
    """None / NaN -> '' ; everything else -> str."""
    if x is None or (not isinstance(x, str) and pd.isna(x)):
        return ""
    return str(x)


def _norm(text: str) -> str:
    return re.sub(r"[_\-]+", " ", text).strip().lower()


def normalize_category(value, cat_map: dict[str, str] | None = None) -> str:
    """Map user/bot input to a known category name (custom ones included); common synonyms map to the core groups."""
    cat_map = cat_map if cat_map is not None else group_map()
    raw = _s(value)
    v = _norm(raw)
    if not v:
        raise ValueError("Category is required")
    for name in cat_map:
        if v == _norm(name):
            return name
    words = set(v.split())
    if "sip" in words or "mutual" in v:
        return "SIP"
    if any(k in v for k in ("stock", "equity", "share", "demat", "etf")):
        return "Stock Investment"
    if any(k in v for k in ("home", "essential", "household")):
        return "Home Essential"
    if any(k in v for k in ("extra", "other", "misc", "luxury")):
        return "Extra"
    raise ValueError(f"Unknown category '{raw}'. Use one of: {', '.join(cat_map)}")


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


def _clean(date, bank, category, amount, details, cat_map=None, bank_list=None) -> dict:
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid amount '{amount}'")
    if not amt > 0:
        raise ValueError("Amount must be greater than 0")
    b = _s(bank).strip()[:80]
    if bank_list:  # keep the casing of the saved bank ("hdfc" -> "HDFC")
        b = {x.lower(): x for x in bank_list}.get(b.lower(), b)
    return {
        "date": parse_date(date),
        "bank": b,
        "category": normalize_category(category, cat_map),
        "amount": round(amt, 2),
        "details": _s(details).strip()[:500],
    }


def _remember_banks(c, names) -> None:
    """Add bank names typed in entries (form, bot, import) to the dropdown list."""
    have = {n.lower() for (n,) in c.execute(select(banks.c.name)).all()}
    new = []
    for n in names:
        if n and n.lower() not in have:
            have.add(n.lower())
            new.append({"name": n})
    if new:
        c.execute(insert(banks), new)


# ---------- CRUD ----------
def add_expense(date, bank, category, amount, details) -> int:
    cats, bnk = _lookups()
    vals = _clean(date, bank, category, amount, details, cats, bnk)
    with engine().begin() as c:
        _remember_banks(c, [vals["bank"]])
        return int(c.execute(insert(expenses).values(**vals)).inserted_primary_key[0])


def add_many(rows: list[dict]) -> tuple[int, list[str]]:
    """All-or-nothing batch insert. Row dicts: date, bank, category, amount, details (+ optional _row label)."""
    cats, bnk = _lookups()
    clean, errors = [], []
    for i, r in enumerate(rows, 1):
        try:
            clean.append(_clean(r.get("date"), r.get("bank"), r.get("category"), r.get("amount"), r.get("details"), cats, bnk))
        except ValueError as e:
            errors.append(f"Row {r.get('_row', i)}: {e}")
    if errors or not clean:
        return 0, errors
    with engine().begin() as c:
        _remember_banks(c, [v["bank"] for v in clean])
        c.execute(insert(expenses), clean)
    log.info("batch insert: %d entries", len(clean))
    return len(clean), []


def update_expense(expense_id: int, **fields) -> None:
    cats, bnk = _lookups()
    vals = {}
    if fields.get("date") not in (None, ""):
        vals["date"] = parse_date(fields["date"])
    if fields.get("bank") not in (None, ""):
        b = str(fields["bank"]).strip()[:80]
        vals["bank"] = {x.lower(): x for x in bnk}.get(b.lower(), b)
    if fields.get("category") not in (None, ""):
        vals["category"] = normalize_category(fields["category"], cats)
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
        if "bank" in vals:
            _remember_banks(c, [vals["bank"]])
        if c.execute(update(expenses).where(expenses.c.id == int(expense_id)).values(**vals)).rowcount == 0:
            raise ValueError(f"No entry with id {expense_id}")


def delete_expense(expense_id: int) -> None:
    with engine().begin() as c:
        if c.execute(delete(expenses).where(expenses.c.id == int(expense_id))).rowcount == 0:
            raise ValueError(f"No entry with id {expense_id}")


def get_expenses(start=None, end=None, categories_filter=None, bank=None, text=None) -> pd.DataFrame:
    """categories_filter may hold category names and/or group names (a group includes all its categories)."""
    gm = group_map()
    q = select(*[expenses.c[c] for c in COLS])
    if start:
        q = q.where(expenses.c.date >= start)
    if end:
        q = q.where(expenses.c.date <= end)
    if categories_filter:
        wanted = set(categories_filter)
        names = {n for n, g in gm.items() if n in wanted or g in wanted} | wanted
        q = q.where(expenses.c.category.in_(list(names)))
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
    df["group"] = df["category"].map(gm).fillna(df["category"])  # analytics works on the four groups
    return df


def last_entry_date() -> dt.date | None:
    with engine().connect() as c:
        return c.execute(select(func.max(expenses.c.date))).scalar()


def apply_changes(orig: pd.DataFrame, edited: pd.DataFrame) -> tuple[dict, list[str]]:
    """Persist grid edits: new rows (no id), changed rows, and removed rows."""
    stats = {"added": 0, "updated": 0, "deleted": 0}
    errors: list[str] = []
    cats, bnk = _lookups()
    orig_by_id = {int(r["id"]): r for _, r in orig.iterrows()}
    kept: set[int] = set()
    with engine().begin() as c:
        for i, r in edited.iterrows():
            has_id = pd.notna(r.get("id"))
            if has_id:
                kept.add(int(r["id"]))
            elif pd.isna(r.get("amount")) and not _s(r.get("details")).strip() and not _s(r.get("category")):
                continue  # blank row
            try:
                vals = _clean(r["date"], r["bank"], r["category"], r["amount"], r["details"], cats, bnk)
            except ValueError as e:
                errors.append(f"Row {i + 1}: {e}")
                continue
            _remember_banks(c, [vals["bank"]])
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
    cats, bnk = _lookups()
    rows, errors = [], []
    for i, r in df.iterrows():
        try:
            rows.append(_clean(r["date"], r.get("bank", ""), r["category"], r["amount"], r.get("details", ""), cats, bnk))
        except ValueError as e:
            errors.append(f"Row {i + 2}: {e}")
    if rows:
        with engine().begin() as c:
            _remember_banks(c, [v["bank"] for v in rows])
            c.execute(insert(expenses), rows)
    return len(rows), errors


# ---------- editable dropdown lists ----------
_ZERO = {"added": 0, "updated": 0, "removed": 0}


def save_categories(orig: pd.DataFrame, edited: pd.DataFrame) -> tuple[dict, list[str]]:
    """Add / rename / regroup / remove custom categories. Nothing is written if any row is invalid.
    Renaming also renames the category on existing entries; a category used by entries cannot be removed."""
    errors: list[str] = []
    orig_by_id = {int(r["id"]): r for _, r in orig.iterrows()}
    kept, seen, adds, upds = set(), set(), [], []
    for i, r in edited.iterrows():
        has_id = pd.notna(r.get("id"))
        name, grp = _s(r.get("name")).strip(), _s(r.get("grp")).strip()
        if has_id:
            kept.add(int(r["id"]))
        elif not name and not grp:
            continue  # blank new row
        label = f"Row {i + 1}"
        if not name:
            errors.append(f"{label}: name is required")
        elif len(name) > 32:
            errors.append(f"{label}: '{name}' is longer than 32 characters")
        elif grp not in CATEGORIES:
            errors.append(f"{label}: choose a group for '{name}'")
        elif name.lower() in seen:
            errors.append(f"{label}: duplicate name '{name}'")
        else:
            seen.add(name.lower())
            if has_id:
                o = orig_by_id[int(r["id"])]
                if o["name"] in CATEGORIES and (name != o["name"] or grp != o["name"]):
                    errors.append(f"'{o['name']}' is a core category and cannot be changed")
                elif name != o["name"] or grp != o["grp"]:
                    upds.append((int(r["id"]), o["name"], name, grp))
            else:
                adds.append({"name": name, "grp": grp})
    removed = [o for rid, o in orig_by_id.items() if rid not in kept]
    errors += [f"'{o['name']}' is a core category and cannot be removed" for o in removed if o["name"] in CATEGORIES]
    if errors:
        return dict(_ZERO), errors
    with engine().begin() as c:
        for o in removed:
            n = c.execute(select(func.count()).select_from(expenses).where(expenses.c.category == o["name"])).scalar()
            if n:
                errors.append(f"'{o['name']}' is used by {n} entries. Move those entries to another category first, then remove it.")
        if errors:
            return dict(_ZERO), errors
        for rid, old, new, grp in upds:
            c.execute(update(categories).where(categories.c.id == rid).values(name=new, grp=grp))
            if new != old:
                c.execute(update(expenses).where(expenses.c.category == old).values(category=new))
        for o in removed:
            c.execute(delete(categories).where(categories.c.id == int(o["id"])))
        if adds:
            c.execute(insert(categories), adds)
    log.info("categories saved: +%d ~%d -%d", len(adds), len(upds), len(removed))
    return {"added": len(adds), "updated": len(upds), "removed": len(removed)}, []


def save_banks(orig: pd.DataFrame, edited: pd.DataFrame) -> tuple[dict, list[str]]:
    """Add / rename / remove banks. Renaming also renames the bank on existing entries.
    Removing a bank only removes it from the dropdown; old entries keep their text."""
    errors: list[str] = []
    orig_by_id = {int(r["id"]): r for _, r in orig.iterrows()}
    kept, seen, adds, upds = set(), set(), [], []
    for i, r in edited.iterrows():
        has_id = pd.notna(r.get("id"))
        name = _s(r.get("name")).strip()
        if has_id:
            kept.add(int(r["id"]))
        elif not name:
            continue
        label = f"Row {i + 1}"
        if not name:
            errors.append(f"{label}: name is required")
        elif len(name) > 80:
            errors.append(f"{label}: name is longer than 80 characters")
        elif name.lower() in seen:
            errors.append(f"{label}: duplicate bank '{name}'")
        else:
            seen.add(name.lower())
            if has_id:
                o = orig_by_id[int(r["id"])]
                if name != o["name"]:
                    upds.append((int(r["id"]), o["name"], name))
            else:
                adds.append({"name": name})
    removed = [o for rid, o in orig_by_id.items() if rid not in kept]
    if errors:
        return dict(_ZERO), errors
    with engine().begin() as c:
        for rid, old, new in upds:
            c.execute(update(banks).where(banks.c.id == rid).values(name=new))
            c.execute(update(expenses).where(expenses.c.bank == old).values(bank=new))
        for o in removed:
            c.execute(delete(banks).where(banks.c.id == int(o["id"])))
        if adds:
            c.execute(insert(banks), adds)
    log.info("banks saved: +%d ~%d -%d", len(adds), len(upds), len(removed))
    return {"added": len(adds), "updated": len(upds), "removed": len(removed)}, []


# ---------- budgets / targets ----------
def get_budgets() -> dict[str, float]:
    with engine().connect() as c:
        return {k: float(v) for k, v in c.execute(select(budgets.c.category, budgets.c.monthly_limit)).all()}


def set_budget(category: str, limit: float) -> None:
    with engine().begin() as c:
        c.execute(delete(budgets).where(budgets.c.category == category))
        if limit and limit > 0:
            c.execute(insert(budgets).values(category=category, monthly_limit=float(limit)))
