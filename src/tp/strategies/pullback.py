"""20/200-day moving-average pullback on daily bars, with a bracket.

Uptrend: the 20-day SMA is above the 200-day, rising over `slope_days`, and the close is above the 200-day.
The signal is the first close back to the 20-day SMA (within `touch_atr` ATRs above it) after a close above it.
Downtrend mirrors that for shorts. Decided at the close, entered at the next open.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from tp import features
from tp.backtest import Signal
from tp.swing import decision_ts


@dataclass(frozen=True)
class PullbackParams:
    sma_fast: int = 20
    sma_slow: int = 200
    slope_days: int = 5
    touch_atr: float = 0.0  # how far above the fast SMA still counts as touching it, in ATRs
    stop_atr: float = 2.0
    atr_n: int = 14
    rr: float = 1.5
    max_hold: int = 10
    sides: str = "both"
    min_risk_pct: float = 0.002


class MAPullback:
    name = "pullback"
    params_cls = PullbackParams

    def __init__(self, **overrides):
        self.params = PullbackParams(**overrides)
        p = self.params
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
        p = self.params
        close = bars["close"]
        fast, slow = close.rolling(p.sma_fast).mean(), close.rolling(p.sma_slow).mean()
        atr = features.atr_through(bars, p.atr_n)
        band_up = fast + p.touch_atr * atr  # touching the average from above
        band_dn = fast - p.touch_atr * atr  # touching it from below
        up_trend = (fast > slow) & (fast > fast.shift(p.slope_days)) & (close > slow)
        down_trend = (fast < slow) & (fast < fast.shift(p.slope_days)) & (close < slow)
        long_ok = up_trend & (close <= band_up) & (close.shift(1) > band_up.shift(1)) & atr.notna()
        short_ok = down_trend & (close >= band_dn) & (close.shift(1) < band_dn.shift(1)) & atr.notna()
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
            signals.append(Signal.bracket(symbol, when[t], "long" if long else "short", entry, stop, p.rr, "pullback", p.max_hold))
        return signals
