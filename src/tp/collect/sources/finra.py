"""FINRA sources: the consolidated daily short-sale volume files (Reg SHO, CNMS) and the bi-monthly short-interest files.

cdn.finra.org answers 403 (not 404) for a file that does not exist, so a 403 is never read as rate limiting here; only
429 is. Days with no file (weekends, holidays) are remembered in small text files so they are not asked for again.
`fetch_day` and `merge_shortvol` are shared with scripts/fetch_finra.py.

A missing file is not proof of absence (a transient 403, a late post, a proxy block), so recent days are probed again on
every run, absences are recorded only once a date is clearly stale, and a run that suddenly stops finding files raises
instead of recording a streak of absences. The survivorship-free symbols are in finra_shortvol only from the first
recorder run on (earlier days were fetched for a smaller universe); that history is deliberately not backfilled.
"""
from __future__ import annotations

import io
import logging
import os
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd

from tp import config
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

URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{day}.txt"
SHORT_INTEREST_URL = "https://cdn.finra.org/equity/otcmarket/biweekly/shrt{day}.csv"
FIRST = date(2018, 8, 1)  # the first consolidated daily file
FIRST_SETTLEMENT = date(2017, 12, 29)  # the first biweekly short-interest file the recorder keeps
MIN_AGE_BUSINESS_DAYS = 10  # a short-interest file is requested only this long after its settlement date
HOLIDAY_FALLBACK_DAYS = 4  # a settlement date on a market holiday is filed under one of the previous business days
RETRY_AFTER_S = 600
RETRIES = 4
RETRY_PAUSE_S = 0.5  # between tries of one file after a transport error or an unexpected status
NO_FILE_TRUST_DAYS = 5  # short volume: a recorded no-file day is believed only once it is this old
STREAK_OLD_DAYS = 10  # short volume: a day this old should certainly have a file
SHORTVOL_STREAK = 5  # consecutive old days without a file, after a hit in the same run, that stop the run
INTEREST_STREAK = 3  # consecutive settlement dates without a file, after a hit in the same run, that stop the run
STALE_AGE_BUSINESS_DAYS = 25  # short interest: only a date this old is recorded as having no file
WRITE_EVERY = 25  # short interest: files read between writes of a long backfill
COLUMNS = {"Date": "date", "Symbol": "symbol", "ShortVolume": "short", "ShortExemptVolume": "exempt", "TotalVolume": "total"}
VOLUME_COLUMNS = ["short", "exempt", "total"]
KEY = ["date", "symbol"]


class FinraUnavailable(RuntimeError):
    """FINRA gave no usable answer after the retries; `status` is the last HTTP status (None for transport errors)."""

    def __init__(self, message: str, status: int | None) -> None:
        super().__init__(message)
        self.status = status


def _download(http: httpx.Client, url: str, label: str) -> str | None:
    """The body of `url`, or None for a 403/404 (the CDN's answer for an absent file). Transport errors and other statuses
    are retried; a 429 stops at once."""
    status: int | None = None
    for attempt in range(RETRIES):
        if attempt:
            time.sleep(RETRY_PAUSE_S)
        try:
            r = http.get(url)
        except httpx.TransportError:
            status = None
            continue
        status = r.status_code
        if status in (403, 404):
            return None
        if status == 200:
            return r.text
        if status == 429:
            break
    raise FinraUnavailable(f"FINRA {label}: no usable response after retries (last status {status})", status)


def fetch_day(http: httpx.Client, day: date, symbols: set[str]) -> pd.DataFrame | None:
    """Rows for the universe on `day`, or None when FINRA has no file for that date."""
    text = _download(http, URL.format(day=day.strftime("%Y%m%d")), str(day))
    if text is None:
        return None
    df = pd.read_csv(io.StringIO(text), sep="|", dtype={"Date": str, "Symbol": str})
    df = df[df["Symbol"].isin(symbols)].rename(columns=COLUMNS)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    return df[["date", "symbol", "short", "exempt", "total"]].reset_index(drop=True)


def merge_shortvol(prior: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    """`fresh` rows added to the stored file; a (date, symbol) already stored keeps its row, so the recorder's `ingested_at`
    and its survivorship-free symbols survive a rebuild from the daily cache."""
    out = pd.concat([prior, fresh], ignore_index=True).drop_duplicates(KEY, keep="first")
    out["date"] = out["date"].astype("datetime64[us]")
    return out.sort_values("date", kind="stable").reset_index(drop=True)


def universe_symbols() -> set[str]:
    """Traded, events, confirm and survivorship-free symbols plus SPY and QQQ."""
    traded = config.load_universe()["universe"]["traded"]
    return {*traded, *config.events_symbols(), *config.confirm_symbols(), *config.sf_symbols(), "SPY", "QQQ"}


def _et_date(now: datetime) -> date:
    return now.astimezone(ZoneInfo(DEFAULT_TZ)).date()


def _weekday_on_or_before(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _weekdays(first: date, last: date) -> list[date]:
    return [d for i in range((last - first).days + 1) if (d := first + timedelta(days=i)).weekday() < 5]


def settlement_dates(first: date, last: date) -> list[date]:
    """Short-interest settlement dates in [first, last]: the 15th and the last business day of each month, each moved back
    to the previous weekday when it falls on a weekend. Market holidays are handled when the files are fetched."""
    out: set[date] = set()
    for period in pd.period_range(first, last, freq="M"):
        for nominal in (date(period.year, period.month, 15), period.end_time.date()):
            d = _weekday_on_or_before(nominal)
            if first <= d <= last:
                out.add(d)
    return sorted(out)


def _candidates(settlement: date) -> list[date]:
    """The settlement date and the previous business days FINRA may have dated its file with when it was a holiday."""
    out = [settlement]
    while len(out) < HOLIDAY_FALLBACK_DAYS:
        out.append(_weekday_on_or_before(out[-1] - timedelta(days=1)))
    return out


def read_days(path: Path) -> set[str]:
    try:
        return set(path.read_text().split())
    except OSError:
        return set()


def write_days(path: Path, days: set[str]) -> None:
    """Replace the list via a pid-suffixed temp file, in the format scripts/fetch_finra.py has always written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text("\n".join(sorted(days)))
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _stored_column(ds: Dataset, column: str) -> pd.Series | None:
    if not ds.path.exists():
        return None
    try:
        return pd.read_parquet(ds.path, columns=[column])[column]
    except Exception as e:
        raise SourceError(f"cannot read {ds.path}: {e}") from e


def _default_http() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": "sift-research"}, timeout=60.0, follow_redirects=True)


def _failure(e: Exception, what: str) -> SourceError:
    if isinstance(e, FinraUnavailable) and e.status == 429:
        return RateLimited(str(e), retry_after_s=RETRY_AFTER_S)
    return SourceError(f"FINRA {what} failed: {e}")


class _FinraSource(Source):
    """Shared run: whatever was read before a failure is stored, then the failure is raised."""

    rate_group = "finra"

    def __init__(self, schedule: str, lag_minutes: int, http_factory: Callable[[], httpx.Client] | None) -> None:
        self.schedule = parse_schedule(schedule)
        self.lag = timedelta(minutes=lag_minutes)
        self._http_factory = http_factory or _default_http

    def _gather(
        self, ctx: RunContext, flush: Callable[[pd.DataFrame], None]
    ) -> tuple[pd.DataFrame, SourceError | None]:
        """The rows read (the last batch; earlier full batches went to `flush`) and the error that stopped the run."""
        raise NotImplementedError

    def fetch(self, ctx: RunContext) -> dict[Dataset, pd.DataFrame]:
        batches: list[pd.DataFrame] = []
        frame, error = self._gather(ctx, batches.append)
        if error:
            raise error
        return {self.datasets[0]: pd.concat([*batches, frame], ignore_index=True)}

    def run(self, ctx: RunContext) -> int:
        added = 0

        def flush(batch: pd.DataFrame) -> None:
            nonlocal added
            added += ctx.writer(self.datasets[0], batch)

        frame, error = self._gather(ctx, flush)
        if not frame.empty:
            flush(frame)
        if error:
            raise error
        return added


def _run_ending_at(order: list[date], position: dict[date, int], hit: set[date], item: date) -> int:
    """How many consecutive entries of `order` up to and including `item` are not hits."""
    i, n = position[item], 0
    while i >= 0 and order[i] not in hit:
        n += 1
        i -= 1
    return n


def _confirmed(order: list[date], hit: set[date], misses: set[date], limit: int) -> set[date]:
    """The probed `misses` that a later hit confirms as absent: the run of non-hits around them is shorter than `limit` and
    is followed by a hit. A trailing run, or a run of `limit` or more (a block rather than a holiday), is never confirmed."""
    out: set[date] = set()
    i = 0
    while i < len(order):
        if order[i] in hit:
            i += 1
            continue
        j = i
        while j < len(order) and order[j] not in hit:
            j += 1
        if j - i < limit and j < len(order):
            out.update(d for d in order[i:j] if d in misses)
        i = j
    return out


def _no_file_path() -> Path:
    return config.DATA_DIR / "finra" / "no_file.txt"


def _empty_shortvol() -> pd.DataFrame:
    out = pd.DataFrame({"date": pd.Series(dtype="datetime64[us]"), "symbol": pd.Series(dtype="str")})
    for col in VOLUME_COLUMNS:
        out[col] = pd.Series(dtype="float64")
    return out


def _stored_dates(ds: Dataset, column: str) -> set[date]:
    stored = _stored_column(ds, column)
    return set() if stored is None else {t.date() for t in pd.to_datetime(stored).dropna().unique()}


class FinraShortVolume(_FinraSource):
    """Daily short volume for the universe. Each run probes every weekday from the first stored date up to yesterday (ET)
    that is neither stored nor a trusted no-file day, so a file is never asked for before FINRA has had a day to post it, and
    a day that answered 403 once and was filled in later is not lost.

    An absence is recorded in no_file.txt only when a later day has a file (stored or read in this run) and fewer than
    SHORTVOL_STREAK weekdays in a row are missing around it, so a block or a late post is never made permanent. A
    recorded day is skipped only when it is at least NO_FILE_TRUST_DAYS old."""

    name = "finra_shortvol"

    def __init__(
        self,
        schedule: str = "daily 18:30 America/New_York",
        lag_minutes: int = 0,
        http_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        super().__init__(schedule, lag_minutes, http_factory)
        self.datasets = (datasets.dataset("finra_shortvol"),)

    def _days(self, today: date, have: set[date]) -> list[date]:
        start = FIRST if not have else max(FIRST, min(have))
        known = read_days(_no_file_path())
        trusted = {d for d in _weekdays(start, today) if f"{d:%Y%m%d}" in known and (today - d).days >= NO_FILE_TRUST_DAYS}
        return [d for d in _weekdays(start, today - timedelta(days=1)) if d not in have and d not in trusted]

    def _gather(
        self, ctx: RunContext, flush: Callable[[pd.DataFrame], None]
    ) -> tuple[pd.DataFrame, SourceError | None]:
        today = _et_date(ctx.now)
        have = _stored_dates(self.datasets[0], "date")
        days = self._days(today, have)
        if not days:
            return _empty_shortvol(), None
        order = _weekdays(FIRST, today - timedelta(days=1))
        position = {d: i for i, d in enumerate(order)}
        symbols = universe_symbols()
        parts: list[pd.DataFrame] = []
        hit = set(have)
        misses: set[date] = set()
        error: SourceError | None = None
        http = self._http_factory()
        try:
            for day in days:
                try:
                    df = fetch_day(http, day, symbols)
                except (FinraUnavailable, httpx.HTTPError, ValueError, KeyError) as e:
                    error = _failure(e, "short volume download")
                    break
                if df is not None:
                    parts.append(df)
                    hit.add(day)
                    continue
                misses.add(day)
                streak = _run_ending_at(order, position, hit, day)
                if parts and streak >= SHORTVOL_STREAK and (today - day).days > STREAK_OLD_DAYS:
                    first = order[position[day] - streak + 1]
                    error = SourceError(
                        f"finra_shortvol: {streak} consecutive days {first:%Y%m%d} to {day:%Y%m%d} have no file after "
                        "earlier days in this run did; not recording them (a proxy or block?)"
                    )
                    break
        finally:
            if isinstance(http, httpx.Client):
                http.close()
            confirmed = _confirmed(order, hit, misses, SHORTVOL_STREAK)
            known = read_days(_no_file_path())
            updated = (known - {f"{d:%Y%m%d}" for d in hit}) | {f"{d:%Y%m%d}" for d in confirmed}
            if updated != known:
                write_days(_no_file_path(), updated)
        log.info("finra_shortvol: %d days asked for, %d read, %d without a file", len(days), len(parts), len(confirmed))
        if not parts:
            return _empty_shortvol(), error
        frame = pd.concat(parts, ignore_index=True)
        frame["date"] = frame["date"].astype("datetime64[us]")
        frame[VOLUME_COLUMNS] = frame[VOLUME_COLUMNS].astype("float64")
        return frame, error


def _short_interest_no_file_path() -> Path:
    return config.DATA_DIR / "finra" / "short_interest_no_file.txt"


def fetch_short_interest(http: httpx.Client, day: date, symbols: set[str]) -> pd.DataFrame | None:
    """The universe rows of the short-interest file dated `day`, or None when FINRA has no file for it. `symbol` is the
    file's symbolCode; every other column is kept and `settlement_date` is added."""
    text = _download(http, SHORT_INTEREST_URL.format(day=day.strftime("%Y%m%d")), f"short interest {day}")
    if text is None:
        return None
    df = pd.read_csv(io.StringIO(text), sep="|", dtype={"symbolCode": str})
    df = df[df["symbolCode"].isin(symbols)].rename(columns={"symbolCode": "symbol"}).reset_index(drop=True)
    df.insert(0, "settlement_date", pd.Series(pd.Timestamp(day), index=df.index, dtype="datetime64[us]"))
    return df


class FinraShortInterest(_FinraSource):
    """Biweekly short interest. A settlement date is requested once it is MIN_AGE_BUSINESS_DAYS business days old and again
    on every run until its file turns up. It is recorded in short_interest_no_file.txt only when it is at least
    STALE_AGE_BUSINESS_DAYS old, a later settlement date has a file (stored or read in this run) and fewer than
    INTEREST_STREAK dates in a row are missing around it. Each file is cut to the universe as it is read, and the rows are
    stored in batches of WRITE_EVERY files."""

    name = "finra_short_interest"

    def __init__(
        self,
        schedule: str = "daily 09:00 America/New_York",
        lag_minutes: int = 0,
        http_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        super().__init__(schedule, lag_minutes, http_factory)
        self.datasets = (datasets.dataset("finra_short_interest"),)

    def _state(self, today: date) -> tuple[list[date], set[date], list[date]]:
        """Every settlement date so far, those already stored, and those to request now."""
        order = settlement_dates(FIRST_SETTLEMENT, today)
        have = _stored_dates(self.datasets[0], "settlement_date")
        done = {d for d in order if have.intersection(_candidates(d))}
        due = [d for d in order if d not in done and int(np.busday_count(d, today)) >= MIN_AGE_BUSINESS_DAYS]
        return order, done, due

    def _gather(
        self, ctx: RunContext, flush: Callable[[pd.DataFrame], None]
    ) -> tuple[pd.DataFrame, SourceError | None]:
        today = _et_date(ctx.now)
        order, hit, due = self._state(today)
        if not due:
            return pd.DataFrame(), None
        position = {d: i for i, d in enumerate(order)}
        symbols = universe_symbols()
        known = read_days(_short_interest_no_file_path())
        tried_days: dict[date, list[date]] = {}
        parts: list[pd.DataFrame] = []
        read = 0
        error: SourceError | None = None
        http = self._http_factory()
        try:
            for settlement in due:
                tried = [d for d in _candidates(settlement) if f"{d:%Y%m%d}" not in known]
                if not tried:
                    continue
                found = None
                try:
                    for day in tried:
                        found = fetch_short_interest(http, day, symbols)
                        if found is not None:
                            break
                except (FinraUnavailable, httpx.HTTPError, ValueError, KeyError) as e:
                    error = _failure(e, "short interest download")
                    break
                if found is None:
                    tried_days[settlement] = tried
                    streak = _run_ending_at(order, position, hit, settlement)
                    if read and streak >= INTEREST_STREAK:
                        error = SourceError(
                            f"finra_short_interest: {streak} consecutive settlement dates "
                            f"{order[position[settlement] - streak + 1]:%Y%m%d} to {settlement:%Y%m%d} have no file after "
                            "earlier dates in this run did; not recording them (a proxy or block?)"
                        )
                        break
                    continue
                hit.add(settlement)
                parts.append(found)
                read += 1
                if len(parts) >= WRITE_EVERY:
                    flush(pd.concat(parts, ignore_index=True))
                    parts = []
        finally:
            if isinstance(http, httpx.Client):
                http.close()
            absent: set[str] = set()
            for settlement in _confirmed(order, hit, set(tried_days), INTEREST_STREAK):
                if int(np.busday_count(settlement, today)) >= STALE_AGE_BUSINESS_DAYS:
                    absent.update(f"{d:%Y%m%d}" for d in tried_days[settlement])
                    log.warning(
                        "finra_short_interest: no file for %s (tried %s); not retrying",
                        settlement, ", ".join(f"{d:%Y%m%d}" for d in tried_days[settlement]),
                    )
            if absent:
                write_days(_short_interest_no_file_path(), known | absent)
        log.info("finra_short_interest: %d settlement dates due, %d files read", len(due), read)
        return (pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()), error
