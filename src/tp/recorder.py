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
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from tp import config, corp_actions, store
from tp.alpaca_data import AlpacaClient, AlpacaError

log = logging.getLogger("tp.recorder")
ET = ZoneInfo("America/New_York")

# Order matters: daily bars are fast and unblock the split/validation checks first.
SPECS: tuple[tuple[str, str], ...] = (("sip", "1Day"), ("sip", "1Min"), ("iex", "1Min"), ("sip", "5Min"))
# Which bar types each universe records. 5-minute SIP bars match 1-minute bars resampled to 5 minutes exactly,
# so the wide universe skips the 1-minute and IEX history, which is roughly 10x more data.
CORE_SPECS = (("sip", "1Day"), ("sip", "1Min"), ("iex", "1Min"))
WIDE_SPECS = (("sip", "1Day"), ("sip", "5Min"))
DAILY_SPECS = (("sip", "1Day"),)  # symbols that exist only for event studies
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


def run_plan(client: AlpacaClient, plan: list[tuple[str, str, str]], now: datetime, workers: int = 1) -> list[str]:
    """Sync every (feed, timeframe, symbol). Each series writes its own files, so they can run in parallel; the
    client throttles all threads to one shared request rate. Returns the failures instead of raising."""
    total, failures = len(plan), []
    lock, finished = threading.Lock(), [0]

    def one(item: tuple[str, str, str]) -> None:
        feed, timeframe, symbol = item
        t0 = _time.monotonic()
        try:
            added, error = sync_series(client, feed, timeframe, symbol, now), None
        except Exception as e:  # noqa: BLE001 - one bad series must not stop the rest
            added, error = 0, e
        with lock:
            finished[0] += 1
            if error is not None:
                failures.append(f"{feed}/{timeframe}/{symbol}: {error}")
                log.error("[%d/%d] %s %s %s FAILED: %s", finished[0], total, feed, timeframe, symbol, error)
            else:
                log.info("[%d/%d] %s %s %s +%d bars (%.1fs)", finished[0], total, feed, timeframe, symbol, added, _time.monotonic() - t0)

    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        list(pool.map(one, plan))
    return failures


def build_plan(symbols: list[str] | None, universe: str, specs: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    """(feed, timeframe, symbol) triples to sync, in SPECS order. `symbols` restricts to those names."""
    core, wide, events = config.core_symbols(), config.wide_symbols(), config.events_symbols()
    everyone = list(dict.fromkeys([*core, *wide, *events]))
    pool = {"core": core, "wide": wide, "events": events, "all": everyone}[universe]
    if symbols:
        pool = symbols
    plan = []
    for feed, tf in specs:
        for sym in pool:
            allowed = CORE_SPECS if sym in core else WIDE_SPECS if sym in wide else DAILY_SPECS
            if (feed, tf) in allowed:
                plan.append((feed, tf, sym))
    return plan


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", help="comma-separated; default is the chosen universe")
    ap.add_argument("--universe", choices=["core", "wide", "events", "all"], default="all")
    ap.add_argument("--specs", help="comma-separated feed:timeframe; default is all")
    ap.add_argument("--workers", type=int, default=1, help="parallel series (all share one request-rate budget)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per request drowns the progress log

    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None
    plan = build_plan(symbols, args.universe, parse_specs(args.specs))
    all_names = sorted({sym for _, _, sym in plan})

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock = open(config.DATA_DIR / ".recorder.lock", "w")  # noqa: SIM115 - held for the whole run
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.error("Another recorder run holds the lock; exiting.")
        return 2

    client = AlpacaClient(config.Settings.from_env())
    now = datetime.now(UTC)

    splits = corp_actions.sync_splits(client, all_names, FEED_START["sip"], now.astimezone(ET).date())
    log.info("splits synced: %d records for %d symbols", len(splits), len(all_names))

    total = len(plan)
    failures = run_plan(client, plan, now, args.workers)

    if failures:
        log.error("%d series failed:\n  %s", len(failures), "\n  ".join(failures))
        return 1
    log.info("done, %d series synced", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
