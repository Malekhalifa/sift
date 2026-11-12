"""Download shares outstanding from SEC XBRL company facts, with the filing date of every value (M17).

    uv run python scripts/fetch_shares.py

For each universe symbol: the cover-page share counts (dei:EntityCommonStockSharesOutstanding) of every 10-K and 10-Q,
saved in data/xbrl/shares.parquet (symbol, cik, accn, form, filed, end, val). The raw company-facts file (several MB)
is read and discarded. Resumable per symbol (data/xbrl/by_symbol/). Filings from 2025 on are stored for the holdout;
no analysis reads them.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from tp import config
from tp.collect import daemon, datasets, store
from tp.collect.sources import sec
from tp.edgar import EdgarBadResponse, EdgarBlocked, EdgarClient


def main() -> int:
    if (refused := daemon.refuse_while_daemon_runs()) is not None:
        return refused
    folder = config.DATA_DIR / "xbrl"
    by_symbol = folder / "by_symbol"
    by_symbol.mkdir(parents=True, exist_ok=True)
    symbols = sec.xbrl_symbols()
    client = EdgarClient()
    cik_of = client.ticker_map()
    todo = [(sym, cik_of[sym]) for sym in symbols if sym in cik_of and not (by_symbol / f"{sym}.parquet").exists()]

    def one(item: tuple[str, int]) -> None:
        sym, cik = item
        sec.atomic_parquet(sec.fetch_shares(client._http, sym, cik), by_symbol / f"{sym}.parquet")

    try:
        with ThreadPoolExecutor(4) as pool:
            for i, _ in enumerate(pool.map(one, todo), 1):
                if i % 25 == 0:
                    print(f"  {i}/{len(todo)}", file=sys.stderr)
    except EdgarBlocked as e:
        print(f"SEC rate limit: {e}. Finished symbols are kept; rerun later.", file=sys.stderr)
        return 2
    except EdgarBadResponse as e:
        print(f"Bad SEC response: {e}. Finished symbols are kept; rerun later.", file=sys.stderr)
        return 1
    allrows = pd.concat([pd.read_parquet(p) for p in sorted(by_symbol.glob("*.parquet"))], ignore_index=True)
    ds = datasets.dataset("xbrl_shares")  # keep the rows the recorder added since the caches were built
    allrows = store.merge_rebuilt(ds, allrows)
    sec.atomic_parquet(allrows, ds.path)
    print(f"{len(allrows):,} share counts for {allrows['symbol'].nunique()} symbols; filed {allrows['filed'].min():%Y-%m-%d} to {allrows['filed'].max():%Y-%m-%d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
