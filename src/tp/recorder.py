"""Backfill and incremental sync of raw bars and splits into the parquet store.

    uv run python -m tp.recorder                            # whole universe, every spec
    uv run python -m tp.recorder --symbols AAPL,NVDA        # subset
    uv run python -m tp.recorder --specs sip:1Day           # subset of feed:timeframe

Safe to re-run any time: it resumes from the last stored bar (re-fetching a 3-day overlap so late
corrections are picked up) and a lock file stops two runs overlapping.
"""

from __future__ import annotations

import argparse
import fcntl
import logging
import time as _time
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from tp import config, corp_actions, store
from tp.alpaca_data import AlpacaClient, AlpacaError

log = logging.getLogger("tp.recorder")
ET = ZoneInfo("America/New_York")

# Order matters: daily bars are fast and unblock the split/validation checks first.
SPECS: tuple[tuple[str, str], ...] = (("sip", "1Day"), ("sip", "1Min"), ("iex", "1Min"))
FEED_START = {"sip": date(2016, 1, 1), "iex": date(2020, 7, 27)}
OVERLAP = timedelta(days=3)
# Free tier withholds the newest 15 min of SIP data. IEX is real time, but skip the minute in progress.
LAG = {"sip": timedelta(minutes=20), "iex": timedelta(minutes=2)}


def fetch_end(feed: str, timeframe: str, now: datetime) -> datetime:
    """Exclusive upper bound for a fetch, so only finished bars are stored."""
    if timeframe == "1Day":
        # A daily bar is final only after the 20:00 ET extended session closes (+ SIP lag).
        et = now.astimezone(ET)
        midnight = et.replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = midnight if et.time() < time(20, 30) else midnight + timedelta(days=1)
        return cutoff.astimezone(UTC)
    return (now - LAG[feed]).replace(second=0, microsecond=0)


def sync_series(client: AlpacaClient, feed: str, timeframe: str, symbol: str, now: datetime) -> int:
    end = fetch_end(feed, timeframe, now)
    floor = datetime.combine(FEED_START[feed], time(), tzinfo=UTC)
    last = store.last_ts(feed, timeframe, symbol)
    added = 0
    for year in range(floor.year, end.year + 1):
        if last is not None and year < last.year and store.year_path(feed, timeframe, symbol, year).exists():
            continue  # complete: year files are written whole, so an existing past year is finished
        start = max(datetime(year, 1, 1, tzinfo=UTC), floor)
        if last is not None and year == last.year:
            start = max(start, last.to_pydatetime() - OVERLAP)
        stop = min(datetime(year + 1, 1, 1, tzinfo=UTC), end)
        if start >= stop:
            continue
        frame = store.frame_from_api(list(client.bars(symbol, timeframe, start, stop, feed=feed)))
        added += store.write_bars(feed, timeframe, symbol, frame)
    return added


def parse_specs(text: str | None) -> list[tuple[str, str]]:
    if not text:
        return list(SPECS)
    specs = [tuple(item.split(":", 1)) for item in text.split(",")]
    unknown = [s for s in specs if s not in SPECS]
    if unknown:
        raise SystemExit(f"Unknown spec(s) {unknown}; choose from {[f'{f}:{t}' for f, t in SPECS]}")
    return specs  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", help="comma-separated; default is the whole universe")
    ap.add_argument("--specs", help="comma-separated feed:timeframe; default is all")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per request drowns the progress log

    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else config.all_symbols()
    specs = parse_specs(args.specs)

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock = open(config.DATA_DIR / ".recorder.lock", "w")  # noqa: SIM115 - held for the whole run
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.error("Another recorder run holds the lock; exiting.")
        return 2

    client = AlpacaClient(config.Settings.from_env())
    now = datetime.now(UTC)

    splits = corp_actions.sync_splits(client, symbols, FEED_START["sip"], now.astimezone(ET).date())
    log.info("splits synced: %d records for %d symbols", len(splits), len(symbols))

    total = len(specs) * len(symbols)
    failures: list[str] = []
    done = 0
    for feed, timeframe in specs:
        for symbol in symbols:
            done += 1
            t0 = _time.monotonic()
            try:
                added = sync_series(client, feed, timeframe, symbol, now)
            except AlpacaError as e:
                failures.append(f"{feed}/{timeframe}/{symbol}: {e}")
                log.error("[%d/%d] %s %s %s FAILED: %s", done, total, feed, timeframe, symbol, e)
                continue
            log.info("[%d/%d] %s %s %s +%d bars (%.1fs)", done, total, feed, timeframe, symbol, added, _time.monotonic() - t0)

    if failures:
        log.error("%d series failed:\n  %s", len(failures), "\n  ".join(failures))
        return 1
    log.info("done, %d series synced", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
