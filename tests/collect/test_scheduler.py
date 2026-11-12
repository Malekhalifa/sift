import asyncio
import threading
import time as walltime
from datetime import datetime, time, timedelta, timezone

import pytest

from tp.collect.scheduler import RunResult, Scheduler
from tp.collect.source import Daily, Every, RateLimited, RunContext, Source, SourceError
from tp.collect.state import State


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class Clock:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw) -> None:
        self.t += timedelta(**kw)


async def no_sleep(_seconds: float) -> None:
    return None


class Fake(Source):
    """A source whose run is scripted: returns rows, or raises the queued exception."""

    def __init__(self, name, group="default", schedule=None, rows=1, raises=None, log=None, hold=0.0):
        self.name = name
        self.rate_group = group
        self.schedule = schedule or Every(timedelta(hours=1))
        self.rows = rows
        self.raises = raises
        self.log = log if log is not None else []
        self.hold = hold
        self.calls = 0

    def run(self, ctx: RunContext) -> int:
        self.calls += 1
        self.log.append(("start", self.name))
        if self.hold:
            walltime.sleep(self.hold)
        self.log.append(("end", self.name))
        if self.raises is not None:
            raise self.raises
        return self.rows


def make(tmp_path, sources, now=None):
    clock = Clock(now or utc(2026, 3, 2, 12, 0))
    state = State(path=tmp_path / "state.json")
    sched = Scheduler(sources, state, {}, clock, no_sleep, writer=lambda ds, df: 0)
    return sched, state, clock


def tick(sched):
    return asyncio.run(sched.tick())


def test_never_run_source_is_due(tmp_path):
    a = Fake("a", schedule=Daily(time(21, 0), "UTC"))
    sched, _, _ = make(tmp_path, [a])
    assert sched.due() == [a]


def test_every_source_anchors_on_last_success(tmp_path):
    a = Fake("a", schedule=Every(timedelta(hours=1)))
    sched, state, clock = make(tmp_path, [a])
    state.record_success("a", clock.t - timedelta(minutes=30), 5)
    assert sched.due() == []
    clock.advance(minutes=30)
    assert sched.due() == [a]


def test_daily_source_not_due_before_its_slot_and_due_after(tmp_path):
    a = Fake("a", schedule=Daily(time(21, 0), "UTC"))
    sched, state, clock = make(tmp_path, [a], now=utc(2026, 3, 2, 22, 0))
    state.record_success("a", utc(2026, 3, 2, 21, 0, 5), 5)
    assert sched.due() == []
    clock.t = utc(2026, 3, 3, 21, 0, 1)
    assert sched.due() == [a]


def test_tick_runs_due_source_and_records_success(tmp_path):
    a = Fake("a", rows=7)
    sched, state, clock = make(tmp_path, [a])
    results = tick(sched)
    assert results == [RunResult("a", True, 7, results[0].seconds, None)]
    assert results[0].seconds >= 0
    assert state.last_success("a") == clock.t
    assert state.rows("a") == 7
    assert sched.due() == []
    assert tick(sched) == []
    assert a.calls == 1


def test_source_runs_once_after_a_long_sleep(tmp_path):
    a = Fake("a", schedule=Daily(time(21, 0), "UTC"))
    sched, state, clock = make(tmp_path, [a], now=utc(2026, 3, 2, 22, 0))
    state.record_success("a", utc(2026, 3, 2, 21, 0, 5), 5)
    clock.t = utc(2026, 3, 5, 12, 0)

    assert sched.due() == [a]
    assert len(tick(sched)) == 1
    assert tick(sched) == []
    assert a.calls == 1
    assert state.last_success("a") == utc(2026, 3, 5, 12, 0)
    assert sched.due() == []
    assert sched.next_due(a) == utc(2026, 3, 5, 21, 0)

    clock.t = utc(2026, 3, 5, 21, 0, 1)
    assert sched.due() == [a]


def test_every_source_after_a_long_sleep_runs_once_and_waits_a_period(tmp_path):
    a = Fake("a", schedule=Every(timedelta(hours=1)))
    sched, state, clock = make(tmp_path, [a])
    state.record_success("a", clock.t, 1)
    clock.advance(days=3)
    assert len(tick(sched)) == 1
    assert tick(sched) == []
    assert sched.next_due(a) == clock.t + timedelta(hours=1)


def test_one_failure_does_not_block_other_sources(tmp_path):
    bad = Fake("bad", group="sec", raises=SourceError("boom"))
    same_group = Fake("same", group="sec")
    other = Fake("other", group="finra")
    sched, state, _ = make(tmp_path, [bad, same_group, other])
    results = {r.source: r for r in tick(sched)}
    assert results["bad"].ok is False
    assert results["same"].ok is True
    assert results["other"].ok is True
    assert state.last_success("same") is not None
    assert state.last_success("other") is not None
    assert state.failures("bad") == 1


def test_same_rate_group_runs_serially(tmp_path):
    log: list = []
    a = Fake("a", group="sec", log=log, hold=0.05)
    b = Fake("b", group="sec", log=log, hold=0.05)
    sched, _, _ = make(tmp_path, [a, b])
    tick(sched)
    assert len(log) == 4
    assert log[0][0] == "start" and log[1] == ("end", log[0][1])
    assert log[2][0] == "start" and log[3] == ("end", log[2][1])
    assert {log[0][1], log[2][1]} == {"a", "b"}


def test_different_rate_groups_run_concurrently(tmp_path):
    barrier = threading.Barrier(2, timeout=5)

    class Rendezvous(Fake):
        def run(self, ctx):
            barrier.wait()
            return 1

    a = Rendezvous("a", group="sec")
    b = Rendezvous("b", group="finra")
    sched, _, _ = make(tmp_path, [a, b])
    results = tick(sched)
    assert [r.ok for r in results] == [True, True]


def test_overlapping_ticks_do_not_run_a_source_twice(tmp_path):
    a = Fake("a", group="sec", hold=0.05)
    sched, _, _ = make(tmp_path, [a])

    async def two_ticks():
        return await asyncio.gather(sched.tick(), sched.tick())

    first, second = asyncio.run(two_ticks())
    assert a.calls == 1
    assert len(first) + len(second) == 1


def test_rate_limit_backs_off_only_its_group(tmp_path):
    limited = Fake("limited", group="sec", raises=RateLimited("429", retry_after_s=600))
    sibling = Fake("sibling", group="sec")
    other = Fake("other", group="finra")
    sched, state, clock = make(tmp_path, [limited, sibling, other])
    start = clock.t

    results = {r.source: r for r in tick(sched)}
    assert set(results) == {"limited", "other"}
    assert results["limited"].ok is False
    assert sibling.calls == 0
    assert other.calls == 1
    assert state.backoff_until("limited") == start + timedelta(seconds=600)
    assert state.failures("sibling") == 0

    assert sibling not in sched.due()
    assert other not in sched.due()
    clock.advance(seconds=599)
    assert sibling not in sched.due()
    clock.advance(seconds=2)
    assert sibling in sched.due()
    assert limited in sched.due()
    limited.raises = None
    tick(sched)
    assert sibling.calls == 1


def test_rate_limit_window_does_not_touch_other_groups_due_sources(tmp_path):
    limited = Fake("limited", group="sec", raises=RateLimited("429", retry_after_s=600))
    other = Fake("other", group="finra", schedule=Every(timedelta(minutes=5)))
    sched, state, clock = make(tmp_path, [limited, other])
    tick(sched)
    clock.advance(minutes=6)
    assert sched.due() == [other]


@pytest.mark.parametrize("given, expected", [(10**9, 6 * 3600), (-5, 60), (0, 60), (90, 90)])
def test_rate_limit_retry_after_is_clamped(tmp_path, given, expected):
    a = Fake("a", raises=RateLimited("429", retry_after_s=given))
    sched, state, clock = make(tmp_path, [a])
    tick(sched)
    assert state.backoff_until("a") == clock.t + timedelta(seconds=expected)


def test_retry_after_below_the_exponential_backoff_does_not_shorten_it(tmp_path):
    a = Fake("a", raises=RateLimited("429", retry_after_s=30))
    sched, state, clock = make(tmp_path, [a])
    for _ in range(4):
        tick(sched)
        clock.t = state.backoff_until("a")
    tick(sched)
    assert state.failures("a") == 5
    assert state.backoff_until("a") == clock.t + timedelta(seconds=960)


def test_group_window_matches_the_effective_backoff_of_the_limited_source(tmp_path):
    limited = Fake("limited", group="sec", raises=RateLimited("429", retry_after_s=30))
    sibling = Fake("sibling", group="sec")
    sched, state, clock = make(tmp_path, [limited, sibling])
    state.record_failure("limited", clock.t, "earlier", None)
    state.record_failure("limited", clock.t, "earlier", None)
    state.record_failure("limited", clock.t, "earlier", None)
    clock.t = state.backoff_until("limited")
    start = clock.t
    tick(sched)
    assert state.backoff_until("limited") == start + timedelta(seconds=480)
    assert sibling.calls == 0
    clock.advance(seconds=479)
    assert sibling not in sched.due()
    clock.advance(seconds=1)
    assert sibling in sched.due()


def test_backoff_grows_and_caps(tmp_path):
    a = Fake("a", raises=SourceError("down"))
    sched, state, clock = make(tmp_path, [a])
    waits = []
    for _ in range(12):
        tick(sched)
        waits.append((state.backoff_until("a") - clock.t).total_seconds())
        assert sched.due() == []
        clock.t = state.backoff_until("a")
    assert waits[:4] == [60, 120, 240, 480]
    assert waits[-1] == 6 * 3600
    assert max(waits) == 6 * 3600
    assert waits == sorted(waits)
    assert state.failures("a") == 12


def test_source_in_backoff_is_not_due_until_the_window_ends(tmp_path):
    a = Fake("a", raises=SourceError("down"))
    sched, _, clock = make(tmp_path, [a])
    tick(sched)
    clock.advance(seconds=59)
    assert tick(sched) == []
    clock.advance(seconds=1)
    assert len(tick(sched)) == 1


def test_success_resets_failures(tmp_path):
    a = Fake("a", raises=SourceError("down"))
    sched, state, clock = make(tmp_path, [a])
    tick(sched)
    clock.t = state.backoff_until("a")
    tick(sched)
    assert state.failures("a") == 2

    a.raises = None
    clock.t = state.backoff_until("a")
    results = tick(sched)
    assert results[0].ok is True
    assert state.failures("a") == 0
    assert state.backoff_until("a") is None
    assert state.last_error("a") is None


def test_exception_inside_source_is_caught_and_recorded(tmp_path):
    a = Fake("a", raises=RuntimeError("kaboom"))
    b = Fake("b")
    sched, state, _ = make(tmp_path, [a, b])
    results = {r.source: r for r in tick(sched)}
    assert results["a"].ok is False
    assert results["a"].rows == 0
    assert "RuntimeError" in results["a"].error and "kaboom" in results["a"].error
    assert "kaboom" in state.last_error("a")
    assert state.failures("a") == 1
    assert state.backoff_until("a") is not None
    assert results["b"].ok is True


def test_ctx_carries_now_settings_and_writer(tmp_path):
    seen = {}

    class Spy(Fake):
        def run(self, ctx):
            seen["ctx"] = ctx
            return 0

    clock = Clock(utc(2026, 3, 2, 12, 0))
    writer = lambda ds, df: 0  # noqa: E731
    sched = Scheduler([Spy("s")], State(path=tmp_path / "s.json"), {"k": 1}, clock, no_sleep, writer)
    tick(sched)
    assert seen["ctx"].now == clock.t
    assert seen["ctx"].settings == {"k": 1}
    assert seen["ctx"].writer is writer
