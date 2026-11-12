"""Command line for the recorder: run | once <source> | qa [--date] [--full] [--no-advance] | status."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import date, datetime, time, timezone

from tp.collect import daemon, store
from tp.collect.datasets import load_settings
from tp.collect.qa import run_qa
from tp.collect.scheduler import Scheduler
from tp.collect.sources import build_sources
from tp.collect.state import State


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tp.collect", description="Sift recorder")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="run the daemon")
    once = sub.add_parser("once", help="run one source now")
    once.add_argument("source")
    qa = sub.add_parser("qa", help="run the data quality checks")
    qa.add_argument("--date", type=date.fromisoformat, help="YYYY-MM-DD; checks as of the end of that day (UTC)")
    qa.add_argument(
        "--full", action="store_true",
        help="scan all price history for holes and jumps (writes <date>-full.json); only price_jumps and "
        "calendar_completeness are informational here, every other check still counts toward the exit status",
    )
    qa.add_argument(
        "--no-advance", action="store_true",
        help="manual inspection: change no schema baseline and write <date>-manual.json, not the day's report",
    )
    sub.add_parser("status", help="show each source's last success, failures and next due time")
    return parser


def _lock_or_report() -> object | None:
    try:
        return daemon.acquire_lock(daemon.lock_path())
    except daemon.AlreadyRunning as e:
        print(f"recorder already running: {e}", file=sys.stderr)
        return None


async def _serve(settings: dict, sources: list) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await daemon.run(settings, sources, clock=_now, sleep=asyncio.sleep, stop=stop)


def _run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    lock = _lock_or_report()
    if lock is None:
        return 1
    with lock:
        settings = load_settings()
        asyncio.run(_serve(settings, build_sources(settings)))
    return 0


def _once(name: str) -> int:
    settings = load_settings()
    sources = {s.name: s for s in build_sources(settings)}
    if name not in sources:
        print(f"unknown source {name!r}; valid sources: {', '.join(sorted(sources)) or '(none)'}", file=sys.stderr)
        return 2
    lock = _lock_or_report()
    if lock is None:
        return 1
    with lock:
        state = State.load()
        scheduler = Scheduler([sources[name]], state, settings, _now, asyncio.sleep, writer=store.write)
        result = asyncio.run(scheduler.run_now(sources[name]))
    if result.ok:
        print(f"{name}: {result.rows} new rows in {result.seconds:.1f}s")
        return 0
    print(f"{name}: failed: {result.error}", file=sys.stderr)
    return 1


def _status() -> int:
    settings = load_settings()
    sources = build_sources(settings)
    state = State.load()
    scheduler = Scheduler(sources, state, settings, _now, asyncio.sleep, writer=store.write)
    print(f"{'source':<24} {'last success':<26} {'failures':>8}  next due")
    for s in sources:
        last = state.last_success(s.name)
        print(
            f"{s.name:<24} {last.isoformat(timespec='seconds') if last else 'never':<26} "
            f"{state.failures(s.name):>8}  {scheduler.next_due(s).isoformat(timespec='seconds')}"
        )
    return 0


def _qa(day: date | None, full: bool, advance_baseline: bool) -> int:
    now = datetime.combine(day, time(23, 59, 59), tzinfo=timezone.utc) if day else _now()
    report = run_qa(now, State.load(), load_settings(), full=full, advance_baseline=advance_baseline)
    print(json.dumps(report, indent=2))
    failed = any(
        not check["ok"] for src in report["sources"].values() for check in src["checks"].values()
    )
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "run":
        return _run()
    if args.command == "once":
        return _once(args.source)
    if args.command == "qa":
        return _qa(args.date, args.full, not args.no_advance)
    return _status()
