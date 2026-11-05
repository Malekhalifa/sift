from __future__ import annotations

import threading
import time
from collections.abc import Iterator, Sequence
from datetime import date, datetime

import httpx

from tp.config import Settings

DATA_URL = "https://data.alpaca.markets"
PAPER_URL = "https://paper-api.alpaca.markets"

# Free tier allows 200 calls/min; stay just under it.
MIN_INTERVAL_S = 0.31
MAX_ATTEMPTS = 6


class AlpacaError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


class AlpacaClient:
    def __init__(self, settings: Settings, timeout: float = 30.0):
        self._http = httpx.Client(
            headers={
                "APCA-API-KEY-ID": settings.alpaca_key_id,
                "APCA-API-SECRET-KEY": settings.alpaca_secret,
            },
            timeout=timeout,
        )
        self._last_request = 0.0
        self._throttle_lock = threading.Lock()

    def _throttle(self) -> None:
        """Space request starts at least MIN_INTERVAL_S apart across all threads, so parallel downloads share
        one rate budget instead of each spending it."""
        with self._throttle_lock:
            wait = MIN_INTERVAL_S - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    def _get(self, url: str, params: dict | None = None) -> dict:
        last_error = "no attempt made"
        for attempt in range(MAX_ATTEMPTS):
            self._throttle()
            try:
                r = self._http.get(url, params=params)
            except httpx.TransportError as e:
                last_error = f"transport error: {e!r}"
                time.sleep(2**attempt)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                last_error = f"HTTP {r.status_code}: {r.text[:200]}"
                time.sleep(float(r.headers.get("Retry-After", 2**attempt)))
                continue
            if r.status_code >= 400:
                raise AlpacaError(r.status_code, r.text[:300])
            return r.json()
        raise AlpacaError(0, f"gave up after {MAX_ATTEMPTS} attempts ({last_error})")

    def account(self) -> dict:
        return self._get(f"{PAPER_URL}/v2/account")

    def bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        feed: str = "iex",
        adjustment: str = "raw",
        limit: int = 10_000,
    ) -> Iterator[dict]:
        """Yield bars (t,o,h,l,c,v,n,vw), following pagination. start/end are UTC datetimes."""
        params = {
            "timeframe": timeframe,
            "start": _iso(start),
            "end": _iso(end),
            "feed": feed,
            "adjustment": adjustment,
            "limit": limit,
            "sort": "asc",
        }
        while True:
            payload = self._get(f"{DATA_URL}/v2/stocks/{symbol}/bars", params)
            yield from payload.get("bars") or []
            token = payload.get("next_page_token")
            if not token:
                return
            params["page_token"] = token

    def multi_bars(
        self,
        symbols: Sequence[str],
        timeframe: str,
        start: datetime | date,
        end: datetime | date,
        feed: str = "sip",
        adjustment: str = "raw",
        limit: int = 10_000,
    ) -> Iterator[tuple[str, dict]]:
        """Yield (symbol, bar) for many symbols in one paginated request. Keep len(symbols) x bars-per-symbol
        under `limit` per page or pagination takes over."""
        fmt = (lambda d: _iso(d)) if isinstance(start, datetime) else (lambda d: d.isoformat())
        params = {
            "symbols": ",".join(symbols), "timeframe": timeframe, "start": fmt(start), "end": fmt(end),
            "feed": feed, "adjustment": adjustment, "limit": limit, "sort": "asc",
        }
        while True:
            payload = self._get(f"{DATA_URL}/v2/stocks/bars", params)
            for sym, bars in (payload.get("bars") or {}).items():
                for bar in bars:
                    yield sym, bar
            token = payload.get("next_page_token")
            if not token:
                return
            params["page_token"] = token

    def assets(self) -> list[dict]:
        return self._get(f"{PAPER_URL}/v2/assets", {"status": "active", "asset_class": "us_equity"})

    def splits(self, symbols: Sequence[str], start: date, end: date) -> Iterator[dict]:
        """Yield forward/reverse split records (symbol, ex_date, new_rate, old_rate)."""
        params = {
            "symbols": ",".join(symbols),
            "types": "forward_split,reverse_split",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 1000,
        }
        while True:
            payload = self._get(f"{DATA_URL}/v1/corporate-actions", params)
            for records in (payload.get("corporate_actions") or {}).values():
                yield from records
            token = payload.get("next_page_token")
            if not token:
                return
            params["page_token"] = token
