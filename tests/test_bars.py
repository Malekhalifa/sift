import numpy as np
import pandas as pd

from conftest import make_bars
from tp import bars, corp_actions, store


def splits_df(rows):
    return pd.DataFrame(
        [{"symbol": s, "ex_date": pd.Timestamp(d), "ratio": r} for s, d, r in rows],
        columns=["symbol", "ex_date", "ratio"],
    )


def test_adjust_splits_makes_series_continuous():
    # Raw NVDA-style 10:1 split on 2024-06-10: price ~1200 before, ~120 after.
    raw = make_bars(["2024-06-07T20:00:00Z", "2024-06-10T13:30:00Z"])
    raw.loc[raw.index[0], ["open", "high", "low", "close", "vwap"]] = 1200.0
    raw.loc[raw.index[1], ["open", "high", "low", "close", "vwap"]] = 120.0
    adj = bars.adjust_splits(raw, splits_df([("NVDA", "2024-06-10", 10.0)]))
    assert adj["close"].tolist() == [120.0, 120.0]
    assert adj["volume"].tolist() == [10_000, 1000]  # pre-split volume scaled up
    assert raw["close"].iloc[0] == 1200.0  # input untouched


def test_adjust_splits_compounds_multiple_splits():
    raw = make_bars(["2020-01-02T15:00:00Z", "2022-01-03T15:00:00Z", "2025-01-02T15:00:00Z"], price=100)
    adj = bars.adjust_splits(raw, splits_df([("X", "2021-01-04", 4.0), ("X", "2024-01-02", 10.0)]))
    factors = (raw["open"] / adj["open"]).round(6).tolist()
    assert factors == [40.0, 10.0, 1.0]


def test_split_ex_date_bar_is_unadjusted():
    raw = make_bars(["2024-06-10T13:30:00Z"])
    f = bars.split_factor(raw.index, splits_df([("NVDA", "2024-06-10", 10.0)]))
    assert f.tolist() == [1.0]


def test_rth_mask_handles_dst():
    idx = pd.DatetimeIndex(
        pd.to_datetime(
            [
                "2024-01-02T14:29:00Z",  # 09:29 EST
                "2024-01-02T14:30:00Z",  # 09:30 EST
                "2024-01-02T20:59:00Z",  # 15:59 EST
                "2024-01-02T21:00:00Z",  # 16:00 EST
                "2024-07-02T13:30:00Z",  # 09:30 EDT
                "2024-07-02T13:29:00Z",  # 09:29 EDT
            ],
            utc=True,
        )
    )
    assert bars.rth_mask(idx).tolist() == [False, True, True, False, True, False]


def test_resample_5min_ohlcv_and_vwap():
    ts = [f"2024-03-01T14:{m:02d}:00Z" for m in range(30, 40)]  # 09:30-09:39 EST... 14:30Z in March = 09:30 EST
    df = make_bars(ts, price=100.0, volume=100)
    out = bars.resample_ohlcv(df, "5min")
    assert len(out) == 2
    first = out.iloc[0]
    assert first["open"] == df["open"].iloc[0]
    assert first["close"] == df["close"].iloc[4]
    assert first["high"] == df["high"].iloc[:5].max()
    assert first["low"] == df["low"].iloc[:5].min()
    assert first["volume"] == 500
    assert np.isclose(first["vwap"], df["vwap"].iloc[:5].mean())  # equal volumes -> plain mean
    assert out.index[0] == pd.Timestamp("2024-03-01T14:30:00Z")


def test_resample_skips_empty_buckets():
    df = make_bars(["2024-03-01T14:30:00Z", "2024-03-01T14:50:00Z"])
    out = bars.resample_ohlcv(df, "5min")
    assert len(out) == 2


def test_resample_60min_aligns_to_session_open():
    ts = ["2024-03-01T14:30:00Z", "2024-03-01T15:29:00Z", "2024-03-01T15:30:00Z"]
    out = bars.resample_ohlcv(make_bars(ts), "60min")
    assert list(out.index) == [pd.Timestamp("2024-03-01T14:30:00Z"), pd.Timestamp("2024-03-01T15:30:00Z")]


def test_load_bars_end_to_end(tmp_data_dir):
    raw = make_bars(["2024-06-07T14:30:00Z", "2024-06-10T13:30:00Z", "2024-06-10T20:30:00Z"])
    store.write_bars("sip", "1Min", "NVDA", raw)
    splits = splits_df([("NVDA", "2024-06-10", 10.0)])
    corp_actions.splits_path().parent.mkdir(parents=True, exist_ok=True)
    splits.to_parquet(corp_actions.splits_path(), index=False)

    unadj = bars.load_bars("NVDA", adjusted=False)
    adj = bars.load_bars("NVDA")
    assert unadj["open"].iloc[0] == 100.0
    assert adj["open"].iloc[0] == 10.0
    assert len(bars.load_bars("NVDA", rth=True)) == 2  # 20:30Z is 16:30 EDT, outside the session
