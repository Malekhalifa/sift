"""Registry of every backtest run. The count of trials per strategy is the input the Deflated Sharpe Ratio
needs to correct for selection bias, so log every run, including the bad ones."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from datetime import UTC, datetime

from tp import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    git_sha TEXT,
    strategy TEXT NOT NULL,
    params TEXT NOT NULL,
    scope TEXT NOT NULL,
    holdout INTEGER NOT NULL DEFAULT 0,
    metrics TEXT NOT NULL,
    grp TEXT
)
"""


def _db() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    # TP_TRIALS_DB lets throwaway dev checks use their own registry without inflating the real trial count.
    conn = sqlite3.connect(os.environ.get("TP_TRIALS_DB") or config.DATA_DIR / "trials.sqlite")
    conn.execute(SCHEMA)
    if "grp" not in {row[1] for row in conn.execute("PRAGMA table_info(trials)")}:
        conn.execute("ALTER TABLE trials ADD COLUMN grp TEXT")  # databases created before sweeps existed
    return conn


def git_sha() -> str | None:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=config.ROOT, capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "src", "scripts"], cwd=config.ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return f"{sha}+dirty" if dirty else sha


def log_trial(strategy: str, params: dict, scope: dict, metrics: dict, holdout: bool = False, group: str | None = None) -> int:
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO trials (created_at, git_sha, strategy, params, scope, holdout, metrics, grp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (datetime.now(UTC).isoformat(), git_sha(), strategy, json.dumps(params, sort_keys=True), json.dumps(scope, sort_keys=True), int(holdout), json.dumps(metrics), group),
        )
        return int(cur.lastrowid)


def count_trials(strategy: str | None = None, group: str | None = None) -> int:
    """Trials logged, optionally for one strategy and/or one sweep group."""
    where, args = [], []
    if strategy is not None:
        where.append("strategy = ?")
        args.append(strategy)
    if group is not None:
        where.append("grp = ?")
        args.append(group)
    with _db() as conn:
        sql = "SELECT COUNT(*) FROM trials" + (" WHERE " + " AND ".join(where) if where else "")
        return int(conn.execute(sql, args).fetchone()[0])


def logged_params(group: str) -> set[tuple[str, str]]:
    """(strategy, params JSON) already logged in a sweep group, so a restarted sweep never double-counts."""
    with _db() as conn:
        rows = conn.execute("SELECT strategy, params FROM trials WHERE grp = ?", (group,)).fetchall()
    return {(strategy, params) for strategy, params in rows}
