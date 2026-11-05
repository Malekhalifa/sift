from datetime import UTC, date, datetime, timedelta

import pandas as pd

from tp import recorder, store


class FakeClient:
    """One bar per day at 15:00Z inside [start, end)."""

    def __init__(self):
        self.calls = []

    def bars(self, symbol, timeframe, start, end, feed="iex", **_):
        self.calls.append((start, end))
        day = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while day < end:
            t = day.replace(hour=15)
            if start <= t < end and t.weekday() < 5:
                yield {"t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10, "n": 1, "vw": 1.2}
            day += timedelta(days=1)


def test_fetch_end_daily_waits_for_extended_session_close():
    morning = datetime(2025, 2, 10, 14, 0, tzinfo=UTC)  # 09:00 EST
    evening = datetime(2025, 2, 11, 1, 45, tzinfo=UTC)  # 20:45 EST on Feb 10
    assert recorder.fetch_end("sip", "1Day", morning) == datetime(2025, 2, 10, 5, 0, tzinfo=UTC)
    assert recorder.fetch_end("sip", "1Day", evening) == datetime(2025, 2, 11, 5, 0, tzinfo=UTC)


def test_fetch_end_minutes_respects_feed_lag():
    now = datetime(2025, 2, 10, 15, 37, 42, tzinfo=UTC)
    assert recorder.fetch_end("sip", "1Min", now) == datetime(2025, 2, 10, 15, 17, tzinfo=UTC)
    assert recorder.fetch_end("iex", "1Min", now) == datetime(2025, 2, 10, 15, 35, tzinfo=UTC)


def test_sync_series_backfills_then_resumes(monkeypatch):
    monkeypatch.setitem(recorder.FEED_START, "sip", date(2023, 12, 1))
    now = datetime(2025, 2, 10, 18, 0, tzinfo=UTC)
    client = FakeClient()

    first = recorder.sync_series(client, "sip", "1Min", "AAA", now)
    assert first > 0
    assert len(client.calls) == 3  # 2023, 2024, 2025
    stored = store.load_raw("sip", "1Min", "AAA")
    assert stored.index.is_monotonic_increasing and stored.index.is_unique

    client.calls.clear()
    assert recorder.sync_series(client, "sip", "1Min", "AAA", now) == 0
    assert len(client.calls) == 1  # finished years skipped, current year re-fetched with overlap
    start, _ = client.calls[0]
    assert start >= stored.index.max().to_pydatetime() - recorder.OVERLAP

    later = now + timedelta(days=3)
    assert recorder.sync_series(client, "sip", "1Min", "AAA", later) > 0
    assert store.last_ts("sip", "1Min", "AAA") > pd.Timestamp(now)


def test_sync_series_refetches_missing_past_year(monkeypatch):
    monkeypatch.setitem(recorder.FEED_START, "sip", date(2023, 12, 1))
    now = datetime(2025, 2, 10, 18, 0, tzinfo=UTC)
    client = FakeClient()
    recorder.sync_series(client, "sip", "1Min", "AAA", now)

    store.year_path("sip", "1Min", "AAA", 2024).unlink()  # simulate an interrupted/incomplete backfill
    client.calls.clear()
    recorder.sync_series(client, "sip", "1Min", "AAA", now)
    assert len(client.calls) == 2  # missing 2024 plus the current-year overlap
    assert 2024 in store.stored_years("sip", "1Min", "AAA")


def test_build_plan_gives_each_universe_its_own_bar_types(monkeypatch):
    from tp import config

    monkeypatch.setattr(config, "core_symbols", lambda: ["AAA", "SPY"])
    monkeypatch.setattr(config, "wide_symbols", lambda: ["WIDE1", "WIDE2"])
    everything = list(recorder.SPECS)
    plan = recorder.build_plan(None, "all", everything)
    assert ("sip", "1Min", "AAA") in plan and ("iex", "1Min", "AAA") in plan
    assert ("sip", "5Min", "WIDE1") in plan and ("sip", "1Day", "WIDE2") in plan
    assert ("sip", "1Min", "WIDE1") not in plan and ("iex", "1Min", "WIDE1") not in plan  # wide skips 1-minute data
    assert ("sip", "5Min", "AAA") not in plan  # core derives 5-minute bars from 1-minute data
    assert plan.index(("sip", "1Day", "AAA")) < plan.index(("sip", "1Min", "AAA"))  # spec order kept
    assert {s for *_, s in recorder.build_plan(None, "wide", everything)} == {"WIDE1", "WIDE2"}
    assert recorder.build_plan(["WIDE2"], "all", [("sip", "5Min")]) == [("sip", "5Min", "WIDE2")]


def test_run_plan_parallel_matches_sequential_and_isolates_failures(monkeypatch, tmp_data_dir):
    from tp import store as st

    monkeypatch.setitem(recorder.FEED_START, "sip", date(2023, 12, 1))
    now = datetime(2025, 2, 10, 18, 0, tzinfo=UTC)
    plan = [("sip", "5Min", s) for s in ("AAA", "BBB", "CCC", "DDD")]

    class Flaky(FakeClient):
        def bars(self, symbol, *a, **k):
            if symbol == "CCC":
                raise RuntimeError("boom")
            yield from super().bars(symbol, *a, **k)

    failures = recorder.run_plan(Flaky(), plan, now, workers=4)
    assert len(failures) == 1 and "CCC" in failures[0] and "boom" in failures[0]
    assert st.stored_years("sip", "5Min", "AAA") and not st.stored_years("sip", "5Min", "CCC")
    parallel = {s: st.load_raw("sip", "5Min", s) for s in ("AAA", "BBB", "DDD")}

    for s in ("AAA", "BBB", "DDD"):  # a sequential run into a clean store must give identical bars
        for y in st.stored_years("sip", "5Min", s):
            st.year_path("sip", "5Min", s, y).unlink()
    assert recorder.run_plan(FakeClient(), [("sip", "5Min", s) for s in ("AAA", "BBB", "DDD")], now, workers=1) == []
    for s, df in parallel.items():
        assert df.equals(st.load_raw("sip", "5Min", s))
