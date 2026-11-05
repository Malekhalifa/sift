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
