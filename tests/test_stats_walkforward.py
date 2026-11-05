import math

import numpy as np
import pandas as pd
import pytest

from conftest import et
from tp import stats, sweeps, trials, walkforward as wf
from tp.strategies import FailedBreakoutFade, OpeningRangeBreakout


def test_expected_max_sharpe():
    assert stats.expected_max_sharpe(1, 1.0) == 0.0
    assert stats.expected_max_sharpe(100, 1.0) == pytest.approx(2.53, abs=0.02)
    assert stats.expected_max_sharpe(10, 1.0) < stats.expected_max_sharpe(100, 1.0) < stats.expected_max_sharpe(1000, 1.0)
    assert stats.expected_max_sharpe(100, 4.0) == pytest.approx(2 * stats.expected_max_sharpe(100, 1.0))


def test_probabilistic_sharpe():
    assert stats.probabilistic_sharpe(0.1, 0.1, 500, 0.0, 3.0) == pytest.approx(0.5)
    assert stats.probabilistic_sharpe(0.1, 0.0, 1000, 0.0, 3.0) > stats.probabilistic_sharpe(0.1, 0.0, 100, 0.0, 3.0)
    assert math.isnan(stats.probabilistic_sharpe(0.1, 0.0, 1, 0.0, 3.0))


def test_deflated_sharpe_penalises_many_trials_and_rewards_real_edge():
    rng = np.random.default_rng(1)
    noise = pd.Series(rng.normal(0.0, 1.0, 1500))
    edge = pd.Series(rng.normal(0.15, 1.0, 1500))
    few = stats.deflated_sharpe(edge, n_trials=5, sr_variance=0.0004)
    many = stats.deflated_sharpe(edge, n_trials=500, sr_variance=0.0004)
    assert few["dsr"] > many["dsr"]
    assert few["dsr"] > 0.95
    assert stats.deflated_sharpe(noise, n_trials=500, sr_variance=0.0004)["dsr"] < 0.95
    assert few["n_obs"] == 1500 and few["sharpe_annualised"] == pytest.approx(few["sharpe_per_period"] * math.sqrt(252))


def test_daily_r_series_sums_by_exit_day_and_fills_zeros():
    raw = pd.DataFrame({"exit_ts": [et("2024-03-05", "10:00"), et("2024-03-05", "11:00"), et("2024-03-07", "10:00")], "pnl_R": [1.5, -1.0, 0.5]})
    sessions = [pd.Timestamp(d) for d in ("2024-03-05", "2024-03-06", "2024-03-07")]
    s = stats.daily_r_series(raw, sessions)
    assert s.tolist() == [0.5, 0.0, 0.5]
    assert stats.daily_r_series(raw.iloc[0:0], sessions).eq(0).all()


def raws_for(spec):
    """spec: config id -> {year: list of R}. Builds the frames walk_forward expects."""
    out = {}
    for cid, years in spec.items():
        rows = [(et(f"{y}-06-03", "10:00"), r) for y, rs in years.items() for r in rs]
        out[cid] = wf.with_year(pd.DataFrame(rows, columns=["entry_ts", "pnl_R"]))
    return out


def test_walk_forward_selects_on_earlier_years_only():
    good_then_bad = {2019: [1.0, 1.0, -0.5] * 40, 2020: [-1.0] * 120}  # looks great until it fails in 2020
    steady = {2019: [0.2, -0.1] * 60, 2020: [0.2, -0.1] * 60}
    raws = raws_for({"a": good_then_bad, "b": steady})
    folds = wf.walk_forward(raws, [2020], min_trades=50)
    assert folds[0].config_id == "a"  # chosen on 2019 alone
    assert folds[0].oos_expectancy_R == pytest.approx(-1.0)  # and punished by 2020, which it never saw
    out = wf.stitch(raws, folds)
    assert set(out["config_id"]) == {"a"} and set(out["year"]) == {2020}


def test_score_penalises_small_samples():
    small = pd.Series([2.0] * 10)
    assert wf.score(small, min_trades=50) == -math.inf
    lucky = pd.Series([3.0, -1.0, 3.0, -1.0, 3.0] * 20)
    solid = pd.Series([0.4, 0.2] * 500)
    assert wf.score(solid, 50) > 0 and wf.score(lucky, 50) < lucky.mean()


def test_walk_forward_with_nothing_eligible():
    raws = raws_for({"a": {2019: [1.0] * 5}})
    folds = wf.walk_forward(raws, [2020], min_trades=50)
    assert folds[0].config_id is None and wf.stitch(raws, folds).empty


def test_grid_diagnostics_and_neighbors():
    raws = raws_for({"a": {2020: [1, 1, -1], 2021: [1, 1]}, "b": {2020: [-1, -1], 2021: [-1]}, "c": {2020: [1, -1], 2021: [1, -1]}})
    diag = wf.grid_diagnostics(raws, [2020, 2021])
    assert diag.loc["a", "positive_years"] == 2 and diag.loc["b", "positive_years"] == 0
    params = {"a": {"x": 1, "y": 1}, "b": {"x": 2, "y": 1}, "c": {"x": 1, "y": 2}, "d": {"x": 2, "y": 2}}
    assert sorted(wf.neighbors("a", params, ["x", "y"])) == ["b", "c"]  # d differs on both axes
    joint = {"a": {"mode": "m", "k": None}, "b": {"mode": "atr", "k": 0.1}, "c": {"mode": "atr", "k": 0.2}}
    assert sorted(wf.neighbors("a", joint, ["mode", "k"], (("mode", "k"),))) == ["b", "c"]
    stab = wf.neighbor_stability("a", params, ["x", "y"], diag.rename(index={"a": "a", "b": "b", "c": "c"}).reindex(["a", "b", "c", "d"]))
    assert stab["n_neighbors"] == 2


def test_coerce_booleans_and_numbers():
    assert sweeps.coerce(False, "true") is True and sweeps.coerce(True, "False") is False
    assert sweeps.coerce(5, "15") == 15 and sweeps.coerce(1.5, "2") == 2.0 and sweeps.coerce("a", "b") == "b"
    with pytest.raises(ValueError):
        sweeps.coerce(False, "maybe")


def test_parse_sets_rejects_unknown_keys():
    assert sweeps.parse_sets(["gap_align=true", "or_minutes=15"], OpeningRangeBreakout.params_cls) == {"gap_align": True, "or_minutes": 15}
    with pytest.raises(SystemExit):
        sweeps.parse_sets(["nope=1"], OpeningRangeBreakout.params_cls)


def test_expand_grid_dedupes_irrelevant_parameters():
    grid = {"or_minutes": [5, 15], "stop_mode": ["or_opposite", "atr"], "atr_mult": [0.1, 0.25]}
    configs = sweeps.expand_grid(OpeningRangeBreakout, grid)
    assert len(configs) == 2 * 3  # or_opposite ignores atr_mult: 1 + 2 stop choices per or_minutes
    assert sum(1 for c in configs if "atr_mult" not in c) == 2
    with pytest.raises(ValueError):
        sweeps.expand_grid(OpeningRangeBreakout, {"or_minutes": ["5"]})
    with pytest.raises(ValueError):
        sweeps.expand_grid(FailedBreakoutFade, {"nope": [1]})
    assert len(sweeps.expand_grid(FailedBreakoutFade, {"max_per_day": [1, 3], "rvol_min": [0.0, 1.5]})) == 4


def test_trial_groups_are_counted_separately():
    trials.log_trial("orb", {}, {}, {}, group="sweep-a")
    trials.log_trial("orb", {}, {}, {}, group="sweep-a")
    trials.log_trial("fade", {}, {}, {}, group="sweep-b")
    trials.log_trial("orb", {}, {}, {})
    assert trials.count_trials(group="sweep-a") == 2
    assert trials.count_trials("fade") == 1 and trials.count_trials("orb", "sweep-a") == 2
    assert trials.count_trials() == 4
