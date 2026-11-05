"""Opening-range failed breakout (fade).

Adapted from the 4H-range idea for stocks, which have a real open: the range is the first `or_minutes` of the
regular session. A bar that CLOSES outside it starts an excursion; a later bar that closes back inside (same
day) is the signal to fade it. A failed move up is a short, a failed move down is a long. The stop sits at the
extreme of the excursion (including the re-entry bar's own wick), the target is rr x risk.

Excursions that need a stop wider than `max_risk_atr` x daily ATR are skipped: a 1.5R target that far away
rarely fills before the close. Shares the relative-volume, gap and trend filters with the breakout.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import time

import numpy as np
import pandas as pd

from tp import features
from tp.backtest import Signal
from tp.bars import ET
from tp.filters import FilterParams, SessionContext


@dataclass(frozen=True)
class FadeParams(FilterParams):
    or_minutes: int = 5
    rr: float = 1.5
    last_entry: str = "11:30"  # ET; ignore re-entries whose bar closes after this time
    max_per_day: int = 1  # failed breakouts taken per symbol per day
    min_risk_pct: float = 0.001  # skip tiny stops (< 0.1% of price)
    max_risk_atr: float = 0.5  # 0 = off. Skip if the stop is further than this many daily ATRs
    sides: str = "both"  # trade direction: "long", "short" or "both"
    bar_minutes: int = 5


class FailedBreakoutFade:
    name = "fade"
    params_cls = FadeParams

    def __init__(self, **overrides):
        self.params = FadeParams(**overrides)
        p = self.params
        if p.or_minutes % p.bar_minutes:
            raise ValueError("or_minutes must be a multiple of bar_minutes")
        if p.sides not in ("long", "short", "both"):
            raise ValueError(f"unknown sides {p.sides!r}")
        if p.max_per_day < 1:
            raise ValueError("max_per_day must be >= 1")

    def params_dict(self) -> dict:
        return asdict(self.params)

    @staticmethod
    def canonical(overrides: dict) -> dict:
        return dict(overrides)

    def generate(
        self,
        symbol: str,
        bars: pd.DataFrame,
        daily: pd.DataFrame | None = None,
        spy_daily: pd.DataFrame | None = None,
    ) -> list[Signal]:
        p = self.params
        bar = pd.Timedelta(minutes=p.bar_minutes)
        or_bars = p.or_minutes // p.bar_minutes
        last_entry = time.fromisoformat(p.last_entry)
        atr = features.daily_atr(daily) if p.max_risk_atr > 0 and daily is not None else None
        ctx = SessionContext(bars, daily, spy_daily, p)

        local = bars.index.tz_convert(ET)
        day_key = np.asarray(local.year * 10_000 + local.month * 100 + local.day)
        mod = np.asarray(local.hour * 60 + local.minute)
        signals: list[Signal] = []
        for _, pos in bars.groupby(day_key).indices.items():
            if len(pos) <= or_bars or mod[pos[0]] != 9 * 60 + 30:
                continue
            if mod[pos[or_bars - 1]] != 9 * 60 + 30 + p.or_minutes - p.bar_minutes:
                continue
            g = bars.iloc[pos]
            or_high, or_low = g["high"].iloc[:or_bars].max(), g["low"].iloc[:or_bars].min()
            hi, lo, cl = g["high"].to_numpy(), g["low"].to_numpy(), g["close"].to_numpy()
            idx = g.index
            day_ts = pd.Timestamp(idx[0].tz_convert(ET).date())
            day_atr = atr.get(day_ts, np.nan) if atr is not None else np.nan

            state, extreme, taken = 0, 0.0, 0  # state: +1 excursion above the range, -1 below, 0 none
            for k in range(or_bars, len(g)):
                ts = idx[k] + bar  # decision time: bar k has just closed
                if ts.tz_convert(ET).time() > last_entry:
                    break
                c = cl[k]
                signal_side = None
                if state == 0:
                    if c > or_high:
                        state, extreme = 1, hi[k]
                    elif c < or_low:
                        state, extreme = -1, lo[k]
                elif state == 1:
                    extreme = max(extreme, hi[k])
                    if c < or_low:  # went straight through the whole range: a breakdown, not a failed move up
                        state, extreme = -1, lo[k]
                    elif c <= or_high:  # back inside the range
                        signal_side, stop, state = "short", extreme, 0
                else:
                    extreme = min(extreme, lo[k])
                    if c > or_high:
                        state, extreme = 1, hi[k]
                    elif c >= or_low:
                        signal_side, stop, state = "long", extreme, 0
                if signal_side is None:
                    continue
                if p.sides not in (signal_side, "both") or not ctx.allows(signal_side, day_ts, int(mod[pos[k]])):
                    continue
                risk = abs(c - stop)
                too_wide = p.max_risk_atr > 0 and (not np.isfinite(day_atr) or risk > p.max_risk_atr * day_atr)
                if risk < p.min_risk_pct * c or too_wide:
                    continue
                signals.append(Signal.bracket(symbol, ts, signal_side, float(c), float(stop), p.rr, tag="fade"))
                taken += 1
                if taken >= p.max_per_day:
                    break
        return signals
