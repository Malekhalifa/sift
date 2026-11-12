"""M17 (docs/m17-issuance-protocol.md): long the strongest net repurchasers, short the heaviest issuers, monthly.

    uv run python scripts/issuance_study.py

One frozen setting, no tuning; replicated on the 250 unseen stocks. Reads bars and filings only before the 2025+ holdout.
"""

from __future__ import annotations

import pandas as pd
from high52_study import panel, stats

from tp import config, corp_actions, features, high52, issuance, trials
from tp.bars import load_bars

FIRST = "2016-02-01"
MIN_MONTHS, MIN_POSITIVE_YEARS = 60, 6


def signal_panel(shares: pd.DataFrame, base: pd.DatetimeIndex, columns: pd.Index) -> pd.DataFrame:
    out = {}
    for sym in columns:
        rows = shares[shares["symbol"] == sym]
        filings = issuance.by_filing(rows) if len(rows) else rows
        iss = issuance.issuance_by_filing(filings, corp_actions.load_splits(sym)) if len(filings) else pd.DataFrame(columns=["filed", "issuance"])
        out[sym] = issuance.signal_at(iss, base)
    return pd.DataFrame(out, index=base)


def run(symbols: list[str], base: pd.DatetimeIndex, spy_open: pd.Series, shares: pd.DataFrame) -> pd.DataFrame:
    o, c = panel(symbols, base)
    broken = c.columns[(c.pct_change(fill_method=None) > 1.0).any()]  # a missed reverse split (declared in the protocol)
    if len(broken):
        print(f"  dropped {len(broken)} stocks with a one-session gain above +100%: {', '.join(broken)}")
    o, c = o.drop(columns=broken), c.drop(columns=broken)
    return high52.monthly_spread(o, c, spy_open, FIRST, signal=signal_panel(shares, base, o.columns))


def main() -> None:
    hi = pd.Timestamp(config.HOLDOUT_START, tz="UTC")
    spy = load_bars("SPY", "sip", "1Day", None, hi)
    base = pd.DatetimeIndex(features.session_dates(spy.index))
    spy_open = pd.Series(spy["open"].to_numpy(), index=base)
    shares = pd.read_parquet(config.DATA_DIR / "xbrl" / "shares.parquet")
    shares = shares[shares["filed"] < pd.Timestamp(config.HOLDOUT_START)]  # the holdout is never read
    p = stats(run(config.events_symbols(), base, spy_open, shares), "PRIMARY: 150 stocks (ranks 1-150)")
    r = stats(run(config.confirm_symbols(), base, spy_open, shares), "REPLICATION: 250 unseen stocks (ranks 151-400)")
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
    trials.log_trial("m17-issuance-v1", {"stale_days": issuance.STALE_DAYS, "prior_days": 365, "quintile": 0.2, "hold": "1 month", "cost_per_side": 0.0005},
                     {"primary": "events150", "replication": "confirm250", "period": "2016-02..2024-11"},
                     {"primary_mean": p["mean"], "primary_lower": p["lower"], "replication_mean": r["mean"],
                      "primary_sharpe_monthly": p["sharpe_m"], "eligible": bool(all(checks.values()))}, group="m17-issuance-v1")


if __name__ == "__main__":
    main()
