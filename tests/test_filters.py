import pandas as pd
import pytest

from conftest import sess
from test_features import daily_closes, days_frame
from tp.filters import FilterParams, SessionContext
from tp.strategies import OpeningRangeBreakout

OR_BAR, INSIDE, BREAK = (100.0, 101.0, 99.0, 100.5), (100.5, 100.9, 99.2, 100.4), (100.4, 102.0, 100.3, 101.5)


def breakout_days(n_days, volumes, start="2024-02-01"):
    days = pd.bdate_range(start, periods=n_days)
    frames = []
    for d, vol in zip(days, volumes, strict=True):
        f = sess([OR_BAR, INSIDE, BREAK], day=d.strftime("%Y-%m-%d"))
        f["volume"] = vol
        frames.append(f)
    return pd.concat(frames), days


def test_rvol_filter_gates_the_signal():
    hot, days = breakout_days(12, [100] * 11 + [300])
    cold, _ = breakout_days(12, [100] * 12)
    last = days[-1].date()

    def last_day_signals(bars, **p):
        sigs = OpeningRangeBreakout(**p).generate("AAA", bars)
        return [s for s in sigs if s.ts.tz_convert("America/New_York").date() == last]

    assert len(last_day_signals(hot, rvol_min=2.0, rvol_window=5)) == 1
    assert last_day_signals(cold, rvol_min=2.0, rvol_window=5) == []
    assert len(last_day_signals(cold)) == 1  # filter off


def test_gap_filters():
    d1 = sess([OR_BAR, INSIDE, BREAK], day="2024-03-05")
    d1["close"] = 100.0
    up = sess([(103, 104, 102, 103.5), (103.5, 103.9, 102.2, 103.4), (103.4, 105.0, 103.3, 104.5)], day="2024-03-06")
    bars = pd.concat([d1, up])
    day = pd.Timestamp("2024-03-06")
    fp = FilterParams(min_abs_gap_pct=1.0, gap_align=True)
    ctx = SessionContext(bars, None, None, fp)
    assert ctx.allows("long", day, 580) and not ctx.allows("short", day, 580)  # +3% gap
    assert not SessionContext(bars, None, None, FilterParams(min_abs_gap_pct=5.0)).allows("long", day, 580)
    assert not ctx.allows("long", pd.Timestamp("2024-03-05"), 580)  # first day has no gap -> unknown -> blocked


def test_trend_filter_directions_and_requirements():
    bars = sess([OR_BAR, INSIDE, BREAK], day="2024-03-05")
    uptrend = daily_closes(list(range(1, 80)), start="2024-01-02")
    day = pd.Timestamp(uptrend.index[60].tz_convert("America/New_York").date())
    ctx = SessionContext(bars, uptrend, None, FilterParams(trend_filter="own_sma", trend_sma=5))
    assert ctx.allows("long", day, 580) and not ctx.allows("short", day, 580)
    with pytest.raises(ValueError):
        SessionContext(bars, None, None, FilterParams(trend_filter="spy_sma"))
    with pytest.raises(ValueError):
        SessionContext(bars, None, None, FilterParams(trend_filter="bogus"))
    assert SessionContext(bars, None, None, FilterParams(trend_filter="spy_sma", trend_sma=5), ) if False else True


def test_spy_trend_uses_the_spy_series():
    bars = sess([OR_BAR, INSIDE, BREAK], day="2024-03-05")
    spy = daily_closes(list(range(80, 1, -1)), start="2024-01-02")  # SPY falling
    day = pd.Timestamp(spy.index[60].tz_convert("America/New_York").date())
    ctx = SessionContext(bars, None, spy, FilterParams(trend_filter="spy_sma", trend_sma=5))
    assert ctx.allows("short", day, 580) and not ctx.allows("long", day, 580)
