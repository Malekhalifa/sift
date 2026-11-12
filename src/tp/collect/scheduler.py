"""Decides which sources are due and runs them: one at a time per rate group, groups in parallel."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from tp.collect.source import RateLimited, RunContext, Source
from tp.collect.state import BACKOFF_CAP_S, State

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    source: str
    ok: bool
    rows: int
    seconds: float
    error: str | None


class Scheduler:
    def __init__(
        self,
        sources: list[Source],
        state: State,
        settings: dict,
        clock: Callable[[], datetime],
        sleep: Callable[[float], Awaitable[None]],
        writer,
    ) -> None:
        self.sources = sources
        self.state = state
        self.settings = settings
        self.clock = clock
        self.sleep = sleep
        self.writer = writer
        self._locks: dict[str, asyncio.Lock] = {}
        self._group_until: dict[str, datetime] = {}

    def _blocked_until(self, source: Source) -> datetime | None:
        """End of the later of the source's own backoff and its group's rate-limit window."""
        windows = [self.state.backoff_until(source.name), self._group_until.get(source.rate_group)]
        return max((w for w in windows if w is not None), default=None)

    def _slot(self, source: Source) -> datetime | None:
        """Next scheduled instant, anchored on the last success; None if it has never succeeded."""
        last = self.state.last_success(source.name)
        return None if last is None else source.schedule.next_after(last)

    def _is_due(self, source: Source, now: datetime) -> bool:
        blocked = self._blocked_until(source)
        if blocked is not None and blocked > now:
            return False
        slot = self._slot(source)
        return slot is None or slot <= now

    def due(self) -> list[Source]:
        now = self.clock()
        return [s for s in self.sources if self._is_due(s, now)]

    def next_due(self, source: Source) -> datetime:
        """When the source will next be due, given its schedule and any backoff window."""
        times = [self._slot(source) or self.clock(), self._blocked_until(source)]
        return max(t for t in times if t is not None)

    async def tick(self) -> list[RunResult]:
        """Run everything due once; each overdue source runs a single time however long it was missed."""
        groups: dict[str, list[Source]] = defaultdict(list)
        for source in self.due():
            groups[source.rate_group].append(source)
        batches = await asyncio.gather(*(self._run_group(g, ss) for g, ss in groups.items()))
        return [r for batch in batches for r in batch]

    async def run_now(self, source: Source) -> RunResult:
        """Run one source immediately, whether or not it is due, serialised within its rate group."""
        async with self._locks.setdefault(source.rate_group, asyncio.Lock()):
            return await self._run_one(source)

    async def _run_group(self, group: str, sources: list[Source]) -> list[RunResult]:
        results: list[RunResult] = []
        lock = self._locks.setdefault(group, asyncio.Lock())
        for source in sources:
            async with lock:
                if not self._is_due(source, self.clock()):
                    continue
                results.append(await self._run_one(source))
        return results

    async def _run_one(self, source: Source) -> RunResult:
        ctx = RunContext(now=self.clock(), settings=self.settings, writer=self.writer)
        t0 = time.perf_counter()
        try:
            rows = await asyncio.to_thread(source.run, ctx)
        except Exception as e:
            seconds = time.perf_counter() - t0
            error = f"{type(e).__name__}: {e}"
            self._record_failure(source, e, error)
            return RunResult(source.name, False, 0, seconds, error)
        seconds = time.perf_counter() - t0
        try:
            self.state.record_success(source.name, self.clock(), rows)
        except OSError:
            log.exception("could not save state after source %s succeeded", source.name)
        return RunResult(source.name, True, rows, seconds, None)

    def _record_failure(self, source: Source, exc: Exception, error: str) -> None:
        now = self.clock()
        retry_after = None
        if isinstance(exc, RateLimited):
            retry_after = min(max(exc.retry_after_s, 0), BACKOFF_CAP_S)
        log.warning("source %s failed: %s", source.name, error)
        try:
            self.state.record_failure(source.name, now, error, retry_after)
        except OSError:
            log.exception("could not save state after source %s failed", source.name)
        if retry_after is not None:
            window_end = self.state.backoff_until(source.name)
            self._group_until[source.rate_group] = max(window_end, self._group_until.get(source.rate_group, window_end))
