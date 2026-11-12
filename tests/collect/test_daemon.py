import asyncio
import threading
from datetime import datetime, timedelta, timezone

import pytest
from prometheus_client import CollectorRegistry

from tp import config
from tp.collect import cli, daemon
from tp.collect.daemon import AlreadyRunning, acquire_lock
from tp.collect.metrics import Metrics
from tp.collect.source import Daily, Every, Source
from tp.collect.state import State

T0 = datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc)
SETTINGS = {"metrics": {"port": 0}}


class Fake(Source):
    def __init__(self, name, schedule=None, rows=2, on_run=None, raises=None):
        self.name = name
        self.schedule = schedule or Every(timedelta(hours=1))
        self.rows = rows
        self.on_run = on_run
        self.raises = raises
        self.calls = 0

    def run(self, ctx):
        self.calls += 1
        if self.on_run:
            self.on_run()
        if self.raises:
            raise self.raises
        return self.rows


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


def sample(metrics, name, **labels):
    return metrics.registry.get_sample_value(name, labels)


def run_daemon(sources, *, stop, sleep, clock=None, metrics=None, state=None):
    async def go():
        await daemon.run(
            SETTINGS, sources, clock=clock or Clock(), sleep=sleep, stop=stop,
            metrics=metrics, state=state,
        )

    asyncio.run(go())


def test_second_daemon_refuses_to_start(tmp_path):
    path = tmp_path / ".collect.lock"
    first = acquire_lock(path)
    try:
        with pytest.raises(AlreadyRunning):
            acquire_lock(path)
    finally:
        first.close()
    acquire_lock(path).close()


def test_stop_event_ends_the_loop_after_the_current_tick(tmp_path):
    state = State(path=tmp_path / "state.json")
    holder = {}
    stop_later = lambda: holder["loop"].call_soon_threadsafe(holder["stop"].set)  # noqa: E731
    src = Fake("a", on_run=stop_later)

    async def go():
        holder["loop"] = asyncio.get_running_loop()
        holder["stop"] = asyncio.Event()
        slept = []

        async def sleep(s):
            slept.append(s)
            await asyncio.Event().wait()

        await daemon.run(
            SETTINGS, [src], clock=Clock(), sleep=sleep, stop=holder["stop"],
            metrics=Metrics(CollectorRegistry()), state=state,
        )
        return slept

    slept = asyncio.run(go())
    assert src.calls == 1
    assert state.last_success("a") == T0
    assert slept == []


def test_loop_ticks_every_thirty_seconds_and_keeps_going_after_a_tick_failure(tmp_path, monkeypatch):
    state = State(path=tmp_path / "state.json")
    src = Fake("a")
    stop = None
    sleeps = []
    ticks = []
    real_tick = daemon.Scheduler.tick

    async def flaky_tick(self):
        ticks.append(1)
        if len(ticks) == 1:
            raise OSError("disk full")
        return await real_tick(self)

    monkeypatch.setattr(daemon.Scheduler, "tick", flaky_tick)

    async def go():
        stop = asyncio.Event()

        async def sleep(s):
            sleeps.append(s)
            if len(sleeps) == 2:
                stop.set()

        await daemon.run(
            SETTINGS, [src], clock=Clock(), sleep=sleep, stop=stop,
            metrics=Metrics(CollectorRegistry()), state=state,
        )

    asyncio.run(go())
    assert sleeps[:2] == [30, 30]
    assert len(ticks) == 2
    assert src.calls == 1


def test_stop_during_sleep_exits_without_another_tick(tmp_path):
    src = Fake("a")

    async def go():
        stop = asyncio.Event()

        async def sleep(s):
            asyncio.get_running_loop().call_soon(stop.set)
            await asyncio.Event().wait()

        await daemon.run(
            SETTINGS, [src], clock=Clock(), sleep=sleep, stop=stop,
            metrics=Metrics(CollectorRegistry()), state=State(path=tmp_path / "s.json"),
        )

    asyncio.run(go())
    assert src.calls == 1


def test_metrics_series_are_initialised_and_updated(tmp_path):
    metrics = Metrics(CollectorRegistry())
    good = Fake("good", schedule=Daily(T0.time(), "UTC"))
    bad = Fake("bad", raises=RuntimeError("boom"))
    seen = {}

    async def go():
        stop = asyncio.Event()

        async def sleep(s):
            seen["rows"] = sample(metrics, "sift_source_rows_total", source="good")
            seen["errors"] = sample(metrics, "sift_source_errors_total", source="bad")
            seen["stale_good"] = sample(metrics, "sift_source_stale_after_seconds", source="good")
            seen["stale_bad"] = sample(metrics, "sift_source_stale_after_seconds", source="bad")
            seen["age"] = sample(metrics, "sift_source_last_success_age_seconds", source="good")
            seen["disk"] = sample(metrics, "sift_disk_free_bytes")
            stop.set()

        await daemon.run(
            SETTINGS, [good, bad], clock=Clock(), sleep=sleep, stop=stop,
            metrics=metrics, state=State(path=tmp_path / "s.json"),
        )

    asyncio.run(go())
    assert seen["rows"] == 2
    assert seen["errors"] == 1
    assert seen["stale_good"] == 2 * 86400
    assert seen["stale_bad"] == 2 * 3600
    assert seen["age"] == 0
    assert seen["disk"] > 0


def test_series_exist_at_zero_before_any_run(tmp_path):
    metrics = Metrics(CollectorRegistry())
    src = Fake("idle")
    stop = asyncio.Event()
    stop.set()
    run_daemon([src], stop=stop, sleep=lambda s: asyncio.sleep(0), metrics=metrics, state=State(path=tmp_path / "s.json"))
    assert sample(metrics, "sift_source_rows_total", source="idle") == 0
    assert sample(metrics, "sift_source_errors_total", source="idle") == 0
    assert sample(metrics, "sift_source_stale_after_seconds", source="idle") == 7200
    assert src.calls == 0


def test_metrics_server_is_closed_on_shutdown(tmp_path):
    metrics = Metrics(CollectorRegistry())
    stop = asyncio.Event()
    stop.set()
    run_daemon([], stop=stop, sleep=lambda s: asyncio.sleep(0), metrics=metrics, state=State(path=tmp_path / "s.json"))
    assert metrics.server_address is None


@pytest.fixture
def registry(monkeypatch):
    a, b = Fake("alpha"), Fake("beta", raises=RuntimeError("down"))
    monkeypatch.setattr(cli, "build_sources", lambda settings: [a, b])
    return a, b


def test_once_runs_a_single_named_source_and_updates_state(registry, capsys):
    a, b = registry
    assert cli.main(["once", "alpha"]) == 0
    assert (a.calls, b.calls) == (1, 0)
    state = State.load()
    assert state.last_success("alpha") is not None
    assert state.rows("alpha") == 2
    assert "alpha" in capsys.readouterr().out


def test_once_reports_a_failing_source_with_exit_one(registry, capsys):
    assert cli.main(["once", "beta"]) == 1
    assert State.load().failures("beta") == 1
    assert "down" in capsys.readouterr().err


def test_once_refuses_while_the_daemon_holds_the_lock(registry, capsys):
    held = acquire_lock(config.DATA_DIR / ".collect.lock")
    try:
        assert cli.main(["once", "alpha"]) == 1
    finally:
        held.close()
    assert registry[0].calls == 0
    assert "already running" in capsys.readouterr().err.lower()


def test_status_lists_every_registered_source(registry, capsys):
    State.load().record_success("alpha", T0, 5)
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "alpha" in out and "beta" in out
    assert "2026-03-02" in out
    assert "never" in out


def test_unknown_source_name_exits_with_a_message(registry, capsys):
    assert cli.main(["once", "nope"]) == 2
    err = capsys.readouterr().err
    assert "nope" in err and "alpha" in err and "beta" in err
    assert registry[0].calls == 0


def test_qa_calls_run_qa_with_the_requested_date(registry, capsys, monkeypatch):
    calls = []

    def run_qa(now, state, settings, full=False):
        calls.append((now, full))
        return {"date": "2026-03-01", "sources": {"alpha": {"checks": {"freshness": {"ok": True, "detail": ""}}}}}

    monkeypatch.setattr(cli, "run_qa", run_qa)
    assert cli.main(["qa", "--date", "2026-03-01"]) == 0
    assert calls[0][0].date().isoformat() == "2026-03-01"
    assert calls[0][0].tzinfo is not None
    assert calls[0][1] is False
    assert cli.main(["qa", "--full"]) == 0
    assert calls[1][1] is True
