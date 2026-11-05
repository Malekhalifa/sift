"""Features derived from bars. Every value is known BEFORE the session it is attached to (no look-ahead)."""

from __future__ import annotations

import numpy as np
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


def intraday_rvol(bars: pd.DataFrame, window: int = 14, min_days: int = 10) -> pd.DataFrame:
    """Relative volume by session date (rows) and bar-open minute of day (columns).

    Value = cumulative session volume through that bar (inclusive, so known when the bar closes) divided by the
    average of the same quantity over the previous `window` sessions. Today never enters its own baseline.
    Being a ratio it is scale-free, so it behaves the same on IEX (~4% of volume) and SIP data.
    """
    local = bars.index.tz_convert(ET)
    day = local.tz_localize(None).normalize()
    mod = np.asarray(local.hour * 60 + local.minute)
    vol = pd.Series(bars["volume"].to_numpy(dtype=float), index=pd.MultiIndex.from_arrays([day, mod]))
    wide = vol.groupby(level=[0, 1]).sum().unstack()
    cum = wide.fillna(0.0).cumsum(axis=1)  # a bar with no trades adds nothing
    baseline = cum.shift(1).rolling(window, min_periods=min(min_days, window)).mean()
    return cum / baseline.where(baseline > 0)


def session_gap_pct(bars: pd.DataFrame) -> pd.Series:
    """Opening gap in percent: first regular-session open vs the previous session's last close. NaN if the
    09:30 bar is missing. Known at 09:30, so usable for any later decision that day."""
    local = bars.index.tz_convert(ET)
    day = local.tz_localize(None).normalize()
    mod = np.asarray(local.hour * 60 + local.minute)
    frame = pd.DataFrame({"open": bars["open"].to_numpy(), "close": bars["close"].to_numpy(), "mod": mod}, index=day)
    g = frame.groupby(level=0)
    first_open = g["open"].first().where(g["mod"].first() == 9 * 60 + 30)
    prev_close = g["close"].last().shift(1)
    return 100 * (first_open / prev_close - 1)


def sma_trend(daily: pd.DataFrame, n: int = 200) -> pd.Series:
    """+1 / -1 / 0 by session date: whether the PREVIOUS session closed above / below its n-day SMA
    (0 while there is not enough history). Usable from that next session's open."""
    close = daily["close"]
    sma = close.rolling(n).mean()
    direction = pd.Series(np.sign((close - sma).to_numpy()), index=daily.index).fillna(0.0).shift(1).fillna(0.0)
    direction.index = session_dates(daily.index)
    return direction
