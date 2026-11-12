import json
import sys
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


def form4_rows(per_day, days_back=range(5, 0, -1), today=None, offset=0):
    """Form 4 trades ingested `per_day` rows a day on each of days_back days before NOW, plus `today` rows today."""
    rows, n = [], offset
    plan = [(d, per_day) for d in days_back] + ([(0, today)] if today is not None else [])
    for back, count in plan:
        for _ in range(count):
            rows.append({
                "trade_id": f"t{n}", "owner_cik": "1", "filing_date": pd.Timestamp("2026-11-01", tz="UTC"),
                "shares": 10.0, "ingested_at": pd.Timestamp(NOW - timedelta(days=back)),
            })
            n += 1
    return pd.DataFrame(rows)


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
    monkeypatch.setattr(config, "wide_symbols", lambda: [])


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


def test_schema_drift_is_caught(clean):
    first = checks(qa.run_qa(NOW, fresh_state(), FORM4_SETTINGS), "sec_form4")["schema"]
    assert first["ok"]
    assert "shares" in json.loads((config.DATA_DIR / "qa" / "schemas.json").read_text())["form4"]
    put("form4", form4_rows(10, today=10).drop(columns=["shares"]))
    drift = checks(qa.run_qa(NOW, fresh_state(), FORM4_SETTINGS), "sec_form4")["schema"]
    assert not drift["ok"] and "shares" in drift["detail"]
    again = checks(qa.run_qa(NOW, fresh_state(), FORM4_SETTINGS), "sec_form4")["schema"]
    assert again["ok"]


def test_row_count_collapse_is_caught(clean):
    put("form4", form4_rows(10, today=2))
    out = checks(qa.run_qa(NOW, fresh_state(), FORM4_SETTINGS), "sec_form4")["row_count"]
    assert not out["ok"] and "2" in out["detail"]


def test_row_count_at_thirty_percent_passes(clean):
    put("form4", form4_rows(10, today=3))
    assert checks(qa.run_qa(NOW, fresh_state(), FORM4_SETTINGS), "sec_form4")["row_count"]["ok"]


def test_row_count_without_enough_history_passes(clean):
    put("form4", form4_rows(10, days_back=[2, 1], today=0))
    out = checks(qa.run_qa(NOW, fresh_state(), FORM4_SETTINGS), "sec_form4")["row_count"]
    assert out["ok"] and out["detail"] == "no history"


def test_weekly_source_row_count_compares_whole_weeks():
    settings = {"sources": {"sec_form4": {"schedule": "weekly sun 09:00"}}}
    weeks = [(w * 7) + 2 for w in range(4, 0, -1)]
    put("form4", form4_rows(10, days_back=weeks, today=10, offset=0))
    state = FakeState(sec_form4=NOW - timedelta(days=1))
    assert checks(qa.run_qa(NOW, state, settings), "sec_form4")["row_count"]["ok"]
    put("form4", form4_rows(10, days_back=weeks, today=1))
    assert not checks(qa.run_qa(NOW, state, settings), "sec_form4")["row_count"]["ok"]


def test_missing_trading_day_fails_calendar_completeness(clean):
    full = dbars(flat(20), start="2026-10-05")
    path = bar_store.year_path("sip", "1Day", "AAA", 2026)
    path.unlink()
    bar_store.write_bars("sip", "1Day", "AAA", full.drop(full.index[10]))
    out = checks(qa.run_qa(NOW, fresh_state(), SETTINGS), "alpaca_bars")["calendar_completeness"]
    assert not out["ok"]
    assert "AAA" in out["detail"] and str(full.index[10].tz_convert("America/New_York").date()) in out["detail"]


def test_series_starting_late_is_not_missing_earlier_sessions(clean):
    path = bar_store.year_path("sip", "1Day", "AAA", 2026)
    path.unlink()
    put_bars("AAA", flat(8), start="2026-10-19")
    out = checks(qa.run_qa(NOW, fresh_state(), SETTINGS), "alpaca_bars")["calendar_completeness"]
    assert "2026-10-19" not in out["detail"]
    assert "2026-10-29" in out["detail"]  # bars stop before SPY's last two sessions


def test_jump_above_100_percent_is_flagged_as_probable_missing_split(clean):
    ohlc = flat(10) + [(300.0,) * 4] * 10
    bar_store.year_path("sip", "1Day", "AAA", 2026).unlink()
    put_bars("AAA", ohlc)
    out = checks(qa.run_qa(NOW, fresh_state(), SETTINGS), "alpaca_bars")["price_jumps"]
    assert not out["ok"]
    assert "AAA" in out["detail"] and "2026-10-19" in out["detail"] and "+200%" in out["detail"]
    assert "split" in out["detail"]


def test_drop_below_minus_50_percent_is_flagged(clean):
    bar_store.year_path("sip", "1Day", "AAA", 2026).unlink()
    put_bars("AAA", flat(10) + [(40.0,) * 4] * 10)
    out = checks(qa.run_qa(NOW, fresh_state(), SETTINGS), "alpaca_bars")["price_jumps"]
    assert not out["ok"] and "AAA" in out["detail"] and "-60%" in out["detail"]


@pytest.mark.parametrize("price, flagged", [(199.0, False), (201.0, True), (51.0, False), (49.0, True)])
def test_jump_limits_are_exclusive_of_exactly_the_threshold(clean, price, flagged):
    bar_store.year_path("sip", "1Day", "AAA", 2026).unlink()
    put_bars("AAA", flat(10) + [(price,) * 4] * 10)
    out = checks(qa.run_qa(NOW, fresh_state(), SETTINGS), "alpaca_bars")["price_jumps"]
    assert out["ok"] is not flagged


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


def test_cli_reports_a_missing_qa_module(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "tp.collect.qa", None)
    assert cli.main(["qa"]) == 1
    assert "not implemented" in capsys.readouterr().err


def test_cli_does_not_hide_a_broken_import_inside_qa(monkeypatch, tmp_path):
    import tp.collect

    (tmp_path / "qa.py").write_text("import tp_no_such_dependency\n")
    monkeypatch.delitem(sys.modules, "tp.collect.qa", raising=False)
    monkeypatch.setattr(tp.collect, "__path__", [str(tmp_path), *tp.collect.__path__])
    with pytest.raises(ModuleNotFoundError, match="tp_no_such_dependency"):
        cli.main(["qa"])
