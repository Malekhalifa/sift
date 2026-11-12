"""Political sources: Department of Defense contract transactions of at least $100 million (USAspending.gov) and Donald
Trump's original posts (tweets 2016-2018 from the bpb27 archive, Truth Social from CNN's archive).

`fetch_tweets`, `fetch_truth` and `fetch_awards` are shared with scripts/fetch_political.py. Awards are fetched
incrementally: a run asks again for the month of the newest stored action date, and the writer drops what is already stored.
CNN's archive is downloaded in full on every run (a few MB). The bpb27 tweets never change, so they are downloaded only
while the stored posts file has no `twitter` rows; that is derived from the file itself, there is no separate marker.

A body that is not what was asked for (not a parquet, not a zip, JSON without `results`, missing columns, no rows at all
from the Truth Social archive) raises SourceError and is never turned into rows.
"""
from __future__ import annotations

import io
import json
import logging
import re
import time
import zipfile
from collections.abc import Callable
from datetime import timedelta
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from tp import political
from tp.collect import datasets
from tp.collect.datasets import Dataset
from tp.collect.source import (
    DEFAULT_TZ,
    RateLimited,
    RunContext,
    Source,
    SourceError,
    parse_schedule,
)

log = logging.getLogger(__name__)

TWEETS = "https://raw.githubusercontent.com/bpb27/trump_tweet_data_archive/master/condensed_{year}.json.zip"
TRUTH = "https://ix.cnn.io/data/truth-social/truth_archive.parquet"
USASPENDING = "https://api.usaspending.gov/api/v2/search/spending_by_transaction/"
UA = {"User-Agent": "sift-research"}
TAG = re.compile(r"<[^>]+>")
RETRY_AFTER_S = 600
FIRST_AWARD_DAY = pd.Timestamp(2016, 1, 1)
AWARD_RETRIES = 4
AWARD_KEY = ["award_id", "action_date", "amount"]
AWARD_COLUMNS = ["award_id", "recipient", "action_date", "amount"]
POST_COLUMNS = ["source", "id", "ts", "text"]
# What a body that is not the expected shape raises while it is parsed.
PARSE_ERRORS = (ValueError, KeyError, TypeError, AttributeError, OSError, zipfile.BadZipFile)


def _posts_frame(source: str, ids: pd.Series, ts: pd.Series, text: pd.Series) -> pd.DataFrame:
    """Posts in the legacy file's dtypes: str columns and a microsecond UTC timestamp."""
    return pd.DataFrame({
        "source": pd.Series(source, index=ids.index, dtype="str"), "id": ids.astype("str"),
        "ts": pd.to_datetime(ts, utc=True).astype("datetime64[us, UTC]"), "text": text.astype("str"),
    })[POST_COLUMNS]


def fetch_tweets(http: httpx.Client) -> pd.DataFrame:
    rows = []
    for year in (2016, 2017, 2018):
        r = http.get(TWEETS.format(year=year))
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            rows += json.loads(z.read(z.namelist()[0]))
    df = pd.DataFrame(rows)
    df = df[~df["is_retweet"].astype(bool) & ~df["text"].str.startswith("RT @")].reset_index(drop=True)
    ts = pd.to_datetime(df["created_at"], format="%a %b %d %H:%M:%S %z %Y", utc=True)
    return _posts_frame("twitter", df["id_str"], ts, df["text"])


def fetch_truth(http: httpx.Client) -> pd.DataFrame:
    r = http.get(TRUTH)
    r.raise_for_status()
    df = pd.read_parquet(io.BytesIO(r.content))
    if df.empty:
        raise ValueError("the Truth Social archive has no rows")
    text = df["content"].fillna("").map(lambda s: TAG.sub(" ", s).replace("&amp;", "&").strip())
    keep = ~text.str.startswith("RT") & (text.str.len() > 0)
    return _posts_frame("truth", df["id"], df["created_at"], text)[keep].reset_index(drop=True)


def _empty_awards() -> pd.DataFrame:
    return pd.DataFrame({
        "award_id": pd.Series(dtype="str"), "recipient": pd.Series(dtype="str"),
        "action_date": pd.Series(dtype="datetime64[us]"), "amount": pd.Series(dtype="float64"),
    })


def fetch_awards(http: httpx.Client, since: pd.Timestamp | None = None, until: pd.Timestamp | None = None) -> pd.DataFrame:
    """DoD transactions of at least MIN_AWARD from the month of `since` (2016-01 when None) to the month of `until` (today)."""
    rows = []
    first = since.to_period("M").start_time if since is not None else FIRST_AWARD_DAY
    last = pd.Timestamp.today().normalize() if until is None else until
    for month_start in pd.date_range(first, last, freq="MS"):
        start = month_start.strftime("%Y-%m-%d")
        end = (pd.Timestamp(start) + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")
        page = 1
        while True:
            body = {
                "filters": {
                    "agencies": [{"type": "awarding", "tier": "toptier", "name": "Department of Defense"}],
                    "award_type_codes": ["A", "B", "C", "D"],
                    "time_period": [{"start_date": start, "end_date": end}],
                    "award_amounts": [{"lower_bound": political.MIN_AWARD}],
                },
                "fields": ["Award ID", "Recipient Name", "Action Date", "Transaction Amount"],
                "sort": "Transaction Amount", "order": "desc", "limit": 100, "page": page,
            }
            for attempt in range(AWARD_RETRIES):
                r = http.post(USASPENDING, json=body)
                if r.status_code < 500:
                    break
                time.sleep(2 * (attempt + 1))
            r.raise_for_status()
            data = r.json()
            rows += [x for x in data["results"] if (x.get("Transaction Amount") or 0) >= political.MIN_AWARD]
            # results are sorted by transaction amount, so stop once a page reaches transactions below the threshold
            small = [x for x in data["results"] if (x.get("Transaction Amount") or 0) < political.MIN_AWARD]
            if small or not data.get("page_metadata", {}).get("hasNext"):
                break
            page += 1
        log.info("  awards %s: %s so far", start[:7], f"{len(rows):,}")
    if not rows:
        return _empty_awards()
    df = pd.DataFrame(rows).rename(columns={"Award ID": "award_id", "Recipient Name": "recipient", "Action Date": "action_date",
                                            "Transaction Amount": "amount"})
    out = pd.DataFrame({
        "award_id": df["award_id"].astype("str"), "recipient": df["recipient"].astype("str"),
        "action_date": pd.to_datetime(df["action_date"]).astype("datetime64[us]"),
        "amount": pd.to_numeric(df["amount"]).astype("float64"),
    })[AWARD_COLUMNS]
    return out.drop_duplicates(AWARD_KEY).reset_index(drop=True)


def _default_http() -> httpx.Client:
    return httpx.Client(headers=UA, timeout=120.0, follow_redirects=True)


def _failure(e: Exception, what: str) -> SourceError:
    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429:
        return RateLimited(f"{what}: rate limited", retry_after_s=RETRY_AFTER_S)
    return SourceError(f"{what} failed: {type(e).__name__}: {e}")


def _stored_column(ds: Dataset, column: str) -> pd.Series | None:
    """One column of the stored file (not through store.read: this is bookkeeping, not an analysis read)."""
    if not ds.path.exists():
        return None
    try:
        return pd.read_parquet(ds.path, columns=[column])[column]
    except Exception as e:
        raise SourceError(f"cannot read {ds.path}: {e}") from e


class _PoliticalSource(Source):
    def __init__(self, schedule: str, lag_minutes: int, http_factory: Callable[[], httpx.Client] | None) -> None:
        self.schedule = parse_schedule(schedule)
        self.lag = timedelta(minutes=lag_minutes)
        self._http_factory = http_factory or _default_http


class DodAwards(_PoliticalSource):
    """DoD contract transactions of at least $100 million; each run re-reads from the month of the newest stored one."""

    name = "dod_awards"
    rate_group = "usaspending"

    def __init__(
        self,
        schedule: str = "weekly mon 06:00 America/New_York",
        lag_minutes: int = 0,
        http_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        super().__init__(schedule, lag_minutes, http_factory)
        self.datasets = (datasets.dataset("dod_awards"),)

    def fetch(self, ctx: RunContext) -> dict[Dataset, pd.DataFrame]:
        stored = _stored_column(self.datasets[0], "action_date")
        since = None if stored is None or stored.dropna().empty else pd.Timestamp(stored.max())
        until = pd.Timestamp(ctx.now.astimezone(ZoneInfo(DEFAULT_TZ)).date())
        http = self._http_factory()
        try:
            frame = fetch_awards(http, since, until)
        except (httpx.HTTPError, *PARSE_ERRORS) as e:
            raise _failure(e, "USAspending awards") from e
        finally:
            if isinstance(http, httpx.Client):
                http.close()
        return {self.datasets[0]: frame}


class TrumpPosts(_PoliticalSource):
    """Original posts: CNN's Truth Social archive on every run, the 2016-2018 tweets only while none are stored."""

    name = "trump_posts"
    rate_group = "posts"

    def __init__(
        self,
        schedule: str = "daily 07:00 America/New_York",
        lag_minutes: int = 0,
        http_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        super().__init__(schedule, lag_minutes, http_factory)
        self.datasets = (datasets.dataset("trump_posts"),)

    def fetch(self, ctx: RunContext) -> dict[Dataset, pd.DataFrame]:
        stored = _stored_column(self.datasets[0], "source")
        have_tweets = stored is not None and bool((stored == "twitter").any())
        http = self._http_factory()
        try:
            parts = [] if have_tweets else [fetch_tweets(http)]
            parts.append(fetch_truth(http))
        except (httpx.HTTPError, *PARSE_ERRORS) as e:
            raise _failure(e, "posts download") from e
        finally:
            if isinstance(http, httpx.Client):
                http.close()
        return {self.datasets[0]: pd.concat(parts, ignore_index=True)}
