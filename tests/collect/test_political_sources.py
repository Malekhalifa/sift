import importlib.util
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
import pytest

from tp import config, political
from tp.collect import datasets, store
from tp.collect.source import Daily, RateLimited, RunContext, SourceError, Weekly
from tp.collect.sources import build_sources
from tp.collect.sources import political as pol
from tp.collect.sources.political import (
    DodAwards,
    TrumpPosts,
    fetch_awards,
    fetch_truth,
)

NOW = datetime(2026, 11, 12, 12, 30, tzinfo=UTC)
TODAY = pd.Timestamp("2026-11-12")
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
}}


class FakeHttp:
    """GET answers by URL and POST answers by a function of the request body; a value may be bytes (200), an int status,
    a dict (200 JSON) or an Exception to raise."""

    def __init__(self, gets=None, post=None):
        self.gets = gets or {}
        self.post_fn = post
        self.urls: list[str] = []
        self.bodies: list[dict] = []

    @staticmethod
    def _response(url: str, value) -> httpx.Response:
        request = httpx.Request("GET", url)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, int):
            return httpx.Response(value, request=request)
        if isinstance(value, dict):
            return httpx.Response(200, json=value, request=request)
        return httpx.Response(200, content=value, request=request)

    def get(self, url: str) -> httpx.Response:
        self.urls.append(url)
        return self._response(url, self.gets.get(url, 404))

    def post(self, url: str, json: dict) -> httpx.Response:
        self.bodies.append(json)
        return self._response(url, self.post_fn(json))


def tx(award_id: str, day: str, amount: float, recipient: str = "ACME CORP") -> dict:
    return {"Award ID": award_id, "Recipient Name": recipient, "Action Date": day, "Transaction Amount": amount}


def page(*rows: dict, more: bool = False) -> dict:
    return {"results": list(rows), "page_metadata": {"hasNext": more}}


def month_of(body: dict) -> str:
    return body["filters"]["time_period"][0]["start_date"][:7]


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(pol.time, "sleep", lambda s: None)


def ctx(writer=None) -> RunContext:
    return RunContext(now=NOW, settings=SETTINGS, writer=writer or (lambda ds, df: store.write(ds, df, now=NOW)))


def legacy_awards(*rows: tuple[str, str, float]) -> None:
    """The legacy file: str ids, naive datetime64[us] action_date, float64 amount, no ingested_at."""
    df = pd.DataFrame({
        "award_id": pd.Series([r[0] for r in rows], dtype="str"), "recipient": pd.Series(["OLD CO"] * len(rows), dtype="str"),
        "action_date": pd.to_datetime([r[1] for r in rows]).astype("datetime64[us]"), "amount": [r[2] for r in rows],
    })
    path = political.awards_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


# DoD awards

def test_awards_since_refetches_from_the_last_month_and_dedupes():
    seen = {
        "2026-09": page(tx("A1", "2026-09-30", 2e8), tx("A1", "2026-09-30", 2e8), tx("A2", "2026-09-10", 3e8)),
        "2026-10": page(tx("B1", "2026-10-05", 1.5e8)),
        "2026-11": page(),
    }
    http = FakeHttp(post=lambda body: seen[month_of(body)])
    df = fetch_awards(http, pd.Timestamp("2026-09-20"), until=TODAY)
    assert [month_of(b) for b in http.bodies] == ["2026-09", "2026-10", "2026-11"]
    assert http.bodies[0]["filters"]["time_period"] == [{"start_date": "2026-09-01", "end_date": "2026-09-30"}]
    assert sorted(df["award_id"]) == ["A1", "A2", "B1"]
    assert df.columns.tolist() == ["award_id", "recipient", "action_date", "amount"]


def test_awards_without_since_start_in_2016():
    http = FakeHttp(post=lambda body: page())
    fetch_awards(http, None, until=pd.Timestamp("2016-03-15"))
    assert [month_of(b) for b in http.bodies] == ["2016-01", "2016-02", "2016-03"]


def test_awards_follow_pages_and_stop_below_the_threshold():
    pages = {1: page(tx("A", "2026-11-02", 5e8), more=True), 2: page(tx("B", "2026-11-03", 2e8), tx("C", "2026-11-04", 5e7), more=True)}
    http = FakeHttp(post=lambda body: pages[body["page"]])
    df = fetch_awards(http, pd.Timestamp("2026-11-01"), until=TODAY)
    assert [b["page"] for b in http.bodies] == [1, 2]
    assert sorted(df["award_id"]) == ["A", "B"]


def test_awards_frame_matches_the_legacy_dtypes():
    http = FakeHttp(post=lambda body: page(tx("A1", "2026-11-02", 150000000)))
    df = fetch_awards(http, pd.Timestamp("2026-11-01"), until=TODAY)
    assert str(df["award_id"].dtype) == "str" and str(df["recipient"].dtype) == "str"
    assert str(df["action_date"].dtype) == "datetime64[us]"
    assert str(df["amount"].dtype) == "float64"


def test_awards_with_no_rows_is_an_empty_typed_frame():
    df = fetch_awards(FakeHttp(post=lambda body: page()), pd.Timestamp("2026-11-01"), until=TODAY)
    assert df.empty and df.columns.tolist() == ["award_id", "recipient", "action_date", "amount"]
    assert str(df["action_date"].dtype) == "datetime64[us]" and str(df["amount"].dtype) == "float64"


def test_awards_retry_a_5xx_then_succeed():
    answers = iter([503, page(tx("A1", "2026-11-02", 2e8))])
    http = FakeHttp(post=lambda body: next(answers))
    df = fetch_awards(http, pd.Timestamp("2026-11-01"), until=TODAY)
    assert len(http.bodies) == 2 and df["award_id"].tolist() == ["A1"]


def test_dod_awards_run_appends_to_a_legacy_file_without_touching_its_rows():
    legacy_awards(("OLD1", "2026-10-02", 1e8), ("OLD2", "2026-10-20", 2e8))
    seen = {"2026-10": page(tx("OLD2", "2026-10-20", 2e8), tx("NEW1", "2026-10-25", 3e8)), "2026-11": page(tx("NEW2", "2026-11-03", 4e8))}
    http = FakeHttp(post=lambda body: seen[month_of(body)])
    src = DodAwards(http_factory=lambda: http)
    assert src.run(ctx()) == 2
    assert [month_of(b) for b in http.bodies] == ["2026-10", "2026-11"]
    out = pd.read_parquet(political.awards_path())
    assert sorted(out["award_id"]) == ["NEW1", "NEW2", "OLD1", "OLD2"]
    assert out.set_index("award_id").loc["OLD1", "recipient"] == "OLD CO"
    assert str(out["amount"].dtype) == "float64" and str(out["action_date"].dtype) == "datetime64[us]"
    assert "ingested_at" in out.columns


def test_dod_awards_first_run_without_a_file_backfills_from_2016():
    http = FakeHttp(post=lambda body: page(tx("A" + month_of(body), month_of(body) + "-05", 2e8)) if month_of(body) == "2016-01" else page())
    src = DodAwards(http_factory=lambda: http)
    assert src.run(ctx()) == 1
    assert month_of(http.bodies[0]) == "2016-01"
    assert month_of(http.bodies[-1]) == "2026-11"


def test_dod_awards_never_asks_past_the_run_time():
    http = FakeHttp(post=lambda body: page())
    legacy_awards(("OLD1", "2026-10-02", 1e8))
    DodAwards(http_factory=lambda: http).fetch(ctx())
    assert month_of(http.bodies[-1]) == "2026-11"


def test_dod_awards_429_is_rate_limited_and_other_failures_are_source_errors():
    legacy_awards(("OLD1", "2026-11-02", 1e8))
    with pytest.raises(RateLimited) as e:
        DodAwards(http_factory=lambda: FakeHttp(post=lambda b: 429)).fetch(ctx())
    assert e.value.retry_after_s == 600
    bad = [lambda b: 500, lambda b: httpx.ConnectError("boom"), lambda b: {"unexpected": 1}, lambda b: b"<html>not json</html>",
           lambda b: page({"Award ID": "A", "Transaction Amount": 2e8})]
    for fn in bad:
        with pytest.raises(SourceError) as err:
            DodAwards(http_factory=lambda fn=fn: FakeHttp(post=fn)).fetch(ctx())
        assert not isinstance(err.value, RateLimited)


def test_dod_awards_unreadable_stored_file_is_a_source_error_and_is_not_overwritten():
    path = political.awards_path()
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not parquet")
    http = FakeHttp(post=lambda body: page(tx("A", "2026-11-02", 2e8)))
    with pytest.raises(SourceError):
        DodAwards(http_factory=lambda: http).run(ctx())
    assert path.read_bytes() == b"not parquet" and http.bodies == []


def test_dod_awards_registers_from_settings():
    found = {s.name: s for s in build_sources(SETTINGS)}["dod_awards"]
    assert isinstance(found.schedule, Weekly) and (found.schedule.weekday, found.schedule.at.hour) == (0, 6)
    assert found.rate_group == "usaspending"
    assert found.datasets == (datasets.dataset("dod_awards"),)


# posts

def truth_parquet(rows: list[dict]) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(rows).to_parquet(buf, index=False)
    return buf.getvalue()


def truth(id_: str, created: str, content: str | None) -> dict:
    return {"id": id_, "created_at": created, "content": content}


def tweets_zip(year: int, rows: list[dict]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"condensed_{year}.json", json.dumps(rows))
    return buf.getvalue()


def tweet(id_: str, created: str, text: str, retweet: bool = False) -> dict:
    return {"id_str": id_, "created_at": created, "text": text, "is_retweet": retweet}


TRUTH_ROWS = [
    truth("1", "2026-11-01T12:00:00.000Z", "<p>Great day for <b>Boeing</b> &amp; America</p>"),
    truth("2", "2026-11-02T12:00:00.000Z", "RT @someone: look at this"),
    truth("3", "2026-11-03T12:00:00.000Z", "<p></p>"),
    truth("4", "2026-11-04T12:00:00.000Z", None),
    truth("5", "2026-11-05T12:00:00.000Z", "   "),
    truth("6", "2026-11-06T12:00:00.000Z", "Plain text post"),
]


def tweet_routes() -> dict:
    return {
        pol.TWEETS.format(year=2016): tweets_zip(2016, [tweet("t1", "Fri Jan 01 00:44:14 +0000 2016", "Happy new year"),
                                                      tweet("t2", "Fri Jan 01 05:00:00 +0000 2016", "RT @x: hi", retweet=True)]),
        pol.TWEETS.format(year=2017): tweets_zip(2017, [tweet("t3", "Sun Jan 01 05:00:00 -0500 2017", "RT @y: ok"),
                                                      tweet("t4", "Mon Jan 02 10:00:00 -0500 2017", "Back to work")]),
        pol.TWEETS.format(year=2018): tweets_zip(2018, []),
    }


def legacy_posts(sources=("twitter",)) -> None:
    df = pd.DataFrame({
        "source": pd.Series(list(sources), dtype="str"), "id": pd.Series([f"old{i}" for i in range(len(sources))], dtype="str"),
        "ts": pd.to_datetime(["2016-01-01T00:44:14Z"] * len(sources)).astype("datetime64[us, UTC]"),
        "text": pd.Series(["old post"] * len(sources), dtype="str"),
    })
    path = political.posts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def test_posts_drop_reposts_and_empty_text():
    df = fetch_truth(FakeHttp(gets={pol.TRUTH: truth_parquet(TRUTH_ROWS)}))
    assert df["id"].tolist() == ["1", "6"]
    assert df["text"].tolist() == ["Great day for  Boeing  & America", "Plain text post"]
    assert df.columns.tolist() == ["source", "id", "ts", "text"]
    assert set(df["source"]) == {"truth"}


def test_tweets_drop_retweets_and_use_utc_timestamps():
    df = pol.fetch_tweets(FakeHttp(gets=tweet_routes()))
    assert df["id"].tolist() == ["t1", "t4"]
    assert df["ts"].tolist() == [pd.Timestamp("2016-01-01T00:44:14Z"), pd.Timestamp("2017-01-02T15:00:00Z")]


def test_posts_frame_matches_the_legacy_dtypes():
    df = fetch_truth(FakeHttp(gets={pol.TRUTH: truth_parquet(TRUTH_ROWS)}))
    assert [str(df[c].dtype) for c in ("source", "id", "ts", "text")] == ["str", "str", "datetime64[us, UTC]", "str"]
    tw = pol.fetch_tweets(FakeHttp(gets=tweet_routes()))
    assert [str(tw[c].dtype) for c in ("source", "id", "ts", "text")] == ["str", "str", "datetime64[us, UTC]", "str"]


def test_trump_posts_first_run_fetches_tweets_and_truth():
    http = FakeHttp(gets=tweet_routes() | {pol.TRUTH: truth_parquet(TRUTH_ROWS)})
    src = TrumpPosts(http_factory=lambda: http)
    assert src.run(ctx()) == 4
    assert pol.TRUTH in http.urls and pol.TWEETS.format(year=2016) in http.urls
    out = pd.read_parquet(political.posts_path())
    assert out["source"].value_counts().to_dict() == {"twitter": 2, "truth": 2}


def test_trump_posts_does_not_refetch_tweets_once_the_file_has_twitter_rows():
    legacy_posts(("twitter", "truth"))
    http = FakeHttp(gets={pol.TRUTH: truth_parquet(TRUTH_ROWS)})
    src = TrumpPosts(http_factory=lambda: http)
    assert src.run(ctx()) == 2
    assert http.urls == [pol.TRUTH]


def test_trump_posts_fetches_tweets_when_the_file_has_only_truth_rows():
    legacy_posts(("truth",))
    http = FakeHttp(gets=tweet_routes() | {pol.TRUTH: truth_parquet(TRUTH_ROWS)})
    TrumpPosts(http_factory=lambda: http).run(ctx())
    assert pol.TWEETS.format(year=2016) in http.urls
    assert (pd.read_parquet(political.posts_path())["source"] == "twitter").any()


def test_trump_posts_second_run_adds_nothing_and_keeps_ingested_at():
    http = FakeHttp(gets=tweet_routes() | {pol.TRUTH: truth_parquet(TRUTH_ROWS)})
    src = TrumpPosts(http_factory=lambda: http)
    src.run(ctx())
    first = pd.read_parquet(political.posts_path())
    later = RunContext(now=datetime(2026, 11, 13, tzinfo=UTC), settings=SETTINGS,
                       writer=lambda ds, df: store.write(ds, df, now=datetime(2026, 11, 13, tzinfo=UTC)))
    assert src.run(later) == 0
    assert pd.read_parquet(political.posts_path())["ingested_at"].tolist() == first["ingested_at"].tolist()
    assert http.urls.count(pol.TWEETS.format(year=2016)) == 1


def test_trump_posts_appends_to_a_legacy_file_with_matching_dtypes():
    legacy_posts(("twitter",))
    src = TrumpPosts(http_factory=lambda: FakeHttp(gets={pol.TRUTH: truth_parquet(TRUTH_ROWS)}))
    src.run(ctx())
    out = pd.read_parquet(political.posts_path())
    assert str(out["ts"].dtype) == "datetime64[us, UTC]" and len(out) == 3


@pytest.mark.parametrize("body", [b"<html>not a parquet</html>", b"", truth_parquet([{"id": "1", "created_at": "2026-11-01T12:00:00Z"}]),
                                  truth_parquet([])])
def test_trump_posts_unusable_truth_body_is_a_source_error_and_never_overwrites(body):
    legacy_posts(("twitter",))
    before = political.posts_path().read_bytes()
    src = TrumpPosts(http_factory=lambda: FakeHttp(gets={pol.TRUTH: body}))
    with pytest.raises(SourceError):
        src.run(ctx())
    assert political.posts_path().read_bytes() == before


def test_trump_posts_bad_tweet_archive_is_a_source_error():
    routes = tweet_routes() | {pol.TWEETS.format(year=2017): b"not a zip", pol.TRUTH: truth_parquet(TRUTH_ROWS)}
    with pytest.raises(SourceError):
        TrumpPosts(http_factory=lambda: FakeHttp(gets=routes)).fetch(ctx())
    assert not political.posts_path().exists()


def test_trump_posts_429_is_rate_limited_and_other_statuses_are_source_errors():
    legacy_posts(("twitter",))
    with pytest.raises(RateLimited) as e:
        TrumpPosts(http_factory=lambda: FakeHttp(gets={pol.TRUTH: 429})).fetch(ctx())
    assert e.value.retry_after_s == 600
    for value in (500, 404, httpx.ConnectError("boom")):
        with pytest.raises(SourceError) as err:
            TrumpPosts(http_factory=lambda value=value: FakeHttp(gets={pol.TRUTH: value})).fetch(ctx())
        assert not isinstance(err.value, RateLimited)


def test_trump_posts_unreadable_stored_file_is_a_source_error_and_is_not_overwritten():
    path = political.posts_path()
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not parquet")
    http = FakeHttp(gets=tweet_routes() | {pol.TRUTH: truth_parquet(TRUTH_ROWS)})
    with pytest.raises(SourceError):
        TrumpPosts(http_factory=lambda: http).run(ctx())
    assert path.read_bytes() == b"not parquet" and http.urls == []


def test_trump_posts_registers_from_settings():
    found = {s.name: s for s in build_sources(SETTINGS)}["trump_posts"]
    assert isinstance(found.schedule, Daily) and found.schedule.at.hour == 7
    assert found.rate_group == "posts"
    assert found.datasets == (datasets.dataset("trump_posts"),)


# the legacy script

def test_fetch_political_script_still_writes_both_files(monkeypatch):
    spec = importlib.util.spec_from_file_location("fetch_political", Path(__file__).parents[2] / "scripts" / "fetch_political.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    http = FakeHttp(gets=tweet_routes() | {script.TRUTH: truth_parquet(TRUTH_ROWS)},
                    post=lambda body: page(tx("A1", "2026-02-02", 2e8)) if month_of(body) == "2026-02" else page())

    class Client:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return http

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(script.httpx, "Client", Client)
    assert script.main() == 0
    posts = pd.read_parquet(political.posts_path())
    assert posts.columns.tolist() == ["source", "id", "ts", "text"] and len(posts) == 4
    awards = pd.read_parquet(political.awards_path())
    assert awards["award_id"].tolist() == ["A1"] * len(awards) and len(awards) == 1
    assert not (config.DATA_DIR / "political" / "posts.parquet.tmp").exists()
