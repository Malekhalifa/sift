"""Pre-registered walk-forward sweep (see docs/m4-protocol.md and config/sweeps/m4.toml).

    uv run python scripts/sweep.py                      # every family in the config
    uv run python scripts/sweep.py --family fade
    uv run python scripts/sweep.py --time-only          # time a few configs, log nothing, show no results

Every configuration is logged as a trial under the sweep name. Re-running with the same name resumes without
double counting; to change the grid, change `name` in the config (the old trials still count).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict
from datetime import date, timedelta

import numpy as np
import pandas as pd

from tp import backtest as bt
from tp import swing
from tp import config, metrics, stats, store, trials
from tp import walkforward as wf
from tp.bars import load_bars, split_factor
from tp.corp_actions import load_splits
from tp.strategies import REGISTRY
from tp.sweeps import expand_grid, load_sweep_file

RAW_FIELDS = list(bt.RawTrade.__dataclass_fields__)
JOINT_AXES = {"orb": (("stop_mode", "atr_mult"),)}  # families not listed have independent axes

# Pass criteria, fixed in docs/m4-protocol.md before any sweep was run.
MIN_OOS_TRADES = 300
MIN_DSR = 0.95
MIN_POSITIVE_YEARS_SHARE = 2 / 3
MIN_NEIGHBOR_SHARE = 0.7


class Data:
    def __init__(self, symbols: list[str], start: date, end: date, bar_timeframe: str = "1Min"):
        lo, hi = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end + timedelta(days=1), tz="UTC")
        self.frames, self.prepared, self.daily = {}, {}, {}
        self.engine = swing if bar_timeframe == "1Day" else bt  # both expose simulate_signals(signals, prepared, cost, risk)
        for sym in symbols:
            # 5-minute bars are stored directly for the wide universe, or resampled from 1-minute bars
            bars = load_bars(sym, "sip", bar_timeframe, lo, hi, rth=True, resample="5min" if bar_timeframe == "1Min" else None)
            self.frames[sym] = bars
            factor = split_factor(bars.index, load_splits(sym))
            self.prepared[sym] = (swing.PreparedDaily.from_frame(bars, factor) if bar_timeframe == "1Day"
                                  else bt.PreparedBars.from_frame(bars, 5, factor))
            self.daily[sym] = load_bars(sym, "sip", "1Day")
        self.spy_daily = load_bars("SPY", "sip", "1Day")
        days = sorted({int(d) for pb in self.prepared.values() for d in np.unique(pb.day)})
        self.sessions = [pd.Timestamp(year=d // 10_000, month=d // 100 % 100, day=d % 100) for d in days]


def coverage_problems(symbols: list[str], start: date, end: date, timeframe: str = "1Min") -> list[str]:
    problems = []
    for sym in symbols:
        years = set(store.stored_years("sip", timeframe, sym))
        last = store.last_ts("sip", timeframe, sym)
        if not set(range(start.year, end.year + 1)) <= years:
            problems.append(f"{sym}: sip/{timeframe} missing years {sorted(set(range(start.year, end.year + 1)) - years)}")
        elif last is None or last.date() < end - timedelta(days=10):
            problems.append(f"{sym}: sip/{timeframe} ends {last}")
    return problems


def simulate_config(strategy, data: Data, cost: bt.CostModel, risk: bt.RiskConfig):
    signals = []
    for sym, bars in data.frames.items():
        signals += strategy.generate(sym, bars, data.daily[sym], data.spy_daily)
    raw, rejects = data.engine.simulate_signals(signals, data.prepared, cost, risk)
    return signals, raw, rejects


def raw_frame(raw: list[bt.RawTrade]) -> pd.DataFrame:
    return wf.with_year(pd.DataFrame([asdict(t) for t in raw], columns=RAW_FIELDS))


def to_raw_trades(df: pd.DataFrame) -> list[bt.RawTrade]:
    return [bt.RawTrade(**{k: row[k] for k in RAW_FIELDS}) for row in df.to_dict("records")]


def fmt(x, spec=".3f"):
    return "-" if x is None or (isinstance(x, float) and not math.isfinite(x)) else format(x, spec)


def run_family(family: str, cfg: dict, data: Data, cost: bt.CostModel, risk: bt.RiskConfig, name: str, log: bool):
    cls = REGISTRY[family]
    grid = cfg[family]["grid"]
    configs = expand_grid(cls, grid)
    ids = [f"{family}-{i:03d}" for i in range(len(configs))]
    already = trials.logged_params(name) if log else set()
    raws, signals, params_by_id = {}, {}, dict(zip(ids, configs, strict=True))
    for n, (cid, overrides) in enumerate(params_by_id.items(), 1):
        t0 = time.monotonic()
        strategy = cls(**overrides)
        sigs, raw, rejects = simulate_config(strategy, data, cost, risk)
        df = raw_frame(raw)
        raws[cid], signals[cid] = df, sigs
        if log and (family, json.dumps(strategy.params_dict(), sort_keys=True)) not in already:
            trials.log_trial(
                family, strategy.params_dict(),
                {"sweep": name, "config_id": cid, "period": [cfg["period_start"], cfg["period_end"]], "symbols": sorted(data.frames),
                 "slippage": cost.slippage, "rejects": dict(rejects)},
                metrics.to_jsonable({"strategy": metrics.r_stats(df["pnl_R"]) if len(df) else {"n": 0}}), group=name,
            )
        print(f"  [{n}/{len(configs)}] {cid} {time.monotonic() - t0:.1f}s", file=sys.stderr)
    return configs, ids, params_by_id, raws, signals


def sessions_in(data: Data, years: list[int]) -> list[pd.Timestamp]:
    return [s for s in data.sessions if s.year in years]


def analyse_family(family, cfg, data, cost, risk, name, raws, signals, params_by_id, all_family_raws, n_planned_extra=0):
    test_years = cfg["test_years"]
    rr = REGISTRY[family]().params.rr
    folds = wf.walk_forward(raws, test_years, cfg["min_train_trades"])
    oos = wf.stitch(raws, folds)
    out = {"family": family, "folds": [asdict(f) for f in folds]}
    if oos.empty:
        out["verdict"] = "no configuration met the minimum trade count in any fold"
        return out
    oos_sessions = sessions_in(data, test_years)

    # portfolio view of the stitched out-of-sample record
    trades, rej = bt.apply_portfolio(to_raw_trades(oos), risk)
    res = bt.BacktestResult(oos, trades, dict(rej), oos_sessions, risk, cost)
    out["summary"] = metrics.summarize(res, rr=rr)
    st = out["summary"]["strategy"]

    # deflated Sharpe: sizing-free daily R stream vs the best-of-N luckless trials
    series = stats.daily_r_series(oos, oos_sessions)
    cross = [stats.daily_r_series(df[df["year"].isin(test_years)], oos_sessions) for df in all_family_raws]
    n_trials = trials.count_trials() + n_planned_extra  # registry total + the regime checks still to be logged
    out["dsr"] = stats.deflated_sharpe(series, n_trials, stats.across_trials_sharpe_variance(cross))

    # 2x slippage: re-simulate only the configurations that were ever chosen
    stress_cost = bt.CostModel(slippage=cfg["stress_slippage"])
    stress_parts = []
    for cid in sorted({f.config_id for f in folds if f.config_id}):
        sraw, _ = data.engine.simulate_signals(signals[cid], data.prepared, stress_cost, risk)
        sdf = raw_frame(sraw)
        years = [f.test_year for f in folds if f.config_id == cid]
        stress_parts.append(sdf[sdf["year"].isin(years)])
    stress = pd.concat(stress_parts)
    out["stress"] = metrics.r_stats(stress["pnl_R"])

    diag = wf.grid_diagnostics(raws, test_years)
    modal = pd.Series([f.config_id for f in folds if f.config_id]).mode().iloc[-1]
    keys = list(cfg[family]["grid"])
    out["modal_config"] = {"id": modal, "params": params_by_id[modal]}
    out["stability"] = wf.neighbor_stability(modal, params_by_id, keys, diag, JOINT_AXES.get(family, ()))
    out["grid"] = {
        "configs": len(diag),
        "share_positive_oos": float((diag["oos_expectancy_R"] > 0).mean()),
        "median_oos_expectancy_R": float(diag["oos_expectancy_R"].median()),
        "best_oos_expectancy_R": float(diag["oos_expectancy_R"].max()),
    }
    out["diag"] = diag.join(pd.DataFrame(params_by_id).T)

    pos_years = sum(1 for y in out["summary"]["by_year"] if y["expectancy_R"] > 0)
    out["checks"] = {
        f"OOS trades >= {MIN_OOS_TRADES}": st["n"] >= MIN_OOS_TRADES,
        "OOS expectancy 95% CI lower bound > 0": st["expectancy_R"] - st["expectancy_ci95_R"] > 0,
        f"Deflated Sharpe >= {MIN_DSR}": bool(out["dsr"]["dsr"] >= MIN_DSR),
        f"positive in >= {MIN_POSITIVE_YEARS_SHARE:.0%} of test years": pos_years >= MIN_POSITIVE_YEARS_SHARE * len(test_years),
        "expectancy > 0 at 2x slippage": out["stress"]["expectancy_R"] > 0,
        f">= {MIN_NEIGHBOR_SHARE:.0%} of modal config's neighbours positive OOS": out["stability"]["share_positive"] >= MIN_NEIGHBOR_SHARE,
    }
    out["passed"] = all(out["checks"].values())
    out["oos_trades"] = oos
    return out


def regime_check(family, cfg, data, cost, risk, name, modal_params, log):
    """Registered extra trial: the modal configuration with the SPY 200-day trend filter on."""
    cls = REGISTRY[family]
    base = cls(**modal_params)
    with_spy = cls(**{**modal_params, "trend_filter": "spy_sma"})
    years = cfg["test_years"]
    result = {}
    for label, strat in (("base", base), ("spy_sma", with_spy)):
        _, raw, rejects = simulate_config(strat, data, cost, risk)
        df = raw_frame(raw)
        if label == "spy_sma" and log and (family, json.dumps(strat.params_dict(), sort_keys=True)) not in trials.logged_params(name):
            trials.log_trial(family, strat.params_dict(), {"sweep": name, "role": "regime_check", "rejects": dict(rejects)},
                             metrics.to_jsonable({"strategy": metrics.r_stats(df["pnl_R"])}), group=name)
        result[label] = metrics.r_stats(df.loc[df["year"].isin(years), "pnl_R"])
    return result


def format_family(o: dict, cfg: dict) -> str:
    fam = o["family"].upper()
    lines = [f"\n{'=' * 78}\n{fam}: walk-forward over {cfg['test_years']}\n{'=' * 78}", "Fold  chosen        train-score  train-n  OOS-n  OOS-expR"]
    for f in o["folds"]:
        lines.append(f"{f['test_year']}  {f['config_id'] or '-':<12} {fmt(f['train_score']):>11} {f['train_n']:>8} {f['oos_n']:>6} {fmt(f['oos_expectancy_R'], '+.3f'):>9}")
    if "summary" not in o:
        return "\n".join(lines + [o["verdict"]])
    s = o["summary"]
    lines += ["", "Stitched out-of-sample record", metrics.format_report(s)]
    d, g = o["dsr"], o["grid"]
    lines += [
        "",
        f"Deflated Sharpe (daily R stream): SR/day {fmt(d['sharpe_per_period'], '.4f')} (annualised {fmt(d['sharpe_annualised'], '.2f')}), "
        f"{d['n_trials']} trials logged, benchmark SR/day {fmt(d['benchmark_sharpe'], '.4f')}",
        f"  P(Sharpe > 0) = {fmt(d['psr_vs_zero'], '.3f')}    DSR = {fmt(d['dsr'], '.3f')}",
        f"2x slippage (${cfg['stress_slippage']:.3f}): expectancy {fmt(o['stress']['expectancy_R'], '+.3f')}R over {o['stress']['n']} trades",
        f"Whole grid, out-of-sample: {g['configs']} configs, {100 * g['share_positive_oos']:.0f}% positive, "
        f"median {fmt(g['median_oos_expectancy_R'], '+.3f')}R, best {fmt(g['best_oos_expectancy_R'], '+.3f')}R",
        f"Modal choice {o['modal_config']['id']}: {o['modal_config']['params']}",
        f"  neighbours: {o['stability']['n_neighbors']}, share positive OOS: {fmt(o['stability']['share_positive'], '.2f')}",
        "", "Pre-registered checks:",
    ]
    lines += [f"  [{'PASS' if ok else 'FAIL'}] {name}" for name, ok in o["checks"].items()]
    lines.append(f"  => {'ALL PASS: eligible for the one-shot holdout run' if o['passed'] else 'NOT eligible: do not trade this'}")
    if "regime" in o:
        r = o["regime"]
        lines += ["", "Regime check (informational, modal config, test years):"] + [
            f"  {k:<8} n={v['n']:<6} expectancy {fmt(v.get('expectancy_R'), '+.3f')}R +-{fmt(v.get('expectancy_ci95_R'))}" for k, v in r.items()
        ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(config.ROOT / "config" / "sweeps" / "m4.toml"))
    ap.add_argument("--family", default="all", choices=["all", *sorted(REGISTRY)])
    ap.add_argument("--symbols")
    ap.add_argument("--allow-partial", action="store_true", help="skip symbols whose history is incomplete (dev only)")
    ap.add_argument("--time-only", action="store_true", help="time 3 configs per family; log and show nothing else")
    ap.add_argument("--no-regime-check", action="store_true")
    args = ap.parse_args()

    cfg = load_sweep_file(args.config)
    start, end = date.fromisoformat(cfg["period_start"]), date.fromisoformat(cfg["period_end"])
    if end >= config.HOLDOUT_START:
        print(f"period_end {end} reaches the holdout ({config.HOLDOUT_START}); refusing.", file=sys.stderr)
        return 2
    timeframe = cfg.get("bar_timeframe", "1Min")
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    elif cfg.get("universe", "traded") == "wide":
        symbols = config.wide_symbols()
    else:
        symbols = config.load_universe()["universe"]["traded"]
    problems = coverage_problems(symbols, start, end, timeframe) + coverage_problems(["SPY"], start, end, "1Day")
    if problems and not args.allow_partial:
        print("Incomplete data; finish the backfill first (or --allow-partial for a dev run):\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    bad = {p.split(":")[0] for p in problems}
    symbols = [s for s in symbols if s not in bad]
    if "SPY" in bad and not args.time_only:
        print("SPY history is incomplete, so the regime filter cannot be evaluated.", file=sys.stderr)
        return 1
    families = sorted(REGISTRY) if args.family == "all" else [args.family]
    families = [f for f in families if f in cfg]

    print(f"Loading {len(symbols)} symbols...", file=sys.stderr)
    data = Data(symbols, start, end, timeframe)
    cost = bt.CostModel(slippage=cfg["slippage"])
    risk = bt.RiskConfig(max_positions=cfg.get("max_positions", 5))
    regime_on = cfg.get("regime_check", True) and not args.no_regime_check

    if args.time_only:
        for family in families:
            configs = expand_grid(REGISTRY[family], cfg[family]["grid"])
            t0 = time.monotonic()
            for overrides in configs[:3]:
                simulate_config(REGISTRY[family](**overrides), data, cost, risk)
            per = (time.monotonic() - t0) / 3
            print(f"{family}: {per:.1f}s per config, {len(configs)} configs -> about {per * len(configs) / 60:.1f} min")
        return 0

    name = cfg["name"]
    if problems:
        name += "-partial"
        print(f"WARNING: partial dev run, trials grouped as '{name}'. Do not read this as the M4 result.", file=sys.stderr)
    out_dir = config.DATA_DIR / "sweeps" / name
    out_dir.mkdir(parents=True, exist_ok=True)

    ran = {}
    for family in families:
        print(f"\n{family}: simulating grid", file=sys.stderr)
        ran[family] = run_family(family, cfg, data, cost, risk, name, log=True)
    all_raws = [df for fam in ran.values() for df in fam[3].values()]

    report, summary = [], {"name": name, "symbols": symbols, "families": {}}
    for family in families:
        configs, ids, params_by_id, raws, signals = ran[family]
        o = analyse_family(family, cfg, data, cost, risk, name, raws, signals, params_by_id, all_raws,
                           n_planned_extra=len(families) if regime_on else 0)
        if "summary" in o and regime_on:
            o["regime"] = regime_check(family, cfg, data, cost, risk, name, o["modal_config"]["params"], log=True)
        report.append(format_family(o, cfg))
        if "oos_trades" in o:
            o.pop("oos_trades").to_parquet(out_dir / f"oos_trades_{family}.parquet", index=False)
            o.pop("diag").to_csv(out_dir / f"configs_{family}.csv")
        summary["families"][family] = metrics.to_jsonable({k: v for k, v in o.items()})
    text = "\n".join(report)
    print(text)
    (out_dir / "report.txt").write_text(text)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nTrials in registry: {trials.count_trials()} total, {trials.count_trials(group=name)} in '{name}'. Saved to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
