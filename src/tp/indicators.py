"""Technical indicators from their published definitions, for the strategies taken from the TradingView videos.

Every value at row t uses bars up to and including t only (checked by tests), so a signal read at a bar's close is
legitimate. Formulas follow the common open-source TradingView (Pine) versions:

  * UT Bot Alerts: ATR trailing stop that ratchets with price and flips when price crosses it (QuantNomad/HPotter).
  * Supertrend: ATR bands around (high+low)/2 that ratchet, direction flips on a close through the opposite band.
  * Schaff Trend Cycle: MACD run through a double stochastic and smoothing (Doug Schaff; LazyBear's implementation).
  * Waddah Attar Explosion: MACD momentum against a Bollinger-width "explosion" line and an ATR dead zone (LazyBear).
  * ADX (Wilder) and the Choppiness Index (E. W. Dreiss).

ATR uses Wilder's smoothing (alpha = 1/n). It is seeded from the first value rather than an SMA, which only matters
for the first few n bars.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def rma(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    prev = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return rma(true_range(df), n)


def ut_bot(close: pd.Series, atr_values: pd.Series, key: float) -> pd.DataFrame:
    """UT Bot: columns stop (the trailing stop), buy and sell (True on the bar price crosses it)."""
    c, loss = close.to_numpy(float), (key * atr_values).to_numpy(float)
    n = len(c)
    stop = np.zeros(n)
    for t in range(1, n):
        if np.isnan(loss[t]):
            stop[t] = 0.0
            continue
        prev = stop[t - 1]
        if c[t] > prev and c[t - 1] > prev:
            stop[t] = max(prev, c[t] - loss[t])
        elif c[t] < prev and c[t - 1] < prev:
            stop[t] = min(prev, c[t] + loss[t])
        elif c[t] > prev:
            stop[t] = c[t] - loss[t]
        else:
            stop[t] = c[t] + loss[t]
    prev_c, prev_stop = np.roll(c, 1), np.roll(stop, 1)
    valid = ~np.isnan(loss) & (stop != 0) & (prev_stop != 0)
    valid[0] = False
    buy = valid & (c > stop) & (prev_c <= prev_stop)
    sell = valid & (c < stop) & (prev_c >= prev_stop)
    return pd.DataFrame({"stop": stop, "buy": buy, "sell": sell}, index=close.index)


def supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0) -> pd.Series:
    """+1 while in an uptrend, -1 in a downtrend (0 until the ATR exists)."""
    a = atr(df, period).to_numpy(float)
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy(float)
    c = df["close"].to_numpy(float)
    n = len(c)
    up, dn, trend = np.full(n, np.nan), np.full(n, np.nan), np.zeros(n)
    for t in range(n):
        if np.isnan(a[t]):
            continue
        u, d = hl2[t] - mult * a[t], hl2[t] + mult * a[t]
        if t > 0 and not np.isnan(up[t - 1]):
            u = max(u, up[t - 1]) if c[t - 1] > up[t - 1] else u
            d = min(d, dn[t - 1]) if c[t - 1] < dn[t - 1] else d
            trend[t] = trend[t - 1]
            if trend[t - 1] <= 0 and c[t] > dn[t - 1]:
                trend[t] = 1
            elif trend[t - 1] >= 0 and c[t] < up[t - 1]:
                trend[t] = -1
        else:
            trend[t] = 1
        up[t], dn[t] = u, d
    return pd.Series(trend, index=df.index)


def schaff_trend_cycle(close: pd.Series, length: int = 10, fast: int = 23, slow: int = 50, factor: float = 0.5) -> pd.Series:
    """STC in 0-100: MACD -> stochastic -> smooth -> stochastic -> smooth."""
    macd = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()

    def stoch_smooth(x: pd.Series) -> pd.Series:
        lo, hi = x.rolling(length).min(), x.rolling(length).max()
        span = (hi - lo).to_numpy(float)
        raw = np.where(span > 0, (x.to_numpy(float) - lo.to_numpy(float)) / np.where(span > 0, span, 1) * 100, np.nan)
        out = np.full(len(x), np.nan)
        for t in range(len(x)):
            r = raw[t]
            if np.isnan(r):
                r = out[t - 1] if t > 0 and not np.isnan(out[t - 1]) else np.nan  # carry the last value through a flat window
            if np.isnan(r):
                continue
            out[t] = r if t == 0 or np.isnan(out[t - 1]) else out[t - 1] + factor * (r - out[t - 1])
        return pd.Series(out, index=x.index)

    return stoch_smooth(stoch_smooth(macd))


def waddah_attar(close: pd.Series, df: pd.DataFrame, fast: int = 20, slow: int = 40, sensitivity: float = 150.0,
                 bb_len: int = 20, bb_mult: float = 2.0, dz_len: int = 100, dz_mult: float = 3.7) -> pd.DataFrame:
    """Waddah Attar Explosion: columns up and down (momentum histogram), explosion (Bollinger width), dead_zone,
    long_ok and short_ok (histogram above both the explosion line and the dead zone)."""
    macd = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    t1 = (macd - macd.shift(1)) * sensitivity
    sd = close.rolling(bb_len).std(ddof=0)
    explosion = 2 * bb_mult * sd  # upper band minus lower band
    dead = rma(true_range(df), dz_len) * dz_mult
    up, down = t1.clip(lower=0), (-t1).clip(lower=0)
    return pd.DataFrame({"up": up, "down": down, "explosion": explosion, "dead_zone": dead,
                         "long_ok": (up > explosion) & (up > dead), "short_ok": (down > explosion) & (down > dead)})


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up, down = df["high"].diff(), -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr_n = rma(true_range(df), n)
    plus_di = 100 * rma(pd.Series(plus_dm, index=df.index), n) / tr_n
    minus_di = 100 * rma(pd.Series(minus_dm, index=df.index), n) / tr_n
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return rma(dx.fillna(0.0), n)


def choppiness(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """100 means a choppy range, low values a clean trend."""
    span = df["high"].rolling(n).max() - df["low"].rolling(n).min()
    return 100 * np.log10(true_range(df).rolling(n).sum() / span.replace(0, np.nan)) / np.log10(n)
