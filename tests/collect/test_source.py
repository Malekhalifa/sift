import json
import os
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from tp.collect.datasets import Dataset
from tp.collect.source import (
    Daily,
    Every,
    RateLimited,
    RunContext,
    Source,
    SourceError,
    Weekly,
    parse_schedule,
)
from tp.collect.state import State

NY = ZoneInfo("America/New_York")


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_parse_schedule_kinds():
    assert parse_schedule("daily 21:00 America/New_York") == Daily(time(21, 0), NY)
    assert parse_schedule("weekly sun 09:00 America/New_York") == Weekly(6, time(9, 0), NY)
    assert parse_schedule("weekly mon 06:00 America/New_York") == Weekly(0, time(6, 0), NY)
    assert parse_schedule("daily 06:30 UTC") == Daily(time(6, 30), ZoneInfo("UTC"))
    assert parse_schedule("every 1d") == Every(timedelta(days=1))
    assert parse_schedule("every 15m") == Every(timedelta(minutes=15))
    assert parse_schedule("every 6h") == Every(timedelta(hours=6))


def test_parse_schedule_defaults_to_new_york():
    assert parse_schedule("daily 18:30") == Daily(time(18, 30), NY)
    assert parse_schedule("weekly fri 16:00") == Weekly(4, time(16, 0), NY)


@pytest.mark.parametrize(
    "text",
    ["", "hourly", "daily", "daily 25:00", "daily 9:61", "daily 18:30 Mars/Base", "weekly xyz 09:00",
     "weekly 09:00", "every", "every 0m", "every 5s", "every 1d extra", "daily 18:30 UTC extra"],
)
def test_parse_schedule_rejects_bad_text(text):
    with pytest.raises(ValueError):
        parse_schedule(text)


def test_daily_next_after_is_wall_clock_across_dst():
    s = Daily(time(18, 30), NY)
    # spring forward (Mar 8): 18:30 EST is 23:30 UTC, the next day's 18:30 EDT is 22:30 UTC
    assert s.next_after(utc(2026, 3, 7, 19, 0)) == utc(2026, 3, 7, 23, 30)
    assert s.next_after(utc(2026, 3, 7, 23, 30)) == utc(2026, 3, 8, 22, 30)
    # fall back (Nov 1): 18:30 EDT is 22:30 UTC, the next day's 18:30 EST is 23:30 UTC
    assert s.next_after(utc(2026, 10, 31, 22, 30)) == utc(2026, 11, 1, 23, 30)
    assert s.next_after(utc(2026, 11, 1, 23, 0)) == utc(2026, 11, 1, 23, 30)
    assert s.next_after(utc(2026, 11, 1, 23, 30)) == utc(2026, 11, 2, 23, 30)
    assert s.next_after(utc(2026, 3, 7, 19, 0)).tzinfo is not None


def test_daily_next_after_is_strictly_after():
    s = Daily(time(18, 30), NY)
    at = utc(2026, 6, 1, 22, 30)
    assert s.next_after(at) == utc(2026, 6, 2, 22, 30)
    assert s.next_after(at - timedelta(seconds=1)) == at


def test_daily_next_after_accepts_non_utc_input_and_rejects_naive():
    s = Daily(time(6, 30), ZoneInfo("UTC"))
    assert s.next_after(datetime(2026, 6, 1, 0, 0, tzinfo=NY)) == utc(2026, 6, 1, 6, 30)
    with pytest.raises(ValueError):
        s.next_after(datetime(2026, 6, 1))


def test_daily_skips_a_nonexistent_local_time_without_double_firing():
    s = Daily(time(2, 30), NY)
    first = s.next_after(utc(2026, 3, 8, 0, 0))
    second = s.next_after(first)
    assert first.date() == datetime(2026, 3, 8).date()
    assert second - first < timedelta(hours=25) and second > first


def test_weekly_next_after():
    s = Weekly(0, time(6, 0), NY)
    assert s.next_after(utc(2026, 6, 3, 12, 0)) == utc(2026, 6, 8, 10, 0)
    assert s.next_after(utc(2026, 6, 8, 10, 0)) == utc(2026, 6, 15, 10, 0)
    assert s.next_after(utc(2026, 6, 8, 9, 59)) == utc(2026, 6, 8, 10, 0)
    # across the November fall-back: Monday 06:00 is EST (11:00 UTC) after Nov 1
    assert s.next_after(utc(2026, 10, 27, 12, 0)) == utc(2026, 11, 2, 11, 0)


def test_every_next_after():
    assert Every(timedelta(minutes=15)).next_after(utc(2026, 6, 1, 12, 0)) == utc(2026, 6, 1, 12, 15)
    assert Every(timedelta(days=1)).next_after(utc(2026, 6, 1, 12, 7)) == utc(2026, 6, 2, 12, 7)


def test_interval_seconds():
    assert Daily(time(1, 0), NY).interval_seconds == 86400
    assert Weekly(2, time(1, 0), NY).interval_seconds == 604800
    assert Every(timedelta(hours=6)).interval_seconds == 21600


class Two(Source):
    name = "two"
    rate_group = "none"
    schedule = Every(timedelta(days=1))
    lag = timedelta(0)

    def __init__(self):
        self.a = Dataset(name="a", path=None, key=("id",), ts_col="ts")
        self.b = Dataset(name="b", path=None, key=("id",), ts_col="ts")

    def fetch(self, ctx):
        return {
            self.a: pd.DataFrame({"id": [1, 2, 3], "ts": [ctx.now] * 3}),
            self.b: pd.DataFrame({"id": [1], "ts": [ctx.now]}),
        }


def test_source_run_writes_every_frame_and_sums_rows():
    src, seen = Two(), []

    def writer(ds, frame):
        seen.append(ds.name)
        return len(frame)

    ctx = RunContext(now=utc(2026, 6, 1), settings={}, writer=writer)
    assert src.run(ctx) == 4
    assert seen == ["a", "b"]


def test_source_without_fetch_raises():
    class Bare(Source):
        name = "bare"

    with pytest.raises(NotImplementedError):
        Bare().run(RunContext(now=utc(2026, 6, 1), settings={}, writer=lambda d, f: 0))


def test_rate_limited_carries_retry_after():
    e = RateLimited("slow down", retry_after_s=30.0)
    assert isinstance(e, SourceError) and e.retry_after_s == 30.0


NOW = utc(2026, 6, 1, 12, 0)


def test_state_roundtrip_and_atomic(tmp_path, monkeypatch):
    path = tmp_path / "collect" / "state.json"
    st = State.load(path)
    assert st.last_success("x") is None and st.failures("x") == 0 and st.backoff_until("x") is None
    st.record_success("x", NOW, 7)
    st.record_failure("y", NOW, "boom")

    again = State.load(path)
    assert again.last_success("x") == NOW
    assert again.rows("x") == 7
    assert again.failures("y") == 1 and again.last_error("y") == "boom"
    assert again.backoff_until("y") > NOW
    assert json.loads(path.read_text()) == json.loads(json.dumps(again.snapshot()))

    before = path.read_bytes()

    def boom(*a, **k):
        raise OSError("disk gone")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        st.record_success("x", NOW + timedelta(hours=1), 9)
    assert path.read_bytes() == before
    assert not list(path.parent.glob("*.tmp"))


def test_state_failed_save_still_updates_memory(tmp_path, monkeypatch):
    st = State.load(tmp_path / "s.json")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        st.record_failure("x", NOW, "boom")
    assert st.failures("x") == 1 and st.backoff_until("x") > NOW
    with pytest.raises(OSError):
        st.record_success("x", NOW, 3)
    assert st.last_success("x") == NOW and st.failures("x") == 0


def test_state_failure_backoff_grows_and_success_resets(tmp_path):
    st = State.load(tmp_path / "s.json")
    waits = []
    for i in range(4):
        st.record_failure("x", NOW, "e")
        waits.append(st.backoff_until("x") - NOW)
    assert waits == sorted(waits) and waits[-1] > waits[0]
    assert st.failures("x") == 4
    st.record_success("x", NOW, 1)
    assert st.failures("x") == 0 and st.backoff_until("x") is None and st.last_error("x") is None


def test_state_backoff_is_capped_and_honours_retry_after(tmp_path):
    st = State.load(tmp_path / "s.json")
    for _ in range(40):
        st.record_failure("x", NOW, "e")
    assert st.backoff_until("x") - NOW <= timedelta(hours=6)
    st.record_failure("z", NOW, "rate", retry_after_s=900)
    assert st.backoff_until("z") - NOW == timedelta(seconds=900)


def test_state_default_path_follows_data_dir(tmp_path, monkeypatch):
    from tp import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    State.load().record_success("x", NOW, 1)
    assert (tmp_path / "collect" / "state.json").exists()


def test_state_load_survives_corrupt_file(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json")
    st = State.load(path)
    assert st.last_success("x") is None
    st.record_success("x", NOW, 1)
    assert State.load(path).last_success("x") == NOW
