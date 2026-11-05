import numpy as np
import pandas as pd
import pytest

from conftest import dbars, et
from tp import backtest as bt
from tp import features, swing
from tp.strategies import MAPullback, RSI2Reversion

ZERO = bt.CostModel(slippage=0.0, limit_trade_through=0.0, sell_fee_bps=0.0)
SIG_DAY = (100.0, 101.0, 99.0, 100.0)  # Monday 2024-03-04: the session whose close creates the signal


def long_sig(entry=100.0, stop=99.0, rr=1.5, hold=10, day="2024-03-04", symbol="AAA"):
    return bt.Signal.bracket(symbol, et(day, "16:00"), "long", entry, stop, rr, hold_days=hold)


def short_sig(entry=100.0, stop=101.0, rr=1.5, hold=10, day="2024-03-04"):
    return bt.Signal.bracket("AAA", et(day, "16:00"), "short", entry, stop, rr, hold_days=hold)


def run(sig, rows, cost=ZERO, split=None):
    return swing.simulate_trade(sig, swing.PreparedDaily.from_frame(dbars(rows), split), cost)


def test_session_times_are_correct_across_daylight_saving():
    idx = dbars([SIG_DAY] * 6, start="2024-03-07").index  # Thu 7th, Fri 8th (EST), Mon 11th (EDT)...
    p = swing.PreparedDaily.from_frame(dbars([SIG_DAY] * 6, start="2024-03-07"))
    assert p.open_ts[1] == pd.Timestamp("2024-03-08 14:30", tz="UTC") and p.close_ts[1] == pd.Timestamp("2024-03-08 21:00", tz="UTC")
    assert p.open_ts[2] == pd.Timestamp("2024-03-11 13:30", tz="UTC") and p.close_ts[2] == pd.Timestamp("2024-03-11 20:00", tz="UTC")
    assert swing.decision_ts(idx)[1] == p.close_ts[1]


def test_entry_is_next_session_open_not_the_signal_close():
    rows = [SIG_DAY, (100.4, 100.8, 99.5, 100.2), (100.2, 101.6, 100.0, 101.5)]
    t = run(long_sig(), rows)
    assert t.entry_px == 100.4 and t.entry_ts == pd.Timestamp("2024-03-05 14:30", tz="UTC")  # Tuesday's open
    assert t.exit_reason == "target" and t.exit_px == 101.5 and t.exit_ts == pd.Timestamp("2024-03-06 21:00", tz="UTC")
    assert t.pnl_R == pytest.approx((101.5 - 100.4) / 1.0)  # risk is measured from the SIGNAL close, entry gapped up


def test_friday_signal_enters_monday():
    sig = long_sig(day="2024-03-08")
    rows = dbars([(100, 101, 99, 100)] * 5, start="2024-03-04")  # Mon..Fri
    mon = dbars([(100.0, 100.5, 99.6, 100.1)], start="2024-03-11")
    pb = swing.PreparedDaily.from_frame(pd.concat([rows, mon]))
    t = swing.simulate_trade(sig, pb, ZERO)
    assert t.entry_ts == pd.Timestamp("2024-03-11 13:30", tz="UTC")


def test_stop_wins_when_a_session_touches_both():
    t = run(long_sig(), [SIG_DAY, (100.0, 101.6, 98.9, 100.5)])
    assert t.exit_reason == "stop" and t.pnl_R == pytest.approx(-1.0)


def test_entry_day_can_stop_out():
    t = run(long_sig(), [SIG_DAY, (100.0, 100.3, 98.8, 99.2)])
    assert t.exit_reason == "stop" and t.exit_ts == pd.Timestamp("2024-03-05 21:00", tz="UTC")


def test_overnight_gap_through_the_stop_fills_at_the_open():
    t = run(long_sig(), [SIG_DAY, (100.0, 100.5, 99.5, 100.2), (98.0, 98.5, 97.5, 98.2)])
    assert t.exit_reason == "stop_gap" and t.exit_px == 98.0 and t.pnl_R == pytest.approx(-2.0)
    assert t.exit_ts == pd.Timestamp("2024-03-06 14:30", tz="UTC")  # at the open, not the close


def test_overnight_gap_through_the_target_fills_at_the_open():
    t = run(long_sig(), [SIG_DAY, (100.0, 100.5, 99.5, 100.2), (102.0, 102.5, 101.9, 102.2)])
    assert t.exit_reason == "target_gap" and t.exit_px == 102.0 and t.pnl_R == pytest.approx(2.0)


def test_short_mirrors_long():
    t = run(short_sig(), [SIG_DAY, (100.0, 100.5, 98.4, 98.6)])
    assert t.exit_reason == "target" and t.exit_px == 98.5 and t.pnl_R == pytest.approx(1.5)
    t = run(short_sig(), [SIG_DAY, (100.0, 101.2, 99.5, 100.5)])
    assert t.exit_reason == "stop" and t.pnl_R == pytest.approx(-1.0)


def test_time_exit_is_market_on_close_of_the_last_session_of_the_hold():
    quiet = [(100.0, 100.4, 99.6, 100.1 + k * 0.1) for k in range(6)]
    t = run(long_sig(hold=3), [SIG_DAY, *quiet])
    # entry day is session 1; hold 3 means sessions 1, 2, 3 -> exit at the close of session 3
    assert t.exit_reason == "time" and t.exit_px == pytest.approx(100.3) and t.exit_ts == pd.Timestamp("2024-03-07 21:00", tz="UTC")
    t1 = run(long_sig(hold=1), [SIG_DAY, *quiet])
    assert t1.exit_reason == "time" and t1.exit_ts == pd.Timestamp("2024-03-05 21:00", tz="UTC")


def test_data_ending_before_the_hold_completes_is_flagged():
    t = run(long_sig(hold=10), [SIG_DAY, (100.0, 100.4, 99.6, 100.1), (100.1, 100.4, 99.6, 100.2)])
    assert t.exit_reason == "data_end"


def test_limit_target_needs_trade_through():
    cost = bt.CostModel(slippage=0.0, limit_trade_through=0.01, sell_fee_bps=0.0)
    assert run(long_sig(), [SIG_DAY, (100.0, 101.5, 99.6, 100.4)], cost=cost).exit_reason == "data_end"
    assert run(long_sig(), [SIG_DAY, (100.0, 101.51, 99.6, 100.4)], cost=cost).exit_reason == "target"


def test_costs_slippage_on_market_fills_not_on_targets_and_scales_with_splits():
    cost = bt.CostModel(slippage=0.01, limit_trade_through=0.0, sell_fee_bps=0.0)
    win = run(long_sig(), [SIG_DAY, (100.0, 101.6, 99.6, 101.5)], cost=cost)
    assert win.entry_px == pytest.approx(100.01) and win.pnl_R == pytest.approx(1.49)
    loss = run(long_sig(), [SIG_DAY, (100.0, 100.4, 98.9, 99.0)], cost=cost)
    assert loss.exit_px == pytest.approx(98.99) and loss.pnl_R == pytest.approx(-1.02)
    split = run(long_sig(), [SIG_DAY, (100.0, 101.6, 99.6, 101.5)], cost=cost, split=[4.0, 4.0])
    assert split.entry_px == pytest.approx(100.0025)  # a cent as traded is 0.25c on a share later split 4:1


def test_rejects():
    assert run(long_sig(), [SIG_DAY, (98.9, 99.5, 98.5, 99.0)]) == "fill_outside_bracket"
    assert run(long_sig(day="2024-03-05"), [SIG_DAY, (100.0, 100.4, 99.6, 100.1)]) == "no_entry_bar"  # nothing after the signal
    far = pd.concat([dbars([SIG_DAY]), dbars([(100.0, 100.4, 99.6, 100.1)], start="2024-03-18")])
    assert swing.simulate_trade(long_sig(), swing.PreparedDaily.from_frame(far), ZERO) == "stale_entry"


def test_one_open_trade_per_symbol_and_portfolio_sizing():
    rows = [SIG_DAY, (100.0, 100.4, 99.6, 100.1)] + [(100.1, 100.4, 99.6, 100.1)] * 6
    pb = {"AAA": swing.PreparedDaily.from_frame(dbars(rows))}
    sigs = [long_sig(hold=5), long_sig(hold=5, day="2024-03-06")]  # second arrives while the first is still open
    trades, rejects = swing.simulate_signals(sigs, pb, ZERO)
    assert len(trades) == 1 and rejects["symbol_busy"] == 1
    sized, _ = bt.apply_portfolio(trades, bt.RiskConfig(max_leverage=100))
    assert sized.iloc[0].qty == 1000 and sized.iloc[0].exit_ts > sized.iloc[0].entry_ts + pd.Timedelta(days=2)


# ---- indicators -------------------------------------------------------------------------------------------------
def test_rsi_bounds_direction_and_no_lookahead():
    up = pd.Series(np.arange(1.0, 30.0))
    down = pd.Series(np.arange(30.0, 1.0, -1.0))
    assert features.rsi(up, 2).iloc[-1] == 100.0 and features.rsi(down, 2).iloc[-1] == pytest.approx(0.0, abs=1e-6)
    shock = pd.Series([100, 101, 102, 103, 104, 90.0])
    assert features.rsi(shock, 2).iloc[-1] < 10 < features.rsi(shock, 2).iloc[-2]
    changed = shock.copy()
    changed.iloc[-1] = 500.0
    pd.testing.assert_series_equal(features.rsi(shock, 2).iloc[:-1], features.rsi(changed, 2).iloc[:-1])


def test_atr_through_is_the_unshifted_daily_atr():
    rng = np.arange(30) * 0.1 + 2.0
    d = dbars(list(zip([100.0] * 30, 100 + rng / 2, 100 - rng / 2, [100.0] * 30)))
    through = features.atr_through(d, 14)
    shifted = features.daily_atr(d, 14)
    assert through.iloc[13] == pytest.approx(rng[:14].mean())  # includes the current session
    np.testing.assert_allclose(through.shift(1).to_numpy()[14:], shifted.to_numpy()[14:])


# ---- strategies -------------------------------------------------------------------------------------------------
def closes_to_bars(closes):
    c = np.asarray(closes, dtype=float)
    return dbars(list(zip(c, c + 0.5, c - 0.5, c)))


def uptrend_with_shock(n=260, shock_to=None):
    base = list(100 + 0.4 * np.arange(n))
    base[-1] = shock_to if shock_to is not None else base[-1]
    return closes_to_bars(base)


def test_rsi2_long_after_a_sharp_drop_in_an_uptrend():
    bars = uptrend_with_shock(shock_to=100 + 0.4 * 258 - 7)  # still far above the 200-day average
    sigs = RSI2Reversion().generate("AAA", bars)
    assert len(sigs) == 1
    s = sigs[0]
    assert s.side == "long" and s.ts == swing.decision_ts(bars.index)[-1] and s.hold_days == 5
    assert s.stop < s.entry_ref < s.target and s.target - s.entry_ref == pytest.approx(1.5 * s.risk)


def test_rsi2_trend_filter_blocks_counter_trend_longs_but_not_without_it():
    down = closes_to_bars(list(200 - 0.4 * np.arange(260)))  # long downtrend, then a sharp drop below the 200-day
    down.iloc[-1, down.columns.get_loc("close")] -= 6
    assert RSI2Reversion(trend_filter="sma200", sides="long").generate("AAA", down) == []
    assert len(RSI2Reversion(trend_filter="none", sides="long").generate("AAA", down)) >= 1


def test_rsi2_short_after_a_sharp_spike_in_a_downtrend():
    c = list(200 - 0.4 * np.arange(260))
    c[-1] += 7
    sigs = RSI2Reversion(sides="short").generate("AAA", closes_to_bars(c))
    assert len(sigs) == 1 and sigs[0].side == "short" and sigs[0].target < sigs[0].entry_ref < sigs[0].stop


def test_rsi2_never_uses_later_bars():
    base = list(100 + 0.4 * np.arange(262))
    base[250] -= 7
    calm = RSI2Reversion().generate("AAA", closes_to_bars(base))
    wild = RSI2Reversion().generate("AAA", closes_to_bars(base[:255] + [1.0, 900.0, 3.0, 800.0, 2.0, 700.0, 4.0]))
    key = lambda ss: [(s.ts, s.side, s.entry_ref, s.stop) for s in ss if s.ts <= swing.decision_ts(closes_to_bars(base[:255]).index)[-1]]  # noqa: E731
    assert key(calm) == key(wild) and len(key(calm)) >= 1


def test_rsi2_param_validation_and_stop_guard():
    with pytest.raises(ValueError):
        RSI2Reversion(trend_filter="bogus")
    with pytest.raises(ValueError):
        RSI2Reversion(max_hold=0)
    assert RSI2Reversion(trend_filter="none", stop_atr=0.0).generate("AAA", uptrend_with_shock(shock_to=70.0)) == []  # zero-risk stop skipped


def test_pullback_fires_on_the_first_close_back_to_the_fast_average():
    base = list(100 + 0.5 * np.arange(300))
    base[250] -= 8  # closes below the 20-day average after a close above it
    bars = closes_to_bars(base)
    sigs = MAPullback().generate("AAA", bars)
    assert len(sigs) == 1 and sigs[0].side == "long" and sigs[0].ts == swing.decision_ts(bars.index)[250]
    assert sigs[0].hold_days == 10 and sigs[0].stop < sigs[0].entry_ref < sigs[0].target


def test_pullback_needs_a_trend_and_does_not_fire_every_day_below_the_average():
    flat = closes_to_bars([100 + (-1) ** k * 0.5 for k in range(300)])
    assert MAPullback().generate("AAA", flat) == []
    base = list(100 + 0.5 * np.arange(300))
    base[250] -= 8
    base[251] -= 8
    assert len(MAPullback().generate("AAA", closes_to_bars(base))) == 1  # day 2 is already below: not a fresh touch


def test_pullback_short_in_a_downtrend_and_sides_filter():
    base = list(300 - 0.5 * np.arange(300))
    base[250] += 8
    assert [s.side for s in MAPullback().generate("AAA", closes_to_bars(base))] == ["short"]
    assert MAPullback(sides="long").generate("AAA", closes_to_bars(base)) == []


def test_pullback_never_uses_later_bars():
    base = list(100 + 0.5 * np.arange(300))
    base[250] -= 8
    a = MAPullback().generate("AAA", closes_to_bars(base))
    b = MAPullback().generate("AAA", closes_to_bars(base[:260] + [5.0] * 40))
    cutoff = swing.decision_ts(closes_to_bars(base[:260]).index)[-1]  # the unchanged prefix ends here
    key = lambda ss: [(s.ts, s.side, s.entry_ref, s.stop) for s in ss if s.ts <= cutoff]  # noqa: E731
    assert key(a) == key(b) and len(key(a)) == 1
