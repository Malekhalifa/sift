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


def apify_key() -> str:
    """The Apify API key from APIFY_API_KEY (or `.env`), read only when asked so the other code paths never need it.
    ValueError, without the key, when it is not set."""
    load_dotenv(ROOT / ".env")
    key = os.environ.get("APIFY_API_KEY", "").strip()
    if not key:
        raise ValueError("APIFY_API_KEY is not set; add it to .env (see .env.example)")
    return key


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


def confirm_symbols() -> list[str]:
    """Fourth universe (ranks 151-400, scripts/select_universe.py --skip 150 --n 250 --key confirm): the fresh stocks
    used to confirm one frozen configuration. Daily bars only."""
    path = ROOT / "config" / "universe_confirm.toml"
    if not path.exists():
        return []
    with open(path, "rb") as f:
        return list(tomllib.load(f)["universe"]["confirm"])


def sf_symbols() -> list[str]:
    """Survivorship-free universe (scripts/select_universe.py --include-inactive --no-exclude --n 1000 --key sf): ranks 1-1000
    by Q1-2016 dollar volume across names listed then, including those delisted since. Daily bars only."""
    path = ROOT / "config" / "universe_sf.toml"
    if not path.exists():
        return []
    with open(path, "rb") as f:
        return list(tomllib.load(f)["universe"]["sf"])
