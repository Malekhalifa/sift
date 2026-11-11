"""M14 event study (docs/m14-eightk-protocol.md): average market-adjusted return, signed short, after 8-K filings that carry
a bad-news item. Judges nothing but the fixed protocol criteria; tunes nothing. The 2025+ holdout is never read.

    uv run python scripts/eightk_event_study.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tp import config, eightk, features, political
from tp.bars import load_bars

HOLD = 5  # sessions; the judged horizon
INFO_HOLDS = (1, 20)
COST = 0.001  # round trip, as a fraction
Z = 1.96  # two-sided 95%: one study
MIN_EVENTS, MIN_YEAR_EVENTS = 100, 8
START, END = pd.Timestamp("2016-01-04", tz="UTC"), pd.Timestamp(config.HOLDOUT_START, tz="UTC")


def returns(events: pd.DataFrame) -> pd.DataFrame:
    spy = load_bars("SPY", "sip", "1Day", None, END)
    spy_dates = features.session_dates(spy.index)
    spy_open, spy_close = pd.Series(spy["open"].to_numpy(), index=spy_dates), pd.Series(spy["close"].to_numpy(), index=spy_dates)
    cache, rows = {}, []
    for ev in events.itertuples():
        if ev.symbol not in cache:
            bars = load_bars(ev.symbol, "sip", "1Day", None, END)
            cache[ev.symbol] = (bars, pd.DatetimeIndex(features.session_dates(bars.index))) if not bars.empty else None
        if cache[ev.symbol] is None:
            continue
        bars, dates = cache[ev.symbol]
        if ev.ts.tz_convert("America/New_York").date() < dates[0].date():
            continue
        pos = political.post_entry_pos(ev.ts, dates)
        row = {"symbol": ev.symbol, "ts": ev.ts, "year": ev.ts.year, "items": ev.items}
        for h in (HOLD, *INFO_HOLDS):
            end = pos + h - 1
            if end >= len(bars) or dates[pos] not in spy_open.index or dates[end] not in spy_close.index:
                row[f"ex{h}"] = np.nan
                continue
            stock = bars["close"].iloc[end] / bars["open"].iloc[pos] - 1
            market = spy_close[dates[end]] / spy_open[dates[pos]] - 1
            row[f"ex{h}"] = stock - market  # excess over the market, before direction and cost
        rows.append(row)
    return pd.DataFrame(rows)


def band(v: pd.Series) -> str:
    return f"{100 * v.mean():+.3f}% +-{100 * Z * v.std(ddof=1) / np.sqrt(len(v)):.3f}% (n={len(v)})"


def main() -> None:
    f = pd.read_parquet(eightk.eightk_path())
    res = returns(eightk.bad_news_events(f, START, END))
    for h in (HOLD, *INFO_HOLDS):
        res[f"net{h}"] = -res[f"ex{h}"] - COST  # short the stock, hedge with SPY
    x = res.dropna(subset=[f"net{HOLD}"]).sort_values("ts")
    n, v = len(x), x[f"net{HOLD}"]
    print(f"\n{'=' * 78}\nM14 8-K bad-news items: {n} events with returns (short, market-adjusted, {HOLD}-session hold, net of {COST:.2%})\n{'=' * 78}")
    mean, half = v.mean(), Z * v.std(ddof=1) / np.sqrt(n)
    print(f"mean {100 * mean:+.3f}%   95% interval +-{100 * half:.3f}%   median {100 * v.median():+.3f}%   share > 0 {(v > 0).mean():.0%}")
    by_year = x.groupby("year")[f"net{HOLD}"].agg(["count", "mean"])
    print("by year:", {int(y): f"{100 * r['mean']:+.2f}% (n={int(r['count'])})" for y, r in by_year.iterrows()})
    big = by_year[by_year["count"] >= MIN_YEAR_EVENTS]
    mid = n // 2
    first, second = v.iloc[:mid].mean(), v.iloc[mid:].mean()
    print(f"halves: earlier {100 * first:+.3f}% (n={mid}), later {100 * second:+.3f}% (n={n - mid})")
    checks = {
        f"at least {MIN_EVENTS} events": n >= MIN_EVENTS,
        "mean net return > 0 with interval lower bound > 0": mean - half > 0,
        f"positive in >= 2/3 of years with >= {MIN_YEAR_EVENTS} events": len(big) > 0 and (big["mean"] > 0).mean() >= 2 / 3,
        "positive in both halves": first > 0 and second > 0,
    }
    for label, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print("  => " + ("INCONCLUSIVE (too few events)" if n < MIN_EVENTS else "PASSES: eligible for the one-shot holdout" if all(checks.values()) else "NOT eligible"))

    print("\nInformational (not judged):")
    for h in INFO_HOLDS:
        w = x[f"net{h}"].dropna()
        print(f"  short, {h}-session hold: {band(w)}")
    print(f"  long side (sign flipped, 5 sessions): {band(-x[f'ex{HOLD}'] * -1 - COST)}")
    for code in sorted(eightk.BAD_ITEMS):
        sub = x[x["items"].str.split(",").map(lambda c, code=code: code in c)][f"net{HOLD}"]
        if len(sub) > 2:
            print(f"  item {code}: short {band(sub)}")


if __name__ == "__main__":
    main()
