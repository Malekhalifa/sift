import numpy as np
import pandas as pd

from tp import high52


def _panel(n_days=420, n_sym=10, seed=0):
    idx = pd.bdate_range("2016-01-04", periods=n_days)
    rng = np.random.default_rng(seed)
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n_days, n_sym)), axis=0)), index=idx, columns=[f"S{i}" for i in range(n_sym)])
    return close.shift(1).fillna(close.iloc[0]), close  # open = previous close


def test_nearness_is_one_at_a_new_high_and_needs_full_window():
    _, close = _panel()
    near = high52.nearness(close)
    assert near.iloc[: high52.WINDOW - 1].isna().all().all()
    assert ((near.dropna() <= 1 + 1e-12).all()).all()


def test_selection_uses_only_data_before_the_trade_open():
    open_, close = _panel()
    mkt = open_.iloc[:, 0]
    first = open_.index[high52.WINDOW + 30].strftime("%Y-%m-%d")
    base = high52.monthly_spread(open_, close, mkt, first)
    row_date = base.index[0]
    pos = open_.index.get_loc(row_date)
    close2, open2 = close.copy(), open_.copy()
    close2.iloc[pos:] *= 5.0  # change prices from the trade day on: the choice of names must not move
    open2.iloc[pos:] *= 5.0
    again = high52.monthly_spread(open2, close2, mkt, first)
    assert again.index[0] == row_date
    assert again["long_names"].iloc[0] == base["long_names"].iloc[0] and again["short_names"].iloc[0] == base["short_names"].iloc[0]


def test_top_names_are_the_nearest_to_their_high():
    open_, close = _panel()
    out = high52.monthly_spread(open_, close, open_.iloc[:, 0], open_.index[high52.WINDOW + 30].strftime("%Y-%m-%d"))
    row = out.iloc[0]
    near = high52.nearness(close).iloc[open_.index.get_loc(out.index[0]) - 1]
    assert min(near[row["long_names"].split(",")]) >= max(near[row["short_names"].split(",")])


def test_first_month_turnover_is_two_and_cost_follows():
    open_, close = _panel()
    out = high52.monthly_spread(open_, close, open_.iloc[:, 0], open_.index[high52.WINDOW + 5].strftime("%Y-%m-%d"))
    assert out["turnover"].iloc[0] == 2.0
    assert np.isclose(out["cost"].iloc[0], 2.0 * high52.COST_PER_SIDE)
    assert np.allclose(out["net"], out["gross"] - out["cost"])
