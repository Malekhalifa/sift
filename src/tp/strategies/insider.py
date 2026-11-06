"""Insider buying (Form 4), long only, on daily bars.

Event: a cluster of open-market purchases by officers and directors that the routine/opportunistic rule lets through
(see tp.insiders and docs/m10-insider-protocol.md). The event is known as of its filing date, so the signal is decided
at that session's close and filled at the next open. Bracket: stop at `stop_atr` x ATR(14), a 1.5R target, a time exit.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from tp import features, insiders
from tp.backtest import Signal
from tp.swing import decision_ts


@dataclass(frozen=True)
class InsiderParams:
    classes: str = "opportunistic"  # "opportunistic" or "opportunistic+thin" (first-time and occasional buyers too)
    min_insiders: int = 1
    min_value: float = 100_000.0  # dollars bought in the cluster window
    window_days: int = 10
    cooldown_days: int = 30
    stop_atr: float = 2.0
    atr_n: int = 14
    rr: float = 1.5
    max_hold: int = 20
    min_risk_pct: float = 0.002


class InsiderBuys:
    name = "insider"
    params_cls = InsiderParams

    def __init__(self, **overrides):
        self.params = InsiderParams(**overrides)
        p = self.params
        if p.classes not in insiders.CLASS_SETS:
            raise ValueError(f"unknown classes {p.classes!r}")
        if p.min_insiders < 1 or p.max_hold < 1:
            raise ValueError("min_insiders and max_hold must be >= 1")

    def params_dict(self) -> dict:
        return asdict(self.params)

    @staticmethod
    def canonical(overrides: dict) -> dict:
        return dict(overrides)

    def generate(self, symbol: str, bars: pd.DataFrame, daily=None, spy_daily=None) -> list[Signal]:
        cik = insiders.symbol_ciks().get(symbol)
        if cik is None or bars.empty:
            return []
        p = self.params
        days = insiders.buy_events(insiders.classified_purchases(cik), p.classes, p.min_insiders, p.min_value,
                                   p.window_days, p.cooldown_days)
        if not days:
            return []
        sessions = pd.DatetimeIndex(features.session_dates(bars.index))
        atr = features.atr_through(bars, p.atr_n)
        close = bars["close"]
        when = decision_ts(bars.index)
        signals = []
        for day in days:
            pos = int(sessions.searchsorted(day, side="left"))  # the filing day's session, or the next one if it was not a session
            if pos >= len(bars) or pos < p.atr_n or pd.isna(atr.iloc[pos]):
                continue
            entry = float(close.iloc[pos])
            stop = entry - p.stop_atr * float(atr.iloc[pos])
            if stop <= 0 or abs(entry - stop) < p.min_risk_pct * entry:
                continue
            signals.append(Signal.bracket(symbol, when[pos], "long", entry, stop, p.rr, "insider", p.max_hold))
        return signals
