# NOTE: no `from __future__ import annotations` here. The Gemini SDK needs real type objects on the
# tool functions below; string annotations make its argument check fail with an isinstance() TypeError.
import functools
import logging
import re
import time

from google import genai
from google.genai import errors, types

from core import db
from core.config import get_secret, today
from core.logger import get_logger

log = get_logger("bot")

# Used only when the live model list cannot be fetched. Override with the GEMINI_MODEL secret.
DEFAULT_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3-flash-preview", "gemini-3.1-flash-lite"]
_SKIP = ("image", "tts", "live", "audio", "embed", "robot", "computer", "vision", "aqa")

ERRORS: list[str] = []  # real (non-validation) tool failures, shown under the bot reply
_WRITES = [0]  # successful writes so far; stops a model fallback from repeating a write
_CACHE = {"t": 0.0, "models": []}  # discovered model names, refreshed hourly


def _fail(e: Exception) -> dict:
    msg = f"{type(e).__name__}: {e}"
    if not isinstance(e, ValueError):  # ValueError = normal validation message, the model relays it
        ERRORS.append(msg)
        del ERRORS[:-5]
        log.error("tool exception: %s", msg, exc_info=e)
    return {"ok": False, "error": msg}


# ---------------- tools exposed to Gemini (docstrings are the tool descriptions) ----------------
def add_expense(date: str, bank: str, category: str, amount: float, details: str) -> dict:
    """Add a new entry. date is YYYY-MM-DD. category must be one of the category names listed in the system prompt. bank should match a known bank when possible (new banks are saved automatically)."""
    try:
        new_id = db.add_expense(date, bank, category, amount, details)
        _WRITES[0] += 1
        return {"ok": True, "id": new_id}
    except Exception as e:
        return _fail(e)


def search_expenses(start_date: str = "", end_date: str = "", category: str = "", bank: str = "", text: str = "") -> dict:
    """Find entries. All filters optional. Dates are YYYY-MM-DD inclusive. text must appear in the details column (case-insensitive, all words). Returns count, total and up to 40 rows incl. ids."""
    try:
        df = db.get_expenses(
            db.parse_date(start_date) if start_date else None,
            db.parse_date(end_date) if end_date else None,
            [db.normalize_category(category)] if category else None,
            bank or None,
            text or None,
        )
        rows = [
            {"id": int(r.id), "date": r.date.strftime("%Y-%m-%d"), "bank": r.bank, "category": r.category, "amount": r.amount, "details": r.details}
            for r in df.head(40).itertuples()
        ]
        return {
            "ok": True,
            "count": int(len(df)),
            "total": round(float(df["amount"].sum()), 2),
            "by_category": {k: round(float(v), 2) for k, v in df.groupby("category")["amount"].sum().items()},
            "by_group": {k: round(float(v), 2) for k, v in df.groupby("group")["amount"].sum().items()},
            "truncated": len(df) > 40,
            "rows": rows,
        }
    except Exception as e:
        return _fail(e)


def summarize_expenses(start_date: str, end_date: str, group_by: str = "category", text: str = "", category: str = "") -> dict:
    """Aggregate totals between two dates (YYYY-MM-DD). group_by is one of: category, group, bank, month, day (group = the four main groups). Optional text filter on details and category filter (a group name includes all its categories)."""
    try:
        df = db.get_expenses(
            db.parse_date(start_date),
            db.parse_date(end_date),
            [db.normalize_category(category)] if category else None,
            None,
            text or None,
        )
        key = {"category": df["category"], "group": df["group"], "bank": df["bank"], "month": df["date"].dt.strftime("%Y-%m"), "day": df["date"].dt.strftime("%Y-%m-%d")}.get(group_by)
        if key is None:
            return {"ok": False, "error": "group_by must be category, group, bank, month or day"}
        g = df.groupby(key)["amount"].agg(["sum", "count"])
        return {
            "ok": True,
            "total": round(float(df["amount"].sum()), 2),
            "entries": int(len(df)),
            "groups": {str(k): {"total": round(float(r["sum"]), 2), "entries": int(r["count"])} for k, r in g.iterrows()},
        }
    except Exception as e:
        return _fail(e)


def update_expense(expense_id: int, date: str = "", bank: str = "", category: str = "", amount: float = 0.0, details: str = "") -> dict:
    """Modify an entry by id. Pass only the fields that change (leave others empty / 0)."""
    try:
        db.update_expense(expense_id, date=date, bank=bank, category=category, amount=amount, details=details)
        _WRITES[0] += 1
        return {"ok": True}
    except Exception as e:
        return _fail(e)


def delete_expense(expense_id: int) -> dict:
    """Permanently delete an entry by id. Only call after the user confirmed."""
    try:
        db.delete_expense(expense_id)
        _WRITES[0] += 1
        return {"ok": True}
    except Exception as e:
        return _fail(e)


def _logged(fn):
    """Log every tool call and its outcome. functools.wraps keeps the signature/annotations the SDK reads."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        res = fn(*args, **kwargs)
        ok = bool(isinstance(res, dict) and res.get("ok"))
        log.log(logging.INFO if ok else logging.WARNING, "tool=%s args=%s ok=%s%s", fn.__name__, kwargs or args, ok, "" if ok else f" error={res.get('error')}")
        return res

    return wrapper


TOOLS = [_logged(f) for f in (add_expense, search_expenses, summarize_expenses, update_expense, delete_expense)]


def _system_prompt() -> str:
    t = today()
    gm = db.group_map()
    cat_lines = "\n".join(f"  - {n}" if n == g else f"  - {n} (group: {g})" for n, g in gm.items())
    banks = ", ".join(db.bank_names()) or "(none saved yet)"
    return f"""You are the assistant inside a personal finance tracker. Currency is INR (₹). Today is {t:%A, %Y-%m-%d}.
Each entry has: date, bank, category, amount, details.
Category must be exactly one of these names (the four main groups are Home Essential, SIP, Stock Investment, Extra; the others are the user's own categories inside a group):
{cat_lines}
Known banks: {banks}. Match the user's bank to a known bank when obvious; a new bank name is fine and gets saved.
Rules:
- Use tools for every read or write; never invent numbers or ids. Resolve relative dates ("yesterday", "last month", "this week") to YYYY-MM-DD.
- Adding: if date is missing use today. Prefer a matching user category when one clearly fits; otherwise infer the group: rent, groceries, bills, EMI, utilities, maintenance -> Home Essential; mutual fund / SIP -> SIP; shares, stocks, demat, ETF -> Stock Investment; everything else (dining, shopping, travel, wedding, gifts) -> Extra. If amount is missing or the category is truly unclear, ask one short question instead of guessing.
- Modifying or deleting: first call search_expenses to find the id. If several entries match, list them and ask which. Ask for confirmation before deleting unless the user already clearly named that exact entry and said to delete it.
- Questions like "how much did I spend on X between dates": call search_expenses with text=X and the date range, then report count and total (and a short breakdown if useful).
- If a tool returns ok=false, quote its error text exactly and say nothing was saved. Never claim the system or database is down, and never guess a cause.
- Be concise. Format amounts as ₹ with Indian grouping. Use a small markdown table for lists of more than 3 rows."""


# ---------------- Gemini plumbing ----------------
def _client() -> genai.Client:
    key = get_secret("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it in .streamlit/secrets.toml (free key: aistudio.google.com).")
    return genai.Client(api_key=key)


def _rank(name: str):
    """Newest full Flash first, then Flash-Lite; stable before preview."""
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    ver = float(m.group(1)) if m else 0.0
    return ("lite" in name, -ver, "preview" in name or "exp" in name)


def _discover() -> list[str]:
    """Ask the API which Flash models this key can use right now (names change and old ones get retired)."""
    if time.time() - _CACHE["t"] < 3600:
        return _CACHE["models"]
    _CACHE["t"] = time.time() - 3300  # on failure, retry in ~5 minutes
    try:
        names = set()
        for m in _client().models.list():
            n = (m.name or "").replace("models/", "")
            if "flash" in n and "generateContent" in (m.supported_actions or []) and not any(b in n for b in _SKIP):
                names.add(n)
        found = sorted(names, key=_rank)[:5]
        if found:
            _CACHE.update(t=time.time(), models=found)
            log.info("discovered models: %s", found)
        else:
            log.warning("model discovery returned no usable Flash models")
        return _CACHE["models"]
    except Exception as e:
        log.warning("model discovery failed: %s: %s", type(e).__name__, e)
        return _CACHE["models"]


def _models() -> list[str]:
    first = get_secret("GEMINI_MODEL", "")
    out = [first] if first else []
    for m in _discover() or DEFAULT_MODELS:
        if m not in out:
            out.append(m)
    return out


def _run(fn) -> str:
    """Try each model in turn. Missing (404), rate-limited (429) and overloaded (503) models fall through to the
    next one, since free-tier quotas are per model. Never retry after a write already succeeded."""
    tried: list[tuple[str, int]] = []
    writes_before = _WRITES[0]
    for model in _models():
        try:
            out = fn(model)
            log.info("model=%s ok", model)
            return out or "(empty response)"
        except errors.APIError as e:
            tried.append((model, e.code))
            log.warning("gemini model=%s code=%s status=%s message=%s", model, e.code, getattr(e, "status", ""), e.message)
            if _WRITES[0] != writes_before:
                return f"⚠️ Gemini failed ({e.code}) after a change was already saved. Check the Ledger before retrying."
            if e.code in (404, 429, 503):
                continue
            return f"Gemini error {e.code}: {e.message}"
        except Exception as e:
            log.exception("unexpected error with model=%s", model)
            return f"Unexpected error: {type(e).__name__}: {e} (see Settings → Logs)"
    summary = ", ".join(f"{m} → {c}" for m, c in tried)
    if any(c == 429 for _, c in tried):
        return f"⏳ Gemini free-tier quota/rate limit hit ({summary}). Wait a minute and retry; the daily quota resets at midnight Pacific."
    return f"No Gemini model worked ({summary}). Details are in Settings → Logs."


def _log_tool_failures(resp) -> None:
    """The SDK swallows exceptions raised while *invoking* a tool and feeds them back to the model; log those too."""
    for content in getattr(resp, "automatic_function_calling_history", None) or []:
        for part in content.parts or []:
            fr = getattr(part, "function_response", None)
            out = (fr.response or {}) if fr else {}
            if isinstance(out, dict) and "error" in out:
                msg = f"{fr.name}: {out['error']}"
                ERRORS.append(msg)
                log.error("sdk tool-call failure %s", msg)


def chat(history: list[dict], message: str) -> str:
    """history: [{'role': 'user'|'assistant', 'content': str}, ...] (without the new message)."""
    try:
        client = _client()
    except RuntimeError as e:
        log.error(str(e))
        return str(e)
    ERRORS.clear()
    try:
        system = _system_prompt()  # reads categories and banks from the database
    except Exception as e:
        log.exception("could not build system prompt")
        return f"Database error: {type(e).__name__}: {e} (see Settings → Logs)"
    hist = history[-12:]
    while hist and hist[0]["role"] != "user":
        hist = hist[1:]
    contents = [types.Content(role="user" if m["role"] == "user" else "model", parts=[types.Part(text=m["content"])]) for m in hist]
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        tools=TOOLS,
        temperature=0.2,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(maximum_remote_calls=8),
    )
    log.info("chat prompt=%r history_msgs=%d", message[:300], len(hist))

    def go(model: str) -> str:
        resp = client.chats.create(model=model, config=cfg, history=contents).send_message(message)
        _log_tool_failures(resp)
        return resp.text

    reply = _run(go)
    log.info("chat reply=%r", reply[:300])
    return reply


def advise(summary: str) -> str:
    """One-shot financial coaching text from a precomputed summary."""
    try:
        client = _client()
    except RuntimeError as e:
        log.error(str(e))
        return str(e)
    prompt = (
        "You are a concise personal-finance coach. Based only on this month-to-date summary (INR), give 3 short, "
        "practical tips: reduce Home Essential and Extra spending where it rose, protect or grow SIP and stock investments. "
        "No preamble.\n\n" + summary
    )
    return _run(lambda m: client.models.generate_content(model=m, contents=prompt).text)
