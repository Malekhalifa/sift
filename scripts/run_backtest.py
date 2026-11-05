"""Run a backtest, print the report, log the trial.

    uv run python scripts/run_backtest.py --strategy orb --symbols AAPL,MSFT
    uv run python scripts/run_backtest.py --strategy orb --set or_minutes=15 --set stop_mode=atr --cost-sweep

Data from config.HOLDOUT_START onward is off limits unless --use-holdout is passed (and the trial is flagged).
Every run is appended to data/trials.sqlite; the trial count feeds the Deflated Sharpe check later.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date, timedelta

import pandas as pd

from tp import backtest as bt
from tp import config, metrics, trials
from tp.sweeps import parse_sets
from tp.bars import load_bars, split_factor
from tp.corp_actions import load_splits
from tp.strategies import REGISTRY

SWEEP_SLIPPAGE = (0.0, 0.005, 0.01, 0.02, 0.03)


def utc_midnight(d: date) -> pd.Timestamp:
    return pd.Timestamp(d, tz="UTC")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strategy", default="orb", choices=sorted(REGISTRY))
    ap.add_argument("--symbols", help="comma-separated; default is the traded universe")
    ap.add_argument("--feed", default="sip", choices=["sip", "iex"])
    ap.add_argument("--start", type=date.fromisoformat, default=date(2016, 1, 4))
    ap.add_argument("--end", type=date.fromisoformat, default=config.HOLDOUT_START - timedelta(days=1), help="inclusive")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="strategy parameter")
    ap.add_argument("--slippage", type=float, default=bt.CostModel.slippage, help="$/share, adverse, each market fill")
    ap.add_argument("--equity", type=float, default=bt.RiskConfig.start_equity)
    ap.add_argument("--risk-per-trade", type=float, default=bt.RiskConfig.risk_per_trade)
    ap.add_argument("--max-leverage", type=float, default=bt.RiskConfig.max_leverage)
    ap.add_argument("--max-positions", type=int, default=bt.RiskConfig.max_positions)
    ap.add_argument("--cost-sweep", action="store_true", help="also show results across slippage assumptions")
    ap.add_argument("--use-holdout", action="store_true", help=f"allow data from {config.HOLDOUT_START} on")
    ap.add_argument("--no-log", action="store_true", help="skip the trial registry and artifacts")
    args = ap.parse_args()

    touches_holdout = args.end >= config.HOLDOUT_START
    if touches_holdout and not args.use_holdout:
        print(f"Refusing: --end {args.end} reaches the holdout (from {config.HOLDOUT_START}). "
              "Pass --use-holdout only for the final, pre-registered validation run.", file=sys.stderr)
        return 2

    strategy_cls = REGISTRY[args.strategy]
    overrides = parse_sets(args.set, strategy_cls.params_cls)
    strategy = strategy_cls(**overrides)
    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else config.load_universe()["universe"]["traded"]
    start, end = utc_midnight(args.start), utc_midnight(args.end + timedelta(days=1))
    bar_minutes = strategy.params.bar_minutes

    spy_daily = load_bars("SPY", feed="sip", timeframe="1Day") if strategy.params.trend_filter == "spy_sma" else None
    frames, prepared, signals = {}, {}, []
    for sym in symbols:
        bars = load_bars(sym, feed=args.feed, timeframe="1Min", start=start, end=end, rth=True, resample=f"{bar_minutes}min")
        if bars.empty:
            print(f"  {sym}: no {args.feed} 1Min data in range, skipped", file=sys.stderr)
            continue
        daily = load_bars(sym, feed="sip", timeframe="1Day")
        frames[sym] = bars
        prepared[sym] = bt.PreparedBars.from_frame(bars, bar_minutes, split_factor(bars.index, load_splits(sym)))
        signals += strategy.generate(sym, bars, daily, spy_daily)
        print(f"  {sym}: {len(bars):,} bars, {bars.index[0].date()} -> {bars.index[-1].date()}", file=sys.stderr)
    if not prepared:
        print("No data loaded. Run the recorder first.", file=sys.stderr)
        return 1

    cost = bt.CostModel(slippage=args.slippage)
    risk = bt.RiskConfig(start_equity=args.equity, risk_per_trade=args.risk_per_trade,
                         max_leverage=args.max_leverage, max_positions=args.max_positions)
    res = bt.execute(signals, prepared, cost, risk)
    summary = metrics.summarize(res, rr=strategy.params.rr)

    print(f"\n=== {args.strategy} {strategy.params_dict()} | {args.feed} | {args.start} -> {args.end} | {len(prepared)} symbols ===")
    print(metrics.format_report(summary))
    if len(res.raw):
        print("\nBy symbol      n    win%    expR     PF")
        for sym, g in res.raw.groupby("symbol"):
            x = metrics.r_stats(g["pnl_R"])
            print(f"  {sym:<6} {x['n']:>6}  {100 * x['win_rate']:5.1f}  {x['expectancy_R']:+.3f}  {x['profit_factor']:.2f}")

    if args.cost_sweep and len(res.raw):
        print("\nCost sensitivity (same signals; slippage $/share on each market fill)")
        print("  slip     n    win%    expR     PF    totalR")
        for slip in SWEEP_SLIPPAGE:
            r = bt.execute(signals, prepared, bt.CostModel(slippage=slip), risk)
            x = metrics.r_stats(r.raw["pnl_R"])
            print(f"  {slip:<6.3f} {x['n']:>5}  {100 * x['win_rate']:5.1f}  {x['expectancy_R']:+.3f}  {x['profit_factor']:.2f}  {x['total_R']:+8.1f}")

    if not args.no_log:
        scope = {
            "symbols": sorted(prepared), "feed": args.feed, "start": args.start.isoformat(), "end": args.end.isoformat(),
            "cost": asdict(cost), "risk": {**asdict(risk), "flat_time": risk.flat_time.isoformat()},
        }
        trial_id = trials.log_trial(args.strategy, strategy.params_dict(), scope, metrics.to_jsonable(summary), holdout=touches_holdout)
        out_dir = config.DATA_DIR / "backtests" / f"{trial_id:05d}"
        out_dir.mkdir(parents=True, exist_ok=True)
        res.raw.to_parquet(out_dir / "raw_trades.parquet", index=False)
        res.trades.to_parquet(out_dir / "trades.parquet", index=False)
        (out_dir / "summary.json").write_text(json.dumps(metrics.to_jsonable(summary), indent=2))
        print(f"\nTrial #{trial_id} logged ({trials.count_trials(args.strategy)} for '{args.strategy}'), artifacts in {out_dir}"
              + ("  [HOLDOUT]" if touches_holdout else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
