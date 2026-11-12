import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from prometheus_client import CollectorRegistry

from conftest import dbars
from tp import config, store as bar_store
from tp.collect import cli, qa
from tp.collect.datasets import DATASETS
from tp.collect.metrics import Metrics

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
SETTINGS = {
    "sources": {
        "sec_form4": {"schedule": "daily 08:00 America/New_York"},
        "alpaca_bars": {"schedule": "daily 21:00 America/New_York"},
    }
}
FORM4_SETTINGS = {"sources": {"sec_form4": SETTINGS["sources"]["sec_form4"]}}
DATASET_CHECKS = {"freshness", "duplicates", "future_timestamps", "schema", "row_count"}
PRICE_CHECKS = {"freshness", "calendar_completeness", "price_jumps"}


class FakeState:
    def __init__(self, **last_success):
        self.last = last_success

    def last_success(self, name):
        return self.last.get(name)


def fresh_state():
    return FakeState(sec_form4=NOW - timedelta(hours=3), alpaca_bars=NOW - timedelta(hours=15))


def form4_at(plan, now=NOW):
    """Form 4 trades from (days_before_now, row_count) pairs, ingested that many days before now."""
    rows, n = [], 0
    for back, count in plan:
        for _ in range(count):
            rows.append({
                "trade_id": f"t{n}", "owner_cik": "1", "filing_date": pd.Timestamp("2026-11-01", tz="UTC"),
                "shares": 10.0, "ingested_at": pd.Timestamp(now - timedelta(days=back)),
            })
            n += 1
    return pd.DataFrame(rows)


def daily(per_day=10, first=40, last=1, now=NOW, weekdays_only=False):
    days = range(first, last - 1, -1)
    return [(d, per_day) for d in days if not weekdays_only or (now - timedelta(days=d)).weekday() < 5]


def form4_rows(per_day, today=None):
    return form4_at(daily(per_day) + ([(0, today)] if today else []))


def put(name, df):
    path = DATASETS[name].path
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def put_bars(symbol, ohlc, start="2026-10-05"):
    bar_store.write_bars("sip", "1Day", symbol, dbars(ohlc, start=start))


def flat(n, price=100.0):
    return [(price, price, price, price)] * n


@pytest.fixture(autouse=True)
def universe(monkeypatch):
    monkeypatch.setattr(config, "core_symbols", lambda: ["SPY", "AAA"])
    for name in ("wide_symbols", "events_symbols", "confirm_symbols", "sf_symbols"):
        monkeypatch.setattr(config, name, lambda: [])


@pytest.fixture
def clean():
    put("form4", form4_rows(10, today=10))
    put_bars("SPY", flat(20))
    put_bars("AAA", flat(20))


def checks(report, source):
    return report["sources"][source]["checks"]


def test_clean_data_passes_everything(clean):
    report = qa.run_qa(NOW, fresh_state(), SETTINGS)
    assert report["date"] == "2026-11-12"
    assert set(checks(report, "sec_form4")) == DATASET_CHECKS
    assert set(checks(report, "alpaca_bars")) == PRICE_CHECKS
    failed = {(s, c): v["detail"] for s, b in report["sources"].items() for c, v in b["checks"].items() if not v["ok"]}
    assert failed == {}
    assert all(set(v) == {"ok", "detail"} for b in report["sources"].values() for v in b["checks"].values())


def test_stale_source_fails_freshness(clean):
    state = fresh_state()
    state.last["sec_form4"] = NOW - timedelta(days=2, minutes=1)
    out = checks(qa.run_qa(NOW, state, SETTINGS), "sec_form4")["freshness"]
    assert not out["ok"]


def test_source_just_inside_twice_the_interval_is_fresh(clean):
    state = fresh_state()
    state.last["sec_form4"] = NOW - timedelta(days=2) + timedelta(minutes=1)
    assert checks(qa.run_qa(NOW, state, SETTINGS), "sec_form4")["freshness"]["ok"]


def test_never_succeeded_source_fails_freshness(clean):
    out = checks(qa.run_qa(NOW, FakeState(), SETTINGS), "sec_form4")["freshness"]
    assert not out["ok"] and "never" in out["detail"]


def test_missing_dataset_fails_freshness_when_enabled_and_never_raises():
    out = qa.run_qa(NOW, fresh_state(), FORM4_SETTINGS)
    c = checks(out, "sec_form4")
    assert c["freshness"]["ok"] is False and "dataset not found" in c["freshness"]["detail"]


def test_missing_dataset_of_a_disabled_source_is_skipped():
    settings = {"sources": {"sec_form4": {"schedule": "daily 08:00", "enabled": False}}}
    assert qa.run_qa(NOW, FakeState(), settings)["sources"] == {}


def test_duplicate_keys_are_caught(clean):
    df = form4_rows(10, today=10)
    put("form4", pd.concat([df, df.iloc[:3]], ignore_index=True))
    out = checks(qa.run_qa(NOW, fresh_state(), FORM4_SETTINGS), "sec_form4")["duplicates"]
    assert not out["ok"] and "3" in out["detail"]


def test_future_timestamp_is_caught(clean):
    df = form4_rows(10, today=10)
    df.loc[0, "filing_date"] = pd.Timestamp(NOW + timedelta(days=5))
    put("form4", df)
    assert not checks(qa.run_qa(NOW, fresh_state(), FORM4_SETTINGS), "sec_form4")["future_timestamps"]["ok"]


def test_timestamp_within_a_day_of_now_is_not_future(clean):
    df = form4_rows(10, today=10)
    df.loc[0, "filing_date"] = pd.Timestamp(NOW + timedelta(hours=23))
    put("form4", df)
    assert checks(qa.run_qa(NOW, fresh_state(), FORM4_SETTINGS), "sec_form4")["future_timestamps"]["ok"]


def schema(settings=FORM4_SETTINGS, **kw):
    return checks(qa.run_qa(NOW, fresh_state(), settings, **kw), "sec_form4")["schema"]


def test_schema_drift_is_caught(clean):
    assert schema()["ok"]
    assert "shares" in json.loads((config.DATA_DIR / "qa" / "schemas.json").read_text())["form4"]
    put("form4", form4_rows(10, today=10).drop(columns=["shares"]))
    drift = schema()
    assert not drift["ok"] and "shares" in drift["detail"]


def test_scheduled_run_reports_drift_once_then_the_next_passes(clean):
    schema()
    put("form4", form4_rows(10, today=10).drop(columns=["shares"]))
    drift = schema()
    assert not drift["ok"] and "shares" in drift["detail"]
    assert schema()["ok"]
    assert "shares" not in json.loads((config.DATA_DIR / "qa" / "schemas.json").read_text())["form4"]


def test_no_advance_run_does_not_consume_drift_or_touch_the_days_report(clean):
    schema()
    put("form4", form4_rows(10, today=10).drop(columns=["shares"]))
    daily_report = config.DATA_DIR / "qa" / "2026-11-12.json"
    baseline = (config.DATA_DIR / "qa" / "schemas.json").read_text()
    scheduled_before = daily_report.read_text()
    for _ in range(2):
        out = schema(advance_baseline=False)
        assert not out["ok"] and "shares" in out["detail"]
    assert (config.DATA_DIR / "qa" / "schemas.json").read_text() == baseline
    assert daily_report.read_text() == scheduled_before
    assert (config.DATA_DIR / "qa" / "2026-11-12-manual.json").exists()
    assert not schema()["ok"]  # the scheduled run still sees the drift
    assert schema()["ok"]


def test_no_advance_run_records_nothing_on_first_sight(clean):
    out = schema(advance_baseline=False)
    assert out["ok"]
    assert not (config.DATA_DIR / "qa" / "schemas.json").exists()
    assert not (config.DATA_DIR / "qa" / "2026-11-12.json").exists()


def test_metrics_no_longer_decides_whether_the_baseline_advances(clean):
    schema()
    put("form4", form4_rows(10, today=10).drop(columns=["shares"]))
    assert not schema()["ok"]
    assert schema(metrics=Metrics(CollectorRegistry()))["ok"]


def test_no_advance_run_leaves_a_corrupt_baseline_alone(clean):
    schema()
    path = config.DATA_DIR / "qa" / "schemas.json"
    path.write_text("{not json")
    assert schema(advance_baseline=False)["detail"] == "schema baseline unreadable"
    assert path.read_text() == "{not json"


def test_full_scan_does_not_move_the_baseline(clean):
    schema()
    put("form4", form4_rows(10, today=10).drop(columns=["shares"]))
    qa.run_qa(NOW, fresh_state(), FORM4_SETTINGS, full=True)
    assert not schema()["ok"]


def test_unreadable_schema_baseline_fails_once_then_is_rewritten(clean):
    schema()
    (config.DATA_DIR / "qa" / "schemas.json").write_text("{not json")
    out = schema()
    assert not out["ok"] and out["detail"] == "schema baseline unreadable"
    assert "shares" in json.loads((config.DATA_DIR / "qa" / "schemas.json").read_text())["form4"]
    assert schema()["ok"]


def row_count(settings=FORM4_SETTINGS, now=NOW, state=None, **kw):
    state = state or FakeState(sec_form4=now - timedelta(hours=3))
    return checks(qa.run_qa(now, state, settings, **kw), "sec_form4")["row_count"]


def test_row_count_collapse_is_caught(clean):
    put("form4", form4_at(daily(first=40, last=8) + [(3, 1), (1, 1)]))
    out = row_count()
    assert not out["ok"] and "2 new rows" in out["detail"]


def test_row_count_at_thirty_percent_passes(clean):
    put("form4", form4_at(daily(first=40, last=8) + [(3, 21)]))
    assert row_count()["ok"]


def test_row_count_below_thirty_percent_fails(clean):
    put("form4", form4_at(daily(first=40, last=8) + [(3, 20)]))
    assert not row_count()["ok"]


def test_source_that_stopped_inserting_fails_row_count(clean):
    put("form4", form4_at(daily(first=40, last=8)))
    assert not row_count()["ok"]


def test_weekend_day_with_zero_new_rows_passes(clean):
    saturday = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    put("form4", form4_at(daily(first=40, last=1, now=saturday, weekdays_only=True), now=saturday))
    out = row_count(now=saturday)
    assert out["ok"], out["detail"]


def test_sparse_source_between_publications_passes(clean):
    put("form4", form4_at([(100, 3), (70, 3), (40, 3), (10, 3)]))
    out = row_count()
    assert out["ok"] and "median of 0" in out["detail"]


def test_row_count_without_enough_history_passes(clean):
    put("form4", form4_at([(10, 10), (5, 10)]))
    out = row_count()
    assert out["ok"] and out["detail"] == "no history"


def test_weekly_source_row_count_uses_four_interval_windows():
    settings = {"sources": {"sec_form4": {"schedule": "weekly sun 09:00"}}}
    weekly = [(d, 10) for d in range(300, 1, -7)]
    put("form4", form4_at(weekly))
    state = FakeState(sec_form4=NOW - timedelta(days=1))
    assert row_count(settings, state=state)["ok"]
    put("form4", form4_at([(d, n) for d, n in weekly if d > 28] + [(2, 1)]))
    assert not row_count(settings, state=state)["ok"]


def replace_aaa(ohlc, start="2026-10-05"):
    bar_store.year_path("sip", "1Day", "AAA", 2026).unlink()
    put_bars("AAA", ohlc, start=start)


def jump_series(at, price=300.0, n=20):
    return flat(at) + [(price,) * 4] * (n - at)


def price(settings=SETTINGS, **kw):
    return checks(qa.run_qa(NOW, fresh_state(), settings, **kw), "alpaca_bars")


def with_qa(**lists):
    return {"sources": SETTINGS["sources"], "qa": lists}


def drop_session(i):
    full = dbars(flat(20), start="2026-10-05")
    bar_store.year_path("sip", "1Day", "AAA", 2026).unlink()
    bar_store.write_bars("sip", "1Day", "AAA", full.drop(full.index[i]))
    return str(full.index[i].tz_convert("America/New_York").date())


def test_missing_trading_day_fails_calendar_completeness(clean):
    day = drop_session(12)
    out = price()["calendar_completeness"]
    assert not out["ok"] and "AAA" in out["detail"] and day in out["detail"]


def test_hole_older_than_the_lookback_does_not_fail(clean):
    drop_session(2)
    assert price()["calendar_completeness"]["ok"]


def test_hole_at_the_edge_of_the_lookback(clean):
    drop_session(10)
    assert not price()["calendar_completeness"]["ok"]
    drop_session(9)
    assert price()["calendar_completeness"]["ok"]


def test_allowlisted_gap_passes(clean):
    day = drop_session(12)
    assert price(with_qa(ignore_gaps=[f"AAA:{day}"]))["calendar_completeness"]["ok"]
    other = price(with_qa(ignore_gaps=["AAA:2026-01-01"]))["calendar_completeness"]
    assert not other["ok"]


def test_series_starting_late_is_not_missing_earlier_sessions(clean):
    replace_aaa(flat(8), start="2026-10-19")
    out = price()["calendar_completeness"]
    assert not out["ok"] and "2026-10-19" not in out["detail"] and "2026-10-29" in out["detail"]


def test_trailing_sessions_of_a_delisted_series_are_exempt(clean):
    replace_aaa(flat(9))  # last bar 11 SPY sessions before SPY's last
    assert price()["calendar_completeness"]["ok"]
    replace_aaa(flat(10))  # last bar exactly 10 sessions old: still a live series that stopped
    assert not price()["calendar_completeness"]["ok"]


def test_jump_above_100_percent_is_flagged_as_probable_missing_split(clean):
    replace_aaa(jump_series(15))
    out = price()["price_jumps"]
    assert not out["ok"]
    assert "AAA" in out["detail"] and "2026-10-26" in out["detail"] and "+200%" in out["detail"]
    assert "split" in out["detail"]


def test_drop_below_minus_50_percent_is_flagged(clean):
    replace_aaa(jump_series(15, price=40.0))
    out = price()["price_jumps"]
    assert not out["ok"] and "AAA" in out["detail"] and "-60%" in out["detail"]


@pytest.mark.parametrize("level, flagged", [(199.0, False), (201.0, True), (51.0, False), (49.0, True)])
def test_jump_limits_are_exclusive_of_exactly_the_threshold(clean, level, flagged):
    replace_aaa(jump_series(15, price=level / 100 * 100.0))
    assert price()["price_jumps"]["ok"] is not flagged


def test_old_jump_outside_the_lookback_passes(clean):
    replace_aaa(jump_series(2))
    assert price()["price_jumps"]["ok"]


@pytest.mark.parametrize("at, flagged", [(10, True), (9, False)])
def test_jump_lookback_is_ten_sessions(clean, at, flagged):
    replace_aaa(jump_series(at))
    assert price()["price_jumps"]["ok"] is not flagged


def test_allowlisted_jump_passes(clean):
    replace_aaa(jump_series(15))
    assert price(with_qa(ignore_jumps=["AAA:2026-10-26"]))["price_jumps"]["ok"]
    assert not price(with_qa(ignore_jumps=["AAA:2026-10-27"]))["price_jumps"]["ok"]


def test_move_across_a_missing_session_is_a_gap_not_a_jump(clean):
    full = dbars(jump_series(15), start="2026-10-05")
    bar_store.year_path("sip", "1Day", "AAA", 2026).unlink()
    bar_store.write_bars("sip", "1Day", "AAA", full.drop(full.index[14]))
    out = price()
    assert out["price_jumps"]["ok"]
    assert not out["calendar_completeness"]["ok"]


def test_full_scan_reports_old_events_without_failing_or_feeding_metrics(clean):
    replace_aaa(jump_series(2))
    drop_session_later = dbars(jump_series(2), start="2026-10-05")
    bar_store.year_path("sip", "1Day", "AAA", 2026).unlink()
    bar_store.write_bars("sip", "1Day", "AAA", drop_session_later.drop(drop_session_later.index[4]))
    registry = CollectorRegistry()
    report = qa.run_qa(NOW, fresh_state(), SETTINGS, metrics=Metrics(registry), full=True)
    c = report["sources"]["alpaca_bars"]["checks"]
    assert c["price_jumps"]["ok"] and "AAA 2026-10-07" in c["price_jumps"]["detail"]
    assert c["calendar_completeness"]["ok"] and "AAA missing 2026-10-09" in c["calendar_completeness"]["detail"]
    gauge = lambda chk: registry.get_sample_value("sift_qa_failures", {"source": "alpaca_bars", "check": chk})  # noqa: E731
    assert gauge("price_jumps") is None and gauge("calendar_completeness") is None
    assert gauge("freshness") == 0
    qa_dir = config.DATA_DIR / "qa"
    assert (qa_dir / "2026-11-12-full.json").exists() and not (qa_dir / "2026-11-12.json").exists()


def test_full_scan_still_honours_the_allowlist(clean):
    replace_aaa(jump_series(2))
    out = price(with_qa(ignore_jumps=["AAA:2026-10-07"]), full=True)["price_jumps"]
    assert "AAA" not in out["detail"]


def test_every_recorded_universe_is_sampled(clean, monkeypatch):
    for name, sym in (("wide_symbols", "WWW"), ("events_symbols", "EEE"), ("confirm_symbols", "CCC"), ("sf_symbols", "SSS")):
        monkeypatch.setattr(config, name, lambda sym=sym: [sym, "AAA"])
        put_bars(sym, jump_series(15))
    out = price()["price_jumps"]
    assert not out["ok"]
    assert all(sym in out["detail"] for sym in ("WWW", "EEE", "CCC", "SSS"))


def test_universe_symbol_without_any_bars_is_skipped(clean, monkeypatch):
    monkeypatch.setattr(config, "sf_symbols", lambda: ["GONE"])
    assert price()["calendar_completeness"]["ok"]


def test_a_recorded_split_does_not_raise_a_jump(clean):
    from tp import corp_actions

    bar_store.year_path("sip", "1Day", "AAA", 2026).unlink()
    put_bars("AAA", flat(10, 400.0) + flat(10, 100.0))
    corp_actions.splits_path().parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"symbol": ["AAA"], "ex_date": [pd.Timestamp("2026-10-19")], "ratio": [4.0]}).to_parquet(
        corp_actions.splits_path(), index=False
    )
    assert checks(qa.run_qa(NOW, fresh_state(), SETTINGS), "alpaca_bars")["price_jumps"]["ok"]


def test_no_bars_fails_price_checks_without_raising():
    out = checks(qa.run_qa(NOW, fresh_state(), {"sources": {"alpaca_bars": {"schedule": "daily 21:00"}}}), "alpaca_bars")
    assert not out["calendar_completeness"]["ok"] and not out["price_jumps"]["ok"]


def test_unreadable_dataset_is_reported_not_raised(clean):
    DATASETS["form4"].path.write_bytes(b"not parquet")
    out = checks(qa.run_qa(NOW, fresh_state(), FORM4_SETTINGS), "sec_form4")
    assert not out["freshness"]["ok"] and "unreadable" in out["freshness"]["detail"]


def test_source_with_several_datasets_reports_the_failing_one():
    settings = {"sources": {"sec_filings": {"schedule": "daily 07:30"}}}
    for name in ("eightk", "earnings"):
        put(name, pd.DataFrame({"accession": ["a", "b"], "filed_at": [pd.Timestamp("2026-11-01", tz="UTC")] * 2}))
    put("tenk_index", pd.DataFrame({"accn": ["a", "a"], "filed_at": [pd.Timestamp("2026-11-01", tz="UTC")] * 2}))
    c = checks(qa.run_qa(NOW, FakeState(sec_filings=NOW), settings), "sec_filings")
    assert not c["duplicates"]["ok"] and "tenk_index" in c["duplicates"]["detail"]
    assert c["future_timestamps"]["ok"]


def test_report_is_written_atomically_and_matches_return_value(clean):
    report = qa.run_qa(NOW, fresh_state(), SETTINGS)
    out = config.DATA_DIR / "qa"
    assert json.loads((out / "2026-11-12.json").read_text()) == report
    assert not list(out.glob("*.tmp"))


def test_failed_report_write_leaves_no_partial_file(clean, monkeypatch):
    import os

    def boom(*a):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        qa.run_qa(NOW, fresh_state(), SETTINGS)
    assert not list((config.DATA_DIR / "qa").glob("*"))


def test_failures_are_exported_per_source_and_check(clean):
    put("form4", form4_rows(10, today=10).pipe(lambda d: pd.concat([d, d.iloc[:3]], ignore_index=True)))
    registry = CollectorRegistry()
    qa.run_qa(NOW, fresh_state(), SETTINGS, metrics=Metrics(registry))
    get = lambda s, c: registry.get_sample_value("sift_qa_failures", {"source": s, "check": c})  # noqa: E731
    assert get("sec_form4", "duplicates") == 3
    assert get("sec_form4", "freshness") == 0
    assert get("alpaca_bars", "price_jumps") == 0


def test_cli_qa_prints_the_report_and_exits_nonzero_on_failure(clean, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda: SETTINGS)
    code = cli.main(["qa", "--date", "2026-11-12"])
    report = json.loads(capsys.readouterr().out)
    assert report["date"] == "2026-11-12"
    assert code == 1  # nothing in State.load() has ever succeeded, so freshness fails


def test_cli_qa_full_exits_zero_with_only_old_events(clean, monkeypatch, capsys):
    replace_aaa(jump_series(2))
    monkeypatch.setattr(cli, "load_settings", lambda: SETTINGS)
    monkeypatch.setattr(cli.State, "load", classmethod(lambda cls, path=None: fresh_state()))
    assert cli.main(["qa", "--date", "2026-11-12", "--full"]) == 0
    assert "AAA 2026-10-07" in capsys.readouterr().out


def test_temp_files_are_unique_per_process(clean, monkeypatch):
    import os

    seen = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda src, dst: (seen.append(str(src)), real(src, dst))[1])
    qa.run_qa(NOW, fresh_state(), SETTINGS)
    assert seen and all(str(os.getpid()) in name for name in seen)
