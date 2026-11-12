"""Download the SEC insider-transaction bulk files (Form 4, 2013 Q1 to the last finished quarter) and build data/insider/trades.parquet.

    uv run python scripts/fetch_insider.py

Each quarterly zip (about 10 MB) is downloaded, reduced to the open-market purchases and sales by officers and
directors (data/insider/parsed/<quarter>.parquet) and then deleted, so disk use stays small. Resumable: finished
quarters are skipped. Also writes data/insider/symbol_cik.csv, the universe symbols matched to SEC company IDs. Nothing
Data from 2025 on is stored for the sealed holdout, but every analysis script refuses to read it (config.HOLDOUT_START).
"""

from __future__ import annotations

import sys
import time
from datetime import date

import httpx
import pandas as pd

from tp import config, insiders
from tp.collect import daemon, datasets, store
from tp.collect.sources import sec
from tp.edgar import EdgarBadResponse, EdgarBlocked, EdgarClient, user_agent


def write_symbol_map() -> int:
    traded = config.load_universe()["universe"]["traded"]
    ordered = list(dict.fromkeys([*traded, *config.events_symbols(), *config.confirm_symbols()]))
    cik_of = EdgarClient().ticker_map()
    rows, seen = [], set()
    for sym in ordered:
        cik = cik_of.get(sym)
        if cik is None or cik in seen:  # no SEC match, or a second share class of a company already listed
            continue
        seen.add(cik)
        rows.append((sym, cik))
    pd.DataFrame(rows, columns=["symbol", "cik"]).to_csv(insiders.symbol_map_path(), index=False)
    return len(rows)


def main() -> int:
    if (refused := daemon.refuse_while_daemon_runs()) is not None:
        return refused
    folder = config.DATA_DIR / "insider"
    parsed = folder / "parsed"
    parsed.mkdir(parents=True, exist_ok=True)
    http = httpx.Client(headers={"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"}, timeout=120.0, follow_redirects=True)
    quarters = sec.finished_quarters(date.today())  # a quarter's file appears shortly after it ends
    try:
        for i, quarter in enumerate(quarters, 1):
            out = parsed / f"{quarter}.parquet"
            if out.exists():
                continue
            t0 = time.monotonic()
            try:
                df = sec.fetch_quarter(http, quarter, folder / f"{quarter}.zip.part")
            except FileNotFoundError:
                print(f"{quarter} is not published yet; stopping here.", file=sys.stderr)
                break
            sec.atomic_parquet(df, out)
            print(f"[{i}/{len(quarters)}] {quarter}: {len(df):,} trades ({time.monotonic() - t0:.0f}s)", file=sys.stderr)
            time.sleep(sec.QUARTER_PAUSE_S)
    except EdgarBlocked as e:
        print(f"SEC rate limit: {e}. Finished quarters are kept; rerun later.", file=sys.stderr)
        return 2
    except EdgarBadResponse as e:
        print(f"Bad SEC download: {e}. Finished quarters are kept; rerun later.", file=sys.stderr)
        return 1
    trades = pd.concat([pd.read_parquet(p) for p in sorted(parsed.glob("*.parquet"))], ignore_index=True)
    trades = trades.drop_duplicates(["trade_id", "owner_cik"])
    trades = store.merge_rebuilt(datasets.dataset("form4"), trades)  # keep the recorder's rows and ingested_at
    sec.atomic_parquet(trades, insiders.trades_path())
    n = write_symbol_map()
    print(f"{len(trades):,} trades ({(trades['code'] == 'P').sum():,} purchases) from {trades['filing_date'].min():%Y-%m-%d} "
          f"to {trades['filing_date'].max():%Y-%m-%d}; {n} universe symbols matched to SEC company IDs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
