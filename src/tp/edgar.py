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

from tp import config

USER_AGENT = os.environ.get("SEC_USER_AGENT") or "trading-pipeline-research (github.com/Malekhalifa/trading-pipeline)"
MIN_INTERVAL_S = 0.34
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/{name}"


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


class EdgarClient:
    def __init__(self, cache_dir: Path | None = None, http: httpx.Client | None = None):
        self.cache = Path(cache_dir) if cache_dir else config.DATA_DIR / "edgar"
        self.cache.mkdir(parents=True, exist_ok=True)
        self._http = http or httpx.Client(headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}, timeout=30.0)
        self._last = 0.0

    def _get_json(self, url: str, cache_name: str) -> dict:
        path = self.cache / cache_name
        if path.exists():
            return json.loads(path.read_text())
        wait = MIN_INTERVAL_S - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        r = self._http.get(url)
        if r.status_code in (403, 429):
            raise EdgarBlocked(f"HTTP {r.status_code} from {url.split('/')[2]}: rate-limited, retry in ~10 minutes")
        r.raise_for_status()
        data = r.json()
        path.write_text(json.dumps(data))
        return data

    def ticker_map(self) -> dict[str, int]:
        """Current ticker -> CIK."""
        raw = self._get_json(TICKERS_URL, "company_tickers.json")
        return {row["ticker"].upper(): int(row["cik_str"]) for row in raw.values()}

    def earnings_filings(self, cik: int) -> pd.DataFrame:
        main = self._get_json(SUBMISSIONS_URL.format(name=f"CIK{cik:010d}.json"), f"CIK{cik:010d}.json")
        pages = [main]
        for extra in main.get("filings", {}).get("files", []):
            pages.append(self._get_json(SUBMISSIONS_URL.format(name=extra["name"]), extra["name"]))
        return parse_earnings(pages)
