import importlib.util
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd
import pytest

from tp import config, edgar
from tp.collect import datasets, store
from tp.collect.source import Daily, RateLimited, RunContext, SourceError
from tp.collect.sources import build_sources, source_settings
from tp.collect.sources.sec import SecFilings
from tp.edgar import SUBMISSIONS_URL, TICKERS_URL, EdgarClient

NOW = datetime(2026, 11, 12, 12, 30, tzinfo=UTC)
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "submissions_aaa.json").read_text())
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


def old_version() -> dict:
    """The cached submissions JSON before the newest 8-K was filed."""
    old = json.loads(json.dumps(FIXTURE))
    for col, vals in old["filings"]["recent"].items():
        old["filings"]["recent"][col] = vals[1:]
    return old


def listed_as(*names: str) -> dict:
    """The fixture submissions JSON with its ticker list set."""
    return FIXTURE | {"tickers": list(names)}


def tickers(**ciks: int) -> dict:
    return {str(i): {"cik_str": cik, "ticker": t, "title": t} for i, (t, cik) in enumerate(ciks.items())}


class FakeHttp:
    """Serves canned JSON by URL and records every request; a status code maps a URL to an error."""

    def __init__(self, routes: dict[str, dict | int]):
        self.routes = routes
        self.urls: list[str] = []

    def get(self, url: str) -> httpx.Response:
        self.urls.append(url)
        body = self.routes[url]
        if isinstance(body, int):
            return httpx.Response(body, request=httpx.Request("GET", url))
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))


def sub_url(name: str) -> str:
    return SUBMISSIONS_URL.format(name=name)


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(edgar, "MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(config, "load_universe", lambda: {"universe": {"traded": ["AAA"], "regime": []}})
    monkeypatch.setattr(config, "events_symbols", lambda: ["BBB"])
    monkeypatch.setattr(config, "confirm_symbols", lambda: ["AAA"])
    monkeypatch.setattr(config, "sf_symbols", lambda: ["ZZZ"])


def make(tmp_path, routes) -> tuple[SecFilings, FakeHttp, Path]:
    http = FakeHttp(routes)
    cache = tmp_path / "edgar-cache"
    src = SecFilings(client_factory=lambda: EdgarClient(cache_dir=cache, http=http))
    return src, http, cache


def routes(**extra) -> dict:
    r = {TICKERS_URL: tickers(AAA=1000, BBB=2000), sub_url("CIK0000001000.json"): listed_as("AAA"),
         sub_url("CIK0000002000.json"): listed_as("BBB")}
    r.update(extra)
    return r


def ctx(writer=lambda ds, df: 0) -> RunContext:
    return RunContext(now=NOW, settings=SETTINGS, writer=writer)


def test_declares_name_group_schedule_and_lag():
    s = SecFilings(schedule="daily 07:30 America/New_York", lag_minutes=0)
    assert (s.name, s.rate_group, s.lag) == ("sec_filings", "sec", timedelta(0))
    assert isinstance(s.schedule, Daily)
    assert {d.name for d in s.datasets} == {"eightk", "earnings", "tenk_index"}


def test_build_sources_registers_it_from_settings():
    found = [s for s in build_sources(SETTINGS) if s.name == "sec_filings"]
    assert len(found) == 1 and found[0].schedule.at.hour == 7 and found[0].schedule.at.minute == 30


def test_new_8k_appears_after_refresh(tmp_path):
    src, http, cache = make(tmp_path, routes())
    cache.mkdir()
    (cache / "CIK0000001000.json").write_text(json.dumps(old_version()))
    (cache / "company_tickers.json").write_text(json.dumps(tickers(AAA=1000)))
    frames = src.fetch(ctx())
    eightk = frames[datasets.dataset("eightk")]
    assert "0001000-26-000003" in set(eightk["accession"])
    assert len(eightk[eightk["symbol"] == "AAA"]) == 2


def test_cache_is_replaced_when_refreshing(tmp_path):
    src, http, cache = make(tmp_path, routes())
    cache.mkdir()
    (cache / "CIK0000001000.json").write_text(json.dumps(old_version()))
    src.fetch(ctx())
    assert json.loads((cache / "CIK0000001000.json").read_text()) == listed_as("AAA")
    assert not list(cache.glob("*.tmp"))


def test_get_json_without_refresh_reads_the_cache(tmp_path):
    http = FakeHttp({"https://x.test/a": {"v": 2}})
    client = EdgarClient(cache_dir=tmp_path, http=http)
    (tmp_path / "a.json").write_text('{"v": 1}')
    assert client._get_json("https://x.test/a", "a.json") == {"v": 1} and http.urls == []
    assert client._get_json("https://x.test/a", "a.json", refresh=True) == {"v": 2}
    assert json.loads((tmp_path / "a.json").read_text()) == {"v": 2}


@pytest.mark.parametrize("status", [429, 403])
def test_http_429_raises_rate_limited_with_retry_after(tmp_path, status):
    src, _, _ = make(tmp_path, routes(**{sub_url("CIK0000001000.json"): status}))
    with pytest.raises(RateLimited) as e:
        src.fetch(ctx())
    assert e.value.retry_after_s == 600


def test_other_http_errors_are_source_errors_not_crashes(tmp_path):
    src, _, _ = make(tmp_path, routes(**{sub_url("CIK0000001000.json"): 500}))
    with pytest.raises(SourceError):
        src.fetch(ctx())


def test_symbol_without_cik_is_skipped_and_reported_not_fatal(tmp_path, caplog):
    src, _, _ = make(tmp_path, routes())
    with caplog.at_level(logging.INFO, logger="tp.collect.sources.sec"):
        frames = src.fetch(ctx())
    assert set(frames[datasets.dataset("eightk")]["symbol"]) == {"AAA", "BBB"}
    lines = [r for r in caplog.records if r.levelno == logging.INFO and "ZZZ" in r.getMessage()]
    assert len(lines) == 1 and "sec_filings" in lines[0].getMessage()


def test_only_the_main_submissions_json_is_refreshed_older_pages_come_from_cache(tmp_path):
    page = "CIK0000001000-submissions-001.json"
    main = json.loads(json.dumps(FIXTURE))
    main["filings"]["files"] = [{"name": page}, {"name": "CIK0000001000-submissions-002.json"}]
    older = {"accessionNumber": ["0001000-20-000001"], "form": ["8-K"], "items": ["2.02"],
             "acceptanceDateTime": ["2020-05-01T20:00:00.000Z"], "reportDate": [""], "primaryDocument": ["x.htm"]}
    r = routes(**{sub_url("CIK0000001000.json"): main, sub_url("CIK0000001000-submissions-002.json"): older})
    src, http, cache = make(tmp_path, r)
    cache.mkdir()
    (cache / page).write_text(json.dumps(older | {"accessionNumber": ["0001000-19-000009"]}))
    frames = src.fetch(ctx())
    assert sub_url(page) not in http.urls
    assert http.urls.count(sub_url("CIK0000001000-submissions-002.json")) == 1
    assert {"0001000-19-000009", "0001000-20-000001"} <= set(frames[datasets.dataset("eightk")]["accession"])


def test_requests_once_per_cik_and_refreshes_the_ticker_map_once(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "events_symbols", lambda: ["AAA2"])
    src, http, _ = make(tmp_path, routes(**{TICKERS_URL: tickers(AAA=1000, AAA2=1000),
                                            sub_url("CIK0000001000.json"): listed_as("AAA", "AAA2")}))
    src.fetch(ctx())
    assert http.urls.count(TICKERS_URL) == 1
    assert http.urls.count(sub_url("CIK0000001000.json")) == 1


def test_frames_have_the_dataset_columns(tmp_path):
    src, _, _ = make(tmp_path, routes())
    frames = src.fetch(ctx())
    assert list(frames[datasets.dataset("eightk")].columns) == ["symbol", "accession", "filed_at", "items"]
    assert list(frames[datasets.dataset("earnings")].columns) == ["symbol", "cik", "accession", "filed_at"]
    assert list(frames[datasets.dataset("tenk_index")].columns) == ["symbol", "cik", "accn", "filed_at", "report_date", "doc"]
    earnings = frames[datasets.dataset("earnings")]
    assert earnings["accession"].tolist() == ["0001000-26-000001"] * 2 and set(earnings["cik"]) == {1000, 2000}
    assert frames[datasets.dataset("tenk_index")]["accn"].iloc[0] == "0001000-26-000002"


def test_run_writes_all_three_datasets(tmp_path):
    src, _, _ = make(tmp_path, routes())
    seen = {}
    total = src.run(ctx(lambda ds, df: seen.setdefault(ds.name, len(df))))
    assert seen == {"eightk": 4, "earnings": 2, "tenk_index": 2} and total == 8


def test_empty_universe_result_still_yields_typed_frames(tmp_path):
    src, _, _ = make(tmp_path, routes(**{TICKERS_URL: {}}))
    frames = src.fetch(ctx())
    assert list(frames[datasets.dataset("eightk")].columns) == ["symbol", "accession", "filed_at", "items"]
    assert all(f.empty for f in frames.values())


def test_scripts_still_produce_the_same_8k_columns(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("fetch_eightk", config.ROOT / "scripts" / "fetch_eightk.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    http = FakeHttp(routes())
    monkeypatch.setattr(script, "EdgarClient", lambda: EdgarClient(cache_dir=tmp_path / "c", http=http))
    assert script.main() == 0
    out = pd.read_parquet(tmp_path / "events" / "eightk.parquet")
    assert out.columns.tolist() == ["symbol", "accession", "filed_at", "items"]


def test_source_settings_returns_the_table():
    assert source_settings(SETTINGS, "alpaca_bars")["lag_minutes"] == 20


def test_source_settings_missing_table_exits_with_a_clear_message():
    with pytest.raises(SystemExit) as e:
        source_settings({"sources": {}}, "sec_filings")
    assert str(e.value) == "config/collect.toml is missing [sources.sec_filings]"
    with pytest.raises(SystemExit):
        source_settings({}, "sec_filings")


def test_build_sources_exits_when_a_source_table_is_missing():
    with pytest.raises(SystemExit, match=r"missing \[sources.alpaca_bars\]"):
        build_sources({"sources": {"sec_filings": SETTINGS["sources"]["sec_filings"]}})


def test_dual_class_tickers_sharing_a_cik_keep_both_rows_when_merged_into_a_legacy_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "events_symbols", lambda: ["AAA2"])
    monkeypatch.setattr(config, "confirm_symbols", lambda: [])
    legacy_ts = pd.Timestamp("2026-01-28T21:30:42Z")
    legacy = pd.DataFrame({
        "symbol": ["AAA", "AAA2", "AAA", "AAA2", "OLD"],
        "accession": ["0001000-26-000001"] * 2 + ["0001000-20-000007"] * 2 + ["0009-19-000001"],
        "filed_at": [legacy_ts, legacy_ts, pd.Timestamp("2020-05-01T20:00:00Z"), pd.Timestamp("2020-05-01T20:00:00Z"),
                     pd.Timestamp("2019-05-01T20:00:00Z")],
        "items": ["2.02,9.01"] * 2 + ["8.01"] * 2 + ["1.01"],
    })
    ds = datasets.dataset("eightk")
    ds.path.parent.mkdir(parents=True)
    legacy.to_parquet(ds.path, index=False)
    src, _, _ = make(tmp_path, routes(**{TICKERS_URL: tickers(AAA=1000, AAA2=1000),
                                         sub_url("CIK0000001000.json"): listed_as("AAA", "AAA2")}))
    frames = src.fetch(ctx())
    store.write(ds, frames[ds], now=NOW)
    out = pd.read_parquet(ds.path)
    assert len(out) >= len(legacy)
    assert len(out) == len(legacy) + 2  # one new accession, one row per symbol
    pairs = set(zip(out["symbol"], out["accession"], strict=True))
    assert {("AAA", "0001000-26-000001"), ("AAA2", "0001000-26-000001"), ("AAA", "0001000-20-000007"),
            ("AAA2", "0001000-20-000007"), ("AAA", "0001000-26-000003"), ("AAA2", "0001000-26-000003")} <= pairs


def test_a_rate_limit_midway_is_resumed_not_restarted(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "events_symbols", lambda: ["BBB", "CCC", "DDD"])
    monkeypatch.setattr(config, "confirm_symbols", lambda: [])
    monkeypatch.setattr(config, "sf_symbols", lambda: [])
    r = routes(**{TICKERS_URL: tickers(AAA=1000, BBB=2000, CCC=3000, DDD=4000),
                  sub_url("CIK0000003000.json"): 429, sub_url("CIK0000004000.json"): listed_as("DDD")})
    r[sub_url("CIK0000002000.json")] = listed_as("BBB")
    src, http, _ = make(tmp_path, r)
    with pytest.raises(RateLimited):
        src.fetch(ctx())
    first = list(http.urls)
    assert sub_url("CIK0000002000.json") in first and sub_url("CIK0000004000.json") not in first
    progress = json.loads((config.DATA_DIR / "collect" / "sec_filings_progress.json").read_text())
    assert progress["date"] == "2026-11-12" and progress["ciks"] == [1000, 2000]

    r[sub_url("CIK0000003000.json")] = listed_as("CCC")
    http.urls.clear()
    restarted = SecFilings(client_factory=lambda: EdgarClient(cache_dir=tmp_path / "edgar-cache", http=http))
    frames = restarted.fetch(ctx())  # a new instance, as after a daemon restart
    assert http.urls == [sub_url("CIK0000003000.json"), sub_url("CIK0000004000.json")]
    assert set(frames[datasets.dataset("eightk")]["symbol"]) == {"AAA", "BBB", "CCC", "DDD"}
    assert not (config.DATA_DIR / "collect" / "sec_filings_progress.json").exists()


def test_progress_from_another_day_is_ignored(tmp_path):
    path = config.DATA_DIR / "collect" / "sec_filings_progress.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"date": "2026-11-11", "tickers": True, "ciks": [1000, 2000]}))
    src, http, _ = make(tmp_path, routes())
    src.fetch(ctx())
    assert http.urls.count(sub_url("CIK0000001000.json")) == 1 and http.urls.count(TICKERS_URL) == 1


def test_invalid_json_body_never_overwrites_the_cache(tmp_path):
    good = json.dumps(old_version())

    class Garbage(FakeHttp):
        def get(self, url):
            if url == TICKERS_URL:
                return super().get(url)
            self.urls.append(url)
            return httpx.Response(200, content=b"<html>maintenance</html>", request=httpx.Request("GET", url))

    http = Garbage({TICKERS_URL: tickers(AAA=1000)})
    cache = tmp_path / "edgar-cache"
    cache.mkdir()
    (cache / "CIK0000001000.json").write_text(good)
    src = SecFilings(client_factory=lambda: EdgarClient(cache_dir=cache, http=http))
    with pytest.raises(SourceError):
        src.fetch(ctx())
    assert http.urls == [TICKERS_URL, sub_url("CIK0000001000.json")]
    assert (cache / "CIK0000001000.json").read_text() == good
    assert not list(cache.glob("*.tmp"))


@pytest.mark.parametrize("body", [{"error": "Not Found"}, [1, 2]])
def test_json_without_filings_never_overwrites_the_cache(tmp_path, body):
    good = json.dumps(old_version())
    src, _, cache = make(tmp_path, routes(**{sub_url("CIK0000001000.json"): body}))
    cache.mkdir()
    (cache / "CIK0000001000.json").write_text(good)
    with pytest.raises(SourceError):
        src.fetch(ctx())
    assert (cache / "CIK0000001000.json").read_text() == good
    assert not list(cache.glob("*.tmp"))


def test_cache_tmp_file_name_is_unique_per_process(tmp_path, monkeypatch):
    seen = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: (seen.append(Path(a).name), real(a, b)))
    client = EdgarClient(cache_dir=tmp_path, http=FakeHttp({"https://x.test/a": {"v": 1}}))
    client._get_json("https://x.test/a", "a.json")
    assert seen == [f"a.json.{os.getpid()}.tmp"]


def test_symbol_not_in_the_cik_ticker_list_is_skipped_and_reported(tmp_path, caplog):
    src, _, _ = make(tmp_path, routes(**{sub_url("CIK0000002000.json"): listed_as("NEWCO")}))
    with caplog.at_level(logging.INFO, logger="tp.collect.sources.sec"):
        frames = src.fetch(ctx())
    assert set(frames[datasets.dataset("eightk")]["symbol"]) == {"AAA"}
    lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO and "sec_filings" in r.getMessage()]
    assert len(lines) == 1 and "BBB" in lines[0] and "ZZZ" in lines[0]


def test_ticker_list_match_is_case_insensitive_and_absent_list_is_accepted(tmp_path):
    no_list = {k: v for k, v in FIXTURE.items() if k != "tickers"}
    src, _, _ = make(tmp_path, routes(**{sub_url("CIK0000001000.json"): listed_as("aaa"),
                                         sub_url("CIK0000002000.json"): no_list}))
    frames = src.fetch(ctx())
    assert set(frames[datasets.dataset("eightk")]["symbol"]) == {"AAA", "BBB"}
