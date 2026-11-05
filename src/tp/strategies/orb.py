"""Opening-range breakout.

The opening range is the high/low of the first `or_minutes` of the regular session. The first bar that CLOSES
outside it gives the signal (wicks do not count). One signal per symbol per day, taken only if the day passes
the shared filters (relative volume, gap, trend) at the moment the breakout bar closes.
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
class ORBParams(FilterParams):
    or_minutes: int = 5
    rr: float = 1.5
    stop_mode: str = "or_opposite"  # "or_opposite" = other side of the range, "atr" = atr_mult x daily ATR(14)
    atr_mult: float = 0.5  # only used when stop_mode == "atr"
    last_entry: str = "11:00"  # ET; ignore breakouts whose bar closes after this time
    min_risk_pct: float = 0.001  # skip tiny stops (< 0.1% of price): slippage would dominate
    sides: str = "both"  # "long", "short" or "both"
    bar_minutes: int = 5


class OpeningRangeBreakout:
    name = "orb"
    params_cls = ORBParams

    def __init__(self, **overrides):
        self.params = ORBParams(**overrides)
        p = self.params
        if p.or_minutes % p.bar_minutes:
            raise ValueError("or_minutes must be a multiple of bar_minutes")
        if p.stop_mode not in ("or_opposite", "atr"):
            raise ValueError(f"unknown stop_mode {p.stop_mode!r}")
        if p.sides not in ("long", "short", "both"):
            raise ValueError(f"unknown sides {p.sides!r}")

    def params_dict(self) -> dict:
        return asdict(self.params)

    @staticmethod
    def canonical(overrides: dict) -> dict:
        """Drop parameters that cannot change the result, so equivalent grid points dedupe."""
        out = dict(overrides)
        if out.get("stop_mode", "or_opposite") == "or_opposite":
            out.pop("atr_mult", None)
        return out

    def generate(
        self,
        symbol: str,
        bars: pd.DataFrame,
        daily: pd.DataFrame | None = None,
        spy_daily: pd.DataFrame | None = None,
    ) -> list[Signal]:
        """bars: regular-hours bars at `bar_minutes` resolution, UTC index of bar opens, split-adjusted."""
        p = self.params
        bar = pd.Timedelta(minutes=p.bar_minutes)
        or_bars = p.or_minutes // p.bar_minutes
        last_entry = time.fromisoformat(p.last_entry)
        atr = features.daily_atr(daily) if p.stop_mode == "atr" and daily is not None else None
        ctx = SessionContext(bars, daily, spy_daily, p)

        local = bars.index.tz_convert(ET)
        day_key = np.asarray(local.year * 10_000 + local.month * 100 + local.day)
        mod = np.asarray(local.hour * 60 + local.minute)
        signals: list[Signal] = []
        for _, pos in bars.groupby(day_key).indices.items():
            if len(pos) <= or_bars or mod[pos[0]] != 9 * 60 + 30:
                continue  # no session open captured, or nothing after the range
            if mod[pos[or_bars - 1]] != 9 * 60 + 30 + p.or_minutes - p.bar_minutes:
                continue  # missing bars inside the opening range
            g = bars.iloc[pos]
            or_high, or_low = g["high"].iloc[:or_bars].max(), g["low"].iloc[:or_bars].min()
            rest = g.iloc[or_bars:]
            close = rest["close"].to_numpy()
            up = np.flatnonzero(close > or_high) if p.sides in ("long", "both") else np.array([], dtype=int)
            dn = np.flatnonzero(close < or_low) if p.sides in ("short", "both") else np.array([], dtype=int)
            if not len(up) and not len(dn):
                continue
            k_up = up[0] if len(up) else np.inf
            k_dn = dn[0] if len(dn) else np.inf
            long = k_up < k_dn
            k = int(k_up if long else k_dn)

            ts = rest.index[k] + bar  # decision time: the breakout bar has just closed
            ts_local = ts.tz_convert(ET)
            if ts_local.time() > last_entry:
                continue
            day_ts = pd.Timestamp(ts_local.date())
            side = "long" if long else "short"
            if not ctx.allows(side, day_ts, int(mod[pos[or_bars + k]])):
                continue
            entry_ref = float(close[k])
            if p.stop_mode == "or_opposite":
                stop = float(or_low if long else or_high)
            else:
                a = atr.get(day_ts, np.nan) if atr is not None else np.nan
                if not np.isfinite(a):
                    continue
                stop = entry_ref - p.atr_mult * a if long else entry_ref + p.atr_mult * a
            risk = abs(entry_ref - stop)
            wrong_side = stop >= entry_ref if long else stop <= entry_ref
            if wrong_side or risk < p.min_risk_pct * entry_ref:
                continue
            signals.append(Signal.bracket(symbol, ts, side, entry_ref, stop, p.rr, tag="orb"))
        return signals
