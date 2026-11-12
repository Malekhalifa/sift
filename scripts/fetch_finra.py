"""Download FINRA's consolidated daily short-sale volume (Reg SHO, CNMS files) for the universe symbols (M16).

    uv run python scripts/fetch_finra.py

One small file per trading day from 2018-08-01 (the first consolidated file) to today: each is filtered to the universe
symbols and saved as data/finra/daily/<date>.parquet, then joined into data/finra/shortvol.parquet. Resumable: days
already saved are skipped. Days FINRA has no file for (weekends, holidays) are recorded in data/finra/no_file.txt.
Rows from 2025 on are kept for the sealed holdout; no analysis reads them.
"""

from __future__ import annotations

import io
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import httpx
import pandas as pd

from tp import config

URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{day}.txt"
FIRST = date(2018, 8, 1)
COLUMNS = {"Date": "date", "Symbol": "symbol", "ShortVolume": "short", "ShortExemptVolume": "exempt", "TotalVolume": "total"}


def fetch_day(http: httpx.Client, day: date, symbols: set[str]) -> pd.DataFrame | None:
    """Rows for the universe on `day`, or None when FINRA has no file for that date."""
    for attempt in range(4):
        try:
            r = http.get(URL.format(day=day.strftime("%Y%m%d")))
        except httpx.TransportError:
            continue
        if r.status_code in (403, 404):
            return None
        if r.status_code == 200:
            df = pd.read_csv(io.StringIO(r.text), sep="|", dtype={"Date": str, "Symbol": str})
            df = df[df["Symbol"].isin(symbols)].rename(columns=COLUMNS)
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
            return df[["date", "symbol", "short", "exempt", "total"]].reset_index(drop=True)
    raise RuntimeError(f"FINRA {day}: no usable response after retries")


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
    gaps_path.write_text("\n".join(sorted(known_gaps)))
    out = pd.concat([pd.read_parquet(p) for p in sorted(daily.glob("*.parquet"))], ignore_index=True)
    out.to_parquet(folder / "shortvol.parquet", index=False)
    print(f"{len(out):,} rows, {out['symbol'].nunique()} symbols, {out['date'].nunique()} days, {out['date'].min():%Y-%m-%d} to {out['date'].max():%Y-%m-%d}; {len(known_gaps)} days without a file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
