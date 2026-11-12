from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
import pytest

from tp import config
from tp.collect import datasets, store
from tp.collect.source import RateLimited, RunContext, SourceError, Weekly
from tp.collect.sources import build_sources, sp500
from tp.collect.sources.sp500 import Sp500Changes

NOW = datetime(2026, 11, 12, 12, 30, tzinfo=UTC)
HTML = (Path(__file__).parent / "fixtures" / "sp500_changes.html").read_text()
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


class FakeHttp:
    def __init__(self, body: str | int | Exception):
        self.body = body
        self.urls: list[str] = []

    def get(self, url: str) -> httpx.Response:
        self.urls.append(url)
        if isinstance(self.body, Exception):
            raise self.body
        request = httpx.Request("GET", url)
        if isinstance(self.body, int):
            return httpx.Response(self.body, request=request)
        return httpx.Response(200, text=self.body, request=request)


def source(body: str | int | Exception) -> tuple[Sp500Changes, FakeHttp]:
    http = FakeHttp(body)
    return Sp500Changes(http_factory=lambda: http), http


def ctx(writer=None) -> RunContext:
    return RunContext(now=NOW, settings=SETTINGS, writer=writer or (lambda ds, df: store.write(ds, df, now=NOW)))


def fetched(body: str) -> pd.DataFrame:
    src, _ = source(body)
    return src.fetch(ctx())[src.datasets[0]]


def test_sp500_parses_added_and_removed_tickers_from_fixture_html():
    df = fetched(HTML)
    assert df.columns.tolist() == ["effective_date", "added", "removed", "reason"]
    assert len(df) == 5
    first = df.iloc[0]
    assert (first["effective_date"], first["added"], first["removed"]) == (pd.Timestamp("2013-12-02"), "ALLE", "JCP")
    last = df.iloc[-1]
    assert (last["effective_date"], last["added"], last["removed"]) == (pd.Timestamp("2026-10-30"), "OKTA", "KVUE")
    assert last["reason"] == "S&P 500 constituent Kimberly-Clark acquired Kenvue."


def test_sp500_empty_cells_are_empty_strings_and_dual_class_tickers_survive():
    df = fetched(HTML).set_index(["effective_date", "added", "removed"])
    assert (pd.Timestamp("2026-10-06"), "", "CTVA") in df.index
    assert (pd.Timestamp("2026-10-01"), "VYLR", "") in df.index
    assert (pd.Timestamp("2026-10-01"), "BRK.B", "BF.B") in df.index


def test_sp500_dtypes_match_what_the_writer_stores():
    df = fetched(HTML)
    assert str(df["effective_date"].dtype) == "datetime64[us]"
    for col in ("added", "removed", "reason"):
        assert str(df[col].dtype) == "str"
        assert not df[col].isna().any()


def test_sp500_run_writes_the_dataset_and_a_second_run_adds_nothing():
    src, _ = source(HTML)
    assert src.run(ctx()) == 5
    assert src.run(ctx()) == 0
    out = pd.read_parquet(datasets.dataset("sp500_changes").path)
    assert len(out) == 5 and "ingested_at" in out.columns
    assert out["effective_date"].is_monotonic_increasing


def test_sp500_requests_the_wikipedia_page():
    src, http = source(HTML)
    src.fetch(ctx())
    assert http.urls == [sp500.URL]
    assert sp500.URL.endswith("Historical_components_of_the_S%26P_500")


def test_sp500_default_client_sends_a_descriptive_user_agent():
    client = sp500._default_http()
    try:
        assert client.headers["User-Agent"].startswith("sift-research")
    finally:
        client.close()


def test_sp500_layout_change_raises_source_error_not_empty_success():
    src, _ = source("<html><body><table id='constituents'><tr><td>x</td></tr></table></body></html>")
    with pytest.raises(SourceError, match="changes"):
        src.fetch(ctx())
    writes = []
    with pytest.raises(SourceError):
        src.run(ctx(lambda ds, df: writes.append(df) or 0))
    assert writes == []


def test_sp500_table_with_other_columns_raises_source_error():
    renamed = HTML.replace("<th colspan=\"2\">Removed</th>", "<th colspan=\"2\">Dropped</th>")
    assert renamed != HTML
    src, _ = source(renamed)
    with pytest.raises(SourceError, match="columns"):
        src.fetch(ctx())
    flat = HTML.replace("<th colspan=\"2\">Added</th>", "<th>Added</th>")
    with pytest.raises(SourceError):
        source(flat)[0].fetch(ctx())


def test_sp500_unparseable_date_raises_source_error():
    src, _ = source(HTML.replace("October 30, 2026", "the end of October"))
    with pytest.raises(SourceError, match="date"):
        src.fetch(ctx())


def test_sp500_table_without_rows_raises_source_error():
    head = HTML[: HTML.index("<tr>\n<td>October 30")]
    src, _ = source(head + "</tbody></table></body></html>")
    with pytest.raises(SourceError):
        src.fetch(ctx())


def test_sp500_a_failed_run_never_overwrites_the_stored_file():
    ds = datasets.dataset("sp500_changes")
    src, _ = source(HTML)
    src.run(ctx())
    before = ds.path.read_bytes()
    broken, _ = source("<html>maintenance</html>")
    with pytest.raises(SourceError):
        broken.run(ctx())
    assert ds.path.read_bytes() == before


def test_sp500_429_is_rate_limited_and_other_failures_are_source_errors():
    with pytest.raises(RateLimited) as e:
        source(429)[0].fetch(ctx())
    assert e.value.retry_after_s == 600
    for body in (500, 404, httpx.ConnectError("boom")):
        with pytest.raises(SourceError) as err:
            source(body)[0].fetch(ctx())
        assert not isinstance(err.value, RateLimited)


def test_sp500_registers_from_settings():
    found = {s.name: s for s in build_sources(SETTINGS)}["sp500_changes"]
    assert isinstance(found.schedule, Weekly) and (found.schedule.weekday, found.schedule.at.hour) == (6, 10)
    assert found.rate_group == "wikipedia"
    assert [d.name for d in found.datasets] == ["sp500_changes"]
    assert found.datasets[0].path == config.DATA_DIR / "store" / "sp500_changes.parquet"


@pytest.mark.parametrize("cell", ["AAPL, MSFT", "AAPL [1]", "aapl", "TOOLONG", "A.BC", "BRK.B.X"])
def test_sp500_a_ticker_cell_that_is_not_a_single_ticker_raises_source_error(cell):
    src, _ = source(HTML.replace("<td>OKTA</td>", f"<td>{cell}</td>"))
    with pytest.raises(SourceError, match="not a ticker"):
        src.fetch(ctx())
