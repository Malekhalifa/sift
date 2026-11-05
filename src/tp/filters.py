"""Entry filters shared by the strategies: relative volume, opening gap, trend regime.

Each strategy decides *when* to trigger; this decides whether the day qualifies. All inputs are known at the
decision time (see tp.features), so filtering cannot leak the future.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tp import features


@dataclass(frozen=True)
class FilterParams:
    rvol_min: float = 0.0  # 0 = off. Cumulative volume vs the same time over the prior `rvol_window` sessions
    rvol_window: int = 14
    min_abs_gap_pct: float = 0.0  # 0 = off. Require an opening gap of at least this many percent either way
    gap_align: bool = False  # trade only in the direction of the opening gap
    trend_filter: str = "none"  # "none", "own_sma" (the stock) or "spy_sma" (the market)
    trend_sma: int = 200


class SessionContext:
    """Per-symbol lookup of everything a filter needs. Build once per (symbol, params)."""

    def __init__(self, bars: pd.DataFrame, daily: pd.DataFrame | None, spy_daily: pd.DataFrame | None, fp: FilterParams):
        if fp.trend_filter not in ("none", "own_sma", "spy_sma"):
            raise ValueError(f"unknown trend_filter {fp.trend_filter!r}")
        self.fp = fp
        self.rvol = features.intraday_rvol(bars, fp.rvol_window) if fp.rvol_min > 0 else None
        self.gap = features.session_gap_pct(bars) if (fp.min_abs_gap_pct > 0 or fp.gap_align) else None
        self.trend = None
        if fp.trend_filter != "none":
            source = daily if fp.trend_filter == "own_sma" else spy_daily
            if source is None:
                raise ValueError(f"trend_filter={fp.trend_filter!r} needs the matching daily bars")
            self.trend = features.sma_trend(source, fp.trend_sma)

    def allows(self, side: str, day: pd.Timestamp, bar_minute: int) -> bool:
        """day: naive ET midnight of the session; bar_minute: ET minute of day at the signal bar's open."""
        fp = self.fp
        if self.rvol is not None:
            try:
                r = self.rvol.at[day, bar_minute]
            except KeyError:
                return False
            if not np.isfinite(r) or r < fp.rvol_min:
                return False
        if self.gap is not None:
            g = self.gap.get(day, np.nan)
            if not np.isfinite(g) or abs(g) < fp.min_abs_gap_pct:
                return False
            if fp.gap_align and (g <= 0 if side == "long" else g >= 0):
                return False
        if self.trend is not None:
            d = self.trend.get(day, 0.0)
            if (d <= 0) if side == "long" else (d >= 0):
                return False
        return True
