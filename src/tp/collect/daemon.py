"""The recorder daemon: tick the scheduler, keep the gauges current, hold the single-instance lock."""
from __future__ import annotations

import asyncio
import fcntl
import logging
import shutil
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO

from tp import config
from tp.collect import qa, store
from tp.collect.metrics import Metrics
from tp.collect.scheduler import Scheduler
from tp.collect.source import Source
from tp.collect.state import State

log = logging.getLogger(__name__)

TICK_SECONDS = 30
STALE_AFTER_INTERVALS = 2
QA_EXPORT_EVERY = timedelta(minutes=5)


class AlreadyRunning(Exception):
    """Another process holds the lock for this data directory."""


def lock_path() -> Path:
    return config.DATA_DIR / ".collect.lock"


def acquire_lock(path: Path) -> IO:
    """Take a non-blocking exclusive flock on path; the lock lasts as long as the returned file stays open."""
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        raise AlreadyRunning(f"another recorder holds {path}") from None
    return f


def refuse_while_daemon_runs() -> int | None:
    """For legacy scripts that write under data/: 2 (after a message on stderr) while a recorder daemon holds the data
    directory's lock, else None. The lock is probed without blocking and released at once."""
    try:
        acquire_lock(lock_path()).close()
    except AlreadyRunning:
        print(f"the recorder daemon is running ({lock_path()} is locked); stop it before running this script", file=sys.stderr)
        return 2
    return None


def _update_gauges(metrics: Metrics, sources: list[Source], state: State, now: datetime, started: datetime) -> None:
    """Age is measured from daemon start for a source that has never succeeded, so staleness still shows."""
    for source in sources:
        last = state.last_success(source.name) or started
        metrics.set_age(source.name, max((now - last).total_seconds(), 0.0))
    try:
        metrics.set_disk_free(shutil.disk_usage(config.DATA_DIR).free)
    except OSError:
        log.exception("cannot read free disk space for %s", config.DATA_DIR)


async def _wait(sleep: Callable[[float], Awaitable[None]], stop: asyncio.Event) -> None:
    """Sleep one tick period, returning early when stop is set."""
    waiters = {asyncio.ensure_future(sleep(TICK_SECONDS)), asyncio.ensure_future(stop.wait())}
    try:
        await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for w in waiters:
            w.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)


async def run(
    settings: dict,
    sources: list[Source],
    *,
    clock: Callable[[], datetime],
    sleep: Callable[[float], Awaitable[None]],
    stop: asyncio.Event,
    metrics: Metrics | None = None,
    state: State | None = None,
) -> None:
    """Tick every 30 s until stop is set; the tick in flight always finishes first."""
    metrics = metrics or Metrics()
    state = state or State.load()
    scheduler = Scheduler(sources, state, settings, clock, sleep, writer=store.write)
    metrics.serve(settings["metrics"]["port"])
    try:
        started = clock()
        for source in sources:
            metrics.init_source(source.name)
            metrics.set_stale_after(source.name, STALE_AFTER_INTERVALS * source.schedule.interval_seconds)
        qa_exporter = qa.QaExporter(metrics)
        qa_exported: datetime | None = None
        while not stop.is_set():
            try:
                for result in await scheduler.tick():
                    metrics.record_run(result)
            except Exception:
                log.exception("scheduler tick failed")
            now = clock()
            _update_gauges(metrics, sources, state, now, started)
            if qa_exported is None or now - qa_exported >= QA_EXPORT_EVERY:
                qa_exported = now
                try:
                    qa_exporter.export(now)
                except Exception:
                    log.exception("cannot export the QA report")
            if stop.is_set():
                break
            await _wait(sleep, stop)
    finally:
        metrics.close()
