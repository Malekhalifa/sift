"""Supertrend + Waddah Attar Explosion, an NNFX-style stack (the "Algo Flex" bot of video 1).

Direction from Supertrend, confirmation from the Waddah Attar Explosion histogram being above both its explosion
line and its ATR dead zone. The signal is the FIRST bar on which both agree. Stop at `stop_atr` x ATR(14) from the
entry (the video uses 3.6), target rr x risk. An optional regime gate, as in the other bots of that video, needs
ADX >= 20 (a trend exists) or the Choppiness Index <= 50 (not a range) at the signal bar.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import time

import numpy as np
import pandas as pd

from tp import indicators as ind
from tp.backtest import Signal
from tp.bars import ET
from tp.strategies._memo import frame_key, memo


@dataclass(frozen=True)
class StackParams:
    st_period: int = 10
    st_mult: float = 3.0
    stop_atr: float = 3.6
    atr_n: int = 14
    gate: str = "none"  # "none", "adx20" or "chop50"
    rr: float = 1.5
    first_entry: str = "09:45"
    last_entry: str = "15:00"
    min_risk_pct: float = 0.001
    sides: str = "both"
    bar_minutes: int = 5


class SuperTrendWAE:
    name = "stack"
    params_cls = StackParams

    def __init__(self, **overrides):
        self.params = StackParams(**overrides)
        p = self.params
        if p.gate not in ("none", "adx20", "chop50"):
            raise ValueError(f"unknown gate {p.gate!r}")
        if p.sides not in ("long", "short", "both"):
            raise ValueError(f"unknown sides {p.sides!r}")

    def params_dict(self) -> dict:
        return asdict(self.params)

    @staticmethod
    def canonical(overrides: dict) -> dict:
        return dict(overrides)

    def generate(self, symbol: str, bars: pd.DataFrame, daily=None, spy_daily=None) -> list[Signal]:
        p = self.params
        fk = frame_key(symbol, bars)
        close = bars["close"]
        trend = memo((*fk, "st", p.st_period, p.st_mult), lambda: ind.supertrend(bars, p.st_period, p.st_mult))
        wae = memo((*fk, "wae"), lambda: ind.waddah_attar(close, bars))
        atr = memo((*fk, "atr", p.atr_n), lambda: ind.atr(bars, p.atr_n)).to_numpy()
        long_c = ((trend > 0) & wae["long_ok"]).to_numpy()
        short_c = ((trend < 0) & wae["short_ok"]).to_numpy()
        if p.gate == "adx20":
            gate = (memo((*fk, "adx"), lambda: ind.adx(bars, 14)) >= 20).to_numpy()
        elif p.gate == "chop50":
            gate = (memo((*fk, "chop"), lambda: ind.choppiness(bars, 14)) <= 50).to_numpy()
        else:
            gate = np.ones(len(bars), bool)
        fresh_long = long_c & ~np.concatenate([[False], long_c[:-1]]) & gate & (p.sides in ("long", "both"))
        fresh_short = short_c & ~np.concatenate([[False], short_c[:-1]]) & gate & (p.sides in ("short", "both"))

        local = bars.index.tz_convert(ET)
        decision = np.asarray(local.hour * 60 + local.minute) + p.bar_minutes
        f, l = time.fromisoformat(p.first_entry), time.fromisoformat(p.last_entry)
        in_window = (decision >= f.hour * 60 + f.minute) & (decision <= l.hour * 60 + l.minute)
        bar = pd.Timedelta(minutes=p.bar_minutes)
        c = close.to_numpy()
        signals = []
        for t in np.flatnonzero((fresh_long | fresh_short) & in_window):
            long = bool(fresh_long[t])
            if not np.isfinite(atr[t]):
                continue
            entry = float(c[t])
            stop = entry - p.stop_atr * atr[t] if long else entry + p.stop_atr * atr[t]
            if stop <= 0 or abs(entry - stop) < p.min_risk_pct * entry:
                continue
            signals.append(Signal.bracket(symbol, bars.index[t] + bar, "long" if long else "short", entry, float(stop), p.rr, "stack"))
        return signals
