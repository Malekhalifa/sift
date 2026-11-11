"""M14: 8-K bad-news items as one event family (docs/m14-eightk-protocol.md)."""

from __future__ import annotations

import pandas as pd

from tp import config

# 1.02 termination of a material agreement, 2.05 exit or disposal costs, 2.06 impairments, 3.01 delisting notice,
# 4.01 change of auditor, 4.02 non-reliance on past financials.
BAD_ITEMS = frozenset({"1.02", "2.05", "2.06", "3.01", "4.01", "4.02"})
DEDUPE_DAYS = 5


def eightk_path():
    return config.DATA_DIR / "events" / "eightk.parquet"


def bad_news_events(filings: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """One row per event: symbol, ts (UTC acceptance time), items (the bad-news codes in the filing).

    A filing counts when it carries at least one BAD_ITEMS code and no Item 2.02 (an earnings release the same day
    would confound the reaction). Within a symbol, a filing less than DEDUPE_DAYS after the last kept one is dropped.
    `start` and `end` are UTC bounds on the acceptance time; `end` is exclusive.
    """
    codes = filings["items"].str.split(",").map(set)
    has_bad = codes.map(lambda c: bool(c & BAD_ITEMS)) & ~codes.map(lambda c: "2.02" in c)
    x = filings[has_bad & (filings["filed_at"] >= start) & (filings["filed_at"] < end)].copy()
    x["bad"] = [",".join(sorted(c & BAD_ITEMS)) for c in codes[x.index]]
    rows = []
    for sym, g in x.sort_values("filed_at").groupby("symbol"):
        last = None
        for r in g.itertuples():
            if last is None or r.filed_at - last > pd.Timedelta(days=DEDUPE_DAYS):
                rows.append({"symbol": sym, "ts": r.filed_at, "items": r.bad})
                last = r.filed_at
    return pd.DataFrame(rows, columns=["symbol", "ts", "items"]).sort_values("ts").reset_index(drop=True)
