import numpy as np
import pandas as pd
import pytest

from conftest import et, sess
from tp import features
from tp.strategies import OpeningRangeBreakout

D = "2024-03-05"
OR_BAR = (100.0, 101.0, 99.0, 100.5)  # opening range 99-101
INSIDE = (100.5, 100.9, 99.2, 100.4)


def gen(rows, daily=None, **params):
    return OpeningRangeBreakout(**params).generate("AAA", sess(rows), daily)


def test_long_breakout_on_close_above_range():
    sigs = gen([OR_BAR, INSIDE, (100.4, 102.0, 100.3, 101.5)])
    assert len(sigs) == 1
    s = sigs[0]
    assert s.side == "long" and s.ts == et(D, "09:45")  # decision at the close of the 09:40 bar
    assert s.entry_ref == 101.5 and s.stop == 99.0
    assert s.target == pytest.approx(101.5 + 1.5 * 2.5)


def test_short_breakout_on_close_below_range():
    sigs = gen([OR_BAR, INSIDE, (100.4, 100.5, 98.0, 98.5)])
    s = sigs[0]
    assert s.side == "short" and s.stop == 101.0 and s.target == pytest.approx(98.5 - 1.5 * 2.5)


def test_wick_beyond_range_is_not_a_breakout():
    assert gen([OR_BAR, (100.5, 103.0, 100.2, 100.8), (100.8, 101.0, 98.0, 100.0)]) == []


def test_only_first_breakout_each_day():
    sigs = gen([OR_BAR, (100.5, 102.0, 100.4, 101.5), (101.5, 103.0, 101.4, 102.5), (102.5, 104.0, 102.4, 103.5)])
    assert len(sigs) == 1 and sigs[0].ts == et(D, "09:40")


def test_sides_filter():
    rows = [OR_BAR, (100.4, 100.5, 98.0, 98.5)]
    assert gen(rows, sides="long") == []
    assert len(gen(rows, sides="short")) == 1


def test_last_entry_cutoff():
    rows = [OR_BAR] + [INSIDE] * 24 + [(100.4, 102.0, 100.3, 101.5)]  # breakout bar 11:30-11:35
    assert gen(rows) == []
    assert len(gen(rows, last_entry="12:00")) == 1


def test_longer_opening_range():
    rows = [(100.0, 100.8, 99.5, 100.4), (100.4, 101.0, 100.0, 100.6), (100.6, 100.9, 99.2, 100.5), (100.5, 102.0, 100.4, 101.8)]
    s = gen(rows, or_minutes=15)[0]
    assert s.stop == 99.2 and s.ts == et(D, "09:50") and s.entry_ref == 101.8


def test_skips_day_without_the_open_bar():
    df = sess([OR_BAR, INSIDE, (100.4, 102.0, 100.3, 101.5)], start="09:35")
    assert OpeningRangeBreakout().generate("AAA", df) == []


def test_skips_tiny_stop():
    rows = [(100.0, 100.04, 99.99, 100.0), (100.0, 100.1, 100.0, 100.06)]  # stop distance $0.07 = 0.07% of price
    assert gen(rows) == []
    assert len(gen(rows, min_risk_pct=0.0001)) == 1


def test_signal_never_depends_on_later_bars():
    base = [OR_BAR, INSIDE, (100.4, 102.0, 100.3, 101.5)]
    calm = gen(base + [(101.5, 102.0, 101.0, 101.5)] * 5)
    crash = gen(base + [(101.5, 101.6, 50.0, 55.0)] * 5)
    assert [(s.ts, s.side, s.entry_ref, s.stop, s.target) for s in calm] == [
        (s.ts, s.side, s.entry_ref, s.stop, s.target) for s in crash
    ]


def test_atr_stop_mode_uses_prior_days_only():
    days = pd.bdate_range("2024-02-01", D, tz="America/New_York")
    daily = pd.DataFrame(
        {"open": 100.0, "high": 102.0, "low": 98.0, "close": 100.0, "volume": 1, "trade_count": 1, "vwap": 100.0},
        index=days.tz_convert("UTC"),
    )
    sigs = OpeningRangeBreakout(stop_mode="atr", atr_mult=0.5).generate(
        "AAA", sess([OR_BAR, INSIDE, (100.4, 102.0, 100.3, 101.5)]), daily
    )
    assert sigs[0].stop == pytest.approx(101.5 - 0.5 * 4.0)  # ATR of constant 4.0 ranges
    assert OpeningRangeBreakout(stop_mode="atr").generate("AAA", sess([OR_BAR, INSIDE, (100.4, 102, 100.3, 101.5)]), None) == []


def test_daily_atr_has_no_lookahead():
    days = pd.bdate_range("2024-01-02", periods=30, tz="America/New_York")
    rng = np.arange(30) * 0.1 + 2.0
    daily = pd.DataFrame({"high": 100 + rng / 2, "low": 100 - rng / 2, "close": 100.0}, index=days.tz_convert("UTC"))
    atr = features.daily_atr(daily, n=14)
    d = pd.Timestamp(days[20].date())
    assert atr[d] == pytest.approx(rng[6:20].mean())  # the 14 sessions BEFORE day 20
    bumped = daily.copy()
    bumped.iloc[20, bumped.columns.get_loc("high")] = 500.0
    assert features.daily_atr(bumped, n=14)[d] == pytest.approx(atr[d])  # today's range cannot leak in
    assert np.isnan(atr.iloc[13])


def test_invalid_params_rejected():
    with pytest.raises(ValueError):
        OpeningRangeBreakout(or_minutes=7)
    with pytest.raises(ValueError):
        OpeningRangeBreakout(stop_mode="nope")
