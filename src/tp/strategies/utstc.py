"""UT Bot Alerts with an optional Schaff Trend Cycle confirmation (video 4 of the original list).

UT Bot is an ATR trailing stop that flips when price crosses it. A buy is price crossing above the stop, a sell is
price crossing below it. The video runs two copies with different ATR periods for longs and shorts, so the long and
short settings are separate parameters here. Optional STC confirmation: a long needs STC below its lower band and
rising, a short needs STC above its upper band and falling ("strict": 25/75; "loose": the 50 line). Stop beyond the
recent swing low or high, target rr x risk, flat by the engine's close. Entries only between `first_entry` and
`last_entry` (decision time, ET); the indicators run continuously across sessions.
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
class UTSTCParams:
    key_long: float = 1.0
    atr_long: int = 10
    key_short: float = 1.0
    atr_short: int = 10
    stc_mode: str = "off"  # "off", "strict" (long below 25, short above 75) or "loose" (below / above 50)
    swing_n: int = 5  # stop sits beyond the lowest low / highest high of this many bars
    rr: float = 1.5
    first_entry: str = "09:45"
    last_entry: str = "15:00"
    min_risk_pct: float = 0.001
    sides: str = "both"
    bar_minutes: int = 5


class UTBotSTC:
    name = "utstc"
    params_cls = UTSTCParams

    def __init__(self, **overrides):
        self.params = UTSTCParams(**overrides)
        p = self.params
        if p.stc_mode not in ("off", "strict", "loose"):
            raise ValueError(f"unknown stc_mode {p.stc_mode!r}")
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

        def ut(key: float, n: int) -> pd.DataFrame:
            return memo((*fk, "ut", key, n), lambda: ind.ut_bot(close, memo((*fk, "atr", n), lambda: ind.atr(bars, n)), key))

        buy = ut(p.key_long, p.atr_long)["buy"].to_numpy()
        sell = ut(p.key_short, p.atr_short)["sell"].to_numpy()
        long_ok = np.ones(len(bars), bool)
        short_ok = np.ones(len(bars), bool)
        if p.stc_mode != "off":
            stc = memo((*fk, "stc"), lambda: ind.schaff_trend_cycle(close))
            lo, hi = (25.0, 75.0) if p.stc_mode == "strict" else (50.0, 50.0)
            long_ok = ((stc < lo) & (stc > stc.shift(1))).to_numpy()
            short_ok = ((stc > hi) & (stc < stc.shift(1))).to_numpy()
        want_long = buy & long_ok & (p.sides in ("long", "both"))
        want_short = sell & short_ok & (p.sides in ("short", "both"))
        swing_lo = bars["low"].rolling(p.swing_n).min().to_numpy()
        swing_hi = bars["high"].rolling(p.swing_n).max().to_numpy()

        local = bars.index.tz_convert(ET)
        decision = np.asarray(local.hour * 60 + local.minute) + p.bar_minutes
        f, l = time.fromisoformat(p.first_entry), time.fromisoformat(p.last_entry)
        in_window = (decision >= f.hour * 60 + f.minute) & (decision <= l.hour * 60 + l.minute)
        bar = pd.Timedelta(minutes=p.bar_minutes)
        c = close.to_numpy()
        signals = []
        for t in np.flatnonzero((want_long | want_short) & in_window):
            long = bool(want_long[t])
            entry, stop = float(c[t]), float(swing_lo[t] if long else swing_hi[t])
            if not np.isfinite(stop) or (stop >= entry if long else stop <= entry) or abs(entry - stop) < p.min_risk_pct * entry:
                continue
            signals.append(Signal.bracket(symbol, bars.index[t] + bar, "long" if long else "short", entry, stop, p.rr, "utstc"))
        return signals
