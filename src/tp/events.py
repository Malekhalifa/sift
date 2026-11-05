"""Earnings events: when results were released, and which trading session was the first to react.

A release before the open (before 09:30 ET) is first traded on that day's session; one after the close (from 16:00 ET)
on the next session. A release during the session is ambiguous (part of the reaction happened before it) and is
excluded. Everything here uses only the filing timestamp, so nothing about the outcome leaks into the classification.
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd

from tp import config, features
from tp.bars import ET

DEDUPE_DAYS = 5  # a second 2.02 filing this soon after the first is the same quarter's announcement


def events_path():
    return config.DATA_DIR / "events" / "earnings.parquet"


@lru_cache(maxsize=4)
def _table(path_str: str, mtime: float) -> pd.DataFrame:
    return pd.read_parquet(path_str)


def load_earnings(symbol: str) -> pd.DataFrame:
    """Earnings filings for one symbol, columns accession and filed_at (UTC). Empty if none are stored."""
    path = events_path()
    if not path.exists():
        return pd.DataFrame(columns=["accession", "filed_at"])
    df = _table(str(path), path.stat().st_mtime)
    return df[df["symbol"] == symbol][["accession", "filed_at"]].reset_index(drop=True)


def classify(filed_at: pd.Series) -> pd.Series:
    """'pre' (before 09:30 ET), 'intraday' (09:30 to 16:00) or 'post' (16:00 onward), by Eastern time."""
    local = filed_at.dt.tz_convert(ET)
    minutes = local.dt.hour * 60 + local.dt.minute
    return pd.Series(
        ["pre" if m < 9 * 60 + 30 else "intraday" if m < 16 * 60 else "post" for m in minutes], index=filed_at.index
    )


def reaction_positions(filed_at: pd.Series, session_index: pd.DatetimeIndex) -> pd.DataFrame:
    """For each tradable release: the row position, in `session_index`, of the first session that could react.

    Returns columns filed_at, klass, pos. Excludes intraday releases, duplicates of the same announcement, and
    events whose reaction session is missing or has no previous session to measure against.
    """
    if filed_at.empty:
        return pd.DataFrame(columns=["filed_at", "klass", "pos"])
    ts = filed_at.sort_values().reset_index(drop=True)
    kept: list[pd.Timestamp] = []
    for t in ts:  # a filing within DEDUPE_DAYS of the last event we KEPT is a repeat of that announcement
        if not kept or t - kept[-1] > pd.Timedelta(days=DEDUPE_DAYS):
            kept.append(t)
    ts = pd.Series(kept, dtype=ts.dtype)
    klass = classify(ts)
    sessions = features.session_dates(session_index).values
    local_day = ts.dt.tz_convert(ET).dt.tz_localize(None).dt.normalize().values
    # A filing on a weekend or holiday is first traded at the next open, whatever the clock said.
    klass = pd.Series(["pre" if day not in set(sessions) else k for day, k in zip(local_day, klass, strict=True)], index=klass.index)
    pos = [
        int(pd.Index(sessions).searchsorted(day, side="left" if k == "pre" else "right"))
        for day, k in zip(local_day, klass, strict=True)
    ]
    out = pd.DataFrame({"filed_at": ts, "klass": klass, "pos": pos})
    return out[(out["klass"] != "intraday") & (out["pos"] >= 1) & (out["pos"] < len(session_index))].reset_index(drop=True)


def reaction_table(bars: pd.DataFrame, spy_daily: pd.DataFrame, filed_at: pd.Series, atr_n: int = 14) -> pd.DataFrame:
    """One row per tradable earnings event: pos (reaction session row), ar (stock return minus SPY return that
    session), z (ar in units of the stock's ATR-as-percent-of-price over the sessions BEFORE it) and atr (ATR
    including the reaction session, for stops). Rows with missing inputs are dropped."""
    react = reaction_positions(filed_at, bars.index)
    if react.empty:
        return react.assign(ar=pd.Series(dtype=float), z=pd.Series(dtype=float), atr=pd.Series(dtype=float))
    close = bars["close"]
    atr = features.atr_through(bars, atr_n)
    vol_before = (atr / close).shift(1)
    spy_ret = spy_daily["close"].pct_change()
    spy_ret.index = features.session_dates(spy_daily.index)
    dates = features.session_dates(bars.index)
    pos = react["pos"].to_numpy()
    ar = close.pct_change().iloc[pos].to_numpy() - spy_ret.reindex(dates[pos]).to_numpy()
    vol = vol_before.iloc[pos].to_numpy()
    out = react.assign(ar=ar, z=ar / vol, atr=atr.iloc[pos].to_numpy())
    out = out.replace([float("inf"), float("-inf")], float("nan"))
    return out[(vol > 0)].dropna(subset=["ar", "z", "atr"]).reset_index(drop=True)
