"""M15: nearness to the 52-week high as a monthly long-short basket (docs/m15-high52-protocol.md)."""

from __future__ import annotations

import numpy as np
import pandas as pd

WINDOW = 252
COST_PER_SIDE = 0.0005


def nearness(close: pd.DataFrame) -> pd.DataFrame:
    """Close over the highest close of the last WINDOW sessions (including today). NaN until WINDOW sessions exist."""
    return close / close.rolling(WINDOW, min_periods=WINDOW).max()


def month_starts(index: pd.DatetimeIndex) -> list[int]:
    """Row position of the first session of each calendar month."""
    months = index.to_period("M")
    return [i for i in range(len(index)) if i == 0 or months[i] != months[i - 1]]


def monthly_spread(open_: pd.DataFrame, close: pd.DataFrame, market_open: pd.Series, first_rebalance: str) -> pd.DataFrame:
    """One row per month: long-short net return, legs, cost, turnover, market return.

    Signal = nearness at the previous session's close; trade at the first session's open of the month; hold to the next
    month's first-session open. Quintile size is round(ranked / 5). Only months whose exit open exists are returned.
    """
    near = nearness(close)
    starts = month_starts(open_.index)
    rows, prev = [], {}
    for k, pos in enumerate(starts[:-1]):
        date, exit_pos = open_.index[pos], starts[k + 1]
        if date < pd.Timestamp(first_rebalance) or pos == 0:
            continue
        sig = near.iloc[pos - 1]
        ret = open_.iloc[exit_pos] / open_.iloc[pos] - 1
        ranked = pd.DataFrame({"near": sig, "ret": ret}).dropna().sort_index()
        n = round(len(ranked) / 5)
        if n < 2:
            continue
        ordered = ranked.sort_values("near", ascending=False, kind="stable")
        top, bottom = ordered.iloc[:n], ordered.iloc[-n:]
        weights = {**{s: 1 / n for s in top.index}, **{s: -1 / n for s in bottom.index}}
        turnover = sum(abs(weights.get(s, 0.0) - prev.get(s, 0.0)) for s in set(weights) | set(prev))
        cost = COST_PER_SIDE * turnover
        gross = top["ret"].mean() - bottom["ret"].mean()
        rows.append({
            "date": date, "ranked": len(ranked), "long_names": ",".join(top.index), "short_names": ",".join(bottom.index),
            "long": top["ret"].mean(), "short": bottom["ret"].mean(),
            "gross": gross, "cost": cost, "net": gross - cost, "turnover": turnover,
            "market": market_open.iloc[exit_pos] / market_open.iloc[pos] - 1,
        })
        prev = weights
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame(columns=["long_names", "short_names", "long", "short", "gross", "cost", "net", "turnover", "market"])
