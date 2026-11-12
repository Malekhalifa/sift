"""SEC filings for the whole universe: every 8-K, the earnings 8-Ks (Item 2.02) and the 10-K index.

One request per CIK per run refreshes that company's main submissions JSON; the older pages listed under
`filings.files` never change, so they stay cached and are downloaded only when missing.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta

import httpx
import pandas as pd

from tp import config
from tp.collect import datasets
from tp.collect.datasets import Dataset
from tp.collect.source import RateLimited, RunContext, Source, SourceError, parse_schedule
from tp.edgar import EdgarBlocked, EdgarClient, parse_earnings, parse_eightk, parse_tenk

log = logging.getLogger(__name__)

RETRY_AFTER_S = 600
COLUMNS = {
    "eightk": ["symbol", "accession", "filed_at", "items"],
    "earnings": ["symbol", "cik", "accession", "filed_at"],
    "tenk_index": ["symbol", "cik", "accn", "filed_at", "report_date", "doc"],
}


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
        parts: dict[str, list[pd.DataFrame]] = {n: [] for n in COLUMNS}
        missing: list[str] = []
        refreshed: set[int] = set()
        try:
            cik_of = client.ticker_map(refresh=True)
            for sym in symbols:
                cik = cik_of.get(sym)
                if cik is None:
                    missing.append(sym)
                    continue
                pages = client.submission_pages(cik, refresh=cik not in refreshed)
                refreshed.add(cik)
                for name, parse in (("eightk", parse_eightk), ("earnings", parse_earnings), ("tenk_index", parse_tenk)):
                    df = parse(pages)
                    df.insert(0, "symbol", sym)
                    if name in ("earnings", "tenk_index"):
                        df.insert(1, "cik", cik)
                    parts[name].append(df)
        except EdgarBlocked as e:
            raise RateLimited(str(e), retry_after_s=RETRY_AFTER_S) from e
        except httpx.HTTPError as e:
            raise SourceError(f"SEC request failed: {e}") from e
        log.info(
            "sec_filings: %d symbols, %d CIKs refreshed, %d without a CIK%s",
            len(symbols), len(refreshed), len(missing), f": {', '.join(missing)}" if missing else "",
        )
        return {datasets.dataset(n): _frame(p, n) for n, p in parts.items()}
