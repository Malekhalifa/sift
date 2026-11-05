"""RSI(2) mean reversion on daily bars (Connors-style), with a bracket.

Long when the 2-day RSI is deeply oversold, short when deeply overbought, optionally only with the 200-day trend
(longs above the SMA, shorts below). Decided at the close, entered at the next open. Stop at `stop_atr` x ATR(14),
target at rr x risk, time exit after `max_hold` sessions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from tp import features
from tp.backtest import Signal
from tp.swing import decision_ts


@dataclass(frozen=True)
class RSI2Params:
    rsi_period: int = 2
    rsi_low: float = 10.0  # long when RSI <= rsi_low; short when RSI >= 100 - rsi_low
    trend_filter: str = "sma200"  # "none" or "sma200"
    sma_n: int = 200
    stop_atr: float = 2.0
    atr_n: int = 14
    rr: float = 1.5
    max_hold: int = 5
    sides: str = "both"
    min_risk_pct: float = 0.002  # skip stops tighter than 0.2% of price


class RSI2Reversion:
    name = "rsi2"
    params_cls = RSI2Params

    def __init__(self, **overrides):
        self.params = RSI2Params(**overrides)
        p = self.params
        if p.trend_filter not in ("none", "sma200"):
            raise ValueError(f"unknown trend_filter {p.trend_filter!r}")
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
        """bars: split-adjusted daily bars (UTC index). Everything below at row t uses data through t only."""
        p = self.params
        close = bars["close"]
        rsi = features.rsi(close, p.rsi_period)
        atr = features.atr_through(bars, p.atr_n)
        sma = close.rolling(p.sma_n).mean()
        long_ok = (rsi <= p.rsi_low) & atr.notna()
        short_ok = (rsi >= 100 - p.rsi_low) & atr.notna()
        if p.trend_filter == "sma200":
            long_ok &= close > sma
            short_ok &= close < sma
        if p.sides == "long":
            short_ok &= False
        elif p.sides == "short":
            long_ok &= False
        when = decision_ts(bars.index)
        signals = []
        for t in np.flatnonzero((long_ok | short_ok).to_numpy()):
            long = bool(long_ok.iloc[t])
            entry = float(close.iloc[t])
            stop = entry - p.stop_atr * float(atr.iloc[t]) if long else entry + p.stop_atr * float(atr.iloc[t])
            risk = abs(entry - stop)
            if stop <= 0 or risk < p.min_risk_pct * entry:
                continue
            signals.append(Signal.bracket(symbol, when[t], "long" if long else "short", entry, stop, p.rr, "rsi2", p.max_hold))
        return signals
