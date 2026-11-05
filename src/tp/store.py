"""Parquet bar store: data/bars/<feed>/<timeframe>/<symbol>/<utc year>.parquet, raw (unadjusted) prices.

Writes are idempotent: re-fetching a range replaces overlapping bars (newer fetch wins).
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from tp import config

COLUMNS = ["open", "high", "low", "close", "volume", "trade_count", "vwap"]
API_RENAME = {"t": "ts", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "n": "trade_count", "vw": "vwap"}
DTYPES = {
    "open": "float64",
    "high": "float64",
    "low": "float64",
    "close": "float64",
    "volume": "int64",
    "trade_count": "int64",
    "vwap": "float64",
}


def symbol_dir(feed: str, timeframe: str, symbol: str) -> Path:
    return config.DATA_DIR / "bars" / feed / timeframe / symbol


def year_path(feed: str, timeframe: str, symbol: str, year: int) -> Path:
    return symbol_dir(feed, timeframe, symbol) / f"{year}.parquet"


def empty_frame() -> pd.DataFrame:
    idx = pd.DatetimeIndex([], tz="UTC", name="ts").as_unit("ns")
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in DTYPES.items()}, index=idx)


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.index = df.index.as_unit("ns")
    df.index.name = "ts"
    return df[COLUMNS].astype(DTYPES)


def frame_from_api(bars: list[dict]) -> pd.DataFrame:
    if not bars:
        return empty_frame()
    df = pd.DataFrame(bars).rename(columns=API_RENAME)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return _normalize(df.set_index("ts"))


def read_year(feed: str, timeframe: str, symbol: str, year: int) -> pd.DataFrame:
    path = year_path(feed, timeframe, symbol, year)
    if not path.exists():
        return empty_frame()
    return _normalize(pd.read_parquet(path).set_index("ts"))


def _atomic_write(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    df.reset_index().to_parquet(tmp, index=False)
    os.replace(tmp, path)


def write_bars(feed: str, timeframe: str, symbol: str, new: pd.DataFrame) -> int:
    """Merge bars into the per-year files. Returns the number of bars added (not replaced)."""
    added = 0
    for year, chunk in new.groupby(new.index.year):
        old = read_year(feed, timeframe, symbol, int(year))
        merged = _normalize(pd.concat([old, chunk]))
        _atomic_write(year_path(feed, timeframe, symbol, int(year)), merged)
        added += len(merged) - len(old)
    return added


def stored_years(feed: str, timeframe: str, symbol: str) -> list[int]:
    d = symbol_dir(feed, timeframe, symbol)
    return sorted(int(p.stem) for p in d.glob("*.parquet")) if d.exists() else []


def last_ts(feed: str, timeframe: str, symbol: str) -> pd.Timestamp | None:
    for year in reversed(stored_years(feed, timeframe, symbol)):
        df = read_year(feed, timeframe, symbol, year)
        if not df.empty:
            return df.index.max()
    return None


def load_raw(
    feed: str,
    timeframe: str,
    symbol: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    years = [
        y
        for y in stored_years(feed, timeframe, symbol)
        if (start is None or y >= start.year) and (end is None or y <= end.year)
    ]
    if not years:
        return empty_frame()
    df = pd.concat([read_year(feed, timeframe, symbol, y) for y in years])
    if start is not None:
        df = df[df.index >= start]
    if end is not None:
        df = df[df.index < end]
    return df
