"""Wikipedia daily page views (user traffic) for the articles in the reviewed map config/wikipedia_articles.toml.

The map is `[articles]  SYMBOL = "Article_Title"`, read fresh on every run; a symbol without an entry is ignored and an
empty map makes the run a no-op. Each article is read from the Wikimedia per-article endpoint for the days after the last
stored date of its symbols (2015-07-01 on the first run) up to the previous UTC day, which is final once it has closed.

A 404 for an article (unknown title, or no views in the asked range) is reported once per run and skipped; nothing is
recorded about it, so the next run asks again. 429 raises RateLimited; any other failure, or a body that is not a
`{"items": [...]}` list of dated non-negative view counts, raises SourceError and nothing from it is stored. Articles read
before a failure are stored and listed in the day's progress file, so a retry resumes with the rest.
"""
from __future__ import annotations

import logging
import time
import tomllib
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx
import pandas as pd

from tp import config
from tp.collect import datasets
from tp.collect.datasets import Dataset
from tp.collect.source import (
    RateLimited,
    RunContext,
    Source,
    SourceError,
    parse_schedule,
)
from tp.collect.sources.progress import load_progress, save_progress

log = logging.getLogger(__name__)

URL = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
    "{article}/daily/{start}/{end}"
)
UA = {"User-Agent": "sift-research (market data research; python-httpx)"}
FIRST = date(2015, 7, 1)  # the first day the pageviews API has data for
SPACING_S = 0.12  # at most about 8 requests a second, under the 10 a second guidance
RETRY_AFTER_S = 600
COLUMNS = ["date", "symbol", "article", "views"]


def articles_path() -> Path:
    return config.ROOT / "config" / "wikipedia_articles.toml"


def progress_path() -> Path:
    return config.DATA_DIR / "collect" / "wikipedia_pageviews_progress.json"


def load_articles(path: Path) -> dict[str, str]:
    """The reviewed `symbol -> article` map. Spaces in a title become underscores. SourceError when the file is missing
    or unreadable, or an entry is not a non-empty string."""
    try:
        with open(path, "rb") as f:
            table = tomllib.load(f).get("articles", {})
    except OSError as e:
        raise SourceError(f"Wikipedia pageviews: cannot read {path}: {e}") from e
    except tomllib.TOMLDecodeError as e:
        raise SourceError(f"Wikipedia pageviews: {path.name} is not valid TOML: {e}") from e
    if not isinstance(table, dict):
        raise SourceError(f"Wikipedia pageviews: [articles] in {path.name} is not a table")
    out: dict[str, str] = {}
    for symbol, title in table.items():
        if not isinstance(title, str) or not title.strip():
            raise SourceError(f"Wikipedia pageviews: {path.name} entry {symbol!r} is not a non-empty article title")
        out[symbol.strip()] = "_".join(title.split())
    return out


def _empty() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.Series(dtype="datetime64[us]"), "symbol": pd.Series(dtype="object"),
        "article": pd.Series(dtype="object"), "views": pd.Series(dtype="int64"),
    })


def parse_views(body: object, article: str) -> pd.DataFrame:
    """Frame of date, views from a per-article response; SourceError when it lacks the expected shape."""
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list):
        raise SourceError(f"Wikipedia pageviews: {article}: response has no 'items' list")
    rows: list[tuple[datetime, int]] = []
    for it in items:
        views = it.get("views") if isinstance(it, dict) else None
        stamp = it.get("timestamp") if isinstance(it, dict) else None
        if not isinstance(views, int) or isinstance(views, bool) or views < 0 or not isinstance(stamp, str):
            raise SourceError(f"Wikipedia pageviews: {article}: unusable item {it!r}")
        try:
            rows.append((datetime.strptime(stamp, "%Y%m%d%H"), views))
        except ValueError as e:
            raise SourceError(f"Wikipedia pageviews: {article}: bad timestamp {stamp!r}") from e
    out = pd.DataFrame(rows, columns=["date", "views"])
    out["date"] = pd.to_datetime(out["date"]).astype("datetime64[us]").dt.normalize()
    out["views"] = out["views"].astype("int64")
    return out


def _default_http() -> httpx.Client:
    return httpx.Client(headers=UA, timeout=60.0, follow_redirects=True)


def _report(not_found: list[str]) -> None:
    if not_found:
        log.info("wikipedia_pageviews: %d articles not found or without views in the range, skipped: %s",
                 len(not_found), ", ".join(not_found))


def _last_dates() -> dict[tuple[str, str], date]:
    """Latest stored date for each (symbol, article)."""
    path = datasets.dataset("wikipedia_pageviews").path
    if not path.exists():
        return {}
    try:
        stored = pd.read_parquet(path, columns=["date", "symbol", "article"])
        last = stored.groupby(["symbol", "article"])["date"].max()
    except Exception as e:
        raise SourceError(f"cannot read {path}: {e}") from e
    return {key: pd.Timestamp(d).date() for key, d in last.items()}


class WikipediaPageviews(Source):
    name = "wikipedia_pageviews"
    rate_group = "wikimedia"

    def __init__(
        self,
        schedule: str = "daily 06:30 UTC",
        lag_minutes: int = 0,
        http_factory: Callable[[], httpx.Client] | None = None,
        map_path: Path | None = None,
    ) -> None:
        self.schedule = parse_schedule(schedule)
        self.lag = timedelta(minutes=lag_minutes)
        self.datasets = (datasets.dataset("wikipedia_pageviews"),)
        self._http_factory = http_factory or _default_http
        self._map_path = map_path

    @staticmethod
    def _frame(parts: list[pd.DataFrame]) -> pd.DataFrame:
        return pd.concat(parts, ignore_index=True)[COLUMNS] if parts else _empty()

    def _read(self, http: httpx.Client, article: str, start: date, end: date) -> pd.DataFrame | None:
        """Views of `article` in [start, end], or None for a 404."""
        url = URL.format(article=quote(article, safe=""), start=f"{start:%Y%m%d}00", end=f"{end:%Y%m%d}00")
        try:
            r = http.get(url)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            body = r.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise RateLimited(f"Wikipedia pageviews: {article}: rate limited", retry_after_s=RETRY_AFTER_S) from e
            raise SourceError(f"Wikipedia pageviews: {article}: {e}") from e
        except httpx.HTTPError as e:
            raise SourceError(f"Wikipedia pageviews: {article}: {type(e).__name__}: {e}") from e
        except ValueError as e:
            raise SourceError(f"Wikipedia pageviews: {article}: response is not JSON") from e
        return parse_views(body, article)

    def _bank(self, ctx: RunContext, progress: dict, done: set[str], parts: list[pd.DataFrame], read: list[str]) -> None:
        """Store what this run read before it stopped, then record those articles as done for today."""
        frame = self._frame(parts)
        if not frame.empty:
            ctx.writer(self.datasets[0], frame)
        done.update(read)
        progress["articles"] = sorted(done)
        save_progress(progress_path(), progress)

    def fetch(self, ctx: RunContext) -> dict[Dataset, pd.DataFrame]:
        mapping = load_articles(self._map_path or articles_path())
        end = ctx.now.astimezone(UTC).date() - timedelta(days=1)
        progress = load_progress(progress_path(), "articles", ctx.now.astimezone(UTC).date().isoformat())
        done = set(progress["articles"])
        symbols_of: dict[str, list[str]] = {}
        for symbol, article in mapping.items():
            symbols_of.setdefault(article, []).append(symbol)
        last = _last_dates() if mapping else {}
        parts: list[pd.DataFrame] = []
        read: list[str] = []
        not_found: list[str] = []
        requests = 0
        http = self._http_factory() if mapping else None
        try:
            for article, symbols in symbols_of.items():
                if article in done:
                    continue
                starts = {s: max(last[s, article] + timedelta(days=1), FIRST) if (s, article) in last else FIRST
                          for s in symbols}
                first = min(starts.values())
                if first > end:
                    read.append(article)
                    continue
                if requests:
                    time.sleep(SPACING_S)
                requests += 1
                views = self._read(http, article, first, end)
                read.append(article)
                if views is None:
                    not_found.append(article)
                    continue
                for symbol in symbols:
                    mine = views[(views["date"] >= pd.Timestamp(starts[symbol])) & (views["date"] <= pd.Timestamp(end))]
                    parts.append(mine.assign(symbol=symbol, article=article))
        except SourceError:
            _report(not_found)
            self._bank(ctx, progress, done, parts, read)
            raise
        finally:
            if isinstance(http, httpx.Client):
                http.close()
        progress_path().unlink(missing_ok=True)
        _report(not_found)
        return {self.datasets[0]: self._frame(parts)}
