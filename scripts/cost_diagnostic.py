"""Diagnostic: how much of a finished sweep's out-of-sample result is cost?

Re-simulates exactly the configurations the walk-forward chose, in the years it chose them, at several cost levels.
Nothing is selected or tuned here; it only explains a result that is already recorded.

    uv run python scripts/cost_diagnostic.py --config config/sweeps/m4b-wide.toml
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import date

import numpy as np
import pandas as pd

from tp import backtest as bt
from tp import config, metrics
from tp.strategies import REGISTRY
from tp.sweeps import expand_grid, load_sweep_file

LEVELS = [
    ("zero cost", dict(slippage=0.0, limit_trade_through=0.0, sell_fee_bps=0.0)),
    ("half slippage", dict(slippage=0.005, limit_trade_through=0.005)),
    ("backtest (1c)", dict(slippage=0.01, limit_trade_through=0.01)),
    ("double (2c)", dict(slippage=0.02, limit_trade_through=0.02)),
]


def load_sweep_module():
    spec = importlib.util.spec_from_file_location("sweep_script", config.ROOT / "scripts" / "sweep.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--family", default="orb")
    args = ap.parse_args()
    cfg = load_sweep_file(args.config)
    sweep = load_sweep_module()
    summary = json.loads((config.DATA_DIR / "sweeps" / cfg["name"] / "summary.json").read_text())
    folds = summary["families"][args.family]["folds"]
    cls = REGISTRY[args.family]
    params_by_id = {f"{args.family}-{i:03d}": p for i, p in enumerate(expand_grid(cls, cfg[args.family]["grid"]))}
    chosen: dict[str, list[int]] = {}
    for f in folds:
        if f["config_id"]:
            chosen.setdefault(f["config_id"], []).append(f["test_year"])
    print(f"{cfg['name']}: walk-forward chose {len(chosen)} configurations: " + ", ".join(f"{c} for {y}" for c, y in chosen.items()))

    symbols = config.wide_symbols() if cfg.get("universe") == "wide" else config.load_universe()["universe"]["traded"]
    data = sweep.Data(symbols, date.fromisoformat(cfg["period_start"]), date.fromisoformat(cfg["period_end"]), cfg.get("bar_timeframe", "1Min"))
    risk = bt.RiskConfig()
    signals = {cid: sweep.simulate_config(cls(**params_by_id[cid]), data, bt.CostModel(), risk)[0] for cid in chosen}

    print(f"\n{'cost level':<16}{'trades':>8}{'win%':>7}{'exp R':>9}{'95% CI':>9}{'PF':>7}")
    base_trades = None
    for label, kw in LEVELS:
        cost = bt.CostModel(**kw)
        parts = []
        for cid, years in chosen.items():
            raw, _ = bt.simulate_signals(signals[cid], data.prepared, cost, risk)
            df = sweep.raw_frame(raw)
            parts.append(df[df["year"].isin(years)])
        oos = pd.concat(parts)
        s = metrics.r_stats(oos["pnl_R"])
        print(f"{label:<16}{s['n']:>8}{100 * s['win_rate']:>7.1f}{s['expectancy_R']:>+9.3f}{s['expectancy_ci95_R']:>9.3f}{s['profit_factor']:>7.2f}")
        if label.startswith("backtest"):
            base_trades = oos

    # how big is a penny relative to one R on these trades?
    ratios, risk_pct = [], []
    for _, t in base_trades.iterrows():
        pb = data.prepared[t.symbol]
        adj = pb.adj[int(pb.index.searchsorted(t.entry_ts))]
        ratios.append(2 * (0.01 / adj) / t.risk_per_share)  # round-trip slippage as a share of one R
        risk_pct.append(100 * t.risk_per_share / t.entry_ref)
    ratios, risk_pct = np.array(ratios), np.array(risk_pct)
    print(f"\nCost vs risk on these {len(ratios)} trades (1 cent each way):")
    print(f"  median stop distance {np.median(risk_pct):.2f}% of price; round-trip slippage eats a median {100 * np.median(ratios):.0f}% of one R")
    print(f"  {100 * np.mean(ratios > 0.25):.0f}% of trades lose more than a quarter of an R to slippage alone")


if __name__ == "__main__":
    main()
