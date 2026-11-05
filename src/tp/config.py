from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
# TP_DATA_DIR lets smoke tests and experiments write somewhere other than the real store.
DATA_DIR = Path(os.environ.get("TP_DATA_DIR", ROOT / "data"))
# Out-of-sample data we do not look at while developing. scripts/run_backtest.py refuses to touch it
# without --use-holdout, and flags any trial that does.
HOLDOUT_START = date(2025, 1, 1)


@dataclass(frozen=True)
class Settings:
    alpaca_key_id: str
    alpaca_secret: str

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv(ROOT / ".env")
        key_id = os.environ.get("ALPACA_API_KEY_ID", "").strip()
        secret = os.environ.get("ALPACA_API_SECRET_KEY", "").strip()
        if not key_id or not secret:
            raise SystemExit("Missing ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY. Fill .env (see .env.example).")
        return cls(alpaca_key_id=key_id, alpaca_secret=secret)


def load_universe() -> dict:
    with open(ROOT / "config" / "universe.toml", "rb") as f:
        return tomllib.load(f)


def all_symbols() -> list[str]:
    u = load_universe()["universe"]
    return list(dict.fromkeys([*u["traded"], *u["regime"]]))


def core_symbols() -> list[str]:
    """The first universe plus the regime references: every bar type is recorded for these."""
    return all_symbols()


def wide_symbols() -> list[str]:
    """Second universe (scripts/select_universe.py): only 5-minute and daily bars are recorded."""
    path = ROOT / "config" / "universe_wide.toml"
    if not path.exists():
        return []
    with open(path, "rb") as f:
        return list(tomllib.load(f)["universe"]["wide"])


def events_symbols() -> list[str]:
    """Third universe (scripts/select_universe.py --n 150 --key events): daily bars only, used for event studies."""
    path = ROOT / "config" / "universe_events.toml"
    if not path.exists():
        return []
    with open(path, "rb") as f:
        return list(tomllib.load(f)["universe"]["events"])
