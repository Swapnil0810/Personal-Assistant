from __future__ import annotations

import datetime as dt
import logging
import os
from collections import deque
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

from core.config import get_secret

_ROOT = "finance"


def log_path() -> str:
    return os.path.join(get_secret("LOG_DIR", "logs"), "app.log")


def _setup() -> logging.Logger:
    root = logging.getLogger(_ROOT)
    if root.handlers:
        return root
    root.setLevel(logging.INFO)
    root.propagate = False

    tz = ZoneInfo(get_secret("APP_TIMEZONE", "Asia/Kolkata"))
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    fmt.converter = lambda ts: dt.datetime.fromtimestamp(ts, tz).timetuple()

    handlers: list[logging.Handler] = [logging.StreamHandler()]  # console (visible in host dashboards)
    try:
        path = log_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        handlers.append(RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"))
    except OSError:
        pass  # read-only disk: console logging only
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)
    return root


def get_logger(name: str) -> logging.Logger:
    _setup()
    return logging.getLogger(f"{_ROOT}.{name}")


def tail(n: int = 200) -> str:
    """Last n lines of the current log file (newest at the bottom)."""
    try:
        with open(log_path(), encoding="utf-8", errors="replace") as f:
            return "".join(deque(f, maxlen=n))
    except OSError:
        return ""
