"""Features derived from bars. Every value is known BEFORE the session it is attached to (no look-ahead)."""

from __future__ import annotations

import pandas as pd

from tp.bars import ET


def session_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """ET calendar date of each timestamp, as naive midnight timestamps."""
    return index.tz_convert(ET).tz_localize(None).normalize()


def daily_atr(daily: pd.DataFrame, n: int = 14) -> pd.Series:
    """ATR(n) in price units, indexed by session date. The value on date D uses sessions up to D-1 only."""
    prev_close = daily["close"].shift(1)
    tr = pd.concat(
        [daily["high"] - daily["low"], (daily["high"] - prev_close).abs(), (daily["low"] - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.rolling(n).mean().shift(1)
    atr.index = session_dates(daily.index)
    return atr
