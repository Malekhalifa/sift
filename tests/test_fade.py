import pandas as pd
import pytest

from conftest import et, sess
from tp.strategies import FailedBreakoutFade

D = "2024-03-05"
OR_BAR = (100.0, 101.0, 99.0, 100.5)  # range 99-101
INSIDE = (100.5, 100.9, 99.2, 100.4)


def gen(rows, daily=None, **params):
    params.setdefault("max_risk_atr", 0.0)
    return FailedBreakoutFade(**params).generate("AAA", sess(rows), daily)


def test_failed_breakout_up_is_a_short_with_stop_at_the_excursion_high():
    rows = [OR_BAR, (100.5, 102.0, 100.4, 101.5), (101.4, 101.2, 100.2, 100.5)]  # closes out, then back in
    sigs = gen(rows)
    assert len(sigs) == 1
    s = sigs[0]
    assert s.side == "short" and s.ts == et(D, "09:45") and s.entry_ref == 100.5
    assert s.stop == 102.0 and s.target == pytest.approx(100.5 - 1.5 * 1.5)


def test_failed_breakout_down_is_a_long_with_stop_at_the_excursion_low():
    rows = [OR_BAR, (100.0, 100.1, 98.0, 98.5), (98.6, 100.0, 98.4, 99.5)]
    s = gen(rows)[0]
    assert s.side == "long" and s.entry_ref == 99.5 and s.stop == 98.0
    assert s.target == pytest.approx(99.5 + 1.5 * 1.5)


def test_stop_includes_the_reentry_bars_own_wick():
    rows = [OR_BAR, (100.5, 101.5, 100.4, 101.2), (101.2, 103.0, 100.0, 100.8)]  # re-entry bar wicks to 103
    assert gen(rows)[0].stop == 103.0


def test_longer_excursion_tracks_the_extreme():
    rows = [OR_BAR, (100.5, 102.0, 100.4, 101.5), (101.5, 104.0, 101.4, 103.0), (103.0, 103.1, 100.5, 100.8)]
    s = gen(rows)[0]
    assert s.stop == 104.0 and s.ts == et(D, "09:50")


def test_no_reentry_no_signal():
    assert gen([OR_BAR, (100.5, 102.0, 100.4, 101.5), (101.5, 103.0, 101.4, 102.5)]) == []


def test_wick_outside_without_a_close_outside_is_not_an_excursion():
    assert gen([OR_BAR, (100.5, 103.0, 100.4, 100.8), (100.8, 100.9, 99.5, 100.0)]) == []


def test_straight_through_the_range_is_a_breakdown_not_a_failed_move():
    rows = [OR_BAR, (100.5, 102.0, 100.4, 101.5), (101.5, 101.6, 98.0, 98.5)]
    assert gen(rows) == []  # closed above, then below: no close back inside yet
    rows.append((98.5, 100.0, 98.4, 99.8))  # now back inside after the downside excursion
    sigs = gen(rows)
    assert len(sigs) == 1 and sigs[0].side == "long" and sigs[0].stop == 98.0


def test_max_per_day():
    cycle = [(100.5, 102.0, 100.4, 101.5), (101.4, 101.2, 100.2, 100.5)]
    rows = [OR_BAR] + cycle + cycle
    assert len(gen(rows, max_per_day=1)) == 1
    assert len(gen(rows, max_per_day=2)) == 2


def test_sides_and_cutoff():
    rows = [OR_BAR, (100.5, 102.0, 100.4, 101.5), (101.4, 101.2, 100.2, 100.5)]
    assert gen(rows, sides="long") == [] and len(gen(rows, sides="short")) == 1
    late = [OR_BAR] + [INSIDE] * 24 + [(100.5, 102.0, 100.4, 101.5), (101.4, 101.2, 100.2, 100.5)]
    assert gen(late) == []  # re-entry closes after 11:30
    assert len(gen(late, last_entry="13:00")) == 1


def test_atr_cap_skips_wide_excursions():
    days = pd.bdate_range("2024-02-01", D, tz="America/New_York")
    daily = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1, "trade_count": 1, "vwap": 100.0},
        index=days.tz_convert("UTC"),
    )  # ATR = 2.0
    rows = [OR_BAR, (100.5, 102.0, 100.4, 101.5), (101.4, 101.2, 100.2, 100.5)]  # risk = 1.5
    assert len(gen(rows, daily, max_risk_atr=1.0)) == 1  # 1.5 <= 1.0 x 2.0
    assert gen(rows, daily, max_risk_atr=0.5) == []  # 1.5 > 0.5 x 2.0
    assert gen(rows, None, max_risk_atr=0.5) == []  # unknown ATR with a cap on: skip, never guess


def test_skips_tiny_risk():
    rows = [(100.0, 100.04, 99.99, 100.0), (100.0, 100.06, 100.0, 100.05), (100.05, 100.05, 100.0, 100.03)]
    assert gen(rows) == []
    assert len(gen(rows, min_risk_pct=0.0001)) == 1


def test_signals_never_depend_on_later_bars():
    base = [OR_BAR, (100.5, 102.0, 100.4, 101.5), (101.4, 101.2, 100.2, 100.5)]
    calm = gen(base + [(100.5, 100.6, 100.4, 100.5)] * 4)
    wild = gen(base + [(100.5, 900.0, 1.0, 5.0)] * 4)
    key = lambda ss: [(s.ts, s.side, s.entry_ref, s.stop, s.target) for s in ss]  # noqa: E731
    assert key(calm) == key(wild)
