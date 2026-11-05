"""Collect earnings-release timestamps (SEC 8-K Item 2.02) for the event universe into data/events/earnings.parquet.

    uv run python scripts/fetch_earnings.py

Resumable: every SEC response is cached under data/edgar/, so a rerun (for example after a rate-limit block) only
fetches what is missing. Stops cleanly if the SEC rate-limits us.
"""

from __future__ import annotations

import sys

import pandas as pd

from tp import config, events
from tp.edgar import EdgarBlocked, EdgarClient


def main() -> int:
    symbols = list(dict.fromkeys([*config.load_universe()["universe"]["traded"], *config.events_symbols()]))
    client = EdgarClient()
    try:
        cik_of = client.ticker_map()
        frames, missing = [], []
        for i, sym in enumerate(symbols, 1):
            cik = cik_of.get(sym)
            if cik is None:
                missing.append(sym)
                continue
            df = client.earnings_filings(cik)
            df.insert(0, "symbol", sym)
            df.insert(1, "cik", cik)
            frames.append(df)
            if i % 25 == 0:
                print(f"  {i}/{len(symbols)} symbols", file=sys.stderr)
    except EdgarBlocked as e:
        print(f"SEC rate limit: {e}. Everything fetched so far is cached; rerun in about ten minutes.", file=sys.stderr)
        return 2
    out = pd.concat(frames, ignore_index=True)
    events.events_path().parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(events.events_path(), index=False)
    per = out.groupby("symbol").size()
    print(f"{len(out):,} earnings filings for {out['symbol'].nunique()} symbols ({per.min()} to {per.max()} each, median {int(per.median())})")
    if missing:
        print(f"no CIK found for {len(missing)} symbols: {missing}")
    print(f"filed between {out['filed_at'].min():%Y-%m-%d} and {out['filed_at'].max():%Y-%m-%d}; wrote {events.events_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
