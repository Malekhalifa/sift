"""SEC EDGAR access for earnings-release timestamps.

Free and public. A company announces quarterly results in an 8-K carrying Item 2.02 ("Results of Operations"), and
EDGAR records the exact second it accepted the filing, so the timestamp is point-in-time. The SEC asks for a declared
User-Agent and at most 10 requests a second; this client uses about 3 a second and caches every response on disk, so
a rerun costs nothing. Set SEC_USER_AGENT to override the default contact string.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
import pandas as pd
from dotenv import load_dotenv

from tp import config

DEFAULT_USER_AGENT = "sift-research (github.com/Malekhalifa/sift)"


def user_agent() -> str:
    """The SEC requires a declared contact. Read from SEC_USER_AGENT (kept in the gitignored .env), never hard-coded."""
    load_dotenv(config.ROOT / ".env")
    return os.environ.get("SEC_USER_AGENT") or DEFAULT_USER_AGENT
MIN_INTERVAL_S = 0.34
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/{name}"


class EdgarBadResponse(RuntimeError):
    """A 200 response that is not the JSON document we asked for; the cache is left untouched."""


class EdgarBlocked(RuntimeError):
    """The SEC rate-limited us (403/429). The block usually clears in about ten minutes; stop and retry later."""


def parse_earnings(pages: list[dict]) -> pd.DataFrame:
    """Earnings 8-Ks from submission pages: the `recent` block first, then any older pages (each a bare column dict).
    Keeps form 8-K with Item 2.02 only (not amendments, not 10-Q). filed_at is the EDGAR acceptance time in UTC."""
    rows = []
    for page in pages:
        cols = page.get("filings", {}).get("recent", page)
        for form, items, accepted, accession in zip(
            cols.get("form", []), cols.get("items", []), cols.get("acceptanceDateTime", []), cols.get("accessionNumber", []), strict=False
        ):
            if form == "8-K" and "2.02" in [i.strip() for i in str(items).split(",")]:
                rows.append({"accession": accession, "filed_at": pd.Timestamp(accepted)})
    out = pd.DataFrame(rows, columns=["accession", "filed_at"])
    if out.empty:
        out["filed_at"] = pd.to_datetime(out["filed_at"], utc=True)
        return out
    out["filed_at"] = pd.to_datetime(out["filed_at"], utc=True)
    return out.drop_duplicates("accession").sort_values("filed_at").reset_index(drop=True)

def parse_eightk(pages: list[dict]) -> pd.DataFrame:
    """Every 8-K (not amendments) from submission pages, with its item codes as a comma-separated string.
    filed_at is the EDGAR acceptance time in UTC."""
    rows = []
    for page in pages:
        cols = page.get("filings", {}).get("recent", page)
        for form, items, accepted, accession in zip(
            cols.get("form", []), cols.get("items", []), cols.get("acceptanceDateTime", []), cols.get("accessionNumber", []), strict=False
        ):
            if form == "8-K":
                codes = ",".join(i.strip() for i in str(items).split(",") if i.strip())
                rows.append({"accession": accession, "filed_at": pd.Timestamp(accepted), "items": codes})
    out = pd.DataFrame(rows, columns=["accession", "filed_at", "items"])
    out["filed_at"] = pd.to_datetime(out["filed_at"], utc=True)
    return out.drop_duplicates("accession").sort_values("filed_at").reset_index(drop=True)

def parse_tenk(pages: list[dict]) -> pd.DataFrame:
    """Every 10-K (not amendments) from submission pages: accession, acceptance time (UTC), period end and main document."""
    rows = []
    for page in pages:
        cols = page.get("filings", {}).get("recent", page)
        for form, accn, accepted, report, doc in zip(
            cols.get("form", []), cols.get("accessionNumber", []), cols.get("acceptanceDateTime", []),
            cols.get("reportDate", []), cols.get("primaryDocument", []), strict=False
        ):
            if form == "10-K":
                rows.append({"accn": accn, "filed_at": pd.Timestamp(accepted), "report_date": report, "doc": doc})
    out = pd.DataFrame(rows, columns=["accn", "filed_at", "report_date", "doc"])
    out["filed_at"] = pd.to_datetime(out["filed_at"], utc=True)
    return out.drop_duplicates("accn").sort_values("filed_at").reset_index(drop=True)


class EdgarClient:
    def __init__(self, cache_dir: Path | None = None, http: httpx.Client | None = None):
        self.cache = Path(cache_dir) if cache_dir else config.DATA_DIR / "edgar"
        self.cache.mkdir(parents=True, exist_ok=True)
        self._http = http or httpx.Client(headers={"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"}, timeout=30.0)
        self._last = 0.0

    def _get_json(self, url: str, cache_name: str, refresh: bool = False, require: str | None = None) -> dict:
        """Cached GET. With refresh=True the cache is not read and is atomically replaced by the fresh response.
        A body that is not JSON, or lacks the `require` key, raises EdgarBadResponse and never reaches the cache."""
        path = self.cache / cache_name
        if not refresh and path.exists():
            return json.loads(path.read_text())
        wait = MIN_INTERVAL_S - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        r = self._http.get(url)
        if r.status_code in (403, 429):
            raise EdgarBlocked(f"HTTP {r.status_code} from {url.split('/')[2]}: rate-limited, retry in ~10 minutes")
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError as e:
            raise EdgarBadResponse(f"{url}: response is not JSON") from e
        if require is not None and not (isinstance(data, dict) and require in data):
            raise EdgarBadResponse(f"{url}: response lacks {require!r}")
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(data))
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return data

    def ticker_map(self, refresh: bool = False) -> dict[str, int]:
        """Current ticker -> CIK."""
        raw = self._get_json(TICKERS_URL, "company_tickers.json", refresh=refresh)
        return {row["ticker"].upper(): int(row["cik_str"]) for row in raw.values()}

    def submission_pages(self, cik: int, refresh: bool = False) -> list[dict]:
        """The CIK's main submissions JSON (the recent block) followed by its older pages. Only the main file is
        refreshed; older pages never change, so they come from the cache and are downloaded only when missing."""
        name = f"CIK{cik:010d}.json"
        main = self._get_json(SUBMISSIONS_URL.format(name=name), name, refresh=refresh, require="filings")
        pages = [main]
        for extra in main.get("filings", {}).get("files", []):
            pages.append(self._get_json(SUBMISSIONS_URL.format(name=extra["name"]), extra["name"], require="accessionNumber"))
        return pages

    def earnings_filings(self, cik: int) -> pd.DataFrame:
        return parse_earnings(self.submission_pages(cik))

    def eightk_filings(self, cik: int) -> pd.DataFrame:
        return parse_eightk(self.submission_pages(cik))

    def tenk_filings(self, cik: int) -> pd.DataFrame:
        return parse_tenk(self.submission_pages(cik))
