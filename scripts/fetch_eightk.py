"""Build data/events/eightk.parquet: every 8-K for the universe symbols, with its item codes (M14).

    uv run python scripts/fetch_eightk.py

Reads the SEC submission files that fetch_earnings.py already cached in data/edgar (downloading any that are missing),
so it normally makes no requests. Rows from 2025 on are kept for the sealed holdout; no analysis reads them.
"""

from __future__ import annotations

import sys

import pandas as pd

from tp import config
from tp.edgar import EdgarBlocked, EdgarClient


def main() -> int:
    symbols = list(dict.fromkeys([*config.load_universe()["universe"]["traded"], *config.events_symbols(), *config.confirm_symbols()]))
    client = EdgarClient()
    frames, missing = [], []
    try:
        cik_of = client.ticker_map()
        for sym in symbols:
            cik = cik_of.get(sym)
            if cik is None:
                missing.append(sym)
                continue
            df = client.eightk_filings(cik)
            df.insert(0, "symbol", sym)
            frames.append(df)
    except EdgarBlocked as e:
        print(f"SEC rate limit: {e}. Everything fetched so far is cached; rerun in about ten minutes.", file=sys.stderr)
        return 2
    out = pd.concat(frames, ignore_index=True)
    path = config.DATA_DIR / "events" / "eightk.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    print(f"{len(out):,} 8-Ks for {out['symbol'].nunique()} symbols; filed {out['filed_at'].min():%Y-%m-%d} to {out['filed_at'].max():%Y-%m-%d}")
    if missing:
        print(f"no CIK found for {len(missing)} symbols: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
