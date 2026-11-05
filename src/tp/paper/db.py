"""SQLite log of everything the paper loop sees and does. data/paper.sqlite (TP_PAPER_DB overrides)."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime

from tp import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL, context TEXT
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, logged_at TEXT NOT NULL, decision_ts TEXT NOT NULL, symbol TEXT NOT NULL,
    side TEXT NOT NULL, entry_ref REAL NOT NULL, stop REAL NOT NULL, target REAL NOT NULL, strategy TEXT NOT NULL,
    params TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT, qty INTEGER, client_order_id TEXT, evidence INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    client_order_id TEXT PRIMARY KEY, alpaca_id TEXT, symbol TEXT NOT NULL, side TEXT NOT NULL, qty INTEGER NOT NULL,
    submitted_at TEXT NOT NULL, status TEXT, filled_qty REAL, filled_avg_price REAL, entry_ref REAL, stop REAL,
    target REAL, exit_kind TEXT, exit_price REAL, exit_at TEXT, updated_at TEXT, evidence INTEGER NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class PaperDB:
    def __init__(self, path: str | None = None):
        path = path or os.environ.get("TP_PAPER_DB") or str(config.DATA_DIR / "paper.sqlite")
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def event(self, level: str, message: str, **context) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO events (ts, level, message, context) VALUES (?, ?, ?, ?)",
                              (now_iso(), level, message, json.dumps(context, default=str) if context else None))

    def signal(self, sig, strategy: str, params: dict, decision: str, reason: str | None, qty: int | None,
               coid: str | None, evidence: bool) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO signals (logged_at, decision_ts, symbol, side, entry_ref, stop, target, strategy, params, decision,"
                " reason, qty, client_order_id, evidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (now_iso(), sig.ts.isoformat(), sig.symbol, sig.side, sig.entry_ref, sig.stop, sig.target, strategy,
                 json.dumps(params, sort_keys=True), decision, reason, qty, coid, int(evidence)),
            )

    def order_submitted(self, coid: str, alpaca: dict, sig, qty: int, evidence: bool) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO orders (client_order_id, alpaca_id, symbol, side, qty, submitted_at, status, entry_ref,"
                " stop, target, evidence) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (coid, alpaca.get("id"), sig.symbol, sig.side, qty, now_iso(), alpaca.get("status"), sig.entry_ref,
                 sig.stop, sig.target, int(evidence)),
            )

    def order_update(self, coid: str, **fields) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.conn:
            self.conn.execute(f"UPDATE orders SET {sets}, updated_at = ? WHERE client_order_id = ?", (*fields.values(), now_iso(), coid))

    def has_order(self, coid: str) -> bool:
        return self.conn.execute("SELECT 1 FROM orders WHERE client_order_id = ?", (coid,)).fetchone() is not None

    def trades_submitted_on(self, day_prefix: str) -> int:
        """Orders submitted on a UTC date (YYYY-MM-DD)."""
        return int(self.conn.execute("SELECT COUNT(*) FROM orders WHERE submitted_at LIKE ?", (day_prefix + "%",)).fetchone()[0])

    def rows(self, sql: str, args: tuple = ()) -> list[tuple]:
        return self.conn.execute(sql, args).fetchall()
