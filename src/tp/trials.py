"""Registry of every backtest run. The count of trials per strategy is the input the Deflated Sharpe Ratio
needs to correct for selection bias, so log every run, including the bad ones."""

from __future__ import annotations

import json
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
    metrics TEXT NOT NULL
)
"""


def _db() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DATA_DIR / "trials.sqlite")
    conn.execute(SCHEMA)
    return conn


def git_sha() -> str | None:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=config.ROOT, capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "src", "scripts"], cwd=config.ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return f"{sha}+dirty" if dirty else sha


def log_trial(strategy: str, params: dict, scope: dict, metrics: dict, holdout: bool = False) -> int:
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO trials (created_at, git_sha, strategy, params, scope, holdout, metrics) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (datetime.now(UTC).isoformat(), git_sha(), strategy, json.dumps(params, sort_keys=True), json.dumps(scope, sort_keys=True), int(holdout), json.dumps(metrics)),
        )
        return int(cur.lastrowid)


def count_trials(strategy: str | None = None) -> int:
    with _db() as conn:
        if strategy is None:
            return int(conn.execute("SELECT COUNT(*) FROM trials").fetchone()[0])
        return int(conn.execute("SELECT COUNT(*) FROM trials WHERE strategy = ?", (strategy,)).fetchone()[0])
