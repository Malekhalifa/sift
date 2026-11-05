"""Pure decision logic for the live loop: which signals exist now, what blocks them, how big, what order.

Nothing here talks to the network, so every rule can be tested. The strategy itself is the same class the
backtest uses; this module only filters its output down to "the bar that just closed".
"""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

import pandas as pd

from tp import config
from tp.backtest import Signal
from tp.bars import ET

BAR_MINUTES = 5


@dataclass(frozen=True)
class PaperConfig:
    strategy: str = "orb"
    params: dict = field(default_factory=dict)
    symbols: list[str] = field(default_factory=list)
    tag: str = "plumbing"  # prefix of every client_order_id, so our orders are always identifiable
    evidence: bool = False  # False = machinery test: results must not be read as strategy evidence
    dry_run: bool = True  # log what would be submitted, send nothing
    risk_per_trade: float = 0.0025
    max_positions: int = 3
    max_trades_per_day: int = 6
    max_leverage: float = 1.0
    daily_loss_cap_pct: float = 1.0  # stop entering once the account is this many percent down on the day
    flat_time: str = "15:55"
    poll_delay_s: int = 8  # wait after a bar closes before asking for it, so the feed has finalised it
    history_days: int = 45
    max_consecutive_errors: int = 5
    split_blackout_days: int = 20  # skip a symbol this long after a split: stored history would mismatch live prices


def load_config(path: str | Path) -> PaperConfig:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    section = raw["paper"]
    section["params"] = raw.get("params", {})
    return PaperConfig(**section)


def decision_time(now: pd.Timestamp) -> pd.Timestamp:
    """Close time of the most recent finished 5-minute bar (the moment a signal on that bar is decided)."""
    return now.floor(f"{BAR_MINUTES}min")


def signals_at(signals: list[Signal], decision_ts: pd.Timestamp) -> list[Signal]:
    """Only signals decided on the bar that has just closed; earlier ones were handled (or missed) already."""
    return [s for s in signals if s.ts == decision_ts]


def minute_of_day(ts: pd.Timestamp) -> int:
    local = ts.tz_convert(ET)
    return local.hour * 60 + local.minute


def flat_minute(cfg: PaperConfig) -> int:
    t = time.fromisoformat(cfg.flat_time)
    return t.hour * 60 + t.minute


@dataclass(frozen=True)
class Snapshot:
    """Account and market state at the moment of a decision."""

    equity: float
    last_equity: float  # equity at the previous close
    open_symbols: frozenset[str]  # positions plus symbols with a working entry order
    open_notional: float
    trades_today: int
    kill_switch: bool = False
    recent_split: frozenset[str] = frozenset()


def block_reason(sig: Signal, snap: Snapshot, cfg: PaperConfig) -> str | None:
    """First reason this signal must not be traded, or None."""
    if snap.kill_switch:
        return "kill_switch"
    if minute_of_day(sig.ts) >= flat_minute(cfg) - BAR_MINUTES:
        return "too_close_to_flat_time"
    if snap.last_equity > 0 and 100 * (snap.equity / snap.last_equity - 1) <= -cfg.daily_loss_cap_pct:
        return "daily_loss_cap"
    if sig.symbol in snap.recent_split:
        return "recent_split"
    if sig.symbol in snap.open_symbols:
        return "symbol_busy"
    if len(snap.open_symbols) >= cfg.max_positions:
        return "max_positions"
    if snap.trades_today >= cfg.max_trades_per_day:
        return "max_trades_per_day"
    return None


def position_size(sig: Signal, snap: Snapshot, cfg: PaperConfig) -> tuple[int, str | None]:
    """Shares to trade, or (0, reason). Risk a fixed fraction of equity at the stop, capped by leverage."""
    by_risk = math.floor(cfg.risk_per_trade * snap.equity / sig.risk)
    by_leverage = math.floor((cfg.max_leverage * snap.equity - snap.open_notional) / sig.entry_ref)
    qty = min(by_risk, by_leverage)
    if qty < 1:
        return 0, "qty_below_1" if by_risk < 1 else "leverage_cap"
    return qty, None


def client_order_id(cfg: PaperConfig, sig: Signal) -> str:
    """Deterministic, so a restart can never submit the same signal twice."""
    return f"{cfg.tag}-{sig.symbol}-{sig.ts:%m%d%H%M}"


def order_payload(sig: Signal, qty: int, coid: str) -> dict:
    """Market entry with a bracket: the take-profit and stop-loss are attached and live at the broker."""
    return {
        "symbol": sig.symbol,
        "qty": str(qty),
        "side": "buy" if sig.side == "long" else "sell",
        "type": "market",
        "time_in_force": "day",
        "order_class": "bracket",
        "take_profit": {"limit_price": f"{sig.target:.2f}"},
        "stop_loss": {"stop_price": f"{sig.stop:.2f}"},
        "client_order_id": coid,
    }
