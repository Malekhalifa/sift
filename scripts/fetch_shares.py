"""Download shares outstanding from SEC XBRL company facts, with the filing date of every value (M17).

    uv run python scripts/fetch_shares.py

For each universe symbol: the cover-page share counts (dei:EntityCommonStockSharesOutstanding) of every 10-K and 10-Q,
saved in data/xbrl/shares.parquet (symbol, cik, accn, form, filed, end, val). The raw company-facts file (several MB)
is read and discarded. Resumable per symbol (data/xbrl/by_symbol/). Filings from 2025 on are stored for the holdout;
no analysis reads them.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from tp import config
from tp.edgar import EdgarBlocked, EdgarClient

URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
FORMS = {"10-K", "10-Q"}
COLUMNS = ["accn", "form", "filed", "end", "val"]


def shares_rows(facts: dict) -> pd.DataFrame:
    units = facts.get("facts", {}).get("dei", {}).get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", [])
    rows = [{k: u[k] for k in COLUMNS} for u in units if u.get("form") in FORMS]
    out = pd.DataFrame(rows, columns=COLUMNS)
    out["filed"], out["end"] = pd.to_datetime(out["filed"]), pd.to_datetime(out["end"])
    return out.drop_duplicates()


def _ok(r):
    r.raise_for_status()
    return r


def main() -> int:
    folder = config.DATA_DIR / "xbrl"
    by_symbol = folder / "by_symbol"
    by_symbol.mkdir(parents=True, exist_ok=True)
    symbols = list(dict.fromkeys([*config.load_universe()["universe"]["traded"], *config.events_symbols(), *config.confirm_symbols()]))
    client = EdgarClient()
    cik_of = client.ticker_map()
    todo = [(sym, cik_of[sym]) for sym in symbols if sym in cik_of and not (by_symbol / f"{sym}.parquet").exists()]

    def one(item: tuple[str, int]) -> None:
        sym, cik = item
        time.sleep(0.35)  # SEC fair access: four workers stay well under 10 requests a second
        r = client._http.get(URL.format(cik=cik))
        if r.status_code in (403, 429):
            raise EdgarBlocked(f"HTTP {r.status_code} for {sym}: rate-limited, retry in ~10 minutes")
        df = pd.DataFrame(columns=COLUMNS) if r.status_code == 404 else shares_rows(_ok(r).json())
        df.insert(0, "cik", cik)
        df.insert(0, "symbol", sym)
        df.to_parquet(by_symbol / f"{sym}.parquet", index=False)

    try:
        with ThreadPoolExecutor(4) as pool:
            for i, _ in enumerate(pool.map(one, todo), 1):
                if i % 25 == 0:
                    print(f"  {i}/{len(todo)}", file=sys.stderr)
    except EdgarBlocked as e:
        print(f"SEC rate limit: {e}. Finished symbols are kept; rerun later.", file=sys.stderr)
        return 2
    allrows = pd.concat([pd.read_parquet(p) for p in sorted(by_symbol.glob("*.parquet"))], ignore_index=True)
    allrows.to_parquet(folder / "shares.parquet", index=False)
    print(f"{len(allrows):,} share counts for {allrows['symbol'].nunique()} symbols; filed {allrows['filed'].min():%Y-%m-%d} to {allrows['filed'].max():%Y-%m-%d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
