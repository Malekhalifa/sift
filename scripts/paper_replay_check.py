"""Replay past sessions the way the live loop sees them and compare with the backtest.

For each session and each 5-minute decision time, show the strategy only the bars that had closed by then and keep
the signals decided at that moment. Their union must equal what the backtest produces from the full day. A
mismatch means the live path sees the future or loses a signal.

    uv run python scripts/paper_replay_check.py --sessions 30 --symbols AAPL,MSFT,NVDA
"""

from __future__ import annotations

import argparse

import pandas as pd

from tp import config
from tp.bars import ET, load_bars
from tp.paper import decide
from tp.strategies import OpeningRangeBreakout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sessions", type=int, default=30)
    ap.add_argument("--symbols", default="AAPL,MSFT,NVDA,AMD,TSLA")
    ap.add_argument("--feed", default="iex")
    args = ap.parse_args()
    strat = OpeningRangeBreakout(or_minutes=5, last_entry="10:30")
    total_days = total_signals = mismatches = 0
    for sym in args.symbols.split(","):
        bars = load_bars(sym, args.feed, "1Min", pd.Timestamp("2025-01-01", tz="UTC"), rth=True, resample="5min")
        days = sorted(set(bars.index.tz_convert(ET).normalize()))[-args.sessions :]
        full = strat.generate(sym, bars)
        for day in days:
            window = bars[bars.index >= day.tz_convert("UTC") - pd.Timedelta(days=45)]
            day_bars = window[window.index.tz_convert(ET).normalize() == day]
            live = []
            for decision in pd.date_range(day.replace(hour=9, minute=35), day.replace(hour=15, minute=55), freq="5min"):
                decision = decision.tz_convert("UTC")
                seen = window[window.index <= decision - pd.Timedelta(minutes=decide.BAR_MINUTES)]
                live += decide.signals_at(strat.generate(sym, seen), decision)
            expected = [s for s in full if s.ts.tz_convert(ET).normalize() == day]
            key = lambda ss: [(s.ts, s.side, round(s.entry_ref, 6), round(s.stop, 6), round(s.target, 6)) for s in ss]  # noqa: E731
            total_days += 1
            total_signals += len(expected)
            if key(live) != key(expected):
                mismatches += 1
                print(f"MISMATCH {sym} {day:%Y-%m-%d}: live {key(live)} vs backtest {key(expected)}")
    print(f"{total_days} symbol-sessions replayed, {total_signals} backtest signals, {mismatches} mismatches")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
