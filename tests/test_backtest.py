import pandas as pd
import pytest

from conftest import et, sess
from tp import backtest as bt

D = "2024-03-05"
ZERO = bt.CostModel(slippage=0.0, limit_trade_through=0.0, sell_fee_bps=0.0)
FLAT = (100.0, 100.2, 99.8, 100.0)


def long_sig(ts="09:35", symbol="AAA", entry_ref=100.0, stop=99.0, rr=1.5, day=D):
    return bt.Signal.bracket(symbol, et(day, ts), "long", entry_ref, stop, rr)


def short_sig(ts="09:35", symbol="AAA", entry_ref=100.0, stop=101.0, rr=1.5, day=D):
    return bt.Signal.bracket(symbol, et(day, ts), "short", entry_ref, stop, rr)


def run_one(sig, rows, cost=ZERO, risk=None, day=D):
    pb = bt.PreparedBars.from_frame(sess(rows, day=day))
    risk = risk or bt.RiskConfig()
    flat = risk.flat_time.hour * 60 + risk.flat_time.minute
    return bt.simulate_trade(sig, pb, cost, flat)


def test_signal_rejects_bracket_on_wrong_side():
    with pytest.raises(ValueError):
        bt.Signal("A", et(D, "09:35"), "long", 100.0, 101.0, 102.0)
    with pytest.raises(ValueError):
        bt.Signal("A", et(D, "09:35"), "short", 100.0, 99.0, 98.0)


def test_bracket_target_is_rr_times_risk():
    s = long_sig(entry_ref=100.0, stop=98.0, rr=1.5)
    assert s.target == 103.0 and s.risk == 2.0
    s = short_sig(entry_ref=100.0, stop=102.0, rr=1.5)
    assert s.target == 97.0


def test_long_hits_target_filled_at_next_open():
    rows = [FLAT, (100.0, 100.8, 99.5, 100.5), (100.5, 101.6, 100.2, 101.5)]
    t = run_one(long_sig(), rows)
    assert t.entry_ts == et(D, "09:35") and t.entry_px == 100.0  # next bar's open, not the signal close
    assert t.exit_reason == "target" and t.exit_px == 101.5
    assert t.pnl_R == pytest.approx(1.5)
    assert t.exit_ts == et(D, "09:45")  # end of the bar that hit it


def test_stop_wins_when_one_bar_touches_both():
    rows = [FLAT, (100.0, 101.6, 98.9, 100.5)]
    t = run_one(long_sig(), rows)
    assert t.exit_reason == "stop" and t.pnl_R == pytest.approx(-1.0)


def test_gap_through_stop_fills_at_the_open_not_the_stop():
    rows = [FLAT, (100.0, 100.5, 99.5, 100.2), (98.0, 98.5, 97.5, 98.2)]
    t = run_one(long_sig(), rows)
    assert t.exit_reason == "stop_gap" and t.exit_px == 98.0
    assert t.pnl_R == pytest.approx(-2.0)


def test_gap_through_target_fills_at_the_open():
    rows = [FLAT, (100.0, 100.5, 99.5, 100.2), (102.0, 102.5, 101.9, 102.2)]
    t = run_one(long_sig(), rows)
    assert t.exit_reason == "target_gap" and t.exit_px == 102.0
    assert t.pnl_R == pytest.approx(2.0)


def test_short_mirrors_long():
    rows = [FLAT, (100.0, 100.5, 98.4, 98.6)]
    t = run_one(short_sig(), rows)
    assert t.exit_reason == "target" and t.exit_px == 98.5 and t.pnl_R == pytest.approx(1.5)
    rows = [FLAT, (100.0, 101.2, 99.5, 100.5)]
    t = run_one(short_sig(), rows)
    assert t.exit_reason == "stop" and t.pnl_R == pytest.approx(-1.0)


def test_limit_target_needs_trade_through():
    cost = bt.CostModel(slippage=0.0, limit_trade_through=0.01, sell_fee_bps=0.0)
    touched = [FLAT, (100.0, 101.5, 99.6, 100.4), (100.4, 100.6, 100.0, 100.2)]
    assert run_one(long_sig(), touched, cost=cost).exit_reason == "eod"  # high == target is not a fill
    through = [FLAT, (100.0, 101.51, 99.6, 100.4)]
    assert run_one(long_sig(), through, cost=cost).exit_reason == "target"


def test_slippage_hits_entry_and_stop_but_not_target():
    cost = bt.CostModel(slippage=0.01, limit_trade_through=0.0, sell_fee_bps=0.0)
    win = run_one(long_sig(), [FLAT, (100.0, 101.6, 99.6, 101.5)], cost=cost)
    assert win.entry_px == pytest.approx(100.01)
    assert win.pnl_R == pytest.approx(1.49)  # target 101.5 - fill 100.01, no exit slippage
    loss = run_one(long_sig(), [FLAT, (100.0, 100.4, 98.9, 99.0)], cost=cost)
    assert loss.exit_px == pytest.approx(98.99) and loss.pnl_R == pytest.approx(-1.02)
    short = run_one(short_sig(), [FLAT, (100.0, 101.2, 99.6, 100.5)], cost=cost)
    assert short.entry_px == pytest.approx(99.99) and short.exit_px == pytest.approx(101.01)


def test_fees_apply_to_the_sell_leg():
    cost = bt.CostModel(slippage=0.0, limit_trade_through=0.0, sell_fee_bps=10.0)  # 10 bps, exaggerated
    long_t = run_one(long_sig(), [FLAT, (100.0, 101.6, 99.6, 101.5)], cost=cost)
    assert long_t.pnl_per_share == pytest.approx(1.5 - 0.001 * 101.5)
    short_t = run_one(short_sig(), [FLAT, (100.0, 100.5, 98.4, 98.6)], cost=cost)
    assert short_t.pnl_per_share == pytest.approx(1.5 - 0.001 * 100.0)  # the entry is the sale


def test_flat_at_time_exit():
    rows = [FLAT] + [(100.0, 100.3, 99.7, 100.0)] * 77  # 09:30 .. 15:55
    t = run_one(long_sig(), rows)
    assert t.exit_reason == "time" and t.exit_ts == et(D, "15:55") and t.pnl_R == pytest.approx(0.0)


def test_eod_exit_when_session_ends_before_flat_time():
    rows = [FLAT] + [(100.0, 100.3, 99.7, 100.1)] * 10  # data stops at 10:20
    t = run_one(long_sig(), rows)
    assert t.exit_reason == "eod" and t.exit_px == 100.1


def test_reject_fill_outside_bracket():
    gap = [FLAT, (98.9, 99.5, 98.5, 99.0)]  # next bar opens below the stop: a live bracket would be rejected
    assert run_one(long_sig(), gap) == "fill_outside_bracket"


def test_reject_when_there_is_no_next_bar():
    assert run_one(long_sig(ts="09:35"), [FLAT]) == "no_entry_bar"


def test_reject_stale_entry_when_next_bar_is_far_away():
    frame = pd.concat([sess([FLAT]), sess([FLAT], start="09:50")])  # nothing trades between 09:35 and 09:50
    pb = bt.PreparedBars.from_frame(frame)
    assert bt.simulate_trade(long_sig(ts="09:35"), pb, ZERO, 955) == "stale_entry"


def test_reject_signal_on_last_bar_of_session():
    two_days = pd.concat([sess([FLAT, FLAT], day="2024-03-05"), sess([FLAT, FLAT], day="2024-03-06")])
    pb = bt.PreparedBars.from_frame(two_days)
    sig = long_sig(ts="09:40")  # closes the last bar of day one; the next bar is tomorrow's open
    assert bt.simulate_trade(sig, pb, ZERO, 955) == "stale_entry"
    patient = bt.CostModel(slippage=0.0, limit_trade_through=0.0, sell_fee_bps=0.0, max_entry_delay_min=10**6)
    assert bt.simulate_trade(sig, pb, patient, 955) == "no_entry_bar"  # still never carried overnight


def test_reject_entry_at_or_after_flat_time():
    rows = [FLAT] + [(100.0, 100.3, 99.7, 100.0)] * 77  # 09:30 .. 15:55
    assert run_one(long_sig(ts="15:55"), rows) == "after_flat_time"


def test_one_open_trade_per_symbol():
    rows = [FLAT] + [(100.0, 100.3, 99.7, 100.0)] * 77
    pb = {"AAA": bt.PreparedBars.from_frame(sess(rows))}
    sigs = [long_sig(ts="09:35"), long_sig(ts="10:00")]
    trades, rejects = bt.simulate_signals(sigs, pb, ZERO, bt.RiskConfig())
    assert len(trades) == 1 and rejects["symbol_busy"] == 1


def test_sizing_risk_cap_and_compounding():
    day1 = sess([FLAT, (100.0, 101.6, 99.6, 101.5)], day="2024-03-05")  # +1.5R
    day2 = sess([FLAT, (100.0, 101.6, 99.6, 101.5)], day="2024-03-06")
    pb = {"AAA": bt.PreparedBars.from_frame(pd.concat([day1, day2]))}
    sigs = [long_sig(day="2024-03-05"), long_sig(day="2024-03-06")]
    risk = bt.RiskConfig(start_equity=100_000, risk_per_trade=0.01, max_leverage=100)
    res = bt.execute(sigs, pb, ZERO, risk)
    first, second = res.trades.iloc[0], res.trades.iloc[1]
    assert first.qty == 1000 and first.pnl == pytest.approx(1500.0)
    assert second.equity_before == pytest.approx(101_500.0) and second.qty == 1015  # compounding


def test_leverage_cap_limits_quantity():
    pb = {"AAA": bt.PreparedBars.from_frame(sess([FLAT, (100.0, 101.6, 99.6, 101.5)]))}
    res = bt.execute([long_sig()], pb, ZERO, bt.RiskConfig(max_leverage=0.5))
    t = res.trades.iloc[0]
    assert t.qty == 500 and bool(t.capped)  # 0.5 x 100k / $100


def test_max_positions_caps_concurrent_trades():
    rows = [FLAT, (100.0, 101.6, 99.6, 101.5)]
    pb = {s: bt.PreparedBars.from_frame(sess(rows)) for s in ("AAA", "BBB", "CCC")}
    sigs = [long_sig(symbol=s) for s in pb]
    res = bt.execute(sigs, pb, ZERO, bt.RiskConfig(max_positions=2, max_leverage=100))
    assert len(res.trades) == 2 and res.rejects["max_positions"] == 1
    assert len(res.raw) == 3  # strategy quality still counts every simulated trade


def test_position_slot_frees_after_exit():
    pb = {s: bt.PreparedBars.from_frame(sess([FLAT, (100.0, 101.6, 99.6, 101.5), FLAT, FLAT])) for s in ("AAA", "BBB")}
    # BBB signals one bar after AAA's trade has already closed, so max_positions=1 must still allow it.
    sigs = [long_sig(symbol="AAA", ts="09:35"), long_sig(symbol="BBB", ts="09:45")]
    res = bt.execute(sigs, pb, ZERO, bt.RiskConfig(max_positions=1, max_leverage=100))
    assert len(res.trades) == 2


def test_execute_reports_sessions():
    pb = {"AAA": bt.PreparedBars.from_frame(pd.concat([sess([FLAT, FLAT], day="2024-03-05"), sess([FLAT, FLAT], day="2024-03-06")]))}
    res = bt.execute([], pb, ZERO, bt.RiskConfig())
    assert res.sessions == [pd.Timestamp("2024-03-05"), pd.Timestamp("2024-03-06")]
    assert res.trades.empty and res.raw.empty


def test_slippage_is_as_traded_dollars_scaled_by_split_factor():
    # Prices here are split-adjusted; the share was 4:1 split later, so 1c as-traded is 0.25c adjusted.
    cost = bt.CostModel(slippage=0.01, limit_trade_through=0.0, sell_fee_bps=0.0)
    rows = [FLAT, (100.0, 101.6, 99.6, 101.5)]
    plain = bt.PreparedBars.from_frame(sess(rows))
    split = bt.PreparedBars.from_frame(sess(rows), split_factor=[4.0, 4.0])
    flat_minute = 15 * 60 + 55
    t1 = bt.simulate_trade(long_sig(), plain, cost, flat_minute)
    t4 = bt.simulate_trade(long_sig(), split, cost, flat_minute)
    assert t1.entry_px == pytest.approx(100.01)
    assert t4.entry_px == pytest.approx(100.0025)
    assert t4.pnl_per_share > t1.pnl_per_share


def test_limit_trade_through_scales_with_split_factor():
    cost = bt.CostModel(slippage=0.0, limit_trade_through=0.04, sell_fee_bps=0.0)
    rows = [FLAT, (100.0, 101.51, 99.6, 100.4)]  # clears the target by 0.01 adjusted
    unsplit = bt.PreparedBars.from_frame(sess(rows))
    split = bt.PreparedBars.from_frame(sess(rows), split_factor=[4.0, 4.0])  # needs only 0.01 adjusted
    flat_minute = 15 * 60 + 55
    assert bt.simulate_trade(long_sig(), unsplit, cost, flat_minute).exit_reason == "eod"
    assert bt.simulate_trade(long_sig(), split, cost, flat_minute).exit_reason == "target"
