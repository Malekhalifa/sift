import logging
from datetime import UTC, date, datetime

import httpx
import pandas as pd
import pytest

from tp import config
from tp.collect import datasets, store
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
    store_shortvol("20261110")
    http = FakeHttp({sv_url("20261111"): sv_text("20261111")})
    assert shortvol(http).run(ctx()) == 2
    stored = pd.read_parquet(datasets.dataset("finra_shortvol").path)
    assert len(stored) == 3 and stored["ingested_at"].notna().sum() == 2
    assert str(stored["date"].dtype) == "datetime64[us]"
    assert shortvol(FakeHttp({})).run(ctx()) == 0


def test_shortvol_without_a_stored_file_starts_at_the_first_consolidated_day(monkeypatch):
    monkeypatch.setattr(finra, "FIRST", date(2026, 11, 9))
    http = FakeHttp({})
    shortvol(http).run(ctx())
    assert http.urls == [sv_url(d) for d in ("20261109", "20261110", "20261111")]


def test_shortvol_records_no_file_days_so_they_are_not_retried():
    store_shortvol("20261109")
    http = FakeHttp({})  # 20261110 and 20261111 answer 403
    assert shortvol(http).run(ctx()) == 0
    assert gaps("no_file.txt") == {"20261110", "20261111"}
    again = FakeHttp({})
    shortvol(again).run(ctx())
    assert again.urls == []
    assert not list((config.DATA_DIR / "finra").glob("*.tmp"))


def test_shortvol_skips_the_legacy_no_file_days():
    store_shortvol("20261105")
    (config.DATA_DIR / "finra").mkdir(exist_ok=True)
    (config.DATA_DIR / "finra" / "no_file.txt").write_text("20261106\n20261109")
    http = FakeHttp({sv_url("20261110"): sv_text("20261110"), sv_url("20261111"): sv_text("20261111")})
    shortvol(http).run(ctx())
    assert http.urls == [sv_url("20261110"), sv_url("20261111")]
    assert gaps("no_file.txt") == {"20261106", "20261109"}


def test_shortvol_transport_error_is_a_source_error_and_not_a_no_file_day():
    store_shortvol("20261109")
    http = FakeHttp({sv_url("20261110"): sv_text("20261110"), sv_url("20261111"): httpx.ReadTimeout("slow")})
    calls, writer = captured()
    with pytest.raises(SourceError) as e:
        shortvol(http).run(ctx(writer))
    assert not isinstance(e.value, RateLimited)
    assert gaps("no_file.txt") == set()
    assert [name for name, _ in calls] == ["finra_shortvol"]  # the day read before the failure is still stored
    assert calls[0][1]["date"].dt.strftime("%Y%m%d").unique().tolist() == ["20261110"]


def test_shortvol_429_is_rate_limited_but_403_is_not():
    store_shortvol("20261110")
    with pytest.raises(RateLimited) as e:
        shortvol(FakeHttp({sv_url("20261111"): 429})).run(ctx())
    assert e.value.retry_after_s == 600
    assert gaps("no_file.txt") == set()
    shortvol(FakeHttp({sv_url("20261111"): 403})).run(ctx())  # absent file, no exception


def test_shortvol_unexpected_status_is_a_source_error():
    store_shortvol("20261110")
    with pytest.raises(SourceError):
        shortvol(FakeHttp({sv_url("20261111"): 500})).run(ctx())


def test_shortvol_garbage_body_is_a_source_error_and_not_a_no_file_day():
    store_shortvol("20261110")
    with pytest.raises(SourceError):
        shortvol(FakeHttp({sv_url("20261111"): "<html>maintenance</html>"})).run(ctx())
    assert gaps("no_file.txt") == set()


def test_shortvol_never_asks_for_today_even_after_the_schedule():
    store_shortvol("20261111")
    late = RunContext(now=datetime(2026, 11, 12, 23, 59, tzinfo=UTC), settings=SETTINGS, writer=real_writer)
    http = FakeHttp({sv_url("20261112"): sv_text("20261112")})
    shortvol(http).run(late)
    assert http.urls == []


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


def test_short_interest_missing_file_for_an_older_date_is_recorded_once_not_raised(from_sep, caplog):
    http = FakeHttp({si_url("20260930"): si_text("20260930")})  # 20261015 answers 403 on every candidate day
    with caplog.at_level(logging.WARNING):
        assert interest(http).run(ctx()) == 2
    assert gaps("short_interest_no_file.txt") == {"20261015", "20261014", "20261013", "20261012"}
    assert len([r for r in caplog.records if "20261015" in r.getMessage()]) == 1
    again = FakeHttp({})
    interest(again).run(ctx())
    assert again.urls == []


def test_short_interest_follows_a_holiday_back_to_the_previous_business_day(monkeypatch):
    monkeypatch.setattr(finra, "settlement_dates", lambda first, last: [date(2024, 1, 15), date(2024, 1, 31)])
    http = FakeHttp({si_url("20240112"): si_text("20240112"), si_url("20240131"): si_text("20240131")})  # MLK day 2024-01-15
    interest(http).run(ctx())
    stored = pd.read_parquet(datasets.dataset("finra_short_interest").path)
    assert sorted(stored["settlement_date"].dt.strftime("%Y%m%d").unique()) == ["20240112", "20240131"]
    assert gaps("short_interest_no_file.txt") == {"20240115"}
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
