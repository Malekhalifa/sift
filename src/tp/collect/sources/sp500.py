"""S&P 500 index changes, scraped from the "changes" table of Wikipedia's Historical components of the S&P 500 page.

Each row is one change: the effective date, the ticker added and the ticker removed ('' when a change only adds or only
removes), and Wikipedia's stated reason. Announcement dates are NOT available yet: the page lists only the effective
date, so a later task has to source the announcements (S&P press releases) before a trading rule may act on a change.

Wikipedia is an editable page, so the layout is checked: a page without the table, a table whose leading columns are not
Effective Date, Added (Ticker, Security), Removed (Ticker, Security) and Reason, a date that does not parse, or a table
with no rows raises SourceError. Nothing is stored from such a page.
"""
from __future__ import annotations

import io
import logging
from collections.abc import Callable
from datetime import timedelta

import httpx
import pandas as pd

from tp.collect import datasets
from tp.collect.datasets import Dataset
from tp.collect.source import (
    RateLimited,
    RunContext,
    Source,
    SourceError,
    parse_schedule,
)

log = logging.getLogger(__name__)

URL = "https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500"
UA = {"User-Agent": "sift-research (market data research; python-httpx)"}
RETRY_AFTER_S = 600
DATE_FORMAT = "%B %d, %Y"
KEY = ["effective_date", "added", "removed"]
LAYOUT = [  # the leading columns, in order; columns after them (Refs) are ignored
    ("Effective Date", "Effective Date"), ("Added", "Ticker"), ("Added", "Security"),
    ("Removed", "Ticker"), ("Removed", "Security"), ("Reason", "Reason"),
]
NAMES = {0: "effective_date", 1: "added", 3: "removed", 5: "reason"}


def _default_http() -> httpx.Client:
    return httpx.Client(headers=UA, timeout=60.0, follow_redirects=True)


def _ticker(series: pd.Series) -> pd.Series:
    """Stripped tickers, '' when empty; Wikipedia has a few cells with a stray trailing '|' (ALLE |, JCP |, ITT |)."""
    return series.fillna("").astype("str").str.replace(r"\s*\|\s*$", "", regex=True).str.strip()


def parse_changes(html: str) -> pd.DataFrame:
    """The changes table as a frame of effective_date, added, removed, reason; SourceError when the page is not as expected."""
    try:
        tables = pd.read_html(io.StringIO(html), attrs={"id": "changes"}, flavor="lxml")
    except ValueError as e:
        raise SourceError(f"S&P 500 changes: no table with id 'changes' on the page ({e})") from e
    table = tables[0]
    if not isinstance(table.columns, pd.MultiIndex):
        raise SourceError(f"S&P 500 changes: columns {list(table.columns)} are not the expected two-level layout")
    if list(table.columns[: len(LAYOUT)]) != LAYOUT:
        raise SourceError(f"S&P 500 changes: columns {list(table.columns)} do not start with {LAYOUT}")
    if table.empty:
        raise SourceError("S&P 500 changes: the table has no rows")
    df = table.iloc[:, list(NAMES)].set_axis(list(NAMES.values()), axis=1)
    dates = pd.to_datetime(df["effective_date"], format=DATE_FORMAT, errors="coerce")
    if dates.isna().any():
        bad = df.loc[dates.isna(), "effective_date"].head(3).tolist()
        raise SourceError(f"S&P 500 changes: unparseable effective date {bad}")
    out = pd.DataFrame({
        "effective_date": dates.astype("datetime64[us]"), "added": _ticker(df["added"]), "removed": _ticker(df["removed"]),
        "reason": df["reason"].fillna("").astype("str").str.strip(),
    })
    out = out.drop_duplicates(KEY)
    return out.sort_values("effective_date", kind="stable").reset_index(drop=True)


class Sp500Changes(Source):
    name = "sp500_changes"
    rate_group = "wikipedia"

    def __init__(
        self,
        schedule: str = "weekly sun 10:00 America/New_York",
        lag_minutes: int = 0,
        http_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        self.schedule = parse_schedule(schedule)
        self.lag = timedelta(minutes=lag_minutes)
        self.datasets = (datasets.dataset("sp500_changes"),)
        self._http_factory = http_factory or _default_http

    def fetch(self, ctx: RunContext) -> dict[Dataset, pd.DataFrame]:
        http = self._http_factory()
        try:
            r = http.get(URL)
            r.raise_for_status()
            html = r.text
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise RateLimited("S&P 500 changes: Wikipedia rate limited the request", retry_after_s=RETRY_AFTER_S) from e
            raise SourceError(f"S&P 500 changes download failed: {e}") from e
        except httpx.HTTPError as e:
            raise SourceError(f"S&P 500 changes download failed: {type(e).__name__}: {e}") from e
        finally:
            if isinstance(http, httpx.Client):
                http.close()
        return {self.datasets[0]: parse_changes(html)}
