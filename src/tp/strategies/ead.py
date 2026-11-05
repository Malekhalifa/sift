"""Earnings-announcement drift (price-reaction version), on daily bars.

Event: an earnings release (SEC 8-K Item 2.02). Reaction: the first session that could react to it. We measure the
market-adjusted move of that session, the stock's return minus SPY's, in units of the stock's own recent daily range
(ATR as a percent of price, from the sessions BEFORE the event). If the move is at least `thr_atr` ATRs we trade at the
next open: with the reaction ("drift", the post-earnings-drift idea) or against it ("fade"). Decided at the close of
the reaction session; bracket with a stop at `stop_atr` x ATR(14), a 1.5R target and a time exit.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from tp import events
from tp.backtest import Signal
from tp.swing import decision_ts


@dataclass(frozen=True)
class EADParams:
    mode: str = "drift"  # "drift" follows the reaction, "fade" bets against it
    thr_atr: float = 1.5  # market-adjusted reaction size, in ATRs
    stop_atr: float = 2.0
    atr_n: int = 14
    rr: float = 1.5
    max_hold: int = 10
    sides: str = "both"
    min_risk_pct: float = 0.002


class EarningsDrift:
    name = "ead"
    params_cls = EADParams

    def __init__(self, **overrides):
        self.params = EADParams(**overrides)
        p = self.params
        if p.mode not in ("drift", "fade"):
            raise ValueError(f"unknown mode {p.mode!r}")
        if p.sides not in ("long", "short", "both"):
            raise ValueError(f"unknown sides {p.sides!r}")
        if p.max_hold < 1:
            raise ValueError("max_hold must be >= 1")

    def params_dict(self) -> dict:
        return asdict(self.params)

    @staticmethod
    def canonical(overrides: dict) -> dict:
        return dict(overrides)

    def generate(self, symbol: str, bars: pd.DataFrame, daily=None, spy_daily=None) -> list[Signal]:
        if spy_daily is None or spy_daily.empty:
            raise ValueError("the earnings strategy needs SPY daily bars to market-adjust the reaction")
        p = self.params
        table = events.reaction_table(bars, spy_daily, events.load_earnings(symbol)["filed_at"], p.atr_n)
        if table.empty:
            return []
        close = bars["close"]
        when = decision_ts(bars.index)
        signals = []
        for row in table.itertuples():
            if abs(row.z) < p.thr_atr:
                continue
            long = (row.z > 0) == (p.mode == "drift")
            if p.sides != "both" and (p.sides == "long") != long:
                continue
            entry = float(close.iloc[row.pos])
            stop = entry - p.stop_atr * row.atr if long else entry + p.stop_atr * row.atr
            if stop <= 0 or abs(entry - stop) < p.min_risk_pct * entry:
                continue
            signals.append(Signal.bracket(symbol, when[row.pos], "long" if long else "short", entry, stop, p.rr, "ead", p.max_hold))
        return signals
