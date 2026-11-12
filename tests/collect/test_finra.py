import importlib.util
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest

from tp import config
from tp.collect import daemon, datasets, store
from tp.collect.source import Daily, RateLimited, RunContext, SourceError
from tp.collect.sources import build_sources, finra
from tp.collect.sources.finra import FinraShortInterest, FinraShortVolume, fetch_day

NOW = datetime(2026, 11, 12, 12, 30, tzinfo=UTC)  # Thursday 07:30 ET, so yesterday is Wednesday 2026-11-11
SETTINGS = {"sources": {
    "alpaca_bars": {"schedule": "daily 21:00 America/New_York", "lag_minutes": 20},
    "sec_filings": {"schedule": "daily 07:30 America/New_York", "lag_minutes": 0},
    "sec_form4": {"schedule": "daily 08:00 America/New_York", "lag_minutes": 0},
    "sec_xbrl_shares": {"schedule": "weekly sun 09:00 America/New_York", "lag_minutes": 0},
    "finra_shortvol": {"schedule": "daily 18:30 America/New_York", "lag_minutes": 0},
    "finra_short_interest": {"schedule": "daily 09:00 America/New_York", "lag_minutes": 0},
    "dod_awards": {"schedule": "weekly mon 06:00 America/New_York", "lag_minutes": 0},
    "trump_posts": {"schedule": "daily 07:00 America/New_York", "lag_minutes": 0},
    "sp500_changes": {"schedule": "weekly sun 10:00 America/New_York", "lag_minutes": 0},
    "wikipedia_pageviews": {"schedule": "daily 06:30 UTC", "lag_minutes": 0},
    "congress_trades": {"schedule": "daily 08:30 America/New_York", "lag_minutes": 0, "enabled": False},
}}
SV_HEADER = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
SI_HEADER = (
    "accountingYearMonthNumber|symbolCode|issueName|issuerServicesGroupExchangeCode|marketClassCode|"
    "currentShortPositionQuantity|previousShortPositionQuantity|stockSplitFlag|averageDailyVolumeQuantity|"
    "daysToCoverQuantity|revisionFlag|changePercent|changePreviousNumber|settlementDate\n"
)


def sv_url(day: str) -> str:
    return finra.URL.format(day=day)


def si_url(day: str) -> str:
    return finra.SHORT_INTEREST_URL.format(day=day)


def sv_text(day: str, rows: dict[str, int] | None = None) -> str:
    rows = rows or {"AAA": 100, "BBB": 200, "OTHER": 300}
    return SV_HEADER + "".join(f"{day}|{s}|{v}|{v // 10}|{v * 2}|B,Q,N\n" for s, v in rows.items())


def si_text(day: str, rows: dict[str, int] | None = None) -> str:
    rows = rows or {"AAA": 1000, "BBB": 2000, "OTHER": 3000}
    iso = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    return SI_HEADER + "".join(f"{day}|{s}|{s} Inc|A|NYSE|{v}|{v - 5}||{v * 3}|2.50||1.25|5|{iso}\n" for s, v in rows.items())


class FakeHttp:
    """Serves canned text by URL (a str), an error status (an int, 403 for any URL not listed, as the CDN does), or raises
    a transport error (an Exception instance)."""

    def __init__(self, routes: dict[str, str | int | Exception]):
        self.routes = routes
        self.urls: list[str] = []

    def get(self, url: str) -> httpx.Response:
        self.urls.append(url)
        body = self.routes.get(url, 403)
        if isinstance(body, Exception):
            raise body
        request = httpx.Request("GET", url)
        if isinstance(body, int):
            return httpx.Response(body, request=request)
        return httpx.Response(200, text=body, request=request)


@pytest.fixture(autouse=True)
def universe(monkeypatch):
    monkeypatch.setattr(config, "load_universe", lambda: {"universe": {"traded": ["AAA"], "regime": []}})
    monkeypatch.setattr(config, "events_symbols", lambda: ["BBB"])
    monkeypatch.setattr(config, "confirm_symbols", lambda: ["AAA"])
    monkeypatch.setattr(config, "sf_symbols", lambda: ["ZZZ"])
    monkeypatch.setattr(finra, "RETRY_PAUSE_S", 0.0)


def real_writer(ds, df):
    return store.write(ds, df, now=NOW)


def ctx(writer=real_writer) -> RunContext:
    return RunContext(now=NOW, settings=SETTINGS, writer=writer)


def shortvol(http: FakeHttp) -> FinraShortVolume:
    return FinraShortVolume(http_factory=lambda: http)


def interest(http: FakeHttp) -> FinraShortInterest:
    return FinraShortInterest(http_factory=lambda: http)


def store_shortvol(*days: str) -> None:
    """The legacy file's shape: naive datetime64[us] date, str symbol, float64 volumes, no ingested_at."""
    df = pd.DataFrame({
        "date": pd.to_datetime(list(days), format="%Y%m%d").astype("datetime64[us]"),
        "symbol": pd.Series(["AAA"] * len(days), dtype="str"),
        "short": [1.0] * len(days), "exempt": [0.0] * len(days), "total": [2.0] * len(days),
    })
    path = datasets.dataset("finra_shortvol").path
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def store_through(last: str, missing: tuple[str, ...] = (), first: str = "20261105") -> None:
    """Every weekday from `first` to `last` stored except `missing`: the recheck window then has nothing left to probe."""
    days = [f"{d:%Y%m%d}" for d in pd.bdate_range(first, last)]
    store_shortvol(*(d for d in days if d not in missing))


def gaps(name: str) -> set[str]:
    path = config.DATA_DIR / "finra" / name
    return set(path.read_text().split()) if path.exists() else set()


def captured() -> tuple[list[tuple[str, pd.DataFrame]], object]:
    calls: list[tuple[str, pd.DataFrame]] = []

    def writer(ds, df):
        calls.append((ds.name, df))
        return len(df)

    return calls, writer


# fetch_day

def test_fetch_day_returns_none_on_403_and_404():
    for status in (403, 404):
        http = FakeHttp({sv_url("20260105"): status})
        assert fetch_day(http, date(2026, 1, 5), {"AAA"}) is None
        assert http.urls == [sv_url("20260105")]


def test_fetch_day_filters_to_universe_symbols_and_parses_date():
    http = FakeHttp({sv_url("20260105"): sv_text("20260105")})
    df = fetch_day(http, date(2026, 1, 5), {"AAA", "BBB"})
    assert list(df.columns) == ["date", "symbol", "short", "exempt", "total"]
    assert df["symbol"].tolist() == ["AAA", "BBB"]
    assert df["date"].tolist() == [pd.Timestamp("2026-01-05")] * 2
    assert df["short"].tolist() == [100, 200] and df["total"].tolist() == [200, 400]


def test_fetch_day_retries_transport_errors_then_gives_up():
    http = FakeHttp({sv_url("20260105"): httpx.ConnectError("boom")})
    with pytest.raises(RuntimeError, match="no usable response"):
        fetch_day(http, date(2026, 1, 5), {"AAA"})
    assert len(http.urls) == 4


def test_download_pauses_between_transport_error_retries(monkeypatch):
    pauses: list[float] = []
    monkeypatch.setattr(finra, "RETRY_PAUSE_S", 0.5)
    monkeypatch.setattr(finra.time, "sleep", pauses.append)
    http = FakeHttp({sv_url("20260105"): httpx.ConnectError("boom")})
    with pytest.raises(RuntimeError):
        fetch_day(http, date(2026, 1, 5), {"AAA"})
    assert pauses == [0.5, 0.5, 0.5]


# FinraShortVolume

def test_shortvol_declares_name_group_schedule_and_lag():
    s = FinraShortVolume(schedule="daily 18:30 America/New_York", lag_minutes=0)
    assert (s.name, s.rate_group, s.lag.total_seconds()) == ("finra_shortvol", "finra", 0)
    assert isinstance(s.schedule, Daily) and (s.schedule.at.hour, s.schedule.at.minute) == (18, 30)
    assert [d.name for d in s.datasets] == ["finra_shortvol"]


def test_build_sources_registers_both_from_settings():
    found = {s.name: s for s in build_sources(SETTINGS) if s.name.startswith("finra")}
    assert set(found) == {"finra_shortvol", "finra_short_interest"}
    assert found["finra_short_interest"].schedule.at.hour == 9


def test_shortvol_fetches_only_missing_weekdays():
    store_shortvol("20261105")  # Thursday; Fri 6th, Mon 9th, Tue 10th and Wed 11th are missing, Sat/Sun are not asked for
    days = ["20261106", "20261109", "20261110", "20261111"]
    http = FakeHttp({sv_url(d): sv_text(d) for d in days} | {sv_url("20261112"): sv_text("20261112")})
    calls, writer = captured()
    assert shortvol(http).run(ctx(writer)) == 8
    assert http.urls == [sv_url(d) for d in days]
    (name, frame), = calls
    assert name == "finra_shortvol"
    assert sorted(set(frame["symbol"])) == ["AAA", "BBB"]  # OTHER is not in the universe
    assert sorted(frame["date"].dt.strftime("%Y%m%d").unique()) == days
    assert str(frame["date"].dtype) == "datetime64[us]" and set(map(str, frame[["short", "exempt", "total"]].dtypes)) == {"float64"}


def test_shortvol_frame_merges_into_the_legacy_file_dtypes():
    store_through("20261110")
    http = FakeHttp({sv_url("20261111"): sv_text("20261111")})
    assert shortvol(http).run(ctx()) == 2
    stored = pd.read_parquet(datasets.dataset("finra_shortvol").path)
    assert stored["ingested_at"].notna().sum() == 2 and len(stored) == 6
    assert str(stored["date"].dtype) == "datetime64[us]"
    assert shortvol(FakeHttp({})).run(ctx()) == 0


def test_shortvol_without_a_stored_file_starts_at_the_first_consolidated_day(monkeypatch):
    monkeypatch.setattr(finra, "FIRST", date(2026, 11, 9))
    http = FakeHttp({})
    with pytest.raises(SourceError, match="nothing is stored"):
        shortvol(http).run(ctx())
    assert http.urls == [sv_url(d) for d in ("20261109", "20261110", "20261111")]


def test_shortvol_records_a_no_file_day_that_a_later_day_confirms():
    store_through("20261111", missing=("20261106",))  # Fri 6th has no file, Mon 9th onward is stored
    assert shortvol(FakeHttp({})).run(ctx()) == 0
    assert gaps("no_file.txt") == {"20261106"}
    assert not list((config.DATA_DIR / "finra").glob("*.tmp"))
    again = FakeHttp({})
    shortvol(again).run(ctx())
    assert again.urls == []  # six days old: believed


def test_shortvol_does_not_record_a_trailing_miss():
    store_through("20261109")
    shortvol(FakeHttp({})).run(ctx())  # 10th and 11th answer 403 and nothing later has a file
    assert gaps("no_file.txt") == set()


def test_shortvol_reprobes_a_day_that_failed_once_after_a_later_day_succeeded():
    store_through("20261106")
    first = FakeHttp({sv_url("20261110"): sv_text("20261110"), sv_url("20261111"): sv_text("20261111")})  # 20261109 is 403
    assert shortvol(first).run(ctx()) == 4
    assert gaps("no_file.txt") == {"20261109"}
    second = FakeHttp({sv_url("20261109"): sv_text("20261109")})
    assert shortvol(second).run(ctx()) == 2
    assert second.urls == [sv_url("20261109")]
    stored = pd.read_parquet(datasets.dataset("finra_shortvol").path)
    assert "2026-11-09" in set(stored["date"].dt.strftime("%Y-%m-%d"))
    assert gaps("no_file.txt") == set()  # found, so no longer recorded as absent


def test_shortvol_trusts_recorded_no_file_days_only_from_five_days_old():
    store_through("20261105")
    (config.DATA_DIR / "finra").mkdir(exist_ok=True)
    # Fri 6th is 6 days old (believed), Mon 9th is 3 days old (asked for again)
    (config.DATA_DIR / "finra" / "no_file.txt").write_text("20261106\n20261109")
    http = FakeHttp({sv_url(d): sv_text(d) for d in ("20261109", "20261110", "20261111")})
    shortvol(http).run(ctx())
    assert http.urls == [sv_url(d) for d in ("20261109", "20261110", "20261111")]
    assert gaps("no_file.txt") == {"20261106"}


def test_shortvol_probes_an_old_stored_gap_once_and_then_believes_the_record():
    store_through("20261111", missing=("20261103",), first="20261102")
    http = FakeHttp({})
    shortvol(http).run(ctx())
    assert http.urls == [sv_url("20261103")] and gaps("no_file.txt") == {"20261103"}
    again = FakeHttp({})
    shortvol(again).run(ctx())
    assert again.urls == []


def test_shortvol_breaker_stops_and_records_nothing_when_files_stop_appearing():
    store_through("20261001", first="20260901")
    http = FakeHttp({sv_url("20261002"): sv_text("20261002")})  # then 5 old weekdays in a row answer 403
    calls, writer = captured()
    with pytest.raises(SourceError, match="20261005 to 20261009") as e:
        shortvol(http).run(ctx(writer))
    assert not isinstance(e.value, RateLimited)
    assert http.urls[-1] == sv_url("20261009")
    assert gaps("no_file.txt") == set()
    assert [c[1]["date"].dt.strftime("%Y%m%d").unique().tolist() for c in calls] == [["20261002"]]


def test_shortvol_a_block_is_not_recorded_by_the_retry_that_follows_the_breaker():
    store_through("20261001", first="20260901")
    blocked = FakeHttp({sv_url("20261002"): sv_text("20261002")})
    with pytest.raises(SourceError):
        shortvol(blocked).run(ctx())
    assert pd.read_parquet(datasets.dataset("finra_shortvol").path)["date"].max() == pd.Timestamp("2026-10-02")
    for _ in range(2):  # the retry starts inside the streak, with the block still on
        retry = FakeHttp({})
        with pytest.raises(SourceError, match="no file could be read"):  # the block is still on and the store is stale
            shortvol(retry).run(ctx())
        assert retry.urls[0] == sv_url("20261005")
        assert gaps("no_file.txt") == set()


def test_shortvol_a_streak_of_five_is_not_recorded_even_when_a_later_day_has_a_file():
    store_through("20261002", first="20260901")
    blocked = ("20261005", "20261006", "20261007", "20261008", "20261009", "20261012")  # six weekdays
    later = [f"{d:%Y%m%d}" for d in pd.bdate_range("2026-10-13", "2026-11-11")]
    http = FakeHttp({sv_url(d): sv_text(d) for d in later})
    shortvol(http).run(ctx())
    assert gaps("no_file.txt") == set()
    again = FakeHttp({})
    shortvol(again).run(ctx())
    assert again.urls == [sv_url(d) for d in blocked]  # asked for again until the block lifts


def test_shortvol_records_a_holiday_gap_of_one_to_four_weekdays_between_hits():
    store_through("20261001", first="20260901")
    shut = ("20261005", "20261006", "20261007", "20261008")
    open_days = [f"{d:%Y%m%d}" for d in pd.bdate_range("2026-10-02", "2026-11-11") if f"{d:%Y%m%d}" not in shut]
    shortvol(FakeHttp({sv_url(d): sv_text(d) for d in open_days})).run(ctx())
    assert gaps("no_file.txt") == set(shut)


def test_shortvol_records_a_two_day_gap_after_a_stored_hit_and_before_a_later_one():
    store_through("20261001", first="20260901")
    open_days = [f"{d:%Y%m%d}" for d in pd.bdate_range("2026-10-02", "2026-11-11") if f"{d:%Y%m%d}" not in ("20261008", "20261009")]
    shortvol(FakeHttp({sv_url(d): sv_text(d) for d in open_days})).run(ctx())
    assert gaps("no_file.txt") == {"20261008", "20261009"}


def test_shortvol_transport_error_is_a_source_error_and_not_a_no_file_day():
    store_through("20261109")
    http = FakeHttp({sv_url("20261110"): sv_text("20261110"), sv_url("20261111"): httpx.ReadTimeout("slow")})
    calls, writer = captured()
    with pytest.raises(SourceError) as e:
        shortvol(http).run(ctx(writer))
    assert not isinstance(e.value, RateLimited)
    assert gaps("no_file.txt") == set()
    assert [name for name, _ in calls] == ["finra_shortvol"]  # the day read before the failure is still stored
    assert calls[0][1]["date"].dt.strftime("%Y%m%d").unique().tolist() == ["20261110"]


def test_shortvol_429_is_rate_limited_but_403_is_not():
    store_through("20261110")
    with pytest.raises(RateLimited) as e:
        shortvol(FakeHttp({sv_url("20261111"): 429})).run(ctx())
    assert e.value.retry_after_s == 600
    assert gaps("no_file.txt") == set()
    shortvol(FakeHttp({sv_url("20261111"): 403})).run(ctx())  # absent file, no exception


def test_shortvol_unexpected_status_is_a_source_error():
    store_through("20261110")
    with pytest.raises(SourceError):
        shortvol(FakeHttp({sv_url("20261111"): 500})).run(ctx())


def test_shortvol_garbage_body_is_a_source_error_and_not_a_no_file_day():
    store_through("20261110")
    with pytest.raises(SourceError):
        shortvol(FakeHttp({sv_url("20261111"): "<html>maintenance</html>"})).run(ctx())
    assert gaps("no_file.txt") == set()


def test_shortvol_never_asks_for_today_even_after_the_schedule():
    store_through("20261111")
    late = RunContext(now=datetime(2026, 11, 12, 23, 59, tzinfo=UTC), settings=SETTINGS, writer=real_writer)
    http = FakeHttp({sv_url("20261112"): sv_text("20261112")})
    shortvol(http).run(late)
    assert http.urls == []


def test_shortvol_outage_from_the_start_with_a_stale_store_is_an_error():
    store_through("20261030", first="20261026")  # newest stored day is 8 weekdays before yesterday
    http = FakeHttp({})
    with pytest.raises(SourceError, match=r"newest stored day is 13 days old") as e:
        shortvol(http).run(ctx())
    assert not isinstance(e.value, RateLimited)
    assert len(http.urls) == 8
    assert gaps("no_file.txt") == set()


def test_shortvol_outage_with_a_fresh_store_is_a_quiet_success():
    store_through("20261110")  # yesterday's file is not up yet; the newest stored day is one weekday old
    http = FakeHttp({})
    assert shortvol(http).run(ctx()) == 0
    assert http.urls == [sv_url("20261111")]
    assert gaps("no_file.txt") == set()


def test_shortvol_outage_error_is_raised_by_fetch_too():
    store_through("20261030", first="20261026")
    with pytest.raises(SourceError, match="no file could be read"):
        shortvol(FakeHttp({})).fetch(ctx())


def test_universe_includes_survivorship_free_symbols_and_the_index_etfs():
    assert finra.universe_symbols() == {"AAA", "BBB", "ZZZ", "SPY", "QQQ"}


def test_merge_shortvol_keeps_stored_rows_and_adds_new_days():
    store_shortvol("20261110")
    prior = pd.read_parquet(datasets.dataset("finra_shortvol").path).assign(ingested_at=pd.Timestamp("2026-11-11", tz="UTC"))
    fresh = pd.DataFrame({
        "date": pd.to_datetime(["2026-11-10", "2026-11-11"]).astype("datetime64[us]"),
        "symbol": pd.Series(["AAA", "AAA"], dtype="str"),
        "short": [9.0, 9.0], "exempt": [0.0, 0.0], "total": [9.0, 9.0],
    })
    out = finra.merge_shortvol(prior, fresh)
    assert out["short"].tolist() == [1.0, 9.0]
    assert out["ingested_at"].notna().tolist() == [True, False]


def test_merge_shortvol_casts_date_to_microseconds():
    prior = pd.DataFrame({"date": pd.to_datetime(["2026-11-10"]).astype("datetime64[ns]"), "symbol": ["AAA"], "short": [1.0]})
    fresh = pd.DataFrame({"date": pd.to_datetime(["2026-11-11"]).astype("datetime64[s]"), "symbol": ["AAA"], "short": [2.0]})
    assert str(finra.merge_shortvol(prior, fresh)["date"].dtype) == "datetime64[us]"


# FinraShortInterest

@pytest.fixture
def from_sep(monkeypatch):
    """Settlement dates 2026-09-30, 10-15 and 10-30; on 11-12 only the first two are ten business days old."""
    monkeypatch.setattr(finra, "FIRST_SETTLEMENT", date(2026, 9, 30))


def test_settlement_dates_are_the_fifteenth_and_the_last_business_day():
    got = finra.settlement_dates(date(2017, 12, 29), date(2018, 3, 31))
    assert got == [date(2017, 12, 29), date(2018, 1, 15), date(2018, 1, 31), date(2018, 2, 15), date(2018, 2, 28),
                   date(2018, 3, 15), date(2018, 3, 30)]


def test_settlement_dates_roll_a_weekend_back_to_friday():
    got = finra.settlement_dates(date(2018, 9, 1), date(2018, 9, 30))
    assert got == [date(2018, 9, 14), date(2018, 9, 28)]  # the 15th was a Saturday and the 30th a Sunday


def test_short_interest_declares_name_group_schedule_and_lag():
    s = FinraShortInterest(schedule="daily 09:00 America/New_York", lag_minutes=0)
    assert (s.name, s.rate_group) == ("finra_short_interest", "finra")
    assert isinstance(s.schedule, Daily) and s.schedule.at.hour == 9
    assert [d.name for d in s.datasets] == ["finra_short_interest"]


def test_short_interest_waits_ten_business_days(from_sep):
    http = FakeHttp({si_url(d): si_text(d) for d in ("20260930", "20261015", "20261030")})
    calls, writer = captured()
    interest(http).run(ctx(writer))
    assert http.urls == [si_url("20260930"), si_url("20261015")]
    assert len(calls) == 1  # one write per run
    frame = calls[0][1]
    assert sorted(frame["settlement_date"].dt.strftime("%Y%m%d").unique()) == ["20260930", "20261015"]


def test_short_interest_keeps_universe_symbols_and_the_files_other_columns(from_sep):
    http = FakeHttp({si_url("20260930"): si_text("20260930")})
    calls, writer = captured()
    interest(http).run(ctx(writer))
    frame = calls[0][1]
    assert sorted(set(frame["symbol"])) == ["AAA", "BBB"]
    assert str(frame["settlement_date"].dtype) == "datetime64[us]"
    assert {"currentShortPositionQuantity", "previousShortPositionQuantity", "daysToCoverQuantity", "issueName",
            "marketClassCode"} <= set(frame.columns)
    assert "ingested_at" not in frame.columns
    row = frame[frame["symbol"] == "AAA"].iloc[0]
    assert row["currentShortPositionQuantity"] == 1000 and row["settlement_date"] == pd.Timestamp("2026-09-30")


def test_short_interest_skips_stored_settlement_dates(from_sep):
    http = FakeHttp({si_url("20260930"): si_text("20260930"), si_url("20261015"): si_text("20261015")})
    assert interest(http).run(ctx()) == 4
    again = FakeHttp({si_url("20261030"): si_text("20261030")})
    assert interest(again).run(ctx()) == 0
    assert again.urls == []
    stored = pd.read_parquet(datasets.dataset("finra_short_interest").path)
    assert len(stored) == 4 and stored["ingested_at"].notna().all()


def test_short_interest_missing_file_is_not_an_error_before_it_is_due(from_sep, caplog):
    http = FakeHttp({si_url("20260930"): si_text("20260930"), si_url("20261015"): si_text("20261015")})
    with caplog.at_level(logging.WARNING):
        assert interest(http).run(ctx()) == 4
    assert si_url("20261030") not in http.urls  # nine business days old: not asked for yet
    assert gaps("short_interest_no_file.txt") == set() and not caplog.records


def test_short_interest_does_not_record_a_missing_file_before_it_is_stale(from_sep, caplog):
    http = FakeHttp({si_url("20260930"): si_text("20260930")})  # 20261015 is 20 business days old and answers 403
    with caplog.at_level(logging.WARNING):
        assert interest(http).run(ctx()) == 2
    assert gaps("short_interest_no_file.txt") == set() and not caplog.records
    again = FakeHttp({si_url("20261015"): si_text("20261015")})
    assert interest(again).run(ctx()) == 2  # the file turned up late and is picked up
    assert again.urls == [si_url("20261015")]


def test_short_interest_records_a_missing_file_once_it_is_stale_and_a_later_date_has_one(from_sep, caplog):
    http = FakeHttp({si_url("20261015"): si_text("20261015")})  # 20260930 is 30 business days old and answers 403
    with caplog.at_level(logging.WARNING):
        assert interest(http).run(ctx()) == 2
    assert gaps("short_interest_no_file.txt") == {"20260930", "20260929", "20260928", "20260925"}
    assert len([r for r in caplog.records if "20260930" in r.getMessage()]) == 1
    again = FakeHttp({})
    interest(again).run(ctx())
    assert again.urls == []


@pytest.mark.parametrize(("settlement", "recorded"), [(date(2026, 10, 8), True), (date(2026, 10, 9), False)])
def test_short_interest_staleness_threshold_is_25_business_days(monkeypatch, settlement, recorded):
    later = date(2026, 10, 15)
    monkeypatch.setattr(finra, "settlement_dates", lambda first, last: [settlement, later])
    assert int(np.busday_count(settlement, date(2026, 11, 12))) == (25 if recorded else 24)
    interest(FakeHttp({si_url("20261015"): si_text("20261015")})).run(ctx())
    assert bool(gaps("short_interest_no_file.txt")) is recorded


def dates_in(*days: date):
    return lambda first, last: list(days)


JAN_FEB = [date(2026, 1, 15), date(2026, 1, 30), date(2026, 2, 13), date(2026, 2, 27)]  # all well over 25 business days old


def serve(*days: date) -> FakeHttp:
    return FakeHttp({si_url(f"{d:%Y%m%d}"): si_text(f"{d:%Y%m%d}") for d in days})


def test_short_interest_three_missing_dates_before_a_hit_are_not_recorded(monkeypatch):
    monkeypatch.setattr(finra, "settlement_dates", dates_in(*JAN_FEB))
    interest(serve(JAN_FEB[3])).run(ctx())
    assert gaps("short_interest_no_file.txt") == set()
    again = serve()
    with pytest.raises(SourceError, match="no file could be read"):
        interest(again).run(ctx())
    assert len(again.urls) == 12  # all three are asked for again (four candidate days each)


@pytest.mark.parametrize("missing", [1, 2])
def test_short_interest_one_or_two_missing_dates_before_a_hit_are_recorded(monkeypatch, missing):
    monkeypatch.setattr(finra, "settlement_dates", dates_in(*JAN_FEB[: missing + 1]))
    interest(serve(JAN_FEB[missing])).run(ctx())
    assert len(gaps("short_interest_no_file.txt")) == 4 * missing


def test_short_interest_a_trailing_missing_date_is_not_recorded(monkeypatch):
    monkeypatch.setattr(finra, "settlement_dates", dates_in(*JAN_FEB[:2]))
    interest(serve(JAN_FEB[0])).run(ctx())
    assert gaps("short_interest_no_file.txt") == set()


def test_short_interest_breaker_stops_and_records_nothing_when_files_stop_appearing(monkeypatch):
    monkeypatch.setattr(finra, "FIRST_SETTLEMENT", date(2026, 1, 2))  # 1/15 has a file; 1/30, 2/13 and 2/27 answer 403
    http = FakeHttp({si_url("20260115"): si_text("20260115")})
    calls, writer = captured()
    with pytest.raises(SourceError, match="20260130 to 20260227") as e:
        interest(http).run(ctx(writer))
    assert not isinstance(e.value, RateLimited)
    assert gaps("short_interest_no_file.txt") == set()
    assert [c[1]["settlement_date"].dt.strftime("%Y%m%d").unique().tolist() for c in calls] == [["20260115"]]
    assert si_url("20260313") not in http.urls


def test_short_interest_breaker_retry_inside_the_streak_records_nothing(monkeypatch):
    monkeypatch.setattr(finra, "settlement_dates", dates_in(*JAN_FEB))
    with pytest.raises(SourceError):
        interest(serve(JAN_FEB[0])).run(ctx())
    for _ in range(2):
        with pytest.raises(SourceError, match="no file could be read"):  # no hit in the run and the store is stale
            interest(FakeHttp({})).run(ctx())
        assert gaps("short_interest_no_file.txt") == set()


def test_short_interest_outage_with_nothing_stored_is_an_error(from_sep):
    with pytest.raises(SourceError, match="nothing is stored") as e:
        interest(FakeHttp({})).run(ctx())
    assert not isinstance(e.value, RateLimited)
    assert gaps("short_interest_no_file.txt") == set()


def test_short_interest_outage_with_a_stale_store_is_an_error(monkeypatch):
    monkeypatch.setattr(finra, "settlement_dates", dates_in(date(2026, 9, 30), date(2026, 10, 15)))
    interest(serve(date(2026, 9, 30))).run(ctx())  # newest stored is 30 business days old
    with pytest.raises(SourceError, match=r"newest stored settlement is 43 days old"):
        interest(FakeHttp({})).run(ctx())
    assert gaps("short_interest_no_file.txt") == set()


def test_short_interest_outage_with_a_fresh_store_is_a_quiet_success(monkeypatch):
    monkeypatch.setattr(finra, "settlement_dates", dates_in(date(2026, 10, 15)))
    interest(serve(date(2026, 10, 15))).run(ctx())  # 20 business days old
    monkeypatch.setattr(finra, "settlement_dates", dates_in(date(2026, 10, 15), date(2026, 10, 28)))
    http = FakeHttp({})
    assert interest(http).run(ctx()) == 0
    assert http.urls  # 10/28 was asked for
    assert gaps("short_interest_no_file.txt") == set()


def test_short_interest_writer_errors_propagate_unchanged(from_sep, monkeypatch):
    class Boom(Exception):
        pass

    def writer(ds, df):
        raise Boom

    monkeypatch.setattr(finra, "WRITE_EVERY", 1)
    with pytest.raises(Boom):
        interest(serve(date(2026, 9, 30), date(2026, 10, 15))).run(ctx(writer))


def test_short_interest_writes_in_batches_of_write_every(monkeypatch):
    days = [date(2026, 1, 15), date(2026, 1, 30), date(2026, 2, 13), date(2026, 2, 27), date(2026, 3, 13)]
    monkeypatch.setattr(finra, "settlement_dates", lambda first, last: days)
    monkeypatch.setattr(finra, "WRITE_EVERY", 2)
    http = FakeHttp({si_url(f"{d:%Y%m%d}"): si_text(f"{d:%Y%m%d}") for d in days})
    calls, writer = captured()
    assert interest(http).run(ctx(writer)) == 10
    assert [c[1]["settlement_date"].nunique() for c in calls] == [2, 2, 1]


def test_short_interest_small_run_is_a_single_write(from_sep):
    http = FakeHttp({si_url("20260930"): si_text("20260930"), si_url("20261015"): si_text("20261015")})
    calls, writer = captured()
    interest(http).run(ctx(writer))
    assert len(calls) == 1


def test_short_interest_follows_a_holiday_back_to_the_previous_business_day(monkeypatch):
    monkeypatch.setattr(finra, "settlement_dates", lambda first, last: [date(2024, 1, 15), date(2024, 1, 31)])
    http = FakeHttp({si_url("20240112"): si_text("20240112"), si_url("20240131"): si_text("20240131")})  # MLK day 2024-01-15
    interest(http).run(ctx())
    stored = pd.read_parquet(datasets.dataset("finra_short_interest").path)
    assert sorted(stored["settlement_date"].dt.strftime("%Y%m%d").unique()) == ["20240112", "20240131"]
    again = FakeHttp({})
    interest(again).run(ctx())
    assert again.urls == []


def test_short_interest_429_is_rate_limited_but_403_is_not(from_sep):
    with pytest.raises(RateLimited) as e:
        interest(FakeHttp({si_url("20260930"): 429})).run(ctx())
    assert e.value.retry_after_s == 600
    assert gaps("short_interest_no_file.txt") == set()


def test_short_interest_transport_error_stores_finished_files_and_raises_source_error(from_sep):
    http = FakeHttp({si_url("20260930"): si_text("20260930"), si_url("20261015"): httpx.ReadTimeout("slow")})
    calls, writer = captured()
    with pytest.raises(SourceError):
        interest(http).run(ctx(writer))
    assert [c[1]["settlement_date"].dt.strftime("%Y%m%d").unique().tolist() for c in calls] == [["20260930"]]
    assert gaps("short_interest_no_file.txt") == set()


def test_short_interest_garbage_body_is_a_source_error(from_sep):
    with pytest.raises(SourceError):
        interest(FakeHttp({si_url("20260930"): "<html>x</html>"})).run(ctx())
    assert gaps("short_interest_no_file.txt") == set()


# scripts/fetch_finra.py

def load_script():
    path = Path(__file__).resolve().parents[2] / "scripts" / "fetch_finra.py"
    spec = importlib.util.spec_from_file_location("fetch_finra_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script(monkeypatch):
    mod = load_script()
    monkeypatch.setattr(mod, "FIRST", date.today() - timedelta(days=4))  # noqa: DTZ011 (the script itself uses date.today)

    def fake_fetch_day(http, day, symbols):
        stamp = f"{day:%Y%m%d}"
        return fetch_day(FakeHttp({sv_url(stamp): sv_text(stamp)}), day, {"AAA", "BBB"})

    monkeypatch.setattr(mod, "fetch_day", fake_fetch_day)
    return mod


def seed_stored() -> pd.DataFrame:
    """A recorder-written file: an sf symbol the script's own universe lacks, and ingested_at on every row."""
    stored = pd.DataFrame({
        "date": pd.to_datetime(["2018-08-01", "2018-08-01"]).astype("datetime64[us]"),
        "symbol": pd.Series(["AAA", "ZZZ"], dtype="str"),
        "short": [1.0, 2.0], "exempt": [0.0, 0.0], "total": [3.0, 4.0],
        "ingested_at": pd.Timestamp("2026-11-01", tz="UTC"),
    })
    path = config.DATA_DIR / "finra" / "shortvol.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    stored.to_parquet(path, index=False)
    return stored


def test_script_rebuild_keeps_recorder_rows_and_ingested_at(script):
    seed_stored()
    assert script.main() == 0
    out = pd.read_parquet(config.DATA_DIR / "finra" / "shortvol.parquet")
    assert set(out["symbol"]) == {"AAA", "BBB", "ZZZ"}
    old = out[out["date"] == pd.Timestamp("2018-08-01")]
    assert old["ingested_at"].notna().all() and len(old) == 2
    assert out["date"].is_monotonic_increasing and str(out["date"].dtype) == "datetime64[us]"
    assert (out["date"] > pd.Timestamp("2018-08-01")).any()
    assert not list((config.DATA_DIR / "finra").glob("*.tmp"))


def test_script_failure_mid_write_leaves_the_stored_file_untouched(script, monkeypatch):
    stored = seed_stored()
    real = pd.DataFrame.to_parquet

    def failing(self, path, *args, **kwargs):
        if str(path).endswith(".tmp"):
            Path(path).write_text("partial")
            raise OSError("disk full")
        return real(self, path, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", failing)
    with pytest.raises(OSError, match="disk full"):
        script.main()
    monkeypatch.setattr(pd.DataFrame, "to_parquet", real)
    after = pd.read_parquet(config.DATA_DIR / "finra" / "shortvol.parquet")
    assert after.equals(stored)
    assert not list((config.DATA_DIR / "finra").glob("*.tmp"))


def test_script_refuses_to_run_while_the_daemon_lock_is_held(script, capsys):
    seed_stored()
    held = daemon.acquire_lock(daemon.lock_path())
    try:
        assert script.main() == 2
    finally:
        held.close()
    assert "recorder daemon is running" in capsys.readouterr().err
    assert script.main() == 0  # the probe released the lock, so a later run proceeds


def test_script_does_not_fetch_when_refused(script):
    held = daemon.acquire_lock(daemon.lock_path())
    try:
        assert script.main() == 2
    finally:
        held.close()
    assert not (config.DATA_DIR / "finra").exists()
