"""M18 (docs/m18-lazyprices-protocol.md): long the stocks whose 10-K risk factors changed least, short those that changed most.

    uv run python scripts/lazyprices_study.py

One frozen setting, no tuning; replicated on the 250 unseen stocks. Reads bars and 10-K text only before the 2025+ holdout.
"""

from __future__ import annotations

import pandas as pd
from high52_study import panel, stats
from lazyprices_gate import with_similarity

from tp import config, features, high52, issuance, trials
from tp.bars import load_bars

FIRST = "2016-02-01"
MIN_MONTHS, MIN_POSITIVE_YEARS, N_YEARS, MIN_RANKED = 48, 6, 9, 20


def signal_panel(sims: pd.DataFrame, base: pd.DatetimeIndex, columns: pd.Index) -> pd.DataFrame:
    out = {}
    for sym in columns:
        g = sims[(sims["symbol"] == sym) & sims["similarity"].notna()]
        out[sym] = issuance.latest_known(g.rename(columns={"filed_at": "filed", "similarity": "value"})[["filed", "value"]].assign(
            filed=lambda d: d["filed"].dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()), base)
    return pd.DataFrame(out, index=base)


def run(symbols: list[str], base: pd.DatetimeIndex, spy_open: pd.Series, sims: pd.DataFrame) -> pd.DataFrame:
    o, c = panel(symbols, base)
    broken = c.columns[(c.pct_change(fill_method=None) > 1.0).any()]  # a missed reverse split (declared in the protocol)
    if len(broken):
        print(f"  dropped {len(broken)} stocks with a one-session gain above +100%: {', '.join(broken)}")
    o, c = o.drop(columns=broken), c.drop(columns=broken)
    return high52.monthly_spread(o, c, spy_open, FIRST, signal=signal_panel(sims, base, o.columns), min_ranked=MIN_RANKED)


def main() -> None:
    hi = pd.Timestamp(config.HOLDOUT_START, tz="UTC")
    spy = load_bars("SPY", "sip", "1Day", None, hi)
    base = pd.DatetimeIndex(features.session_dates(spy.index))
    spy_open = pd.Series(spy["open"].to_numpy(), index=base)
    rf = pd.read_parquet(config.DATA_DIR / "riskfactors" / "riskfactors.parquet")
    rf = rf[rf["filed_at"] < hi]  # the holdout is never read
    sims = pd.concat([with_similarity(g) for _, g in rf.groupby("symbol")], ignore_index=True)
    p_out = run(config.events_symbols(), base, spy_open, sims)
    r_out = run(config.confirm_symbols(), base, spy_open, sims)
    p = stats(p_out, f"PRIMARY: 150 stocks, months with >= {MIN_RANKED} ranked")
    r = stats(r_out, "REPLICATION: 250 unseen stocks")
    print(f"\nMonths in the book: primary {p['n']}, replication {r['n']}; by calendar month (primary): "
          f"{ {int(m): int(c) for m, c in p_out.index.month.value_counts().sort_index().items()} }")
    checks = {
        f"1. at least {MIN_MONTHS} months": p["n"] >= MIN_MONTHS,
        "2. mean net > 0 with 95% lower bound > 0": p["lower"] > 0,
        f"3. positive in >= {MIN_POSITIVE_YEARS} of {N_YEARS} years": p["years_pos"] >= MIN_POSITIVE_YEARS,
        "4. positive in both halves": p["first"] > 0 and p["last"] > 0,
        "5. replication: positive mean and both halves on unseen stocks": r["mean"] > 0 and r["first"] > 0 and r["last"] > 0,
    }
    print("\nCriteria")
    for label, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print("  => " + ("INCONCLUSIVE (too few months)" if p["n"] < MIN_MONTHS else "PASSES: eligible for the one-shot holdout" if all(checks.values()) else "NOT eligible"))
    trials.log_trial("m18-lazyprices-v1", {"stale_days": 135, "prior_days": 365, "quintile": 0.2, "min_ranked": MIN_RANKED, "hold": "1 month", "cost_per_side": 0.0005},
                     {"primary": "events150", "replication": "confirm250", "period": "2016-02..2024-11"},
                     {"primary_mean": p["mean"], "primary_lower": p["lower"], "replication_mean": r["mean"],
                      "primary_sharpe_monthly": p["sharpe_m"], "eligible": bool(all(checks.values()))}, group="m18-lazyprices-v1")


if __name__ == "__main__":
    main()
