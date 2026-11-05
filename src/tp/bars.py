"""Bar loading for research: split adjustment, regular-hours filter, resampling.

Bar timestamps are the bar's open time (UTC). The store is raw; everything here is derived at read time.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from tp import corp_actions, store

ET = ZoneInfo("America/New_York")
PRICE_COLS = ["open", "high", "low", "close", "vwap"]


def rth_mask(index: pd.DatetimeIndex) -> np.ndarray:
    """True for bars opening in the regular session, 09:30 <= t < 16:00 ET."""
    local = index.tz_convert(ET)
    minutes = local.hour * 60 + local.minute
    return np.asarray((minutes >= 9 * 60 + 30) & (minutes < 16 * 60))


def split_factor(index: pd.DatetimeIndex, splits: pd.DataFrame) -> np.ndarray:
    """Cumulative split ratio still ahead of each bar: bars before an ex-date carry that split's ratio."""
    local_day = index.tz_convert(ET).tz_localize(None).normalize()
    factor = np.ones(len(index))
    for ex_date, ratio in zip(splits["ex_date"], splits["ratio"], strict=True):
        factor[np.asarray(local_day < ex_date)] *= ratio
    return factor


def adjust_splits(df: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    if df.empty or splits.empty:
        return df
    f = split_factor(df.index, splits)
    out = df.copy()
    out[PRICE_COLS] = out[PRICE_COLS].div(f, axis=0)
    out["volume"] = np.rint(out["volume"].to_numpy() * f).astype("int64")
    return out


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate to coarser bars. Supports rules that divide an hour (5min, 15min, 30min, 60min);
    buckets align to :00/:30 so a 60min rule gives 09:30-10:30, ... in ET."""
    if df.empty:
        return df
    work = df.assign(pv=df["vwap"] * df["volume"])
    g = work.resample(rule, offset="30min")
    out = pd.DataFrame(
        {
            "open": g["open"].first(),
            "high": g["high"].max(),
            "low": g["low"].min(),
            "close": g["close"].last(),
            "volume": g["volume"].sum(),
            "trade_count": g["trade_count"].sum(),
            "pv": g["pv"].sum(),
        }
    ).dropna(subset=["open"])
    out["vwap"] = out.pop("pv") / out["volume"]
    out.index.name = "ts"
    return out[store.COLUMNS].astype(store.DTYPES)


def load_bars(
    symbol: str,
    feed: str = "sip",
    timeframe: str = "1Min",
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    adjusted: bool = True,
    rth: bool = False,
    resample: str | None = None,
) -> pd.DataFrame:
    df = store.load_raw(feed, timeframe, symbol, start, end)
    if adjusted:
        df = adjust_splits(df, corp_actions.load_splits(symbol))
    if rth and timeframe != "1Day" and not df.empty:
        df = df[rth_mask(df.index)]
    if resample:
        df = resample_ohlcv(df, resample)
    return df
