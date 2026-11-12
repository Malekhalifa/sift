"""Download FINRA's consolidated daily short-sale volume (Reg SHO, CNMS files) for the universe symbols (M16).

    uv run python scripts/fetch_finra.py

One small file per trading day from 2018-08-01 (the first consolidated file) to today: each is filtered to the universe
symbols and saved as data/finra/daily/<date>.parquet, then joined into data/finra/shortvol.parquet. Resumable: days
already saved are skipped. Days FINRA has no file for (weekends, holidays) are recorded in data/finra/no_file.txt.
Rows from 2025 on are kept for the sealed holdout; no analysis reads them.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import httpx
import pandas as pd

from tp import config
from tp.collect.sources.finra import FIRST, fetch_day, merge_shortvol, write_days


def main() -> int:
    folder = config.DATA_DIR / "finra"
    daily = folder / "daily"
    daily.mkdir(parents=True, exist_ok=True)
    gaps_path = folder / "no_file.txt"
    known_gaps = set(gaps_path.read_text().split()) if gaps_path.exists() else set()
    symbols = set(config.load_universe()["universe"]["traded"]) | set(config.events_symbols()) | set(config.confirm_symbols()) | {"SPY", "QQQ"}
    last = date.today() - timedelta(days=1)
    days = [FIRST + timedelta(days=i) for i in range((last - FIRST).days + 1) if (FIRST + timedelta(days=i)).weekday() < 5]
    todo = [d for d in days if not (daily / f"{d:%Y%m%d}.parquet").exists() and f"{d:%Y%m%d}" not in known_gaps]
    print(f"{len(todo)} days to fetch of {len(days)} weekdays", file=sys.stderr)
    with httpx.Client(headers={"User-Agent": "sift-research"}, timeout=60.0, follow_redirects=True) as http, ThreadPoolExecutor(4) as pool:
        for i, (day, df) in enumerate(zip(todo, pool.map(lambda d: fetch_day(http, d, symbols), todo), strict=True), 1):
            if df is None:
                known_gaps.add(f"{day:%Y%m%d}")
            else:
                df.to_parquet(daily / f"{day:%Y%m%d}.parquet", index=False)
            if i % 100 == 0:
                print(f"  {i}/{len(todo)}", file=sys.stderr)
    write_days(gaps_path, known_gaps)
    out = pd.concat([pd.read_parquet(p) for p in sorted(daily.glob("*.parquet"))], ignore_index=True)
    stored = folder / "shortvol.parquet"
    if stored.exists():  # keep what the recorder added (ingested_at, survivorship-free symbols)
        out = merge_shortvol(pd.read_parquet(stored), out)
    out.to_parquet(stored, index=False)
    print(f"{len(out):,} rows, {out['symbol'].nunique()} symbols, {out['date'].nunique()} days, {out['date'].min():%Y-%m-%d} to {out['date'].max():%Y-%m-%d}; {len(known_gaps)} days without a file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
