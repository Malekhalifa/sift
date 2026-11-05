import pandas as pd

from conftest import make_bars
from tp import store


def test_write_is_idempotent_and_new_fetch_wins():
    ts = ["2024-03-01T14:30:00Z", "2024-03-01T14:31:00Z"]
    assert store.write_bars("sip", "1Min", "AAA", make_bars(ts)) == 2
    assert store.write_bars("sip", "1Min", "AAA", make_bars(ts)) == 0

    revised = make_bars(ts, price=200.0)
    assert store.write_bars("sip", "1Min", "AAA", revised) == 0
    df = store.read_year("sip", "1Min", "AAA", 2024)
    assert len(df) == 2
    assert df["open"].iloc[0] == 200.0


def test_bars_split_into_year_files_and_last_ts():
    ts = ["2023-12-29T20:00:00Z", "2024-01-02T14:30:00Z"]
    assert store.write_bars("sip", "1Min", "AAA", make_bars(ts)) == 2
    assert store.stored_years("sip", "1Min", "AAA") == [2023, 2024]
    assert store.last_ts("sip", "1Min", "AAA") == pd.Timestamp("2024-01-02T14:30:00Z")
    assert store.last_ts("sip", "1Min", "MISSING") is None


def test_load_raw_slices_by_range():
    ts = ["2023-12-29T20:00:00Z", "2024-01-02T14:30:00Z", "2024-01-02T14:31:00Z"]
    store.write_bars("sip", "1Min", "AAA", make_bars(ts))
    df = store.load_raw("sip", "1Min", "AAA", start=pd.Timestamp("2024-01-02", tz="UTC"))
    assert list(df.index) == [pd.Timestamp(t) for t in ts[1:]]
    assert store.load_raw("sip", "1Min", "NOPE").empty


def test_frame_from_api_normalizes_and_dedupes():
    api = [
        {"t": "2024-03-01T14:31:00Z", "o": 2, "h": 3, "l": 1, "c": 2.5, "v": 10, "n": 1, "vw": 2.2},
        {"t": "2024-03-01T14:30:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 20, "n": 2, "vw": 1.4},
        {"t": "2024-03-01T14:30:00Z", "o": 9, "h": 9, "l": 9, "c": 9, "v": 5, "n": 1, "vw": 9},
    ]
    df = store.frame_from_api(api)
    assert list(df.index) == [pd.Timestamp("2024-03-01T14:30:00Z"), pd.Timestamp("2024-03-01T14:31:00Z")]
    assert df["open"].iloc[0] == 9  # last duplicate wins
    assert df["volume"].dtype == "int64"
    assert store.frame_from_api([]).empty
