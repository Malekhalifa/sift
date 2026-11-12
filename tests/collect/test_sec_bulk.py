import io
import json
import logging
import zipfile
from datetime import UTC, date, datetime, timedelta

import httpx
import pandas as pd
import pytest

from tp import config, edgar
from tp.collect import datasets, store
from tp.collect.source import Daily, RateLimited, RunContext, SourceError, Weekly
from tp.collect.sources import build_sources, sec
from tp.collect.sources.sec import SecForm4, SecXbrlShares
from tp.edgar import TICKERS_URL, EdgarClient

NOW = datetime(2026, 11, 12, 12, 30, tzinfo=UTC)
SETTINGS = {"sources": {
    "alpaca_bars": {"schedule": "daily 21:00 America/New_York", "lag_minutes": 20},
    "sec_filings": {"schedule": "daily 07:30 America/New_York", "lag_minutes": 0},
    "sec_form4": {"schedule": "daily 08:00 America/New_York", "lag_minutes": 0},
    "sec_xbrl_shares": {"schedule": "weekly sun 09:00 America/New_York", "lag_minutes": 0},
    "finra_shortvol": {"schedule": "daily 18:30 America/New_York", "lag_minutes": 0},
    "finra_short_interest": {"schedule": "daily 09:00 America/New_York", "lag_minutes": 0},
}}


def form4_ds():
    """Resolved per test: the dataset paths follow the tmp DATA_DIR fixture."""
    return datasets.dataset("form4")


def xbrl_ds():
    return datasets.dataset("xbrl_shares")


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(sec, "FIRST_YEAR", 2026)
    monkeypatch.setattr(sec, "QUARTER_PAUSE_S", 0.0)
    monkeypatch.setattr(sec, "FACTS_SPACING_S", 0.0)
    monkeypatch.setattr(edgar, "MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(config, "load_universe", lambda: {"universe": {"traded": ["AAA"], "regime": []}})
    monkeypatch.setattr(config, "events_symbols", lambda: ["BBB"])
    monkeypatch.setattr(config, "confirm_symbols", lambda: ["AAA"])
    monkeypatch.setattr(config, "sf_symbols", lambda: ["ZZZ"])


class Recorder:
    """A writer that keeps what it was given."""

    def __init__(self):
        self.calls: list[tuple[str, pd.DataFrame]] = []

    def __call__(self, ds, frame):
        self.calls.append((ds.name, frame))
        return len(frame)


def ctx(writer=None) -> RunContext:
    return RunContext(now=NOW, settings=SETTINGS, writer=writer or Recorder())


def store_writer(ds, frame):
    return store.write(ds, frame, now=NOW)


# ---- Form 4 ---------------------------------------------------------------------------------------------------------
def quarter_zip(accn: str = "0001-26-1", filing: str = "05-AUG-2026", trade: str = "04-AUG-2026") -> bytes:
    """A form345.zip holding one insider purchase."""
    members = {
        "SUBMISSION.tsv": f"ACCESSION_NUMBER\tFILING_DATE\tDOCUMENT_TYPE\tISSUERCIK\n{accn}\t{filing}\t4\t0000000100\n",
        "REPORTINGOWNER.tsv": f"ACCESSION_NUMBER\tRPTOWNERCIK\tRPTOWNER_RELATIONSHIP\n{accn}\t0000000007\tOfficer\n",
        "NONDERIV_TRANS.tsv": "ACCESSION_NUMBER\tNONDERIV_TRANS_SK\tTRANS_DATE\tTRANS_CODE\tTRANS_SHARES\t"
        f"TRANS_PRICEPERSHARE\tTRANS_ACQUIRED_DISP_CD\n{accn}\t1\t{trade}\tP\t100\t10\tA\n",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in members.items():
            z.writestr(name, text)
    return buf.getvalue()


class FakeResponse:
    def __init__(self, url: str, body: int | bytes):
        self.url = url
        self.status_code = body if isinstance(body, int) else 200
        self.body = b"" if isinstance(body, int) else body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_bytes(self, size):
        for i in range(0, len(self.body), size):
            yield self.body[i:i + size]

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=httpx.Request("GET", self.url), response=httpx.Response(self.status_code))


class FakeZipHttp:
    """Serves zips by quarter; an int maps a quarter to an HTTP status."""

    def __init__(self, quarters: dict[str, int | bytes]):
        self.routes = {sec.FORM4_URL.format(quarter=q): body for q, body in quarters.items()}
        self.urls: list[str] = []

    def stream(self, method: str, url: str) -> FakeResponse:
        self.urls.append(url)
        return FakeResponse(url, self.routes.get(url, 404))


def form4_source(http: FakeZipHttp) -> SecForm4:
    return SecForm4(http_factory=lambda: http)


def parsed_dir():
    return config.DATA_DIR / "insider" / "parsed"


def seed_parsed(*quarters: str) -> None:
    parsed_dir().mkdir(parents=True, exist_ok=True)
    for q in quarters:
        pd.DataFrame(columns=["trade_id"]).to_parquet(parsed_dir() / f"{q}.parquet", index=False)


def stray_files() -> list[str]:
    return sorted(p.name for p in (config.DATA_DIR / "insider").rglob("*") if p.suffix in (".part", ".tmp"))


def test_form4_declares_name_group_schedule_and_lag():
    s = SecForm4(schedule="daily 08:00 America/New_York", lag_minutes=0)
    assert (s.name, s.rate_group, s.lag) == ("sec_form4", "sec", timedelta(0))
    assert isinstance(s.schedule, Daily) and (s.schedule.at.hour, s.schedule.at.minute) == (8, 0)
    assert [d.name for d in s.datasets] == ["form4"]


def test_xbrl_declares_name_group_schedule_and_lag():
    s = SecXbrlShares(schedule="weekly sun 09:00 America/New_York", lag_minutes=0)
    assert (s.name, s.rate_group, s.lag) == ("sec_xbrl_shares", "sec", timedelta(0))
    assert isinstance(s.schedule, Weekly) and s.schedule.weekday == 6 and s.schedule.at.hour == 9
    assert [d.name for d in s.datasets] == ["xbrl_shares"]


def test_build_sources_registers_both_from_settings():
    names = [s.name for s in build_sources(SETTINGS)]
    assert "sec_form4" in names and "sec_xbrl_shares" in names
    assert {s.name: s.schedule.at.hour for s in build_sources(SETTINGS)}["sec_form4"] == 8


def test_unpublished_quarter_is_skipped_without_error():
    http = FakeZipHttp({"2026q1": quarter_zip(), "2026q2": 404})
    seed_parsed("2026q1")
    writer = Recorder()
    rows = form4_source(http).run(ctx(writer))
    assert rows == 0 and writer.calls == []
    assert http.urls == [sec.FORM4_URL.format(quarter="2026q2")]  # 2026q3 is not even asked for after a 404
    assert not (parsed_dir() / "2026q2.parquet").exists() and stray_files() == []
    frames = form4_source(FakeZipHttp({})).fetch(ctx())
    assert frames[form4_ds()].empty and list(frames[form4_ds()].columns) == sec.TRADE_COLUMNS


def test_parsed_quarters_are_not_downloaded_again():
    seed_parsed("2026q1", "2026q2")
    http = FakeZipHttp({"2026q3": quarter_zip()})
    writer = Recorder()
    assert form4_source(http).run(ctx(writer)) == 1
    assert http.urls == [sec.FORM4_URL.format(quarter="2026q3")]
    assert (parsed_dir() / "2026q3.parquet").exists()
    http.urls.clear()
    assert form4_source(http).run(ctx(writer)) == 0
    assert http.urls == []


def test_form4_frame_has_the_parsed_trades():
    seed_parsed("2026q1", "2026q2")
    frame = form4_source(FakeZipHttp({"2026q3": quarter_zip()})).fetch(ctx())[form4_ds()]
    assert list(frame.columns) == sec.TRADE_COLUMNS
    assert frame[["trade_id", "owner_cik", "code", "value"]].to_dict("records") == [
        {"trade_id": "0001-26-1-1", "owner_cik": 7, "code": "P", "value": 1000.0}]


def test_a_quarter_is_finished_a_week_after_it_ends():
    assert sec.finished_quarters(date(2026, 7, 7)) == ["2026q1"]
    assert sec.finished_quarters(date(2026, 7, 8)) == ["2026q1", "2026q2"]


def test_truncated_zip_raises_source_error_and_writes_nothing():
    seed_parsed("2026q1")
    http = FakeZipHttp({"2026q2": quarter_zip(), "2026q3": quarter_zip()[:-60]})
    writer = Recorder()
    with pytest.raises(SourceError):
        form4_source(http).run(ctx(writer))
    assert writer.calls == []
    assert sorted(p.name for p in parsed_dir().iterdir()) == ["2026q1.parquet"]
    assert stray_files() == []


@pytest.mark.parametrize("body", [b"", b"<html>not a zip</html>", quarter_zip()[:200]])
def test_garbage_bodies_raise_source_error(body):
    seed_parsed("2026q1", "2026q2")
    with pytest.raises(SourceError):
        form4_source(FakeZipHttp({"2026q3": body})).run(ctx())
    assert sorted(p.name for p in parsed_dir().iterdir()) == ["2026q1.parquet", "2026q2.parquet"]
    assert stray_files() == []


def test_zip_missing_a_table_raises_source_error():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SUBMISSION.tsv", "ACCESSION_NUMBER\tFILING_DATE\tDOCUMENT_TYPE\tISSUERCIK\n")
    seed_parsed("2026q1", "2026q2")
    with pytest.raises(SourceError):
        form4_source(FakeZipHttp({"2026q3": buf.getvalue()})).run(ctx())
    assert stray_files() == []


@pytest.mark.parametrize("status", [403, 429])
def test_form4_rate_limit_becomes_rate_limited(status):
    seed_parsed("2026q1", "2026q2")
    with pytest.raises(RateLimited) as e:
        form4_source(FakeZipHttp({"2026q3": status})).run(ctx())
    assert e.value.retry_after_s == 600
    assert stray_files() == []


def test_form4_server_error_is_a_source_error():
    seed_parsed("2026q1", "2026q2")
    with pytest.raises(SourceError):
        form4_source(FakeZipHttp({"2026q3": 500})).run(ctx())
    assert stray_files() == []


def test_a_failed_write_keeps_the_quarter_for_the_next_run():
    seed_parsed("2026q1", "2026q2")

    def broken(ds, frame):
        raise store.StoreError("disk")

    http = FakeZipHttp({"2026q3": quarter_zip()})
    with pytest.raises(store.StoreError):
        form4_source(http).run(ctx(broken))
    assert not (parsed_dir() / "2026q3.parquet").exists()
    assert form4_source(http).run(ctx()) == 1


def test_several_new_quarters_go_through_one_write():
    seed_parsed("2026q1")
    http = FakeZipHttp({"2026q2": quarter_zip("0001-26-1"), "2026q3": quarter_zip("0001-26-2")})
    writer = Recorder()
    assert form4_source(http).run(ctx(writer)) == 2
    assert len(writer.calls) == 1 and set(writer.calls[0][1]["trade_id"]) == {"0001-26-1-1", "0001-26-2-1"}
    assert (parsed_dir() / "2026q2.parquet").exists() and (parsed_dir() / "2026q3.parquet").exists()


def legacy_trades() -> pd.DataFrame:
    """A trades.parquet as the old script stored it: naive datetime64 dates, float shares, price and value."""
    return pd.DataFrame({
        "trade_id": ["old-1"], "accession": ["old"], "filing_date": pd.to_datetime(["2026-01-05"]), "issuer_cik": [100],
        "owner_cik": [7], "trade_date": pd.to_datetime(["2026-01-04"]), "code": ["P"], "shares": [1.0], "price": [2.0], "value": [2.0],
    })


def test_form4_frame_merges_into_the_legacy_file():
    form4_ds().path.parent.mkdir(parents=True)
    legacy_trades().to_parquet(form4_ds().path, index=False)
    seed_parsed("2026q1", "2026q2")
    assert form4_source(FakeZipHttp({"2026q3": quarter_zip()})).run(ctx(store_writer)) == 1
    merged = pd.read_parquet(form4_ds().path)
    assert set(merged["trade_id"]) == {"old-1", "0001-26-1-1"}
    assert merged["filing_date"].dt.tz is None and str(merged["issuer_cik"].dtype) == "int64"


# ---- XBRL share counts ----------------------------------------------------------------------------------------------
def facts(*units: dict, name: str = "Alpha Corp") -> dict:
    return {"cik": 1000, "entityName": name, "facts": {"dei": {"EntityCommonStockSharesOutstanding": {
        "units": {"shares": list(units)}}}}}


def unit(accn: str, form: str = "10-K", filed: str = "2026-02-20", end: str = "2026-02-10", val: int = 1_000_000) -> dict:
    return {"accn": accn, "form": form, "filed": filed, "end": end, "val": val, "fy": 2025, "fp": "FY"}


def facts_url(cik: int) -> str:
    return sec.FACTS_URL.format(cik=cik)


class FakeHttp:
    """Serves company facts by URL: a dict is a JSON body, an int a status, bytes a raw 200 body."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.urls: list[str] = []

    def get(self, url: str) -> httpx.Response:
        self.urls.append(url)
        body = self.routes[url]
        request = httpx.Request("GET", url)
        if isinstance(body, int):
            return httpx.Response(body, request=request)
        if isinstance(body, bytes):
            return httpx.Response(200, content=body, request=request)
        return httpx.Response(200, json=body, request=request)


def tickers(**ciks: int) -> dict:
    return {str(i): {"cik_str": cik, "ticker": t, "title": t} for i, (t, cik) in enumerate(ciks.items())}


def xbrl_source(tmp_path, routes: dict, http: FakeHttp | None = None) -> tuple[SecXbrlShares, FakeHttp]:
    http = http or FakeHttp(routes)
    return SecXbrlShares(client_factory=lambda: EdgarClient(cache_dir=tmp_path / "edgar-cache", http=http)), http


def xbrl_routes(**extra) -> dict:
    routes = {TICKERS_URL: tickers(AAA=1000, BBB=2000),
              facts_url(1000): facts(unit("a-1"), unit("a-2", "10-Q", "2026-05-01", "2026-04-20", 1_100_000)),
              facts_url(2000): facts(unit("b-1", val=5_000_000))}
    routes.update(extra)
    return routes


def progress_file():
    return config.DATA_DIR / "collect" / "sec_xbrl_shares_progress.json"


def test_xbrl_frame_has_the_legacy_columns_and_dtypes():
    src_frame = sec.shares_rows(facts(unit("a-1")))
    assert list(src_frame.columns) == ["accn", "form", "filed", "end", "val"]


def test_xbrl_rows_keep_only_10k_10q(tmp_path):
    body = facts(unit("a-1"), unit("a-2", "10-Q"), unit("a-3", "10-K/A"), unit("a-4", "S-1"), unit("a-5", "8-K"))
    src, _ = xbrl_source(tmp_path, xbrl_routes(**{facts_url(1000): body}))
    frame = src.fetch(ctx())[xbrl_ds()]
    a = frame[frame["symbol"] == "AAA"]
    assert sorted(a["accn"]) == ["a-1", "a-2"] and set(a["form"]) == {"10-K", "10-Q"}
    assert list(frame.columns) == ["symbol", "cik", "accn", "form", "filed", "end", "val"]
    assert str(frame["cik"].dtype) == "int64" and str(frame["val"].dtype) == "float64"
    assert str(frame["filed"].dtype).startswith("datetime64") and str(frame["end"].dtype).startswith("datetime64")
    assert frame["filed"].dt.tz is None


def test_xbrl_404_for_a_symbol_gives_empty_frame_not_failure(tmp_path):
    src, http = xbrl_source(tmp_path, xbrl_routes(**{facts_url(1000): 404}))
    frame = src.fetch(ctx())[xbrl_ds()]
    assert set(frame["symbol"]) == {"BBB"} and len(frame) == 1
    assert http.urls.count(facts_url(2000)) == 1
    assert not progress_file().exists()


def test_xbrl_404_for_every_symbol_is_an_empty_typed_frame(tmp_path):
    src, _ = xbrl_source(tmp_path, xbrl_routes(**{facts_url(1000): 404, facts_url(2000): 404}))
    frame = src.fetch(ctx())[xbrl_ds()]
    assert frame.empty and list(frame.columns) == ["symbol", "cik", "accn", "form", "filed", "end", "val"]


def test_xbrl_symbols_are_traded_events_and_confirm_without_survivorship_free(tmp_path):
    src, http = xbrl_source(tmp_path, xbrl_routes(**{TICKERS_URL: tickers(AAA=1000, BBB=2000, ZZZ=3000)}))
    src.fetch(ctx())
    assert http.urls == [TICKERS_URL, facts_url(1000), facts_url(2000)]


@pytest.mark.parametrize("status", [403, 429])
def test_xbrl_rate_limit_becomes_rate_limited(tmp_path, status):
    src, _ = xbrl_source(tmp_path, xbrl_routes(**{facts_url(1000): status}))
    with pytest.raises(RateLimited) as e:
        src.fetch(ctx())
    assert e.value.retry_after_s == 600


def test_xbrl_server_error_is_a_source_error(tmp_path):
    src, _ = xbrl_source(tmp_path, xbrl_routes(**{facts_url(1000): 500}))
    with pytest.raises(SourceError) as e:
        src.fetch(ctx())
    assert not isinstance(e.value, RateLimited)


@pytest.mark.parametrize("body", [b"<html>maintenance</html>", {"error": "no facts"}, [1, 2], {"facts": None}])
def test_xbrl_bad_body_is_a_source_error_never_data(tmp_path, body):
    src, _ = xbrl_source(tmp_path, xbrl_routes(**{facts_url(1000): body}))
    writer = Recorder()
    with pytest.raises(SourceError):
        src.run(ctx(writer))
    assert writer.calls == []


def test_a_rate_limit_midway_is_resumed_not_restarted(tmp_path):
    routes = xbrl_routes(**{facts_url(2000): 429})
    src, http = xbrl_source(tmp_path, routes)
    writer = Recorder()
    with pytest.raises(RateLimited):
        src.run(ctx(writer))
    assert [(n, set(f["symbol"])) for n, f in writer.calls] == [("xbrl_shares", {"AAA"})]
    progress = json.loads(progress_file().read_text())
    assert progress["date"] == "2026-11-12" and progress["symbols"] == ["AAA"]

    routes[facts_url(2000)] = facts(unit("b-1", val=5_000_000))
    http.urls.clear()
    restarted, _ = xbrl_source(tmp_path, routes, http)  # a new instance, as after a daemon restart
    frame = restarted.fetch(ctx())[xbrl_ds()]
    assert http.urls == [facts_url(2000)]  # the ticker map is cached too, and AAA is not asked for again
    assert set(frame["symbol"]) == {"BBB"}
    assert not progress_file().exists()


def test_progress_from_another_day_is_ignored(tmp_path):
    progress_file().parent.mkdir(parents=True)
    progress_file().write_text(json.dumps({"date": "2026-11-11", "tickers": True, "symbols": ["AAA", "BBB"]}))
    src, http = xbrl_source(tmp_path, xbrl_routes())
    frame = src.fetch(ctx())[xbrl_ds()]
    assert set(frame["symbol"]) == {"AAA", "BBB"} and http.urls.count(TICKERS_URL) == 1


def test_progress_file_is_written_atomically(tmp_path, monkeypatch):
    seen = []
    real = sec.os.replace
    monkeypatch.setattr(sec.os, "replace", lambda a, b: (seen.append(str(a)), real(a, b)))
    src, _ = xbrl_source(tmp_path, xbrl_routes(**{facts_url(2000): 429}))
    with pytest.raises(RateLimited):
        src.run(ctx())
    assert seen and all(s.endswith(".tmp") for s in seen)
    assert not list(progress_file().parent.glob("*.tmp"))


def legacy_shares() -> pd.DataFrame:
    """A shares.parquet as the old script stored it."""
    return pd.DataFrame({
        "symbol": ["AAA"], "cik": [1000], "accn": ["old"], "form": ["10-K"], "filed": pd.to_datetime(["2025-02-20"]),
        "end": pd.to_datetime(["2025-02-10"]), "val": [900_000.0],
    })


def test_xbrl_frame_merges_into_the_legacy_file(tmp_path):
    xbrl_ds().path.parent.mkdir(parents=True)
    legacy_shares().to_parquet(xbrl_ds().path, index=False)
    src, _ = xbrl_source(tmp_path, xbrl_routes())
    assert src.run(ctx(store_writer)) == 3
    merged = pd.read_parquet(xbrl_ds().path)
    assert set(merged["accn"]) == {"old", "a-1", "a-2", "b-1"}
    assert merged["filed"].dt.tz is None and str(merged["val"].dtype) == "float64"


def test_a_rerun_adds_nothing(tmp_path):
    src, _ = xbrl_source(tmp_path, xbrl_routes())
    assert src.run(ctx(store_writer)) == 3
    again, _ = xbrl_source(tmp_path, xbrl_routes())
    assert again.run(ctx(store_writer)) == 0


def test_dual_class_tickers_sharing_a_cik_do_not_collide(tmp_path):
    routes = {TICKERS_URL: tickers(AAA=1000, BBB=1000), facts_url(1000): facts(unit("a-1"))}
    src, _ = xbrl_source(tmp_path, routes)
    assert src.run(ctx(store_writer)) == 2
    assert sorted(pd.read_parquet(xbrl_ds().path)["symbol"]) == ["AAA", "BBB"]


def test_one_filing_with_several_cover_dates_keeps_every_row(tmp_path):
    """The legacy file has 28 (accn, symbol) pairs with two share counts as of different dates."""
    body = facts(unit("a-1", end="2026-02-10", val=100), unit("a-1", end="2026-03-01", val=90))
    src, _ = xbrl_source(tmp_path, xbrl_routes(**{facts_url(1000): body}))
    assert src.run(ctx(store_writer)) == 3
    stored = pd.read_parquet(xbrl_ds().path)
    assert sorted(stored[stored["accn"] == "a-1"]["val"]) == [90.0, 100.0]


def test_the_xbrl_key_includes_the_cover_date():
    assert xbrl_ds().key == ("accn", "symbol", "end") and xbrl_ds().ts_col == "filed"


def test_xbrl_logs_a_one_line_summary(tmp_path, caplog):
    src, _ = xbrl_source(tmp_path, xbrl_routes(**{TICKERS_URL: tickers(AAA=1000)}))
    with caplog.at_level(logging.INFO, logger="tp.collect.sources.sec"):
        src.fetch(ctx())
    lines = [r.getMessage() for r in caplog.records if "sec_xbrl_shares" in r.getMessage()]
    assert len(lines) == 1 and "BBB" in lines[0]
