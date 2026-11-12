"""Download every universe 10-K from 2015 to 2024, cut out Item 1A (Risk Factors) and keep its word counts (M18).

    uv run python scripts/fetch_riskfactors.py

For each symbol: data/riskfactors/by_symbol/<SYM>.parquet with one row per 10-K (accession, acceptance time, period end,
parse status, length, and the Item 1A word counts as JSON). The raw document (several MB) is read and discarded.
Resumable per symbol. 10-Ks accepted from 2025 on are not downloaded (the holdout). Prints the parse rate when done.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from tp import config, lazyprices
from tp.edgar import EdgarBlocked, EdgarClient

DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{doc}"
FIRST, LAST = pd.Timestamp("2015-01-01", tz="UTC"), pd.Timestamp(config.HOLDOUT_START, tz="UTC")
COLUMNS = ["symbol", "cik", "accn", "filed_at", "report_date", "status", "n_chars", "counts"]


def parse_filing(client: EdgarClient, cik: int, accn: str, doc: str) -> tuple[str, int, str]:
    time.sleep(0.35)  # SEC fair access: four workers stay well under 10 requests a second
    r = client._http.get(DOC_URL.format(cik=cik, accn=accn.replace("-", ""), doc=doc), timeout=60.0)
    if r.status_code in (403, 429):
        raise EdgarBlocked(f"HTTP {r.status_code} for {accn}: rate-limited, retry in ~10 minutes")
    if r.status_code == 404:
        return "missing", 0, ""
    r.raise_for_status()
    section = lazyprices.item_1a(lazyprices.html_to_text(r.text))
    if section is None:
        return "no_item_1a", 0, ""
    return "ok", len(section), lazyprices.counts_to_json(lazyprices.word_counts(section))


def main() -> int:
    folder = config.DATA_DIR / "riskfactors" / "by_symbol"
    folder.mkdir(parents=True, exist_ok=True)
    symbols = list(dict.fromkeys([*config.load_universe()["universe"]["traded"], *config.events_symbols(), *config.confirm_symbols()]))
    client = EdgarClient()
    cik_of = client.ticker_map()
    todo = [(s, cik_of[s]) for s in symbols if s in cik_of and not (folder / f"{s}.parquet").exists()]

    def one(item: tuple[str, int]) -> None:
        sym, cik = item
        tenks = client.tenk_filings(cik)
        tenks = tenks[(tenks["filed_at"] >= FIRST) & (tenks["filed_at"] < LAST)]
        rows = []
        for t in tenks.itertuples():
            status, n_chars, counts = parse_filing(client, cik, t.accn, t.doc)
            rows.append({"symbol": sym, "cik": cik, "accn": t.accn, "filed_at": t.filed_at, "report_date": t.report_date,
                         "status": status, "n_chars": n_chars, "counts": counts})
        pd.DataFrame(rows, columns=COLUMNS).to_parquet(folder / f"{sym}.parquet", index=False)

    print(f"{len(todo)} symbols to fetch", file=sys.stderr)
    try:
        with ThreadPoolExecutor(4) as pool:
            for i, _ in enumerate(pool.map(one, todo), 1):
                if i % 10 == 0:
                    print(f"  {i}/{len(todo)}", file=sys.stderr)
    except EdgarBlocked as e:
        print(f"SEC rate limit: {e}. Finished symbols are kept; rerun later.", file=sys.stderr)
        return 2
    allrows = pd.concat([pd.read_parquet(p) for p in sorted(folder.glob("*.parquet"))], ignore_index=True)
    allrows.to_parquet(folder.parent / "riskfactors.parquet", index=False)
    print(f"{len(allrows):,} 10-Ks for {allrows['symbol'].nunique()} symbols; parse status {allrows['status'].value_counts().to_dict()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
