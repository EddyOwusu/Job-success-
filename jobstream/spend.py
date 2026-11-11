"""What Claude costs you, call by call, and the daily budget.

Every Claude call adds its cost to a small ledger (data/spend.db), worked out from the token
counts the API returns and the list prices below. When today's total reaches
`llm.daily_budget_usd`, JobStream stops calling Claude until tomorrow: searching and scoring
carry on, and jobs it couldn't apply to wait for the next day.

The figures are estimates from list prices; your Claude Console (Usage) has the exact bill.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

# USD per million tokens: (input, output, cache read). Cache writes cost 1.25x input.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
    "claude-sonnet-5": (2.00, 10.00, 0.20),
}
WEB_SEARCH_USD = 10.00 / 1000          # per search (interview research)
MODEL_NAMES = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}


def _n(obj: Any, name: str) -> int:
    return int(getattr(obj, name, 0) or 0) if obj is not None else 0


def cost(model: str, usage: Any) -> float:
    """Estimated USD for one response's usage."""
    if usage is None:
        return 0.0
    p_in, p_out, p_read = PRICES.get(model) or PRICES["claude-opus-5-5"]
    usd = (_n(usage, "input_tokens") * p_in + _n(usage, "output_tokens") * p_out
           + _n(usage, "cache_creation_input_tokens") * p_in * 1.25
           + _n(usage, "cache_read_input_tokens") * p_read) / 1_000_000
    usd += _n(getattr(usage, "server_tool_use", None), "web_search_requests") * WEB_SEARCH_USD
    return usd


class Ledger:
    """Today's Claude spend, shared by every JobStream process on this computer."""

    _lock = threading.Lock()

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS spend (day TEXT, at TEXT, model TEXT, task TEXT, usd REAL)")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path), timeout=30)

    def add(self, usd: float, model: str, task: str = "") -> None:
        if usd <= 0:
            return
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO spend VALUES (?,?,?,?,?)",
                      (date.today().isoformat(), datetime.now().isoformat(timespec="seconds"), model, task, usd))

    def today(self) -> float:
        return self.on(date.today().isoformat())

    def on(self, day: str) -> float:
        with self._conn() as c:
            return float(c.execute("SELECT COALESCE(SUM(usd), 0) FROM spend WHERE day=?", (day,)).fetchone()[0])

    def by_task(self, day: str | None = None) -> list[tuple[str, int, float]]:
        with self._conn() as c:
            return c.execute("SELECT task, COUNT(*), SUM(usd) FROM spend WHERE day=? GROUP BY task ORDER BY 3 DESC",
                             (day or date.today().isoformat(),)).fetchall()

    def last_days(self, n: int = 7) -> list[tuple[str, float]]:
        with self._conn() as c:
            return c.execute("SELECT day, SUM(usd) FROM spend GROUP BY day ORDER BY day DESC LIMIT ?", (n,)).fetchall()
