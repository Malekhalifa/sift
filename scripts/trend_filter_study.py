"""M13 (docs/m13-trend-filter-protocol.md): hold an index while its close is above the 200-session average, else cash.

    uv run python scripts/trend_filter_study.py

One fixed rule, no tuning. Reads daily bars only up to 2024-12-31 (the 2025+ holdout stays untouched).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tp import config, features
from tp.bars import load_bars

SMA_N = 200
SWITCH_COST = 0.0001  # 1 bp per switch
START, END = "2017-01-03", "2024-12-31"
MIN_DD_GAIN, MAX_CAGR_GAP, MIN_EPISODE_GAIN = 0.10, 0.02, 0.05


def max_drawdown(returns: pd.Series) -> float:
    equity = (1 + returns).cumprod()
    return float((equity / equity.cummax() - 1).min())


def study(symbol: str) -> dict:
    hi = pd.Timestamp(config.HOLDOUT_START, tz="UTC")
    bars = load_bars(symbol, "sip", "1Day", None, hi)
    bars.index = features.session_dates(bars.index)
    close, open_ = bars["close"], bars["open"]
    held = (close > close.rolling(SMA_N).mean()).astype(float).where(close.rolling(SMA_N).count() == SMA_N)  # decided at the close
    day_ret = open_.shift(-1) / open_ - 1  # from this open to the next open
    position = held.shift(1)  # the decision from the previous close applies to this day's open
    switches = position.diff().abs().fillna(0)
    rule = position * day_ret - switches * SWITCH_COST
    frame = pd.DataFrame({"hold": day_ret, "rule": rule, "position": position}).loc[START:END].dropna()
    out = {"frame": frame, "symbol": symbol}
    for col in ("hold", "rule"):
        r = frame[col]
        years = len(r) / 252
        out[col] = {
            "total": float((1 + r).prod() - 1), "cagr": float((1 + r).prod() ** (1 / years) - 1), "vol": float(r.std() * np.sqrt(252)),
            "sharpe": float(r.mean() / r.std() * np.sqrt(252)), "max_dd": max_drawdown(r),
            "by_year": {int(y): float((1 + g).prod() - 1) for y, g in r.groupby(r.index.year)},
        }
    out["invested"] = float(frame["position"].mean())
    # switches and how many of the round trips (in then out) lost money
    pos, trades = frame["position"], []
    before = (1 + frame["rule"]).cumprod().shift(1).fillna(1.0)  # equity before each day's return
    entry_equity = 1.0 if pos.iloc[0] == 1 else None
    for day, change in pos.diff().fillna(0).items():
        if change > 0:
            entry_equity = before[day]
        elif change < 0 and entry_equity is not None:  # out at this open: the last held day's equity is `before` today
            trades.append(before[day] / entry_equity - 1)
            entry_equity = None
    out["round_trips"], out["losing_round_trips"] = len(trades), sum(t < 0 for t in trades)
    out["episode"] = {y: {k: max_drawdown(frame.loc[str(y), k]) for k in ("hold", "rule")} for y in (2020, 2022)}
    return out


def show(o: dict, judged: bool) -> None:
    h, r = o["hold"], o["rule"]
    print(f"\n{'=' * 70}\n{o['symbol']}: 200-session trend filter vs buy-and-hold, {START} to {END}\n{'=' * 70}")
    print(f"{'':<22}{'buy and hold':>14}{'trend filter':>14}")
    for label, key, fmt in (("total return", "total", "{:+.1%}"), ("CAGR", "cagr", "{:+.2%}"), ("volatility", "vol", "{:.1%}"),
                            ("Sharpe (rf 0)", "sharpe", "{:.2f}"), ("max drawdown", "max_dd", "{:.1%}")):
        print(f"{label:<22}{fmt.format(h[key]):>14}{fmt.format(r[key]):>14}")
    print(f"days invested {o['invested']:.0%}; round trips {o['round_trips']}, of which {o['losing_round_trips']} lost money")
    print("by year  " + "  ".join(f"{y}: {h['by_year'][y]:+.0%}/{r['by_year'][y]:+.0%}" for y in sorted(h["by_year"])), "(hold/filter)")
    print("drawdown inside year: " + "; ".join(f"{y}: hold {e['hold']:.1%}, filter {e['rule']:.1%}" for y, e in o["episode"].items()))
    if judged:
        gain = r["max_dd"] - h["max_dd"]
        gap = h["cagr"] - r["cagr"]
        checks = {
            f"max drawdown >= {MIN_DD_GAIN:.0%} shallower (gain {gain:+.1%})": gain >= MIN_DD_GAIN,
            f"CAGR no more than {MAX_CAGR_GAP:.0%} below (gap {gap:+.2%})": gap <= MAX_CAGR_GAP,
            f"2020 and 2022 each >= {MIN_EPISODE_GAIN:.0%} shallower ("
            + ", ".join(f"{y}: {e['rule'] - e['hold']:+.1%}" for y, e in o["episode"].items()) + ")":
                all(e["rule"] - e["hold"] >= MIN_EPISODE_GAIN for e in o["episode"].values()),
        }
        for label, ok in checks.items():
            print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        print(f"  => {'PASSES the protocol' if all(checks.values()) else 'does not pass'}")


if __name__ == "__main__":
    show(study("SPY"), judged=True)
    show(study("QQQ"), judged=False)
