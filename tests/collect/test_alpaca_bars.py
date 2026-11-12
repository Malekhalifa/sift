import fcntl
from datetime import UTC, date, datetime, timedelta

import pytest

from tp import config, recorder
from tp.collect.source import Daily, RunContext, SourceError
from tp.collect.sources import build_sources
from tp.collect.sources.alpaca_bars import AlpacaBars

NOW = datetime(2025, 2, 11, 2, 0, tzinfo=UTC)  # 21:00 EST
SETTINGS = {"sources": {"alpaca_bars": {"schedule": "daily 21:00 America/New_York", "lag_minutes": 20}}}


class FakeClient:
    """One bar per weekday at 15:00Z inside [start, end); records every request."""

    def __init__(self, fail=()):
        self.fail = set(fail)
        self.ends = []
        self.split_symbols = None

    def bars(self, symbol, timeframe, start, end, feed="iex", **_):
        if symbol in self.fail:
            raise RuntimeError("boom")
        self.ends.append(end)
        day = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while day < end:
            t = day.replace(hour=15)
            if start <= t < end and t.weekday() < 5:
                yield {"t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10, "n": 1, "vw": 1.2}
            day += timedelta(days=1)

    def splits(self, symbols, start, end):
        self.split_symbols = set(symbols)
        return []


@pytest.fixture(autouse=True)
def universe(monkeypatch):
    monkeypatch.setattr(config, "core_symbols", lambda: ["AAA"])
    monkeypatch.setattr(config, "wide_symbols", lambda: ["WID"])
    monkeypatch.setattr(config, "events_symbols", lambda: ["EVT"])
    monkeypatch.setattr(config, "confirm_symbols", lambda: ["CNF"])
    monkeypatch.setattr(config, "sf_symbols", lambda: ["SFX"])
    monkeypatch.setitem(recorder.FEED_START, "sip", date(2025, 1, 1))
    monkeypatch.setitem(recorder.FEED_START, "iex", date(2025, 1, 1))


def ctx():
    return RunContext(now=NOW, settings=SETTINGS, writer=lambda ds, df: 0)


def source(client):
    return AlpacaBars(client_factory=lambda: client)


def test_declares_name_group_schedule_and_lag():
    s = AlpacaBars(schedule="daily 21:00 America/New_York", lag_minutes=20)
    assert (s.name, s.rate_group, s.lag) == ("alpaca_bars", "alpaca", timedelta(minutes=20))
    assert isinstance(s.schedule, Daily)


def test_build_sources_registers_it_from_settings():
    found = [s for s in build_sources(SETTINGS) if s.name == "alpaca_bars"]
    assert len(found) == 1 and found[0].lag == timedelta(minutes=20)


def test_constructor_never_builds_a_client_or_takes_the_lock(monkeypatch):
    monkeypatch.setattr(config.Settings, "from_env", classmethod(lambda cls: pytest.fail("built a client")))
    AlpacaBars(schedule="daily 21:00", lag_minutes=20)


def test_run_always_plans_the_full_universe(monkeypatch):
    seen = []
    real = recorder.build_plan
    monkeypatch.setattr(recorder, "build_plan", lambda symbols, universe, specs: seen.append((symbols, universe)) or real(symbols, universe, specs))
    client = FakeClient()
    source(client).run(ctx())
    assert seen == [(None, "all")]
    assert client.split_symbols == {"AAA", "WID", "EVT", "CNF", "SFX"}


def test_failed_series_raise_source_error_with_names():
    with pytest.raises(SourceError) as e:
        source(FakeClient(fail={"AAA", "WID"})).run(ctx())
    assert "AAA" in str(e.value) and "WID" in str(e.value) and "EVT" not in str(e.value)


def test_failure_message_is_truncated_to_twenty_series(monkeypatch):
    monkeypatch.setattr(config, "core_symbols", lambda: [f"S{i:02d}" for i in range(30)])
    monkeypatch.setattr(config, "wide_symbols", lambda: [])
    monkeypatch.setattr(config, "events_symbols", lambda: [])
    monkeypatch.setattr(config, "confirm_symbols", lambda: [])
    monkeypatch.setattr(config, "sf_symbols", lambda: [])
    with pytest.raises(SourceError) as e:
        source(FakeClient(fail={f"S{i:02d}" for i in range(30)})).run(ctx())
    assert str(e.value).count("boom") == 20 and "more" in str(e.value)


def test_does_not_request_past_now_minus_lag():
    client = FakeClient()
    source(client).run(ctx())
    expected = {recorder.fetch_end(feed, tf, NOW) for feed, tf in recorder.SPECS}
    assert set(client.ends) == expected
    assert all(end <= NOW - timedelta(minutes=2) for end in client.ends)


def test_returns_bars_added():
    client = FakeClient()
    added = source(client).run(ctx())
    assert added > 0
    assert source(client).run(ctx()) == 0  # nothing new on a re-run


def test_raises_when_another_run_holds_the_lock_and_releases_its_own():
    lock = open(config.DATA_DIR / ".recorder.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    client = FakeClient()
    with pytest.raises(SourceError, match="another recorder run holds the lock"):
        source(client).run(ctx())
    assert client.ends == []
    fcntl.flock(lock, fcntl.LOCK_UN)
    lock.close()
    source(client).run(ctx())  # not blocked, and finishing leaves the lock free
    again = open(config.DATA_DIR / ".recorder.lock", "w")
    fcntl.flock(again, fcntl.LOCK_EX | fcntl.LOCK_NB)
    again.close()


def test_release_lock_even_when_a_series_fails():
    with pytest.raises(SourceError):
        source(FakeClient(fail={"AAA"})).run(ctx())
    lock = open(config.DATA_DIR / ".recorder.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    lock.close()
