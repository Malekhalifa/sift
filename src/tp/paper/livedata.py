"""Assemble what a strategy needs at decision time: stored history through yesterday plus today's live bars.

Both parts come from the IEX feed (the only real-time feed on the free plan), so volume-based filters see the
same kind of volume in the baseline and in the live bars. Daily bars and splits come from the stored SIP data.
"""

from __future__ import annotations

from datetime import UTC, timedelta

import pandas as pd

from tp import store
from tp.alpaca_data import AlpacaClient
from tp.bars import ET, load_bars, rth_mask
from tp.corp_actions import load_splits
from tp.paper.decide import PaperConfig


def session_start_utc(now: pd.Timestamp) -> pd.Timestamp:
    """Midnight ET of the current session day, as UTC."""
    return now.tz_convert(ET).normalize().tz_convert(UTC)


class LiveData:
    def __init__(self, client: AlpacaClient, cfg: PaperConfig):
        self.client, self.cfg = client, cfg
        self.history: dict[str, pd.DataFrame] = {}
        self.today: dict[str, pd.DataFrame] = {}
        self.daily: dict[str, pd.DataFrame] = {}
        self.spy_daily = pd.DataFrame()
        self.recent_split: frozenset[str] = frozenset()

    def load_static(self, now: pd.Timestamp) -> list[str]:
        """Load history, daily bars and split blackouts. Returns warnings (missing or stale data)."""
        warnings: list[str] = []
        start = session_start_utc(now) - timedelta(days=self.cfg.history_days)
        end = session_start_utc(now)
        recent = set()
        for sym in self.cfg.symbols:
            hist = load_bars(sym, "iex", "1Min", start, end, adjusted=True, rth=True, resample="5min")
            if hist.empty:
                warnings.append(f"{sym}: no stored IEX history, skipped")
                continue
            if (end - hist.index[-1]) > timedelta(days=5):
                warnings.append(f"{sym}: stored IEX history ends {hist.index[-1]:%Y-%m-%d}; is the nightly sync running?")
            self.history[sym] = hist
            self.daily[sym] = load_bars(sym, "sip", "1Day")
            splits = load_splits(sym)
            if not splits.empty and (now.tz_localize(None).normalize() - splits["ex_date"].max()).days <= self.cfg.split_blackout_days:
                recent.add(sym)
        self.spy_daily = load_bars("SPY", "sip", "1Day")
        self.recent_split = frozenset(recent)
        return warnings

    def refresh_today(self, now: pd.Timestamp) -> None:
        """One request for every symbol's bars so far today."""
        rows: dict[str, list[dict]] = {}
        for sym, bar in self.client.multi_bars(list(self.history), "5Min", session_start_utc(now), now, feed="iex", adjustment="raw"):
            rows.setdefault(sym, []).append(bar)
        for sym in self.history:
            frame = store.frame_from_api(rows.get(sym, []))
            self.today[sym] = frame[rth_mask(frame.index)] if len(frame) else frame

    def bars(self, symbol: str) -> pd.DataFrame:
        """History plus today, regular hours only; today's bars win any overlap."""
        today = self.today.get(symbol)
        hist = self.history[symbol]
        if today is None or today.empty:
            return hist
        merged = pd.concat([hist, today])
        return merged[~merged.index.duplicated(keep="last")].sort_index()
