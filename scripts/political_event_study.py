"""M12 event studies (docs/m12-political-protocol.md): average market-adjusted return after presidential posts that name a
listed company and after large Pentagon awards to listed primes. Judges nothing but the fixed protocol criteria; tunes
nothing. The 2025+ holdout is never read.

    uv run python scripts/political_event_study.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tp import config, features, political
from tp.bars import load_bars

HOLD = 5  # sessions; the judged horizon
INFO_HOLDS = (1, 20)
COST = 0.001  # round trip, as a fraction
Z = 2.2414  # two-sided 97.5%: the 5% error budget split over the two studies
MIN_EVENTS, MIN_YEAR_EVENTS = 100, 8
POST_PERIODS = (("2016-01-04", "2018-12-31"), ("2022-02-01", "2024-12-31"))
AWARD_PERIOD = ("2016-01-04", "2024-12-31")


def returns(events: pd.DataFrame, entry_pos, signed: bool, holds: tuple[int, ...]) -> pd.DataFrame:
    hi = pd.Timestamp(config.HOLDOUT_START, tz="UTC")  # bars stop before the holdout
    spy = load_bars("SPY", "sip", "1Day", None, hi)
    spy_dates = features.session_dates(spy.index)
    spy_open, spy_close = pd.Series(spy["open"].to_numpy(), index=spy_dates), pd.Series(spy["close"].to_numpy(), index=spy_dates)
    cache, rows = {}, []
    for ev in events.itertuples():
        if ev.symbol not in cache:
            bars = load_bars(ev.symbol, "sip", "1Day", None, hi)
            cache[ev.symbol] = (bars, pd.DatetimeIndex(features.session_dates(bars.index))) if not bars.empty else None
        if cache[ev.symbol] is None:
            continue
        bars, dates = cache[ev.symbol]
        if ev.ts.tz_convert("America/New_York").date() < dates[0].date():
            continue
        pos = entry_pos(ev.ts, dates)
        row = {"symbol": ev.symbol, "ts": ev.ts, "year": ev.ts.year}
        for h in holds:
            end = pos + h - 1
            if end >= len(bars) or dates[pos] not in spy_open.index or dates[end] not in spy_close.index:
                row[f"net{h}"] = np.nan
                continue
            stock = bars["close"].iloc[end] / bars["open"].iloc[pos] - 1
            market = spy_close[dates[end]] / spy_open[dates[pos]] - 1
            sign = ev.tone if signed else 1
            row[f"net{h}"] = sign * (stock - market) - COST
        rows.append(row)
    return pd.DataFrame(rows)


def judge(name: str, df: pd.DataFrame) -> None:
    x = df.dropna(subset=[f"net{HOLD}"]).sort_values("ts")
    n = len(x)
    print(f"\n{'=' * 78}\n{name}: {n} events with returns (net of {COST:.2%} round trip, market-adjusted, {HOLD}-session hold)\n{'=' * 78}")
    if n < 3:
        print("too few events")
        return
    v = x[f"net{HOLD}"]
    mean, half = v.mean(), Z * v.std(ddof=1) / np.sqrt(n)
    print(f"mean {100 * mean:+.3f}%   97.5% interval +-{100 * half:.3f}%   median {100 * v.median():+.3f}%   share > 0 {(v > 0).mean():.0%}")
    for h in INFO_HOLDS:
        w = x[f"net{h}"].dropna()
        if len(w) > 2:
            print(f"  informational {h}-session hold: mean {100 * w.mean():+.3f}% +-{100 * Z * w.std(ddof=1) / np.sqrt(len(w)):.3f}% over {len(w)} events")
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
    verdict = "INCONCLUSIVE (too few events)" if n < MIN_EVENTS else ("PASSES: eligible for the one-shot holdout" if all(checks.values()) else "NOT eligible")
    print(f"  => {verdict}")


def main() -> None:
    posts = pd.read_parquet(political.posts_path())
    keep = pd.Series(False, index=posts.index)
    for lo, hi in POST_PERIODS:
        keep |= (posts["ts"] >= pd.Timestamp(lo, tz="UTC")) & (posts["ts"] < pd.Timestamp(hi, tz="UTC") + pd.Timedelta(days=1))
    pe = political.post_events(posts[keep])
    res = returns(pe, political.post_entry_pos, True, (HOLD, *INFO_HOLDS))
    judge("P1 presidential posts naming a listed company", res)
    x = res.dropna(subset=[f"net{HOLD}"])
    tones = pe.set_index(["symbol", "ts"])["tone"]
    x = x.assign(tone=[tones[(r.symbol, r.ts)] for r in x.itertuples()])
    print("\nInformational (not judged):")
    for label, sub in (("positive posts only", x[x["tone"] > 0]), ("negative posts only", x[x["tone"] < 0]),
                       ("without META and AMZN", x[~x["symbol"].isin(["META", "AMZN"])])):
        v = sub[f"net{HOLD}"]
        if len(v) > 2:
            print(f"  {label:<24} n={len(v):<4} mean {100 * v.mean():+.3f}% +-{100 * Z * v.std(ddof=1) / np.sqrt(len(v)):.3f}%")

    aw = pd.read_parquet(political.awards_path())
    aw = aw[(aw["action_date"] >= AWARD_PERIOD[0]) & (aw["action_date"] <= AWARD_PERIOD[1])]
    res2 = returns(political.award_events(aw), political.award_entry_pos, False, (HOLD, *INFO_HOLDS))
    judge("P2 large Pentagon awards to listed primes", res2)


if __name__ == "__main__":
    main()
