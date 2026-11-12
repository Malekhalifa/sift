import importlib.util
import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx
import pandas as pd
import pytest

from tp import config
from tp.collect import datasets, store
from tp.collect.source import Daily, RateLimited, RunContext, SourceError
from tp.collect.sources import build_sources, source_settings
from tp.collect.sources import wikipedia as wp
from tp.collect.sources.wikipedia import WikipediaPageviews

NOW = datetime(2026, 11, 12, 6, 30, tzinfo=UTC)
YESTERDAY = date(2026, 11, 11)
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
PREFIX = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"


def url_of(article: str, start: date, end: date) -> str:
    return f"{PREFIX}{quote(article, safe='')}/daily/{start:%Y%m%d}00/{end:%Y%m%d}00"


class FakeHttp:
    """Answers the per-article endpoint: one item per day of the requested range unless the article has a status or a
    body in `special`; `events` interleaves requests and the sleeps recorded by `sleeps`."""

    def __init__(self, special=None):
        self.special = special or {}
        self.requests: list[tuple[str, date, date]] = []
        self.urls: list[str] = []
        self.events: list[tuple] = []

    def get(self, url: str) -> httpx.Response:
        assert url.startswith(PREFIX), url
        article, _, start, end = url[len(PREFIX):].split("/")
        article = article.replace("%2F", "/")
        s, e = (datetime.strptime(x, "%Y%m%d00").date() for x in (start, end))
        self.urls.append(url)
        self.requests.append((article, s, e))
        self.events.append(("get", article))
        request = httpx.Request("GET", url)
        value = self.special.get(article)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, int):
            return httpx.Response(value, request=request)
        if isinstance(value, (dict, list)):
            return httpx.Response(200, json=value, request=request)
        if isinstance(value, str):
            return httpx.Response(200, text=value, request=request)
        days = [s + timedelta(days=i) for i in range((e - s).days + 1)]
        return httpx.Response(200, json={"items": [item(article, d) for d in days]}, request=request)


def item(article: str, day: date, views: int | None = None) -> dict:
    return {"project": "en.wikipedia", "article": article, "granularity": "daily", "timestamp": f"{day:%Y%m%d}00",
            "access": "all-access", "agent": "user", "views": day.day * 10 if views is None else views}


def write_map(tmp_path: Path, **articles: str) -> Path:
    path = tmp_path / "articles.toml"
    path.write_text("# header\n[articles]\n" + "".join(f'{s} = "{a}"\n' for s, a in articles.items()))
    return path


def make(tmp_path, special=None, **articles: str) -> tuple[WikipediaPageviews, FakeHttp]:
    http = FakeHttp(special)
    return WikipediaPageviews(map_path=write_map(tmp_path, **articles), http_factory=lambda: http), http


def ctx(writer=None, now=NOW) -> RunContext:
    return RunContext(now=now, settings=SETTINGS, writer=writer or (lambda ds, df: store.write(ds, df, now=now)))


def stored(*rows: tuple[str, str, str]) -> None:
    """Seed the dataset with (date, symbol, article) rows."""
    df = pd.DataFrame(rows, columns=["date", "symbol", "article"])
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[us]")
    df["views"] = 1
    store.write(datasets.dataset("wikipedia_pageviews"), df, now=NOW)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(wp.time, "sleep", sleeps.append)
    return sleeps


def frame_of(src: WikipediaPageviews, **kw) -> pd.DataFrame:
    return src.fetch(ctx(**kw))[datasets.dataset("wikipedia_pageviews")]


def test_declares_name_group_schedule_and_dataset():
    s = WikipediaPageviews(schedule="daily 06:30 UTC", lag_minutes=0)
    assert (s.name, s.rate_group, s.lag) == ("wikipedia_pageviews", "wikimedia", timedelta(0))
    assert isinstance(s.schedule, Daily) and (s.schedule.at.hour, s.schedule.at.minute) == (6, 30)
    assert str(s.schedule.tz) == "UTC"
    assert [d.name for d in s.datasets] == ["wikipedia_pageviews"]


def test_first_run_starts_2015_07_01_and_later_runs_start_after_last_date(tmp_path):
    src, http = make(tmp_path, AAPL="Apple_Inc.")
    first = frame_of(src)
    assert http.requests == [("Apple_Inc.", date(2015, 7, 1), YESTERDAY)]
    assert first["date"].min() == pd.Timestamp("2015-07-01") and first["date"].max() == pd.Timestamp(YESTERDAY)

    stored(("2026-11-05", "AAPL", "Apple_Inc."), ("2026-11-08", "AAPL", "Apple_Inc."))
    src, http = make(tmp_path, AAPL="Apple_Inc.")
    later = frame_of(src)
    assert http.requests == [("Apple_Inc.", date(2026, 11, 9), YESTERDAY)]
    assert list(later["date"]) == [pd.Timestamp("2026-11-09"), pd.Timestamp("2026-11-10"), pd.Timestamp("2026-11-11")]


def test_never_requests_today_or_future_days(tmp_path):
    src, http = make(tmp_path, AAPL="Apple_Inc.", MSFT="Microsoft")
    frame_of(src)
    assert {end for _, _, end in http.requests} == {YESTERDAY}
    late = datetime(2026, 11, 12, 23, 59, tzinfo=UTC)
    src, http = make(tmp_path, AAPL="Apple_Inc.")
    frame_of(src, now=late)
    assert http.requests[0][2] == YESTERDAY


def test_nothing_is_requested_when_the_stored_data_already_reaches_the_previous_day(tmp_path):
    stored(("2026-11-11", "AAPL", "Apple_Inc."))
    src, http = make(tmp_path, AAPL="Apple_Inc.")
    out = frame_of(src)
    assert http.requests == [] and out.empty
    stored(("2026-11-12", "AAPL", "Apple_Inc."))  # even a row from today (written by something else) means up to date
    assert frame_of(src).empty and http.requests == []


def test_rows_outside_the_asked_range_are_dropped(tmp_path):
    stored(("2026-11-09", "AAPL", "Apple_Inc."))
    body = {"items": [item("Apple_Inc.", date(2026, 11, 9)), item("Apple_Inc.", date(2026, 11, 10)),
                      item("Apple_Inc.", date(2026, 11, 12))]}
    src, _ = make(tmp_path, {"Apple_Inc.": body}, AAPL="Apple_Inc.")
    assert list(frame_of(src)["date"]) == [pd.Timestamp("2026-11-10")]


def test_404_article_is_reported_and_skipped_not_fatal(tmp_path, caplog):
    src, http = make(tmp_path, {"Gone_Inc.": 404}, AAA="Gone_Inc.", AAPL="Apple_Inc.", MSFT="Microsoft")
    with caplog.at_level(logging.INFO, logger="tp.collect.sources.wikipedia"):
        out = frame_of(src)
    assert [a for a, _, _ in http.requests] == ["Gone_Inc.", "Apple_Inc.", "Microsoft"]
    assert set(out["symbol"]) == {"AAPL", "MSFT"}
    reports = [r for r in caplog.records if "Gone_Inc." in r.getMessage()]
    assert len(reports) == 1 and reports[0].levelno == logging.INFO


def test_a_404_is_not_recorded_anywhere_so_the_next_run_asks_again(tmp_path):
    src, http = make(tmp_path, {"Gone_Inc.": 404}, AAA="Gone_Inc.")
    assert frame_of(src).empty
    assert not any(config.DATA_DIR.rglob("*no_data*"))
    http.requests.clear()
    src2, http2 = make(tmp_path, {"Gone_Inc.": 404}, AAA="Gone_Inc.")  # a new day's run, no progress carried over
    frame_of(src2, now=NOW + timedelta(days=1))
    assert len(http2.requests) == 1


def test_unmapped_symbols_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "events_symbols", lambda: ["AAPL", "ZZZZ", "YYYY"])
    src, http = make(tmp_path, AAPL="Apple_Inc.")
    out = frame_of(src)
    assert [a for a, _, _ in http.requests] == ["Apple_Inc."]
    assert set(out["symbol"]) == {"AAPL"}


def test_rate_stays_under_ten_requests_a_second(tmp_path, monkeypatch):
    http = FakeHttp()
    monkeypatch.setattr(wp.time, "sleep", lambda s: http.events.append(("sleep", s)))
    src = WikipediaPageviews(map_path=write_map(tmp_path, A="Aa", B="Bb", C="Cc"), http_factory=lambda: http)
    frame_of(src)
    assert [e[0] for e in http.events] == ["get", "sleep", "get", "sleep", "get"]
    assert all(e[1] >= 0.11 for e in http.events if e[0] == "sleep")
    assert wp.SPACING_S == 0.12


def test_empty_map_is_a_harmless_no_op(tmp_path):
    http = FakeHttp()
    path = tmp_path / "articles.toml"
    path.write_text("# reviewed map\n[articles]\n")
    src = WikipediaPageviews(map_path=path, http_factory=lambda: http)
    out = frame_of(src)
    assert http.requests == [] and out.empty
    assert list(out.columns) == ["date", "symbol", "article", "views"]
    written: list = []
    assert src.run(ctx(lambda ds, df: written.append(df) or 0)) == 0 and all(df.empty for df in written)
    assert not (config.DATA_DIR / "collect" / "wikipedia_pageviews_progress.json").exists()


def test_a_map_file_without_the_articles_table_is_also_empty(tmp_path):
    path = tmp_path / "articles.toml"
    path.write_text("# nothing reviewed yet\n")
    http = FakeHttp()
    assert frame_of(WikipediaPageviews(map_path=path, http_factory=lambda: http)).empty and http.requests == []


@pytest.mark.parametrize("text", ["[articles\nAAPL = 1", "[articles]\nAAPL = 5\n", "[articles]\nAAPL = \"\"\n",
                                  "articles = 3\n"])
def test_a_malformed_map_is_a_source_error_not_data(tmp_path, text):
    path = tmp_path / "articles.toml"
    path.write_text(text)
    http = FakeHttp()
    with pytest.raises(SourceError):
        frame_of(WikipediaPageviews(map_path=path, http_factory=lambda: http))
    assert http.requests == []


def test_a_missing_map_file_is_a_source_error(tmp_path):
    with pytest.raises(SourceError, match="articles.toml"):
        frame_of(WikipediaPageviews(map_path=tmp_path / "articles.toml", http_factory=FakeHttp))


def test_the_map_is_read_fresh_on_every_run(tmp_path):
    src, http = make(tmp_path, AAPL="Apple_Inc.")
    frame_of(src)
    write_map(tmp_path, AAPL="Apple_Inc.", MSFT="Microsoft")
    http.requests.clear()
    frame_of(src)
    assert "Microsoft" in [a for a, _, _ in http.requests]


def test_frame_has_the_dataset_columns_and_dtypes(tmp_path):
    src, _ = make(tmp_path, AAPL="Apple_Inc.")
    out = frame_of(src)
    assert list(out.columns) == ["date", "symbol", "article", "views"]
    assert str(out["date"].dtype) == "datetime64[us]" and out["views"].dtype == "int64"
    assert set(out["symbol"]) == {"AAPL"} and set(out["article"]) == {"Apple_Inc."}
    assert out.loc[out["date"] == pd.Timestamp("2026-11-10"), "views"].item() == 100


def test_two_symbols_sharing_an_article_keep_both_rows_with_one_request(tmp_path):
    src, http = make(tmp_path, GOOG="Alphabet_Inc.", GOOGL="Alphabet_Inc.")
    written = src.run(ctx())
    assert [a for a, _, _ in http.requests] == ["Alphabet_Inc."]
    out = pd.read_parquet(datasets.dataset("wikipedia_pageviews").path)
    assert set(out["symbol"]) == {"GOOG", "GOOGL"} and len(out) == written == 2 * len(out[out["symbol"] == "GOOG"])


def test_a_symbol_added_later_to_a_stored_article_is_backfilled(tmp_path):
    stored(("2026-11-10", "GOOG", "Alphabet_Inc."), ("2026-11-11", "GOOG", "Alphabet_Inc."))
    src, http = make(tmp_path, GOOG="Alphabet_Inc.", GOOGL="Alphabet_Inc.")
    out = frame_of(src)
    assert http.requests == [("Alphabet_Inc.", date(2015, 7, 1), YESTERDAY)]
    assert set(out["symbol"]) == {"GOOGL"}


def test_article_titles_are_url_quoted_and_spaces_become_underscores(tmp_path):
    src, http = make(tmp_path, T="AT&T", BRK="Berkshire Hathaway", X="A/B")
    frame_of(src)
    assert [u.split("/user/")[1].split("/daily")[0] for u in http.urls] == ["AT%26T", "Berkshire_Hathaway", "A%2FB"]


def test_http_429_raises_rate_limited_with_retry_after(tmp_path):
    src, _ = make(tmp_path, {"Apple_Inc.": 429}, AAPL="Apple_Inc.")
    with pytest.raises(RateLimited) as e:
        frame_of(src)
    assert e.value.retry_after_s == 600


@pytest.mark.parametrize("value", [500, 503, 403, httpx.ConnectError("down")])
def test_other_failures_are_source_errors(tmp_path, value):
    src, _ = make(tmp_path, {"Apple_Inc.": value}, AAPL="Apple_Inc.")
    with pytest.raises(SourceError) as e:
        frame_of(src)
    assert not isinstance(e.value, RateLimited)


@pytest.mark.parametrize("body", ["<html>maintenance</html>", "", {"detail": "x"}, [1], {"items": "no"},
                                  {"items": [{"timestamp": "2026111000"}]},
                                  {"items": [{"timestamp": "garbage", "views": 1}]},
                                  {"items": [{"timestamp": "2026111000", "views": -1}]},
                                  {"items": [{"timestamp": "2026111000", "views": "many"}]},
                                  {"items": [{"timestamp": "2026111000", "views": True}]}])
def test_a_body_without_the_expected_shape_is_never_data(tmp_path, body):
    written: list = []
    src, _ = make(tmp_path, {"Apple_Inc.": body}, AAPL="Apple_Inc.")
    with pytest.raises(SourceError):
        src.run(ctx(lambda ds, df: written.append(df) or 0))
    assert written == []


def test_the_user_agent_is_descriptive_and_carries_no_email():
    ua = wp.UA["User-Agent"]
    assert len(ua) > 20 and "@" not in ua and "sift" in ua.lower()


def test_a_rate_limit_midway_banks_finished_articles_and_resumes(tmp_path):
    src, http = make(tmp_path, {"Cc": 429}, A="Aa", B="Bb", C="Cc", D="Dd")
    with pytest.raises(RateLimited):
        src.run(ctx())
    assert [a for a, _, _ in http.requests] == ["Aa", "Bb", "Cc"]
    path = config.DATA_DIR / "collect" / "wikipedia_pageviews_progress.json"
    progress = json.loads(path.read_text())
    assert progress["date"] == "2026-11-12" and progress["articles"] == ["Aa", "Bb"]
    assert set(pd.read_parquet(datasets.dataset("wikipedia_pageviews").path)["symbol"]) == {"A", "B"}

    http.special.clear()
    http.requests.clear()
    restarted = WikipediaPageviews(map_path=tmp_path / "articles.toml", http_factory=lambda: http)
    restarted.run(ctx())  # a new instance, as after a daemon restart
    assert [a for a, _, _ in http.requests] == ["Cc", "Dd"]
    assert not path.exists()
    assert set(pd.read_parquet(datasets.dataset("wikipedia_pageviews").path)["symbol"]) == {"A", "B", "C", "D"}


def test_progress_lists_a_404_article_so_a_retry_the_same_day_does_not_ask_again(tmp_path):
    src, http = make(tmp_path, {"Gone": 404, "Cc": 429}, G="Gone", C="Cc")
    with pytest.raises(RateLimited):
        src.run(ctx())
    http.special.pop("Cc")
    http.requests.clear()
    src.run(ctx())
    assert [a for a, _, _ in http.requests] == ["Cc"]


def test_progress_from_another_day_is_ignored(tmp_path):
    path = config.DATA_DIR / "collect" / "wikipedia_pageviews_progress.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"date": "2026-11-11", "articles": ["Aa"]}))
    src, http = make(tmp_path, A="Aa")
    frame_of(src)
    assert [a for a, _, _ in http.requests] == ["Aa"]


def test_a_successful_run_leaves_no_progress_file(tmp_path):
    src, _ = make(tmp_path, A="Aa")
    src.run(ctx())
    assert not (config.DATA_DIR / "collect" / "wikipedia_pageviews_progress.json").exists()


def test_run_stores_the_rows_with_the_composite_key_and_reruns_add_nothing_new(tmp_path):
    src, http = make(tmp_path, AAPL="Apple_Inc.")
    first = src.run(ctx())
    assert first > 0
    http.requests.clear()
    assert src.run(ctx()) == 0 and http.requests == []


def test_dataset_key_includes_the_symbol_so_symbols_sharing_an_article_do_not_collide():
    ds = datasets.dataset("wikipedia_pageviews")
    assert ds.key == ("date", "symbol", "article") and ds.ts_col == "date"


def test_build_sources_registers_it_from_settings():
    found = {s.name: s for s in build_sources(SETTINGS)}["wikipedia_pageviews"]
    assert isinstance(found, WikipediaPageviews) and found.schedule.at.hour == 6 and str(found.schedule.tz) == "UTC"


def test_build_sources_skips_a_source_whose_table_says_enabled_false():
    sources = {k: dict(v) for k, v in SETTINGS["sources"].items()}
    sources["wikipedia_pageviews"]["enabled"] = False
    names = [s.name for s in build_sources({"sources": sources})]
    assert "wikipedia_pageviews" not in names and "sp500_changes" in names
    sources["wikipedia_pageviews"]["enabled"] = True
    assert "wikipedia_pageviews" in [s.name for s in build_sources({"sources": sources})]


def test_build_sources_skips_any_disabled_source_not_only_wikipedia():
    sources = {k: dict(v) for k, v in SETTINGS["sources"].items()}
    sources["sec_form4"]["enabled"] = False
    names = [s.name for s in build_sources({"sources": sources})]
    assert "sec_form4" not in names and "sec_filings" in names


def test_a_disabled_source_may_omit_schedule_keys_but_a_missing_table_still_exits():
    sources = {k: dict(v) for k, v in SETTINGS["sources"].items()}
    sources["wikipedia_pageviews"] = {"enabled": False}
    assert "wikipedia_pageviews" not in [s.name for s in build_sources({"sources": sources})]
    del sources["wikipedia_pageviews"]
    with pytest.raises(SystemExit):
        build_sources({"sources": sources})
    assert source_settings(SETTINGS, "wikipedia_pageviews")["schedule"] == "daily 06:30 UTC"


def test_shipped_config_disables_the_source_and_ships_an_empty_reviewed_map():
    from tp.collect.datasets import load_settings
    assert load_settings()["sources"]["wikipedia_pageviews"]["enabled"] is False
    import tomllib
    text = (config.ROOT / "config" / "wikipedia_articles.toml").read_text()
    assert text.startswith("#") and "scripts/build_wikipedia_map.py" in text
    assert not tomllib.loads(text).get("articles")
    assert wp.articles_path() == config.ROOT / "config" / "wikipedia_articles.toml"
    assert len(wp.load_articles(wp.articles_path())) == 0


# scripts/build_wikipedia_map.py

def load_script():
    spec = importlib.util.spec_from_file_location("build_wikipedia_map", Path(__file__).parents[2] / "scripts" / "build_wikipedia_map.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeSearch:
    def __init__(self, answers: dict[str, object]):
        self.answers = answers
        self.urls: list[str] = []

    def get(self, url: str) -> httpx.Response:
        self.urls.append(url)
        name = httpx.URL(url).params["q"]
        value = self.answers.get(name, {"pages": []})
        request = httpx.Request("GET", url)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, int):
            return httpx.Response(value, request=request)
        return httpx.Response(200, json=value, request=request)


class FakeAlpaca:
    def assets(self, status="active"):
        return [{"symbol": "AAPL", "name": "Apple Inc. Common Stock"}, {"symbol": "BRK.B", "name": "Berkshire Hathaway Inc. Class B"},
                {"symbol": "NONAME", "name": ""}, {"symbol": "OTHER", "name": "Other Corp"}]


def page(title: str) -> dict:
    return {"pages": [{"id": 1, "key": title.replace(" ", "_"), "title": title}]}


def run_script(tmp_path, monkeypatch, search, symbols=("AAPL", "BRK.B", "NONAME", "MISSING", "ZERO")):
    script = load_script()
    monkeypatch.setattr(config, "events_symbols", lambda: list(symbols))
    sleeps: list[float] = []
    monkeypatch.setattr(script.time, "sleep", sleeps.append)
    out = tmp_path / "candidates.toml"
    rc = script.main(["--out", str(out)], client=FakeAlpaca(), http=search)
    return script, rc, out, sleeps


def test_script_writes_candidates_with_the_matched_company_name(tmp_path, monkeypatch):
    search = FakeSearch({"Apple Inc.": page("Apple Inc."), "Berkshire Hathaway Inc.": page("Berkshire Hathaway")})
    _, rc, out, sleeps = run_script(tmp_path, monkeypatch, search, symbols=("AAPL", "BRK.B"))
    assert rc == 0
    text = out.read_text()
    assert 'AAPL = "Apple_Inc."  # matched from "Apple Inc. Common Stock"' in text
    assert '"BRK.B" = "Berkshire_Hathaway"  # matched from "Berkshire Hathaway Inc. Class B"' in text
    import tomllib
    assert tomllib.loads(text)["articles"] == {"AAPL": "Apple_Inc.", "BRK.B": "Berkshire_Hathaway"}
    assert all(u.startswith("https://en.wikipedia.org/w/rest.php/v1/search/title?") and "limit=1" in u for u in search.urls)
    assert sleeps and all(s >= 0.2 for s in sleeps)


def test_script_marks_symbols_without_a_name_or_a_match_as_comments(tmp_path, monkeypatch):
    search = FakeSearch({"Apple Inc.": page("Apple Inc.")})
    _, rc, out, _ = run_script(tmp_path, monkeypatch, search)
    text = out.read_text()
    import tomllib
    assert rc == 0 and list(tomllib.loads(text)["articles"]) == ["AAPL"]
    assert "# NONAME: no company name" in text and "# MISSING: no company name" in text
    assert "# BRK.B: no Wikipedia match" in text


def test_script_never_touches_the_reviewed_file(tmp_path, monkeypatch):
    reviewed = config.ROOT / "config" / "wikipedia_articles.toml"
    before = reviewed.read_text()
    script = load_script()
    assert script.CANDIDATES_PATH.name == "wikipedia_articles.candidates.toml"
    assert script.CANDIDATES_PATH != script.REVIEWED_PATH
    monkeypatch.setattr(config, "events_symbols", lambda: ["AAPL"])
    monkeypatch.setattr(script.time, "sleep", lambda s: None)
    assert script.main(["--out", str(script.REVIEWED_PATH)], client=FakeAlpaca(), http=FakeSearch({})) == 2
    assert reviewed.read_text() == before


def test_script_uses_a_descriptive_user_agent_without_an_email():
    ua = load_script().UA["User-Agent"]
    assert "@" not in ua and "sift" in ua.lower()


def test_script_search_failure_writes_nothing(tmp_path, monkeypatch):
    search = FakeSearch({"Apple Inc.": 429})
    _, rc, out, _ = run_script(tmp_path, monkeypatch, search, symbols=("AAPL",))
    assert rc == 1 and not out.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_script_replaces_an_older_candidates_file_atomically(tmp_path, monkeypatch):
    (tmp_path / "candidates.toml").write_text("old")
    search = FakeSearch({"Apple Inc.": page("Apple Inc.")})
    _, rc, out, _ = run_script(tmp_path, monkeypatch, search, symbols=("AAPL",))
    assert rc == 0 and out.read_text() != "old" and sorted(p.name for p in tmp_path.iterdir()) == ["candidates.toml"]


@pytest.mark.parametrize("raw, name", [
    ("Apple Inc. Common Stock", "Apple Inc."), ("Alphabet Inc. Class A Common Stock", "Alphabet Inc."),
    ("Taiwan Semiconductor Manufacturing Company Ltd. American Depositary Shares", "Taiwan Semiconductor Manufacturing Company Ltd."),
    ("Berkshire Hathaway Inc. Class B", "Berkshire Hathaway Inc."), ("Stock Yards Bancorp, Inc.", "Stock Yards Bancorp, Inc."),
    ("Walmart Inc., Common Stock", "Walmart Inc."), ("", ""),
])
def test_script_company_name_drops_share_class_words_only_at_the_end(raw, name):
    assert load_script().company_name(raw) == name
