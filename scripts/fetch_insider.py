"""Download the SEC insider-transaction bulk files (Form 4, 2013 Q1 to the last finished quarter) and build data/insider/trades.parquet.

    uv run python scripts/fetch_insider.py

Each quarterly zip (about 10 MB) is downloaded, reduced to the open-market purchases and sales by officers and
directors (data/insider/parsed/<quarter>.parquet) and then deleted, so disk use stays small. Resumable: finished
quarters are skipped. Also writes data/insider/symbol_cik.csv, the universe symbols matched to SEC company IDs. Nothing
Data from 2025 on is stored for the sealed holdout, but every analysis script refuses to read it (config.HOLDOUT_START).
"""

from __future__ import annotations

import csv
import sys
import time
import zipfile
from datetime import date, timedelta

import httpx
import pandas as pd

from tp import config, insiders
from tp.edgar import EdgarBlocked, EdgarClient, user_agent

URL = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{quarter}_form345.zip"
FIRST_YEAR = 2013  # three years of look-back before the first test event in 2016
READ = {
    "SUBMISSION.tsv": ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK"],
    "REPORTINGOWNER.tsv": ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP"],
    "NONDERIV_TRANS.tsv": ["ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
                           "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD"],
}


def read_member(z: zipfile.ZipFile, name: str) -> pd.DataFrame:
    with z.open(name) as f:  # QUOTE_NONE: free-text fields contain stray quotes
        return pd.read_csv(f, sep="\t", dtype=str, usecols=READ[name], quoting=csv.QUOTE_NONE, encoding_errors="replace")


def fetch_quarter(http: httpx.Client, quarter: str, tmp) -> pd.DataFrame:
    with http.stream("GET", URL.format(quarter=quarter)) as r:
        if r.status_code == 404:  # quarter not published yet
            raise FileNotFoundError(quarter)
        if r.status_code in (403, 429):
            raise EdgarBlocked(f"HTTP {r.status_code} for {quarter}: rate-limited, retry in ~10 minutes")
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    try:
        with zipfile.ZipFile(tmp) as z:
            return insiders.parse_quarter(*(read_member(z, n) for n in READ))
    finally:
        tmp.unlink(missing_ok=True)


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
    folder = config.DATA_DIR / "insider"
    parsed = folder / "parsed"
    parsed.mkdir(parents=True, exist_ok=True)
    http = httpx.Client(headers={"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"}, timeout=120.0, follow_redirects=True)
    cutoff = date.today() - timedelta(days=7)  # a quarter's file appears shortly after it ends
    quarters = [f"{y}q{q}" for y in range(FIRST_YEAR, cutoff.year + 1) for q in range(1, 5)
                if (pd.Timestamp(year=y, month=3 * q, day=1) + pd.offsets.MonthEnd(0)).date() < cutoff]
    try:
        for i, quarter in enumerate(quarters, 1):
            out = parsed / f"{quarter}.parquet"
            if out.exists():
                continue
            t0 = time.monotonic()
            try:
                df = fetch_quarter(http, quarter, folder / f"{quarter}.zip.part")
            except FileNotFoundError:
                print(f"{quarter} is not published yet; stopping here.", file=sys.stderr)
                break
            df.to_parquet(out, index=False)
            print(f"[{i}/{len(quarters)}] {quarter}: {len(df):,} trades ({time.monotonic() - t0:.0f}s)", file=sys.stderr)
            time.sleep(1.0)
    except EdgarBlocked as e:
        print(f"SEC rate limit: {e}. Finished quarters are kept; rerun later.", file=sys.stderr)
        return 2
    trades = pd.concat([pd.read_parquet(p) for p in sorted(parsed.glob("*.parquet"))], ignore_index=True)
    trades = trades.drop_duplicates(["trade_id", "owner_cik"])
    trades.to_parquet(insiders.trades_path(), index=False)
    n = write_symbol_map()
    print(f"{len(trades):,} trades ({(trades['code'] == 'P').sum():,} purchases) from {trades['filing_date'].min():%Y-%m-%d} "
          f"to {trades['filing_date'].max():%Y-%m-%d}; {n} universe symbols matched to SEC company IDs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
