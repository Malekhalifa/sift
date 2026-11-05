import numpy as np
import pandas as pd
import pytest

from conftest import sess
from tp import indicators as ind
from tp.strategies import SuperTrendWAE, UTBotSTC


def frame(closes, spread=0.1):
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"open": c, "high": c + spread, "low": c - spread, "close": c},
                        index=pd.date_range("2024-03-04 14:30", periods=len(c), freq="5min", tz="UTC"))


def test_atr_of_a_constant_range_is_that_range():
    d = frame([100.0] * 60, spread=0.5)
    assert ind.atr(d, 14).iloc[-1] == pytest.approx(1.0)


# ---- UT Bot -----------------------------------------------------------------------------------------------------
def test_ut_bot_flat_market_gives_no_signal_and_a_drop_then_a_rise_gives_sell_then_buy():
    closes = [100.0] * 40 + [96.0] * 30 + [100.0] * 30
    d = frame(closes, spread=0.1)
    u = ind.ut_bot(d["close"], ind.atr(d, 10), 1.0)
    assert not u.iloc[:40][["buy", "sell"]].to_numpy().any()
    sells, buys = np.flatnonzero(u["sell"]), np.flatnonzero(u["buy"])
    assert list(sells) == [40] and list(buys) == [70]  # the first bar of each move, in order


def test_ut_bot_stop_ratchets_with_the_trend_and_never_loosens():
    d = frame(100 + np.arange(80) * 0.3, spread=0.1)
    stop = ind.ut_bot(d["close"], ind.atr(d, 10), 2.0)["stop"].to_numpy()
    assert (np.diff(stop[20:]) >= -1e-12).all() and stop[-1] < d["close"].iloc[-1]


def test_ut_bot_never_uses_later_bars():
    rng = np.random.default_rng(3)
    c = 100 + np.cumsum(rng.normal(0, 0.3, 200))
    a, b = frame(c), frame(np.concatenate([c[:150], c[150:][::-1] + 40]))
    ua = ind.ut_bot(a["close"], ind.atr(a, 10), 1.5)
    ub = ind.ut_bot(b["close"], ind.atr(b, 10), 1.5)
    pd.testing.assert_frame_equal(ua.iloc[:150], ub.iloc[:150])


# ---- Supertrend -------------------------------------------------------------------------------------------------
def test_supertrend_follows_a_trend_and_flips_on_a_reversal():
    up = frame(100 + np.arange(80) * 0.5)
    assert ind.supertrend(up, 10, 3.0).iloc[-1] == 1
    down = frame(150 - np.arange(80) * 0.5)
    assert ind.supertrend(down, 10, 3.0).iloc[-1] == -1
    rev = frame(list(100 + np.arange(60) * 0.5) + list(130 - np.arange(60) * 1.5))
    t = ind.supertrend(rev, 10, 3.0)
    assert t.iloc[50] == 1 and t.iloc[-1] == -1


def test_supertrend_never_uses_later_bars():
    rng = np.random.default_rng(4)
    c = 100 + np.cumsum(rng.normal(0, 0.4, 200))
    a, b = frame(c), frame(np.concatenate([c[:150], c[150:] * 0 + 50]))
    pd.testing.assert_series_equal(ind.supertrend(a).iloc[:150], ind.supertrend(b).iloc[:150])


# ---- Schaff Trend Cycle -----------------------------------------------------------------------------------------
def test_stc_is_a_momentum_cycle_not_a_trend_level():
    rng = np.random.default_rng(5)
    noisy = pd.Series(100 + np.cumsum(rng.normal(0, 1, 400)))
    s = ind.schaff_trend_cycle(noisy).dropna()
    assert len(s) > 300 and s.min() >= -1e-9 and s.max() <= 100 + 1e-9
    # momentum accelerating up pushes it toward 100; momentum collapsing pushes it toward 0
    base = list(100 + rng.normal(0, 0.2, 120))
    burst_up = pd.Series(base + list(100 + np.cumsum(np.linspace(0.2, 2.5, 25))))
    collapse = pd.Series(base + list(100 - np.cumsum(np.linspace(0.2, 2.5, 25))))
    assert ind.schaff_trend_cycle(burst_up).iloc[120:].max() > 90
    assert ind.schaff_trend_cycle(collapse).iloc[120:].min() < 10
    # a steady trend is NOT "high": the indicator sits mid-range, which is why it is used for turning points
    steady = pd.Series(100 + np.arange(400) * 0.5 + rng.normal(0, 0.4, 400))
    assert 35 < ind.schaff_trend_cycle(steady).iloc[100:].mean() < 65
    assert np.isnan(ind.schaff_trend_cycle(pd.Series(100 + np.arange(200) * 0.5)).iloc[-1])  # degenerate straight line: no value


def test_stc_never_uses_later_bars():
    rng = np.random.default_rng(6)
    c = pd.Series(100 + np.cumsum(rng.normal(0, 1, 300)))
    changed = c.copy()
    changed.iloc[200:] = 500.0
    pd.testing.assert_series_equal(ind.schaff_trend_cycle(c).iloc[:200], ind.schaff_trend_cycle(changed).iloc[:200])


# ---- Waddah Attar, ADX, Choppiness ----------------------------------------------------------------------------------
def test_waddah_is_quiet_in_a_flat_market_and_fires_in_a_burst():
    flat = frame([100.0] * 300, spread=0.2)
    w = ind.waddah_attar(flat["close"], flat)
    assert not w["long_ok"].any() and not w["short_ok"].any()
    burst = frame([100.0] * 200 + list(100 + np.cumsum(np.linspace(0.1, 3.0, 40))), spread=0.2)
    wb = ind.waddah_attar(burst["close"], burst)
    assert wb["long_ok"].iloc[200:].any() and not wb["short_ok"].any()
    mirrored = frame([100.0] * 200 + list(100 - np.cumsum(np.linspace(0.1, 3.0, 40))), spread=0.2)
    assert ind.waddah_attar(mirrored["close"], mirrored)["short_ok"].iloc[200:].any()


def test_adx_and_choppiness_separate_trends_from_ranges():
    trend = frame(100 + np.arange(150) * 0.5, spread=0.2)
    rng = np.random.default_rng(7)
    choppy = frame(100 + rng.normal(0, 0.5, 150), spread=0.4)
    zigzag = frame(100 + (np.arange(150) % 2) * 1.0, spread=0.3)
    a_t, a_c = ind.adx(trend, 14).iloc[-1], ind.adx(choppy, 14).iloc[-1]
    assert 0 <= a_c <= 100 and a_t > 25 > a_c
    assert ind.choppiness(trend, 14).iloc[-1] < 40 < 60 < ind.choppiness(zigzag, 14).iloc[-1]


# ---- the two strategies built on them -------------------------------------------------------------------------------
def intraday(days, drops=None):
    """Several 78-bar sessions; `drops` maps a day index to (bar, level) where price steps to a new level."""
    frames = []
    level = 100.0
    for d, day in enumerate(pd.bdate_range("2024-03-04", periods=days)):
        rows = []
        for b in range(78):
            if drops and d in drops and b == drops[d][0]:
                level = drops[d][1]
            rows.append((level, level + 0.1, level - 0.1, level))
        frames.append(sess(rows, day=day.strftime("%Y-%m-%d")))
    return pd.concat(frames)


def key(sigs):
    return [(s.ts, s.side, s.entry_ref, s.stop, s.target) for s in sigs]


def test_utstc_signals_on_the_flip_and_puts_the_stop_beyond_the_swing():
    bars = intraday(6, drops={4: (30, 96.0), 5: (30, 100.0)})
    sigs = UTBotSTC(sides="both").generate("AAA", bars)
    sells = [s for s in sigs if s.side == "short"]
    assert len(sells) == 1
    s = sells[0]
    drop_bar = bars.index[4 * 78 + 30]
    assert s.ts == drop_bar + pd.Timedelta(minutes=5)  # decided at the close of the bar that crossed
    assert s.stop > s.entry_ref > s.target and s.target == pytest.approx(s.entry_ref - 1.5 * (s.stop - s.entry_ref))
    assert s.stop == pytest.approx(bars["high"].iloc[4 * 78 + 26 : 4 * 78 + 31].max())  # highest high of the last 5 bars
    assert [x.side for x in sigs if x.ts > s.ts] == ["long"]


def test_utstc_entry_window_and_sides_and_validation():
    early = intraday(6, drops={4: (3, 96.0)})  # the flip happens at 09:45, decision 09:50: inside; bar 0 would be too early
    assert any(s.side == "short" for s in UTBotSTC().generate("AAA", early))
    too_early = intraday(6, drops={4: (0, 96.0)})  # decision at 09:35 is before first_entry 09:45
    assert not [s for s in UTBotSTC().generate("AAA", too_early) if s.ts.tz_convert("America/New_York").hour == 9 and s.ts.tz_convert("America/New_York").minute < 45]
    late = intraday(6, drops={4: (70, 96.0)})  # 15:20: after last_entry 15:00
    assert not [s for s in UTBotSTC().generate("AAA", late) if s.side == "short" and s.ts.date().isoformat() == "2024-03-08"]
    bars = intraday(6, drops={4: (30, 96.0), 5: (30, 100.0)})
    assert all(s.side == "long" for s in UTBotSTC(sides="long").generate("AAA", bars))
    with pytest.raises(ValueError):
        UTBotSTC(stc_mode="bogus")


def test_utstc_separate_long_and_short_settings_and_stc_filter_cannot_add_signals():
    bars = intraday(6, drops={4: (30, 96.0), 5: (30, 100.0)})
    base = UTBotSTC().generate("AAA", bars)
    video = UTBotSTC(key_long=2.0, atr_long=30, key_short=2.0, atr_short=1).generate("AAA", bars)
    assert len(video) >= 1
    for mode in ("strict", "loose"):
        filtered = UTBotSTC(stc_mode=mode).generate("AAA", bars)
        assert set(key(filtered)) <= set(key(base))  # a confirmation can only remove entries


def test_utstc_never_uses_later_bars():
    bars = intraday(6, drops={4: (30, 96.0), 5: (30, 100.0)})
    cut = bars.index[4 * 78 + 40]
    wild = bars.copy()
    wild.loc[wild.index > cut, ["open", "high", "low", "close"]] = 500.0
    a = [s for s in UTBotSTC().generate("AAA", bars) if s.ts <= cut]
    b = [s for s in UTBotSTC().generate("AAA", wild) if s.ts <= cut]
    assert key(a) == key(b) and len(a) >= 1


def trending(days):
    frames = []
    level = 100.0
    for d, day in enumerate(pd.bdate_range("2024-03-04", periods=days)):
        rows = []
        for b in range(78):
            step = 0.05 + (0.6 if (d >= days - 2 and 20 <= b < 40) else 0.0)  # a burst of momentum on the last two days
            level += step
            rows.append((level, level + 0.15, level - 0.15, level))
        frames.append(sess(rows, day=day.strftime("%Y-%m-%d")))
    return pd.concat(frames)


def test_stack_enters_only_on_the_first_bar_both_conditions_agree():
    bars = trending(8)
    sigs = SuperTrendWAE().generate("AAA", bars)
    assert sigs and all(s.side == "long" for s in sigs)
    ts = sorted(s.ts for s in sigs)
    assert all(b - a > pd.Timedelta(minutes=5) for a, b in zip(ts, ts[1:]))  # never on consecutive bars
    s = sigs[0]
    assert s.stop < s.entry_ref < s.target and s.target - s.entry_ref == pytest.approx(1.5 * s.risk)
    assert SuperTrendWAE(sides="short").generate("AAA", bars) == []
    assert set(key(SuperTrendWAE(gate="adx20").generate("AAA", bars))) <= set(key(sigs))  # a gate only removes entries
    with pytest.raises(ValueError):
        SuperTrendWAE(gate="bogus")


def test_stack_never_uses_later_bars():
    bars = trending(8)
    cut = bars.index[-78 + 45]
    wild = bars.copy()
    wild.loc[wild.index > cut, ["open", "high", "low", "close"]] = 5.0
    a = [s for s in SuperTrendWAE().generate("AAA", bars) if s.ts <= cut]
    b = [s for s in SuperTrendWAE().generate("AAA", wild) if s.ts <= cut]
    assert key(a) == key(b) and len(a) >= 1
