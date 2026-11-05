"""Event-light backtest engine for intraday bracket strategies.

Pipeline: strategy -> list[Signal] -> simulate_trade() per signal (price path only, in R) ->
apply_portfolio() (position sizing, equity compounding, exposure caps) -> metrics.

Conventions, chosen so a backtest cannot flatter the strategy:
  * A Signal is decided on a closed bar. Entry is a market order filled at the NEXT bar's open, plus slippage.
  * Stop and target levels come from the signal (computed off the signal bar's close), as a live bracket order would.
  * Stop exits are market orders and pay slippage; gaps through the stop fill at the open, not the stop.
  * Target exits are limit orders: they only count as filled when price trades through the target by
    `limit_trade_through`, and pay no slippage.
  * If a bar touches both stop and target, the stop is assumed to hit first.
  * Positions are flat by `flat_time`; nothing is held overnight.
  * R = per-share net pnl / per-share planned risk (|entry_ref - stop|), independent of position size.
"""

from __future__ import annotations

import heapq
import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import time
from typing import Literal

import numpy as np
import pandas as pd

from tp.bars import ET

Side = Literal["long", "short"]


@dataclass(frozen=True)
class Signal:
    symbol: str
    ts: pd.Timestamp  # decision time = close of the signal bar; the fill happens on the next bar
    side: Side
    entry_ref: float  # signal bar close; sizing and bracket levels are computed from it
    stop: float
    target: float
    tag: str = ""

    def __post_init__(self) -> None:
        ok = (
            self.stop < self.entry_ref < self.target
            if self.side == "long"
            else self.target < self.entry_ref < self.stop
        )
        if not ok:
            raise ValueError(f"bracket not on the right side of entry: {self}")

    @property
    def risk(self) -> float:
        return abs(self.entry_ref - self.stop)

    @classmethod
    def bracket(cls, symbol: str, ts: pd.Timestamp, side: Side, entry_ref: float, stop: float, rr: float, tag: str = "") -> Signal:
        risk = abs(entry_ref - stop)
        target = entry_ref + rr * risk if side == "long" else entry_ref - rr * risk
        return cls(symbol, ts, side, entry_ref, stop, target, tag)


@dataclass(frozen=True)
class CostModel:
    # Both are as-traded dollars per share. Bars are split-adjusted, so simulate_trade() divides them by the
    # split factor in force that day (a 1c spread on a $100 stock is 0.025c on a share later split 4:1).
    slippage: float = 0.01  # adverse, on market entries, stop exits and time exits
    limit_trade_through: float = 0.01  # price must trade this far beyond a target for the limit to fill
    sell_fee_bps: float = 0.3  # approx. SEC/FINRA fees on sale notional; Alpaca charges no commission
    max_entry_delay_min: int = 10  # reject if the next bar opens later than this after the decision


@dataclass(frozen=True)
class RiskConfig:
    start_equity: float = 100_000.0
    risk_per_trade: float = 0.01  # fraction of current equity risked at the stop
    max_leverage: float = 2.0  # total open notional / equity
    max_positions: int = 5
    flat_time: time = time(15, 55)  # exit at the open of the bar starting at this ET time


@dataclass
class PreparedBars:
    """Numpy view of one symbol's bars (UTC index, bar-open timestamps) for fast simulation."""

    index: pd.DatetimeIndex
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    mod: np.ndarray  # ET minute of day at bar open
    day: np.ndarray  # ET date as YYYYMMDD
    bar_len: pd.Timedelta
    adj: np.ndarray  # split factor per bar: as-traded price = adjusted price * adj (1.0 when never split)

    @classmethod
    def from_frame(cls, df: pd.DataFrame, bar_minutes: int = 5, split_factor: np.ndarray | None = None) -> PreparedBars:
        local = df.index.tz_convert(ET)
        return cls(
            index=df.index,
            o=df["open"].to_numpy(),
            h=df["high"].to_numpy(),
            l=df["low"].to_numpy(),
            c=df["close"].to_numpy(),
            mod=np.asarray(local.hour * 60 + local.minute),
            day=np.asarray(local.year * 10_000 + local.month * 100 + local.day),
            bar_len=pd.Timedelta(minutes=bar_minutes),
            adj=np.ones(len(df)) if split_factor is None else np.asarray(split_factor, dtype=float),
        )


@dataclass(frozen=True)
class RawTrade:
    symbol: str
    side: Side
    tag: str
    signal_ts: pd.Timestamp
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    entry_ref: float
    entry_px: float
    exit_px: float
    stop: float
    target: float
    exit_reason: str
    risk_per_share: float
    pnl_per_share: float  # net of slippage (in prices) and fees
    pnl_R: float


def simulate_trade(sig: Signal, pb: PreparedBars, cost: CostModel, flat_minute: int) -> RawTrade | str:
    """Walk the bars after a signal. Returns the trade, or a reject reason string."""
    i = int(pb.index.searchsorted(sig.ts))
    if i >= len(pb.index):
        return "no_entry_bar"
    entry_ts = pb.index[i]
    if entry_ts - sig.ts > pd.Timedelta(minutes=cost.max_entry_delay_min):
        return "stale_entry"
    sig_open = (sig.ts - pb.bar_len).tz_convert(ET)
    if pb.day[i] != sig_open.year * 10_000 + sig_open.month * 100 + sig_open.day:
        return "no_entry_bar"  # signal came on the session's last bar
    if pb.mod[i] >= flat_minute:
        return "after_flat_time"

    long = sig.side == "long"
    slip, tt = cost.slippage / pb.adj[i], cost.limit_trade_through / pb.adj[i]
    fill = pb.o[i] + slip if long else pb.o[i] - slip
    inside = sig.stop < fill < sig.target if long else sig.target < fill < sig.stop
    if not inside:
        return "fill_outside_bracket"  # a live bracket order would be rejected

    def adverse(px: float) -> float:
        return px - slip if long else px + slip

    n, d = len(pb.index), pb.day[i]
    exit_px = exit_ts = reason = None
    last = i
    j = i
    while j < n and pb.day[j] == d:
        last = j
        if j > i:
            if pb.mod[j] >= flat_minute:
                exit_px, exit_ts, reason = adverse(pb.o[j]), pb.index[j], "time"
                break
            if long and pb.o[j] <= sig.stop or not long and pb.o[j] >= sig.stop:
                exit_px, exit_ts, reason = adverse(pb.o[j]), pb.index[j], "stop_gap"
                break
            if long and pb.o[j] >= sig.target + tt or not long and pb.o[j] <= sig.target - tt:
                exit_px, exit_ts, reason = pb.o[j], pb.index[j], "target_gap"
                break
        stop_hit = pb.l[j] <= sig.stop if long else pb.h[j] >= sig.stop
        target_hit = pb.h[j] >= sig.target + tt if long else pb.l[j] <= sig.target - tt
        if stop_hit:  # checked first: a bar touching both counts as a loss
            exit_px, exit_ts, reason = adverse(sig.stop), pb.index[j] + pb.bar_len, "stop"
            break
        if target_hit:
            exit_px, exit_ts, reason = sig.target, pb.index[j] + pb.bar_len, "target"
            break
        j += 1
    if exit_px is None:  # data ended before flat_time (early close or missing bars)
        exit_px, exit_ts, reason = adverse(pb.c[last]), pb.index[last] + pb.bar_len, "eod"

    gross = exit_px - fill if long else fill - exit_px
    fee = cost.sell_fee_bps / 1e4 * (exit_px if long else fill)  # fees apply to the sell leg
    net = gross - fee
    return RawTrade(
        symbol=sig.symbol, side=sig.side, tag=sig.tag, signal_ts=sig.ts, entry_ts=entry_ts, exit_ts=exit_ts,
        entry_ref=sig.entry_ref, entry_px=float(fill), exit_px=float(exit_px), stop=sig.stop, target=sig.target,
        exit_reason=reason, risk_per_share=sig.risk, pnl_per_share=float(net), pnl_R=float(net / sig.risk),
    )  # fmt: skip


def simulate_signals(
    signals: Iterable[Signal],
    prepared: dict[str, PreparedBars],
    cost: CostModel,
    risk: RiskConfig,
) -> tuple[list[RawTrade], Counter]:
    """Simulate every signal's price path. One open trade per symbol: signals during a live trade are dropped."""
    flat_minute = risk.flat_time.hour * 60 + risk.flat_time.minute
    trades: list[RawTrade] = []
    rejects: Counter = Counter()
    busy_until: dict[str, pd.Timestamp] = {}
    for sig in sorted(signals, key=lambda s: (s.symbol, s.ts)):
        if sig.symbol in busy_until and sig.ts < busy_until[sig.symbol]:
            rejects["symbol_busy"] += 1
            continue
        res = simulate_trade(sig, prepared[sig.symbol], cost, flat_minute)
        if isinstance(res, str):
            rejects[res] += 1
            continue
        busy_until[sig.symbol] = res.exit_ts
        trades.append(res)
    return trades, rejects


def apply_portfolio(raw: list[RawTrade], risk: RiskConfig) -> tuple[pd.DataFrame, Counter]:
    """Size trades in time order against compounding equity and exposure caps."""
    equity = risk.start_equity
    open_pos: list[tuple[pd.Timestamp, int, float, float]] = []  # heap of (exit_ts, seq, notional, pnl)
    rejects: Counter = Counter()
    rows = []
    for seq, t in enumerate(sorted(raw, key=lambda t: (t.entry_ts, t.symbol))):
        while open_pos and open_pos[0][0] <= t.entry_ts:
            equity += heapq.heappop(open_pos)[3]
        if len(open_pos) >= risk.max_positions:
            rejects["max_positions"] += 1
            continue
        qty_risk = math.floor(risk.risk_per_trade * equity / t.risk_per_share)
        open_notional = sum(p[2] for p in open_pos)
        qty_cap = math.floor((risk.max_leverage * equity - open_notional) / t.entry_px)
        qty = min(qty_risk, qty_cap)
        if qty < 1:
            rejects["qty_below_1" if qty_risk < 1 else "leverage_cap"] += 1
            continue
        pnl = qty * t.pnl_per_share
        heapq.heappush(open_pos, (t.exit_ts, seq, qty * t.entry_px, pnl))
        rows.append({**asdict(t), "qty": qty, "equity_before": equity, "pnl": pnl, "capped": qty < qty_risk})
    cols = [f for f in RawTrade.__dataclass_fields__] + ["qty", "equity_before", "pnl", "capped"]
    return pd.DataFrame(rows, columns=cols), rejects


@dataclass
class BacktestResult:
    raw: pd.DataFrame  # every simulated trade, sizing-free (strategy quality, in R)
    trades: pd.DataFrame  # trades actually taken after sizing and exposure caps
    rejects: dict[str, int]
    sessions: list[pd.Timestamp]  # every trading day covered by the bars (naive ET midnight)
    risk: RiskConfig
    cost: CostModel


def execute(
    signals: Iterable[Signal],
    prepared: dict[str, PreparedBars],
    cost: CostModel = CostModel(),
    risk: RiskConfig = RiskConfig(),
) -> BacktestResult:
    raw, rej_sim = simulate_signals(signals, prepared, cost, risk)
    trades, rej_port = apply_portfolio(raw, risk)
    days = sorted({int(d) for pb in prepared.values() for d in np.unique(pb.day)})
    sessions = [pd.Timestamp(year=d // 10_000, month=d // 100 % 100, day=d % 100) for d in days]
    raw_df = pd.DataFrame([asdict(t) for t in raw], columns=list(RawTrade.__dataclass_fields__))
    return BacktestResult(raw_df, trades, dict(rej_sim + rej_port), sessions, risk, cost)
