import pandas as pd
import pytest

from tp import config


@pytest.fixture(autouse=True)
def tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    return tmp_path


def make_bars(timestamps, price=100.0, volume=1000):
    """Raw frame in store format; price rises 1.0 per bar so ordering is visible."""
    idx = pd.DatetimeIndex(pd.to_datetime(timestamps, utc=True), name="ts").as_unit("ns")
    n = len(idx)
    base = pd.Series([price + i for i in range(n)], index=idx, dtype="float64")
    return pd.DataFrame(
        {
            "open": base,
            "high": base + 0.5,
            "low": base - 0.5,
            "close": base + 0.25,
            "volume": pd.Series([volume] * n, index=idx, dtype="int64"),
            "trade_count": pd.Series([10] * n, index=idx, dtype="int64"),
            "vwap": base + 0.1,
        }
    )


def sess(ohlc, day="2024-03-05", start="09:30", freq="5min"):
    """Bars for one ET session from (open, high, low, close) tuples; UTC index of bar opens."""
    idx = pd.date_range(f"{day} {start}", periods=len(ohlc), freq=freq, tz="America/New_York").tz_convert("UTC")
    df = pd.DataFrame(list(ohlc), columns=["open", "high", "low", "close"], index=idx).astype("float64")
    df.index.name = "ts"
    df["volume"] = 1000
    df["trade_count"] = 10
    df["vwap"] = df["close"]
    return df


def et(day, hhmm):
    return pd.Timestamp(f"{day} {hhmm}", tz="America/New_York").tz_convert("UTC")


def dbars(ohlc, start="2024-03-04", symbol_volume=1000):
    """Daily bars from (open, high, low, close) tuples on consecutive business days; UTC index at midnight ET."""
    idx = pd.bdate_range(start, periods=len(ohlc), tz="America/New_York").tz_convert("UTC")
    df = pd.DataFrame(list(ohlc), columns=["open", "high", "low", "close"], index=idx).astype("float64")
    df.index.name = "ts"
    df["volume"] = symbol_volume
    df["trade_count"] = 10
    df["vwap"] = df["close"]
    return df
