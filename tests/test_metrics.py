import math

import pandas as pd
import pytest

from conftest import sess
from tp import backtest as bt
from tp import metrics, trials

FLAT = (100.0, 100.2, 99.8, 100.0)
ZERO = bt.CostModel(slippage=0.0, limit_trade_through=0.0, sell_fee_bps=0.0)


def test_r_stats_known_values():
    s = metrics.r_stats(pd.Series([1.5, -1.0, -1.0, 1.5]))
    assert s["n"] == 4 and s["win_rate"] == 0.5
    assert s["expectancy_R"] == pytest.approx(0.25)
    assert s["profit_factor"] == pytest.approx(1.5)
    assert s["total_R"] == pytest.approx(1.0)
    assert s["avg_win_R"] == 1.5 and s["avg_loss_R"] == -1.0


def test_r_stats_edge_cases():
    assert metrics.r_stats(pd.Series([], dtype=float)) == {"n": 0}
    assert metrics.r_stats(pd.Series([1.0, 2.0]))["profit_factor"] == math.inf


def test_breakeven_win_rate():
    assert metrics.breakeven_win_rate(1.5) == pytest.approx(0.4)
    assert metrics.breakeven_win_rate(2.0) == pytest.approx(1 / 3)


def two_day_result():
    win = [FLAT, (100.0, 101.6, 99.6, 101.5)]
    loss = [FLAT, (100.0, 100.4, 98.9, 99.0)]
    frame = pd.concat([sess(win, day="2024-03-05"), sess(loss, day="2024-03-06")])
    pb = {"AAA": bt.PreparedBars.from_frame(frame)}
    sigs = [
        bt.Signal.bracket("AAA", pd.Timestamp(f"{d} 09:35", tz="America/New_York").tz_convert("UTC"), "long", 100.0, 99.0, 1.5)
        for d in ("2024-03-05", "2024-03-06")
    ]
    return bt.execute(sigs, pb, ZERO, bt.RiskConfig(max_leverage=100))


def test_summarize_end_to_end():
    res = two_day_result()
    s = metrics.summarize(res, rr=1.5)
    assert s["strategy"]["n"] == 2 and s["strategy"]["win_rate"] == 0.5
    pf = s["portfolio"]
    assert pf["n_taken"] == 2
    assert pf["net_pnl"] == pytest.approx(res.trades["pnl"].sum())
    assert pf["max_drawdown_pct"] < 0  # the second day lost money
    assert s["sessions"] == 2
    assert [y["year"] for y in s["by_year"]] == [2024]
    text = metrics.format_report(s)
    assert "Strategy quality" in text and "Portfolio" in text


def test_no_trades_report():
    pb = {"AAA": bt.PreparedBars.from_frame(sess([FLAT, FLAT]))}
    res = bt.execute([], pb, ZERO, bt.RiskConfig())
    assert metrics.format_report(metrics.summarize(res, rr=1.5)) == "No trades."


def test_to_jsonable_handles_nan_and_numpy():
    import json

    import numpy as np

    out = metrics.to_jsonable({"a": float("nan"), "b": np.float64(1.5), "c": np.int64(3), "d": [float("inf")]})
    assert json.loads(json.dumps(out)) == {"a": None, "b": 1.5, "c": 3, "d": [None]}


def test_trial_registry_counts():
    assert trials.count_trials() == 0
    a = trials.log_trial("orb", {"or_minutes": 5}, {"symbols": ["AAA"]}, {"n": 3})
    b = trials.log_trial("orb", {"or_minutes": 15}, {"symbols": ["AAA"]}, {"n": 4}, holdout=True)
    trials.log_trial("other", {}, {}, {})
    assert (a, b) == (1, 2)
    assert trials.count_trials("orb") == 2 and trials.count_trials() == 3
