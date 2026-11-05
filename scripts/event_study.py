"""Descriptive event study of earnings reactions. Reads the data; selects and tunes nothing.

For each earnings event, take the reaction session's market-adjusted move (in pre-event ATRs, exactly as the strategy
defines it) and report the average market-adjusted return over the following 1 to 20 sessions, by reaction size.
If post-earnings drift exists, large positive reactions should keep rising and large negative ones keep falling.

    uv run python scripts/event_study.py [--end 2024-12-31]
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta

import numpy as np
import pandas as pd

from tp import config, events, features
from tp.bars import load_bars

HORIZONS = (1, 3, 5, 10, 20)
EDGES = [-np.inf, -3, -2, -1, 1, 2, 3, np.inf]
LABELS = ["< -3", "-3 to -2", "-2 to -1", "-1 to +1", "+1 to +2", "+2 to +3", "> +3"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--end", type=date.fromisoformat, default=config.HOLDOUT_START - timedelta(days=1))
    args = ap.parse_args()
    if args.end >= config.HOLDOUT_START:
        raise SystemExit("refusing to read the holdout")
    hi = pd.Timestamp(args.end + timedelta(days=1), tz="UTC")
    spy = load_bars("SPY", "sip", "1Day", None, hi)
    spy_ret = spy["close"].pct_change()
    spy_ret.index = features.session_dates(spy.index)

    rows, excluded, raw_total = [], 0, 0
    for sym in config.events_symbols():
        bars = load_bars(sym, "sip", "1Day", None, hi)
        filed = events.load_earnings(sym)["filed_at"]
        filed = filed[filed < hi]
        if bars.empty or filed.empty:
            continue
        raw_total += len(filed)
        table = events.reaction_table(bars, spy, filed)
        excluded += len(filed) - len(table)
        stock_ret = bars["close"].pct_change().to_numpy()
        spy_aligned = spy_ret.reindex(features.session_dates(bars.index)).to_numpy()
        ab = stock_ret - spy_aligned
        for r in table.itertuples():
            row = {"symbol": sym, "year": r.filed_at.tz_convert("America/New_York").year, "z": r.z, "klass": r.klass}
            for h in HORIZONS:
                row[f"car{h}"] = ab[r.pos + 1 : r.pos + 1 + h].sum() * 100 if r.pos + h < len(bars) else np.nan
            rows.append(row)
    df = pd.DataFrame(rows)
    print(f"{raw_total:,} earnings filings in range; {len(df):,} tradable events after exclusions "
          f"({excluded:,} dropped: intraday releases, repeats, missing data). Pre-market {int((df.klass == 'pre').sum()):,}, after-close {int((df.klass == 'post').sum()):,}.")
    df["bucket"] = pd.cut(df["z"], EDGES, labels=LABELS)
    print("\nAverage market-adjusted return AFTER the reaction session, in percent (positive reaction should drift up if drift exists)")
    print(f"{'reaction (ATRs)':<14}{'events':>8}" + "".join(f"{'+' + str(h) + 'd':>9}" for h in HORIZONS) + "   t-stat at +10d")
    for label in LABELS:
        g = df[df["bucket"] == label]
        cells = "".join(f"{g[f'car{h}'].mean():>+9.2f}" for h in HORIZONS)
        x = g["car10"].dropna()
        t = x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")
        print(f"{label:<14}{len(g):>8}{cells}   {t:>6.2f}")
    print("\nDrift test: (top bucket minus bottom bucket) of average +10d return, by period")
    for name, mask in (("2016-2018", df.year <= 2018), ("2019-2024", df.year >= 2019)):
        sub = df[mask]
        up, down = sub[sub.z > 2]["car10"].dropna(), sub[sub.z < -2]["car10"].dropna()
        if len(up) > 5 and len(down) > 5:
            diff = up.mean() - down.mean()
            se = np.sqrt(up.var(ddof=1) / len(up) + down.var(ddof=1) / len(down))
            print(f"  {name}: up-reactions {up.mean():+.2f}% (n={len(up)}) minus down-reactions {down.mean():+.2f}% (n={len(down)}) = {diff:+.2f}%  (naive t = {diff / se:.2f})")
    print("\nNaive t-statistics ignore that events cluster in earnings seasons, so they overstate certainty.")


if __name__ == "__main__":
    main()
