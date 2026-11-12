"""SEC filings for the whole universe: every 8-K, the earnings 8-Ks (Item 2.02) and the 10-K index.

One request per CIK per run refreshes that company's main submissions JSON; the older pages listed under
`filings.files` never change, so they stay cached and are downloaded only when missing.
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from tp import config
from tp.collect import datasets
from tp.collect.datasets import Dataset
from tp.collect.source import DEFAULT_TZ, RateLimited, RunContext, Source, SourceError, parse_schedule
from tp.edgar import EdgarBadResponse, EdgarBlocked, EdgarClient, parse_earnings, parse_eightk, parse_tenk

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


def progress_path() -> Path:
    return config.DATA_DIR / "collect" / "sec_filings_progress.json"


def _load_progress(day: str) -> dict:
    """CIKs already refreshed for this run date, so a retry after a rate limit resumes instead of starting over."""
    try:
        data = json.loads(progress_path().read_text())
    except (OSError, ValueError):
        return {"date": day, "tickers": False, "ciks": []}
    if not isinstance(data, dict) or data.get("date") != day or not isinstance(data.get("ciks"), list):
        return {"date": day, "tickers": False, "ciks": []}
    return {"date": day, "tickers": bool(data.get("tickers")), "ciks": data["ciks"]}


def _save_progress(progress: dict) -> None:
    path = progress_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(progress))
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


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
        progress = _load_progress(ctx.now.astimezone(ZoneInfo(DEFAULT_TZ)).date().isoformat())
        done = set(progress["ciks"])
        resumed = len(done)
        parts: dict[str, list[pd.DataFrame]] = {n: [] for n in COLUMNS}
        skipped: list[str] = []
        try:
            cik_of = client.ticker_map(refresh=not progress["tickers"])
            if not progress["tickers"]:
                progress["tickers"] = True
                _save_progress(progress)
            for sym in symbols:
                cik = cik_of.get(sym)
                if cik is None:
                    skipped.append(sym)
                    continue
                pages = client.submission_pages(cik, refresh=cik not in done)
                if cik not in done:
                    done.add(cik)
                    progress["ciks"] = sorted(done)
                    _save_progress(progress)
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
