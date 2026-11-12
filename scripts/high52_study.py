"""M15 (docs/m15-high52-protocol.md): long the stocks nearest their 52-week high, short those farthest, rebalanced monthly.

    uv run python scripts/high52_study.py

One frozen setting, no tuning; replicated on the 250 unseen stocks. Reads bars only before the 2025+ holdout.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tp import config, features, high52, trials
from tp.bars import load_bars

Z = 1.96
FIRST = "2017-01-02"
MIN_MONTHS, MIN_POSITIVE_YEARS = 60, 6


def panel(symbols: list[str], base: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    hi = pd.Timestamp(config.HOLDOUT_START, tz="UTC")
    opens, closes = {}, {}
    for sym in symbols:
        bars = load_bars(sym, "sip", "1Day", None, hi)
        if bars.empty:
            continue
        dates = features.session_dates(bars.index)
        opens[sym] = pd.Series(bars["open"].to_numpy(), index=dates).reindex(base)
        closes[sym] = pd.Series(bars["close"].to_numpy(), index=dates).reindex(base)
    return pd.DataFrame(opens), pd.DataFrame(closes)


def run(symbols: list[str], base: pd.DatetimeIndex, spy_open: pd.Series, drop_missed_splits: bool = False) -> pd.DataFrame:
    o, c = panel(symbols, base)
    if drop_missed_splits:  # a one-session gain above +100% in a large cap is a reverse split Alpaca's split list lacks
        broken = c.columns[(c.pct_change(fill_method=None) > 1.0).any()]
        print(f"  dropped {len(broken)} stocks with a missed reverse split: {', '.join(broken)}")
        o, c = o.drop(columns=broken), c.drop(columns=broken)
    return high52.monthly_spread(o, c, spy_open, FIRST)


def stats(out: pd.DataFrame, label: str) -> dict:
    v = out["net"]
    n = len(v)
    half = Z * v.std(ddof=1) / np.sqrt(n)
    mid = n // 2
    by_year = v.groupby(v.index.year).mean()
    beta = np.polyfit(out["market"], v, 1)[0]
    print(f"\n{'=' * 78}\n{label}: {n} months, {int(out['ranked'].median())} ranked stocks a month\n{'=' * 78}")
    print(f"net long-short   mean {100 * v.mean():+.3f}% a month   95% interval +-{100 * half:.3f}%   share of months > 0 {(v > 0).mean():.0%}")
    print(f"gross (before cost) {100 * out['gross'].mean():+.3f}%   cost {100 * out['cost'].mean():.3f}%   turnover {out['turnover'].mean():.2f} a month")
    print(f"halves: first {100 * v.iloc[:mid].mean():+.3f}% (n={mid}), last {100 * v.iloc[mid:].mean():+.3f}% (n={n - mid})")
    print("by year:", {int(y): f"{100 * m:+.2f}%" for y, m in by_year.items()})
    print(f"informational: long leg minus SPY {100 * (out['long'] - out['market']).mean():+.3f}%, short leg alone {100 * out['short'].mean():+.3f}%, "
          f"beta to SPY {beta:+.2f}, January alone {100 * v[v.index.month == 1].mean():+.3f}% (n={int((v.index.month == 1).sum())})")
    return {"n": n, "mean": v.mean(), "lower": v.mean() - half, "years_pos": int((by_year > 0).sum()), "n_years": len(by_year),
            "first": v.iloc[:mid].mean(), "last": v.iloc[mid:].mean(), "sharpe_m": v.mean() / v.std(ddof=1)}


def main() -> None:
    hi = pd.Timestamp(config.HOLDOUT_START, tz="UTC")
    spy = load_bars("SPY", "sip", "1Day", None, hi)
    base = pd.DatetimeIndex(features.session_dates(spy.index))
    spy_open = pd.Series(spy["open"].to_numpy(), index=base)
    p = stats(run(config.events_symbols(), base, spy_open), "PRIMARY: 150 stocks (ranks 1-150)")
    print("\nFirst run, bars as stored (the pre-registered run). Four stocks in the replication set carry a reverse split missing from the split list.")
    stats(run(config.confirm_symbols(), base, spy_open), "REPLICATION as stored: 250 unseen stocks (ranks 151-400)")
    print("\nSame rule after a data-hygiene fix fixed in advance of this rerun: drop stocks with a one-session gain above +100%.")
    r = stats(run(config.confirm_symbols(), base, spy_open, drop_missed_splits=True), "REPLICATION cleaned: unseen stocks without missed reverse splits")
    checks = {
        f"1. at least {MIN_MONTHS} months": p["n"] >= MIN_MONTHS,
        "2. mean net > 0 with 95% lower bound > 0": p["lower"] > 0,
        f"3. positive in >= {MIN_POSITIVE_YEARS} of {p['n_years']} years": p["years_pos"] >= MIN_POSITIVE_YEARS,
        "4. positive in both halves": p["first"] > 0 and p["last"] > 0,
        "5. replication: positive mean and both halves on unseen stocks": r["mean"] > 0 and r["first"] > 0 and r["last"] > 0,
    }
    print("\nCriteria")
    for label, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print("  => " + ("INCONCLUSIVE (too few months)" if p["n"] < MIN_MONTHS else "PASSES: eligible for the one-shot holdout" if all(checks.values()) else "NOT eligible"))
    trials.log_trial("m15-high52-v1", {"window": 252, "quintile": 0.2, "hold": "1 month", "cost_per_side": 0.0005},
                     {"primary": "events150", "replication": "confirm250", "period": "2017-01..2024-11"},
                     {"primary_mean": p["mean"], "primary_lower": p["lower"], "replication_mean": r["mean"],
                      "primary_sharpe_monthly": p["sharpe_m"], "eligible": bool(all(checks.values()))}, group="m15-high52-v1")


if __name__ == "__main__":
    main()
