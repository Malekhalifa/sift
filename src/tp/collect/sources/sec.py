"""SEC sources: filings for the whole universe (every 8-K, the earnings 8-Ks and the 10-K index), the quarterly Form 4
insider-transaction files, and the XBRL cover-page share counts.

One request per CIK per run refreshes that company's main submissions JSON; the older pages listed under
`filings.files` never change, so they stay cached and are downloaded only when missing. The bulk Form 4 zips and the
company-facts reads are shared with scripts/fetch_insider.py and scripts/fetch_shares.py.
"""
from __future__ import annotations

import csv
import logging
import os
import time
import zipfile
import zlib
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from tp import config, insiders
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
from tp.collect.sources.progress import load_progress, save_progress
from tp.edgar import (
    EdgarBadResponse,
    EdgarBlocked,
    EdgarClient,
    parse_earnings,
    parse_eightk,
    parse_tenk,
    user_agent,
)

log = logging.getLogger(__name__)

RETRY_AFTER_S = 600
COLUMNS = {
    "eightk": ["symbol", "accession", "filed_at", "items"],
    "earnings": ["symbol", "cik", "accession", "filed_at"],
    "tenk_index": ["symbol", "cik", "accn", "filed_at", "report_date", "doc"],
}
FORM4_URL = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{quarter}_form345.zip"
FIRST_YEAR = 2013  # three years of look-back before the first test event in 2016
QUARTER_PAUSE_S = 1.0
TRADE_COLUMNS = insiders.TRADE_COLUMNS
READ = {
    "SUBMISSION.tsv": ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK"],
    "REPORTINGOWNER.tsv": ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP"],
    "NONDERIV_TRANS.tsv": ["ACCESSION_NUMBER", "NONDERIV_TRANS_SK", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
                           "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD"],
}
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
FACTS_FORMS = {"10-K", "10-Q"}
FACTS_COLUMNS = ["accn", "form", "filed", "end", "val"]
FACTS_SPACING_S = 0.35  # SEC fair access: spaced reads stay well under the 10 requests a second limit


def universe_symbols() -> list[str]:
    """Traded, events, confirm and survivorship-free symbols, deduplicated in that order."""
    traded = config.load_universe()["universe"]["traded"]
    return list(dict.fromkeys([*traded, *config.events_symbols(), *config.confirm_symbols(), *config.sf_symbols()]))


def _frame(parts: list[pd.DataFrame], name: str) -> pd.DataFrame:
    cols = COLUMNS[name]
    if not parts:
        out = pd.DataFrame(columns=cols)
        out["filed_at"] = pd.to_datetime(out["filed_at"], utc=True)
        return out
    return pd.concat(parts, ignore_index=True)[cols]


def progress_path() -> Path:
    return config.DATA_DIR / "collect" / "sec_filings_progress.json"


def _listed(pages: list[dict], symbol: str) -> bool:
    """False when the submissions JSON carries a ticker list that no longer includes the symbol (reused ticker)."""
    tickers = pages[0].get("tickers")
    return not isinstance(tickers, list) or symbol.upper() in {str(t).upper() for t in tickers}


class SecFilings(Source):
    name = "sec_filings"
    rate_group = "sec"

    def __init__(
        self,
        schedule: str = "daily 07:30 America/New_York",
        lag_minutes: int = 0,
        client_factory: Callable[[], EdgarClient] | None = None,
    ) -> None:
        self.schedule = parse_schedule(schedule)
        self.lag = timedelta(minutes=lag_minutes)
        self.datasets = tuple(datasets.dataset(n) for n in COLUMNS)
        self._client_factory = client_factory or EdgarClient

    def fetch(self, ctx: RunContext) -> dict[Dataset, pd.DataFrame]:
        symbols = universe_symbols()
        client = self._client_factory()
        progress = load_progress(progress_path(), "ciks", _ny_day(ctx.now), ("tickers",))
        done = set(progress["ciks"])
        resumed = len(done)
        parts: dict[str, list[pd.DataFrame]] = {n: [] for n in COLUMNS}
        skipped: list[str] = []
        try:
            cik_of = client.ticker_map(refresh=not progress["tickers"])
            if not progress["tickers"]:
                progress["tickers"] = True
                save_progress(progress_path(), progress)
            for sym in symbols:
                cik = cik_of.get(sym)
                if cik is None:
                    skipped.append(sym)
                    continue
                pages = client.submission_pages(cik, refresh=cik not in done)
                if cik not in done:
                    done.add(cik)
                    progress["ciks"] = sorted(done)
                    save_progress(progress_path(), progress)
                if not _listed(pages, sym):
                    skipped.append(sym)
                    continue
                for name, parse in (("eightk", parse_eightk), ("earnings", parse_earnings), ("tenk_index", parse_tenk)):
                    df = parse(pages)
                    df.insert(0, "symbol", sym)
                    if name in ("earnings", "tenk_index"):
                        df.insert(1, "cik", cik)
                    parts[name].append(df)
        except EdgarBlocked as e:
            raise RateLimited(str(e), retry_after_s=RETRY_AFTER_S) from e
        except (httpx.HTTPError, EdgarBadResponse) as e:
            raise SourceError(f"SEC request failed: {e}") from e
        progress_path().unlink(missing_ok=True)
        log.info(
            "sec_filings: %d symbols, %d CIKs (%d already refreshed earlier today), %d skipped (no CIK or ticker not "
            "listed under it)%s",
            len(symbols), len(done), resumed, len(skipped), f": {', '.join(skipped)}" if skipped else "",
        )
        return {datasets.dataset(n): _frame(p, n) for n, p in parts.items()}


def _ny_day(now: datetime) -> str:
    return now.astimezone(ZoneInfo(DEFAULT_TZ)).date().isoformat()


def finished_quarters(today: date) -> list[str]:
    """Quarters from FIRST_YEAR whose bulk file should exist: ended more than a week before `today`."""
    cutoff = today - timedelta(days=7)
    return [
        f"{y}q{q}" for y in range(FIRST_YEAR, cutoff.year + 1) for q in range(1, 5)
        if (pd.Timestamp(year=y, month=3 * q, day=1) + pd.offsets.MonthEnd(0)).date() < cutoff
    ]


def parsed_dir() -> Path:
    return config.DATA_DIR / "insider" / "parsed"


def read_member(z: zipfile.ZipFile, name: str) -> pd.DataFrame:
    with z.open(name) as f:  # QUOTE_NONE: free-text fields contain stray quotes
        return pd.read_csv(f, sep="\t", dtype=str, usecols=READ[name], quoting=csv.QUOTE_NONE, encoding_errors="replace")


def fetch_quarter(http: httpx.Client, quarter: str, tmp: Path) -> pd.DataFrame:
    """Download one quarter's form345.zip to `tmp`, parse it, and delete `tmp` whatever happens.

    FileNotFoundError: not published yet. EdgarBlocked: 403/429. EdgarBadResponse: a truncated or corrupt zip.
    """
    try:
        with http.stream("GET", FORM4_URL.format(quarter=quarter)) as r:
            if r.status_code == 404:
                raise FileNotFoundError(quarter)
            if r.status_code in (403, 429):
                raise EdgarBlocked(f"HTTP {r.status_code} for {quarter}: rate-limited, retry in ~10 minutes")
            r.raise_for_status()
            tmp.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
        try:
            with zipfile.ZipFile(tmp) as z:
                return insiders.parse_quarter(*(read_member(z, n) for n in READ))
        except (zipfile.BadZipFile, zlib.error, EOFError, KeyError, ValueError) as e:
            raise EdgarBadResponse(f"{quarter}: not a readable form345 zip ({type(e).__name__}: {e})") from e
    finally:
        tmp.unlink(missing_ok=True)


def atomic_parquet(df: pd.DataFrame, out: Path) -> None:
    """Write a Parquet file via a temp file and rename, so a half-written file is never mistaken for a finished cache."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f"{out.name}.{os.getpid()}.tmp")
    try:
        df.to_parquet(tmp, index=False)
        os.replace(tmp, out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _default_http() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"}, timeout=120.0, follow_redirects=True,
    )


class SecForm4(Source):
    """Form 4 trades from the quarterly bulk files. A quarter is cached (data/insider/parsed) only after the writer
    has stored its rows, so a failed write is retried on the next run instead of being lost."""

    name = "sec_form4"
    rate_group = "sec"

    def __init__(
        self,
        schedule: str = "daily 08:00 America/New_York",
        lag_minutes: int = 0,
        http_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        self.schedule = parse_schedule(schedule)
        self.lag = timedelta(minutes=lag_minutes)
        self.datasets = (datasets.dataset("form4"),)
        self._http_factory = http_factory or _default_http

    def _collect(self, ctx: RunContext) -> tuple[pd.DataFrame, list[tuple[str, pd.DataFrame]]]:
        due = [q for q in finished_quarters(ctx.now.date()) if not (parsed_dir() / f"{q}.parquet").exists()]
        pending: list[tuple[str, pd.DataFrame]] = []
        http = self._http_factory()
        try:
            for quarter in due:
                try:
                    pending.append((quarter, fetch_quarter(http, quarter, config.DATA_DIR / "insider" / f"{quarter}.zip.part")))
                except FileNotFoundError:
                    log.info("sec_form4: %s is not published yet", quarter)
                    break
                if QUARTER_PAUSE_S > 0:
                    time.sleep(QUARTER_PAUSE_S)
        except EdgarBlocked as e:
            raise RateLimited(str(e), retry_after_s=RETRY_AFTER_S) from e
        except (httpx.HTTPError, EdgarBadResponse) as e:
            raise SourceError(f"SEC Form 4 download failed: {e}") from e
        finally:
            if isinstance(http, httpx.Client):
                http.close()
        frame = pd.concat([df for _, df in pending], ignore_index=True) if pending else pd.DataFrame(columns=TRADE_COLUMNS)
        return frame, pending

    def fetch(self, ctx: RunContext) -> dict[Dataset, pd.DataFrame]:
        """The new quarters' trades; nothing is cached here (run does that once the rows are stored)."""
        return {self.datasets[0]: self._collect(ctx)[0]}

    def run(self, ctx: RunContext) -> int:
        frame, pending = self._collect(ctx)
        added = ctx.writer(self.datasets[0], frame) if not frame.empty else 0
        for quarter, df in pending:
            atomic_parquet(df, parsed_dir() / f"{quarter}.parquet")
        return added


def shares_rows(facts: dict) -> pd.DataFrame:
    """Cover-page share counts (dei:EntityCommonStockSharesOutstanding) of every 10-K and 10-Q in a company-facts JSON.
    `val` is float64 and `filed`/`end` are naive datetimes, as stored in data/xbrl/shares.parquet."""
    units = facts.get("facts", {}).get("dei", {}).get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", [])
    rows = [{k: u[k] for k in FACTS_COLUMNS} for u in units if u.get("form") in FACTS_FORMS and all(k in u for k in FACTS_COLUMNS)]
    out = pd.DataFrame(rows, columns=FACTS_COLUMNS)
    out["filed"], out["end"] = pd.to_datetime(out["filed"]), pd.to_datetime(out["end"])
    out["val"] = pd.to_numeric(out["val"]).astype("float64")
    return out.drop_duplicates()


def fetch_shares(http: httpx.Client, symbol: str, cik: int) -> pd.DataFrame:
    """One symbol's share counts. A 404 is an empty frame; EdgarBlocked on 403/429; EdgarBadResponse for a body that
    is not a company-facts JSON; httpx.HTTPStatusError for other errors."""
    time.sleep(FACTS_SPACING_S)
    r = http.get(FACTS_URL.format(cik=cik))
    if r.status_code in (403, 429):
        raise EdgarBlocked(f"HTTP {r.status_code} for {symbol}: rate-limited, retry in ~10 minutes")
    if r.status_code == 404:
        df = shares_rows({})
    else:
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError as e:
            raise EdgarBadResponse(f"{symbol}: company facts response is not JSON") from e
        if not isinstance(data, dict) or not isinstance(data.get("facts"), dict):
            raise EdgarBadResponse(f"{symbol}: company facts response lacks 'facts'")
        df = shares_rows(data)
    df.insert(0, "cik", pd.Series(cik, index=df.index, dtype="int64"))
    df.insert(0, "symbol", symbol)
    return df


def _empty_shares() -> pd.DataFrame:
    out = shares_rows({})
    out.insert(0, "cik", pd.Series(dtype="int64"))
    out.insert(0, "symbol", pd.Series(dtype="object"))
    return out


def xbrl_symbols() -> list[str]:
    """Traded, events and confirm symbols, deduplicated in that order (the survivorship-free names are not covered)."""
    traded = config.load_universe()["universe"]["traded"]
    return list(dict.fromkeys([*traded, *config.events_symbols(), *config.confirm_symbols()]))


def xbrl_progress_path() -> Path:
    return config.DATA_DIR / "collect" / "sec_xbrl_shares_progress.json"


class SecXbrlShares(Source):
    """Share counts re-read from company facts for every mapped symbol. Symbols finished before a rate limit or an
    error are stored and recorded in the progress file, so a retry the same day asks only for the rest."""

    name = "sec_xbrl_shares"
    rate_group = "sec"

    def __init__(
        self,
        schedule: str = "weekly sun 09:00 America/New_York",
        lag_minutes: int = 0,
        client_factory: Callable[[], EdgarClient] | None = None,
    ) -> None:
        self.schedule = parse_schedule(schedule)
        self.lag = timedelta(minutes=lag_minutes)
        self.datasets = (datasets.dataset("xbrl_shares"),)
        self._client_factory = client_factory or EdgarClient

    @staticmethod
    def _frame(parts: list[pd.DataFrame]) -> pd.DataFrame:
        return pd.concat(parts, ignore_index=True) if parts else _empty_shares()

    def _bank(self, ctx: RunContext, progress: dict, done: set[str], parts: list[pd.DataFrame], fetched: list[str]) -> None:
        """Store what this run read before it stopped, then record those symbols as done for today."""
        frame = self._frame(parts)
        if not frame.empty:
            ctx.writer(self.datasets[0], frame)
        done.update(fetched)
        progress["symbols"] = sorted(done)
        save_progress(xbrl_progress_path(), progress)

    def fetch(self, ctx: RunContext) -> dict[Dataset, pd.DataFrame]:
        symbols = xbrl_symbols()
        client = self._client_factory()
        progress = load_progress(xbrl_progress_path(), "symbols", _ny_day(ctx.now), ("tickers",))
        done = set(progress["symbols"])
        resumed = len(done)
        parts: list[pd.DataFrame] = []
        fetched: list[str] = []
        skipped: list[str] = []
        try:
            cik_of = client.ticker_map(refresh=not progress["tickers"])
            if not progress["tickers"]:
                progress["tickers"] = True
                save_progress(xbrl_progress_path(), progress)
            for sym in symbols:
                if sym in done:
                    continue
                cik = cik_of.get(sym)
                if cik is None:
                    skipped.append(sym)
                    continue
                parts.append(fetch_shares(client._http, sym, cik))
                fetched.append(sym)
        except EdgarBlocked as e:
            self._bank(ctx, progress, done, parts, fetched)
            raise RateLimited(str(e), retry_after_s=RETRY_AFTER_S) from e
        except (httpx.HTTPError, EdgarBadResponse) as e:
            self._bank(ctx, progress, done, parts, fetched)
            raise SourceError(f"SEC company facts request failed: {e}") from e
        xbrl_progress_path().unlink(missing_ok=True)
        log.info(
            "sec_xbrl_shares: %d symbols, %d read (%d already read earlier today), %d skipped (no CIK)%s",
            len(symbols), len(fetched), resumed, len(skipped), f": {', '.join(skipped)}" if skipped else "",
        )
        return {self.datasets[0]: self._frame(parts)}
