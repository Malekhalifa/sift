"""M16 (docs/m16-shortvol-protocol.md): long the stocks with the lowest abnormal FINRA short share, short the highest, monthly.

    uv run python scripts/shortvol_study.py

One frozen setting, no tuning; replicated on the 250 unseen stocks. Reads bars and short-volume files only before the
2025+ holdout.
"""

from __future__ import annotations

import pandas as pd
from high52_study import panel, stats

from tp import config, features, high52, trials
from tp.bars import load_bars

FIRST = "2019-08-01"
MIN_MONTHS, MIN_POSITIVE_YEARS = 60, 4
FAST, SLOW, FAST_MIN, SLOW_MIN = 60, 250, 45, 200


def abnormal_short_share(shortvol: pd.DataFrame, base: pd.DatetimeIndex, columns: pd.Index) -> pd.DataFrame:
    """Highest = lowest abnormal short share (the long side), known at each session's close."""
    sv = shortvol.pivot_table(index="date", columns="symbol", values=["short", "total"], aggfunc="sum")
    share = (sv["short"] / sv["total"]).reindex(index=base, columns=columns)
    return -(share.rolling(FAST, min_periods=FAST_MIN).mean() - share.rolling(SLOW, min_periods=SLOW_MIN).mean())


def run(symbols: list[str], base: pd.DatetimeIndex, spy_open: pd.Series, shortvol: pd.DataFrame) -> pd.DataFrame:
    o, c = panel(symbols, base)
    broken = c.columns[(c.pct_change(fill_method=None) > 1.0).any()]  # a missed reverse split (declared in the protocol)
    if len(broken):
        print(f"  dropped {len(broken)} stocks with a one-session gain above +100%: {', '.join(broken)}")
    o, c = o.drop(columns=broken), c.drop(columns=broken)
    return high52.monthly_spread(o, c, spy_open, FIRST, signal=abnormal_short_share(shortvol, base, o.columns))


def main() -> None:
    hi = pd.Timestamp(config.HOLDOUT_START, tz="UTC")
    spy = load_bars("SPY", "sip", "1Day", None, hi)
    base = pd.DatetimeIndex(features.session_dates(spy.index))
    spy_open = pd.Series(spy["open"].to_numpy(), index=base)
    shortvol = pd.read_parquet(config.DATA_DIR / "finra" / "shortvol.parquet")
    shortvol = shortvol[shortvol["date"] < pd.Timestamp(config.HOLDOUT_START)]  # the holdout is never read
    p = stats(run(config.events_symbols(), base, spy_open, shortvol), "PRIMARY: 150 stocks (ranks 1-150)")
    r = stats(run(config.confirm_symbols(), base, spy_open, shortvol), "REPLICATION: 250 unseen stocks (ranks 151-400)")
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
    trials.log_trial("m16-shortvol-v1", {"fast": FAST, "slow": SLOW, "quintile": 0.2, "hold": "1 month", "cost_per_side": 0.0005},
                     {"primary": "events150", "replication": "confirm250", "period": "2019-08..2024-11"},
                     {"primary_mean": p["mean"], "primary_lower": p["lower"], "replication_mean": r["mean"],
                      "primary_sharpe_monthly": p["sharpe_m"], "eligible": bool(all(checks.values()))}, group="m16-shortvol-v1")


if __name__ == "__main__":
    main()
