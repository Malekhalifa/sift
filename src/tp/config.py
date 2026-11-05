from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
# TP_DATA_DIR lets smoke tests and experiments write somewhere other than the real store.
DATA_DIR = Path(os.environ.get("TP_DATA_DIR", ROOT / "data"))


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
