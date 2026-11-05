"""Daily-bar engine for multi-day bracket trades. Same contract as tp.backtest, different clock.

A Signal is decided at a session's close. The entry is a market order at the NEXT session's open plus slippage.
Each later session can stop the trade out, hit the target, or time it out at `hold_days`:

  * Gaps at the open fill at the open, not the stop or target.
  * A session whose range touches both stop and target counts as a loss (the order inside a day is unknown).
  * Targets are limit orders that must trade through by `limit_trade_through`; stops and time exits pay slippage.
  * A time exit is a market-on-close order on the last session of the hold.
  * Slippage is as-traded dollars scaled by the split factor, exactly as in the intraday engine.

Not modelled: dividends (bars are split-adjusted, not dividend-adjusted), borrow fees on shorts, overnight financing.
Results use the same RawTrade, so tp.backtest.apply_portfolio, tp.metrics and tp.walkforward work unchanged.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from tp.backtest import CostModel, RawTrade, Signal
from tp.bars import ET
from tp.features import session_dates

DEFAULT_HOLD_DAYS = 10
MAX_ENTRY_GAP = pd.Timedelta(days=5)  # longest plausible weekend plus holiday between decision and next open


def session_times(index: pd.DatetimeIndex, hour: float) -> pd.DatetimeIndex:
    """UTC timestamps of `hour` ET on each session date, correct across daylight-saving changes."""
    local = session_dates(index) + pd.Timedelta(hours=hour)
    return local.tz_localize(ET, ambiguous="NaT", nonexistent="shift_forward").tz_convert("UTC")


@dataclass
class PreparedDaily:
    index: pd.DatetimeIndex
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    day: np.ndarray  # ET date as YYYYMMDD
    adj: np.ndarray  # split factor: as-traded price = adjusted price * adj
    open_ts: pd.DatetimeIndex
    close_ts: pd.DatetimeIndex

    @classmethod
    def from_frame(cls, df: pd.DataFrame, split_factor: np.ndarray | None = None) -> PreparedDaily:
        local = df.index.tz_convert(ET)
        return cls(
            index=df.index, o=df["open"].to_numpy(), h=df["high"].to_numpy(), l=df["low"].to_numpy(), c=df["close"].to_numpy(),
            day=np.asarray(local.year * 10_000 + local.month * 100 + local.day),
            adj=np.ones(len(df)) if split_factor is None else np.asarray(split_factor, dtype=float),
            open_ts=session_times(df.index, 9.5), close_ts=session_times(df.index, 16.0),
        )


def decision_ts(daily_index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """When a signal computed from each session's bar is decided: that session's 16:00 ET close."""
    return session_times(daily_index, 16.0)


def simulate_trade(sig: Signal, pb: PreparedDaily, cost: CostModel) -> RawTrade | str:
    i = int(pb.open_ts.searchsorted(sig.ts))
    if i >= len(pb.index):
        return "no_entry_bar"
    if pb.open_ts[i] - sig.ts > MAX_ENTRY_GAP:
        return "stale_entry"
    long = sig.side == "long"
    slip, tt = cost.slippage / pb.adj[i], cost.limit_trade_through / pb.adj[i]
    fill = pb.o[i] + slip if long else pb.o[i] - slip
    inside = sig.stop < fill < sig.target if long else sig.target < fill < sig.stop
    if not inside:
        return "fill_outside_bracket"  # opened through the stop or target: a live bracket would be rejected

    hold = sig.hold_days or DEFAULT_HOLD_DAYS
    last = min(i + hold - 1, len(pb.index) - 1)
    exit_px = exit_ts = reason = None
    for j in range(i, last + 1):
        if j > i:
            if (long and pb.o[j] <= sig.stop) or (not long and pb.o[j] >= sig.stop):
                exit_px, exit_ts, reason = (pb.o[j] - slip if long else pb.o[j] + slip), pb.open_ts[j], "stop_gap"
                break
            if (long and pb.o[j] >= sig.target + tt) or (not long and pb.o[j] <= sig.target - tt):
                exit_px, exit_ts, reason = pb.o[j], pb.open_ts[j], "target_gap"
                break
        stop_hit = pb.l[j] <= sig.stop if long else pb.h[j] >= sig.stop
        target_hit = pb.h[j] >= sig.target + tt if long else pb.l[j] <= sig.target - tt
        if stop_hit:  # first: a session touching both counts as a loss
            exit_px, exit_ts, reason = (sig.stop - slip if long else sig.stop + slip), pb.close_ts[j], "stop"
            break
        if target_hit:
            exit_px, exit_ts, reason = sig.target, pb.close_ts[j], "target"
            break
    if exit_px is None:
        full = i + hold - 1 <= len(pb.index) - 1
        exit_px, exit_ts = (pb.c[last] - slip if long else pb.c[last] + slip), pb.close_ts[last]
        reason = "time" if full else "data_end"

    gross = exit_px - fill if long else fill - exit_px
    fee = cost.sell_fee_bps / 1e4 * (exit_px if long else fill)
    net = gross - fee
    return RawTrade(
        symbol=sig.symbol, side=sig.side, tag=sig.tag, signal_ts=sig.ts, entry_ts=pb.open_ts[i], exit_ts=exit_ts,
        entry_ref=sig.entry_ref, entry_px=float(fill), exit_px=float(exit_px), stop=sig.stop, target=sig.target,
        exit_reason=reason, risk_per_share=sig.risk, pnl_per_share=float(net), pnl_R=float(net / sig.risk),
    )  # fmt: skip


def simulate_signals(signals: Iterable[Signal], prepared: dict[str, PreparedDaily], cost: CostModel, risk=None):
    """Same shape as tp.backtest.simulate_signals. One open trade per symbol: signals during a live trade are dropped."""
    trades: list[RawTrade] = []
    rejects: Counter = Counter()
    busy_until: dict[str, pd.Timestamp] = {}
    for sig in sorted(signals, key=lambda s: (s.symbol, s.ts)):
        if sig.symbol in busy_until and sig.ts < busy_until[sig.symbol]:
            rejects["symbol_busy"] += 1
            continue
        res = simulate_trade(sig, prepared[sig.symbol], cost)
        if isinstance(res, str):
            rejects[res] += 1
            continue
        busy_until[sig.symbol] = res.exit_ts
        trades.append(res)
    return trades, rejects
