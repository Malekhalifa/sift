import numpy as np
import pandas as pd
import pytest

from conftest import sess
from tp import features


def days_frame(n_days, volumes, start="2024-02-01"):
    """n_days sessions of three 5-min bars; volumes[d] is the per-bar volume of day d."""
    days = pd.bdate_range(start, periods=n_days)
    frames = []
    for d, vol in zip(days, volumes, strict=True):
        f = sess([(100, 101, 99, 100)] * 3, day=d.strftime("%Y-%m-%d"))
        f["volume"] = vol
        frames.append(f)
    return pd.concat(frames), days


def test_rvol_is_cumulative_volume_over_prior_sessions_average():
    df, days = days_frame(12, [100] * 11 + [300])
    rvol = features.intraday_rvol(df, window=5, min_days=3)
    last = pd.Timestamp(days[-1])
    assert rvol.at[last, 570] == pytest.approx(3.0)  # 300 vs 100 at 09:30
    assert rvol.at[last, 580] == pytest.approx(3.0)  # 900 vs 300 through 09:40
    assert rvol.iloc[:3].isna().all().all()  # not enough history yet


def test_rvol_never_uses_today_or_later_in_its_baseline():
    base, days = days_frame(12, [100] * 12)
    bumped, _ = days_frame(12, [100] * 11 + [5000])
    a, b = features.intraday_rvol(base, 5, 3), features.intraday_rvol(bumped, 5, 3)
    pd.testing.assert_frame_equal(a.iloc[:-1], b.iloc[:-1])  # a later day cannot change an earlier day's value
    # within a session, later bars cannot change earlier columns
    late = base.copy()
    late.loc[late.index[-1], "volume"] = 99_999  # last bar of the last day
    c = features.intraday_rvol(late, 5, 3)
    assert c.iloc[-1][[570, 575]].equals(a.iloc[-1][[570, 575]])


def test_gap_pct_uses_previous_session_close():
    d1 = sess([(100, 101, 99, 100.0), (100, 101, 99, 100.0)], day="2024-03-05")
    d2 = sess([(102, 103, 101, 102.5), (102, 103, 101, 102.0)], day="2024-03-06")
    gap = features.session_gap_pct(pd.concat([d1, d2]))
    assert np.isnan(gap.iloc[0])
    assert gap.iloc[1] == pytest.approx(2.0)


def test_gap_is_nan_when_the_open_bar_is_missing():
    d1 = sess([(100, 101, 99, 100.0)], day="2024-03-05")
    d2 = sess([(102, 103, 101, 102.5)], day="2024-03-06", start="09:35")
    assert np.isnan(features.session_gap_pct(pd.concat([d1, d2])).iloc[1])


def daily_closes(closes, start="2024-01-02"):
    idx = pd.bdate_range(start, periods=len(closes), tz="America/New_York").tz_convert("UTC")
    return pd.DataFrame({"close": closes}, index=idx, dtype="float64")


def test_sma_trend_reflects_previous_close_only():
    up = daily_closes(list(range(1, 21)))
    d = features.sma_trend(up, n=5)
    assert d.iloc[:5].eq(0).all()  # warm-up plus the one-day delay
    assert d.iloc[10] == 1.0
    down = features.sma_trend(daily_closes(list(range(20, 0, -1))), n=5)
    assert down.iloc[10] == -1.0
    # changing today's close must not change today's reading
    bumped = up.copy()
    bumped.iloc[10, 0] = -500.0
    assert features.sma_trend(bumped, n=5).iloc[10] == d.iloc[10]
    assert features.sma_trend(bumped, n=5).iloc[11] != d.iloc[11]  # but it does reach tomorrow
