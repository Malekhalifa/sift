"""Two volume-conditioned daily strategies (docs/m11-volume-protocol.md, hypotheses H1 and H2 of docs/ideas/candle-strategies.md).

volrev: a stock that fell against the market over five sessions on falling volume tends to bounce (and the reverse
for a rise), as a payment for providing liquidity to impatient traders.

volspike: a stock whose volume is the highest of the last `window` sessions tends to drift up over the next weeks as
inattentive buyers arrive. Long only.

Both decide at the close of session t using data through t, enter at the next open, and bracket with a stop at
`stop_atr` x ATR(14), a 1.5R target and a time exit after `max_hold` sessions. A parameter value of 0.0 for the volume
or return cap means that condition is off.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from tp import features
from tp.backtest import Signal
from tp.swing import decision_ts


def _signals(symbol, bars, long_ok, short_ok, atr, stop_atr, rr, max_hold, min_risk_pct, tag) -> list[Signal]:
    close = bars["close"]
    when = decision_ts(bars.index)
    out = []
    for t in np.flatnonzero((long_ok | short_ok).to_numpy()):
        long = bool(long_ok.iloc[t])
        entry = float(close.iloc[t])
        stop = entry - stop_atr * float(atr.iloc[t]) if long else entry + stop_atr * float(atr.iloc[t])
        if stop <= 0 or abs(entry - stop) < min_risk_pct * entry:
            continue
        out.append(Signal.bracket(symbol, when[t], "long" if long else "short", entry, stop, rr, tag, max_hold))
    return out


@dataclass(frozen=True)
class VolRevParams:
    mult: float = 2.0  # the 5-session return against SPY must be at least this many daily ranges (ATR as % of price)
    vol_max: float = 0.0  # last week's volume over the prior four weeks' must be at most this (0 = no volume condition)
    lag: int = 5
    vol_fast: int = 5
    vol_base: int = 20
    stop_atr: float = 2.0
    atr_n: int = 14
    rr: float = 1.5
    max_hold: int = 5
    min_risk_pct: float = 0.002


class VolumeReversal:
    name = "volrev"
    params_cls = VolRevParams

    def __init__(self, **overrides):
        self.params = VolRevParams(**overrides)
        if self.params.mult <= 0 or self.params.max_hold < 1:
            raise ValueError("mult must be positive and max_hold >= 1")

    def params_dict(self) -> dict:
        return asdict(self.params)

    @staticmethod
    def canonical(overrides: dict) -> dict:
        return dict(overrides)

    def generate(self, symbol: str, bars: pd.DataFrame, daily=None, spy_daily=None) -> list[Signal]:
        if spy_daily is None or spy_daily.empty:
            raise ValueError("volrev measures the move against SPY and needs its daily bars")
        p = self.params
        close, volume = bars["close"], bars["volume"].astype("float64")
        spy = pd.Series(spy_daily["close"].to_numpy(), index=features.session_dates(spy_daily.index))
        spy = pd.Series(spy.reindex(features.session_dates(bars.index)).to_numpy(), index=bars.index)
        ex = close.pct_change(p.lag, fill_method=None) - spy.pct_change(p.lag, fill_method=None)
        atr = features.atr_through(bars, p.atr_n)
        atrp = atr / close
        vr = volume.rolling(p.vol_fast).mean() / volume.shift(p.vol_fast).rolling(p.vol_base).mean()
        quiet = (vr <= p.vol_max) if p.vol_max > 0 else pd.Series(True, index=bars.index)
        ok = atr.notna() & ex.notna() & quiet
        return _signals(symbol, bars, ok & (ex <= -p.mult * atrp), ok & (ex >= p.mult * atrp), atr,
                        p.stop_atr, p.rr, p.max_hold, p.min_risk_pct, "volrev")


@dataclass(frozen=True)
class VolSpikeParams:
    window: int = 20  # today's volume must be the highest of this many sessions, today included
    ret_max: float = 0.0  # today's absolute return must be at most this many daily ranges (0 = no cap)
    stop_atr: float = 2.0
    atr_n: int = 14
    rr: float = 1.5
    max_hold: int = 10
    min_risk_pct: float = 0.002


class VolumeSpike:
    name = "volspike"
    params_cls = VolSpikeParams

    def __init__(self, **overrides):
        self.params = VolSpikeParams(**overrides)
        if self.params.window < 2 or self.params.max_hold < 1:
            raise ValueError("window must be >= 2 and max_hold >= 1")

    def params_dict(self) -> dict:
        return asdict(self.params)

    @staticmethod
    def canonical(overrides: dict) -> dict:
        return dict(overrides)

    def generate(self, symbol: str, bars: pd.DataFrame, daily=None, spy_daily=None) -> list[Signal]:
        p = self.params
        close, volume = bars["close"], bars["volume"].astype("float64")
        atr = features.atr_through(bars, p.atr_n)
        prior_high = volume.shift(1).rolling(p.window - 1).max()
        top = volume > prior_high  # strictly the highest of the window: ties on flat volume do not count
        ordinary = ((close / close.shift(1) - 1).abs() <= p.ret_max * atr / close) if p.ret_max > 0 else pd.Series(True, index=bars.index)
        long_ok = top & ordinary & atr.notna() & prior_high.notna()
        return _signals(symbol, bars, long_ok, long_ok & False, atr, p.stop_atr, p.rr, p.max_hold, p.min_risk_pct, "volspike")
