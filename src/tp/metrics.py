"""Backtest statistics. Strategy quality is measured in R on every simulated trade; portfolio statistics
(returns, drawdown, Sharpe) use the trades that survived sizing and exposure caps."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from tp.backtest import BacktestResult
from tp.bars import ET


def r_stats(r: pd.Series) -> dict:
    n = len(r)
    if n == 0:
        return {"n": 0}
    wins, losses = r[r > 0], r[r <= 0]
    gross_loss = -float(losses.sum())
    sd = float(r.std(ddof=1)) if n > 1 else float("nan")
    return {
        "n": n,
        "win_rate": len(wins) / n,
        "avg_win_R": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss_R": float(losses.mean()) if len(losses) else 0.0,
        "expectancy_R": float(r.mean()),
        "expectancy_ci95_R": 1.96 * sd / math.sqrt(n) if n > 1 else float("nan"),
        "profit_factor": float(wins.sum()) / gross_loss if gross_loss > 0 else float("inf"),
        "total_R": float(r.sum()),
    }


def breakeven_win_rate(rr: float) -> float:
    return 1.0 / (1.0 + rr)


def _exit_day(ts: pd.Series) -> pd.Series:
    return ts.dt.tz_convert(ET).dt.tz_localize(None).dt.normalize()


def portfolio_stats(res: BacktestResult) -> dict:
    t, risk = res.trades, res.risk
    if t.empty:
        return {"n_taken": 0}
    daily_pnl = t.groupby(_exit_day(t["exit_ts"]))["pnl"].sum().reindex(res.sessions, fill_value=0.0)
    equity = risk.start_equity + daily_pnl.cumsum()
    prev = equity.shift(1).fillna(risk.start_equity)
    daily_ret = daily_pnl / prev
    curve = pd.concat([pd.Series([risk.start_equity]), equity.reset_index(drop=True)], ignore_index=True)
    drawdown = curve / curve.cummax() - 1
    sd = float(daily_ret.std(ddof=1))
    years = max(len(res.sessions) / 252, 1e-9)
    end_equity = float(equity.iloc[-1])
    return {
        "n_taken": len(t),
        "net_pnl": float(t["pnl"].sum()),
        "total_return_pct": 100 * (end_equity / risk.start_equity - 1),
        "cagr_pct": 100 * ((end_equity / risk.start_equity) ** (1 / years) - 1) if end_equity > 0 else -100.0,
        "max_drawdown_pct": 100 * float(drawdown.min()),  # end-of-day equity; intraday swings not captured
        "sharpe": float(daily_ret.mean()) / sd * math.sqrt(252) if sd > 0 else float("nan"),
        "pct_capped": 100 * float(t["capped"].mean()),
        "avg_qty": float(t["qty"].mean()),
    }


def summarize(res: BacktestResult, rr: float) -> dict:
    raw = res.raw
    out = {
        "sessions": len(res.sessions),
        "strategy": r_stats(raw["pnl_R"]) if len(raw) else {"n": 0},
        "breakeven_win_rate": breakeven_win_rate(rr),
        "portfolio": portfolio_stats(res),
        "rejects": res.rejects,
        "exit_reasons": raw["exit_reason"].value_counts().to_dict() if len(raw) else {},
        "by_side": {},
        "by_year": [],
    }
    if len(raw):
        for side, g in raw.groupby("side"):
            out["by_side"][side] = r_stats(g["pnl_R"])
        years = raw["entry_ts"].dt.tz_convert(ET).dt.year
        for year, g in raw.groupby(years):
            out["by_year"].append({"year": int(year), **r_stats(g["pnl_R"])})
    return out


def _fmt(x, spec=".2f"):
    return "-" if x is None or (isinstance(x, float) and not math.isfinite(x)) else format(x, spec)


def format_report(s: dict) -> str:
    st, pf = s["strategy"], s["portfolio"]
    if not st.get("n"):
        return "No trades."
    lines = [
        f"Sessions covered: {s['sessions']}    Simulated trades: {st['n']}    Taken after sizing/caps: {pf.get('n_taken', 0)}",
        "",
        "Strategy quality (R, every simulated trade, costs included)",
        f"  win rate        {100 * st['win_rate']:.1f}%   (breakeven at the target R:R: {100 * s['breakeven_win_rate']:.1f}%)",
        f"  avg win / loss  {st['avg_win_R']:+.2f}R / {st['avg_loss_R']:+.2f}R",
        f"  expectancy      {st['expectancy_R']:+.3f}R  ±{_fmt(st['expectancy_ci95_R'], '.3f')} (95% CI)",
        f"  profit factor   {_fmt(st['profit_factor'])}      total {st['total_R']:+.1f}R",
        "",
        "Portfolio (sized, compounding, exposure caps)",
        f"  net pnl         {pf['net_pnl']:+,.0f}   total return {pf['total_return_pct']:+.1f}%   CAGR {pf['cagr_pct']:+.1f}%",
        f"  max drawdown    {pf['max_drawdown_pct']:.1f}%   Sharpe {_fmt(pf['sharpe'])}",
        f"  sizing          avg qty {pf['avg_qty']:.0f}, capped by leverage on {pf['pct_capped']:.0f}% of trades",
        "",
        f"Exit reasons: {s['exit_reasons']}",
        f"Rejected:     {s['rejects']}",
    ]
    for side, x in s["by_side"].items():
        lines.append(f"  {side:<5} n={x['n']:<5} win {100 * x['win_rate']:.1f}%  exp {x['expectancy_R']:+.3f}R  PF {_fmt(x['profit_factor'])}")
    if s["by_year"]:
        lines += ["", "By year        n    win%    expR     PF"]
        lines += [
            f"  {y['year']}   {y['n']:>5}  {100 * y['win_rate']:5.1f}  {y['expectancy_R']:+.3f}  {_fmt(y['profit_factor'])}"
            for y in s["by_year"]
        ]
    return "\n".join(lines)


def to_jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        return None if not math.isfinite(float(obj)) else float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    return obj
