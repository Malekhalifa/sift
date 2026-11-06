"""Descriptive event study of insider purchases by class (routine, opportunistic, thin). Selects and tunes nothing.

Each purchase event (one insider is enough, at least $100,000, 10-day window, 30-day cooldown) gets one number: the stock's
return from the next session's open to the close 20 sessions later, minus SPY's over the same dates, in percent, no costs.
If the Cohen-Malloy-Pomorski finding holds in our universe, opportunistic events should beat routine ones.

    uv run python scripts/insider_event_study.py [--end 2024-12-31]
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta

import numpy as np
import pandas as pd

from tp import config, features, insiders
from tp.bars import load_bars

HORIZON = 20
MIN_VALUE = 100_000.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--end", type=date.fromisoformat, default=config.HOLDOUT_START - timedelta(days=1))
    args = ap.parse_args()
    if args.end >= config.HOLDOUT_START:
        raise SystemExit("refusing to read the holdout")
    hi = pd.Timestamp(args.end + timedelta(days=1), tz="UTC")
    spy = load_bars("SPY", "sip", "1Day", None, hi)
    spy_dates = features.session_dates(spy.index)
    spy_open = pd.Series(spy["open"].to_numpy(), index=spy_dates)
    spy_close = pd.Series(spy["close"].to_numpy(), index=spy_dates)

    rows = []
    for sym, cik in insiders.symbol_ciks().items():
        buys = insiders.classified_purchases(cik)
        bars = load_bars(sym, "sip", "1Day", None, hi)
        if buys.empty or bars.empty:
            continue
        dates = pd.DatetimeIndex(features.session_dates(bars.index))
        for klass in ("routine", "opportunistic", "thin"):
            for day in insiders.buy_events(buys, {klass}, 1, MIN_VALUE):
                pos = int(dates.searchsorted(day, side="left"))
                if day < dates[0] or pos + HORIZON >= len(bars):
                    continue  # before our price history, or too close to the end to measure
                d_in, d_out = dates[pos + 1], dates[pos + HORIZON]
                if d_in not in spy_open.index or d_out not in spy_close.index:
                    continue
                stock = bars["close"].iloc[pos + HORIZON] / bars["open"].iloc[pos + 1] - 1
                market = spy_close[d_out] / spy_open[d_in] - 1
                rows.append({"symbol": sym, "klass": klass, "year": day.year, "ar": 100 * (stock - market)})
    df = pd.DataFrame(rows)
    print(f"{len(df):,} events. Market-adjusted return, next open to the close {HORIZON} sessions later, percent, no costs.\n")
    print(f"{'class':<15}{'period':<11}{'events':>7}{'mean %':>9}{'+-95%':>8}{'median %':>10}{'share > 0':>11}")
    for klass in ("routine", "opportunistic", "thin"):
        for name, lo in (("2016-2024", 2016), ("2019-2024", 2019)):
            x = df[(df["klass"] == klass) & (df["year"] >= lo)]["ar"]
            if len(x) < 3:
                print(f"{klass:<15}{name:<11}{len(x):>7}")
                continue
            half = 1.96 * x.std(ddof=1) / np.sqrt(len(x))
            print(f"{klass:<15}{name:<11}{len(x):>7}{x.mean():>+9.2f}{half:>8.2f}{x.median():>+10.2f}{(x > 0).mean():>11.0%}")
    print("\nIntervals ignore clustering (insiders buy together in selloffs), so they overstate certainty.")


if __name__ == "__main__":
    main()
