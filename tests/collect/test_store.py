import logging
import os
from datetime import datetime, timezone

import pandas as pd
import pytest

from tp.collect import store
from tp.collect.datasets import Dataset
from tp.collect.store import HoldoutError, StoreError

NOW = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
LATER = datetime(2024, 6, 2, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def ds(tmp_path):
    return Dataset(name="t", path=tmp_path / "sub" / "t.parquet", key=("id",), ts_col="ts")


def rows(*items):
    return pd.DataFrame(
        [{"id": i, "ts": pd.Timestamp(t, tz="UTC"), "v": v} for i, t, v in items]
    )


def stored(ds):
    return pd.read_parquet(ds.path)


def test_write_dedupes_on_key_and_new_rows_win(ds):
    assert store.write(ds, rows((1, "2024-01-01", 1), (2, "2024-01-02", 2), (3, "2024-01-03", 3)), now=NOW) == 3
    added = store.write(ds, rows((3, "2024-01-03", 30), (4, "2024-01-04", 4)), now=NOW)
    df = stored(ds)
    assert added == 1
    assert len(df) == 4
    assert df.loc[df["id"] == 3, "v"].item() == 30
    assert list(df["id"]) == [1, 2, 3, 4]


def test_empty_frame_writes_nothing(ds):
    assert store.write(ds, rows(), now=NOW) == 0
    assert not ds.path.exists()


def test_write_is_atomic(ds, monkeypatch):
    store.write(ds, rows((1, "2024-01-01", 1)), now=NOW)
    before = ds.path.read_bytes()

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        store.write(ds, rows((2, "2024-01-02", 2)), now=NOW)
    assert list(ds.path.parent.glob("*.tmp")) == []
    assert ds.path.read_bytes() == before


def test_ingested_at_is_added_once(ds):
    store.write(ds, rows((1, "2024-01-01", 1)), now=NOW)
    store.write(ds, rows((1, "2024-01-01", 10), (2, "2024-01-02", 2)), now=LATER)
    df = stored(ds).set_index("id")
    assert df.loc[1, "ingested_at"] == pd.Timestamp(NOW)
    assert df.loc[2, "ingested_at"] == pd.Timestamp(LATER)
    assert df.loc[1, "v"] == 10


def test_future_timestamps_are_rejected(ds, caplog):
    frame = rows((1, "2024-01-01", 1), (2, "2024-06-10", 2), (3, "2024-06-02", 3))
    with caplog.at_level(logging.WARNING):
        added = store.write(ds, frame, now=NOW)
    assert added == 2
    assert set(stored(ds)["id"]) == {1, 3}
    assert "future" in caplog.text


def test_unreadable_existing_file_is_never_overwritten(ds):
    ds.path.parent.mkdir(parents=True)
    ds.path.write_bytes(b"not parquet")
    with pytest.raises(StoreError):
        store.write(ds, rows((1, "2024-01-01", 1)), now=NOW)
    assert ds.path.read_bytes() == b"not parquet"


def test_read_refuses_holdout(ds):
    store.write(ds, rows((1, "2024-01-01", 1)), now=NOW)
    with pytest.raises(HoldoutError):
        store.read(ds, until=pd.Timestamp("2025-01-01"))
    assert len(store.read(ds)) == 1

    later = datetime(2025, 3, 1, tzinfo=timezone.utc)
    store.write(ds, rows((2, "2025-02-01", 2)), now=later)
    with pytest.raises(HoldoutError):
        store.read(ds)
    assert len(store.read(ds, holdout=True)) == 2
    assert len(store.read(ds, until=pd.Timestamp("2024-12-31"))) == 1


def test_read_filters_since_until(ds):
    store.write(ds, rows((1, "2024-01-01", 1), (2, "2024-02-01", 2), (3, "2024-03-01", 3)), now=NOW)
    df = store.read(ds, since=pd.Timestamp("2024-02-01"), until=pd.Timestamp("2024-02-15"))
    assert list(df["id"]) == [2]


def test_read_missing_file_is_empty(ds):
    assert store.read(ds).empty


def test_composite_key_and_legacy_file_without_ingested_at(tmp_path):
    ds = Dataset(name="c", path=tmp_path / "c.parquet", key=("a", "b"), ts_col="d")
    pd.DataFrame({"a": ["x", "x"], "b": [1, 2], "d": pd.to_datetime(["2024-01-01", "2024-01-02"], utc=True)}).to_parquet(ds.path)
    new = pd.DataFrame({"a": ["x", "y"], "b": [2, 1], "d": pd.to_datetime(["2024-01-02", "2024-01-03"], utc=True)})
    assert store.write(ds, new, now=NOW) == 1
    df = pd.read_parquet(ds.path)
    assert len(df) == 3
    assert df["ingested_at"].isna().sum() == 2
    assert df.loc[df["a"] == "y", "ingested_at"].item() == pd.Timestamp(NOW)


def _legacy(tmp_path, tz):
    ds = Dataset(name="l", path=tmp_path / "l.parquet", key=("date", "symbol"), ts_col="date")
    dates = pd.to_datetime(["2024-01-01", "2024-01-02"]).tz_localize(tz).as_unit("us")
    pd.DataFrame({"date": dates, "symbol": ["A", "A"], "v": [1, 2]}).to_parquet(ds.path)
    return ds


def test_naive_legacy_file_with_aware_new_frame_replaces_row(tmp_path):
    ds = _legacy(tmp_path, None)
    new = pd.DataFrame({"date": pd.to_datetime(["2024-01-02", "2024-01-03"], utc=True), "symbol": ["A", "A"], "v": [20, 3]})
    assert store.write(ds, new, now=NOW) == 1
    df = pd.read_parquet(ds.path)
    assert list(df["v"]) == [1, 20, 3]
    assert df["date"].dt.tz is None
    assert not df.duplicated(["date", "symbol"]).any()


def test_aware_legacy_file_with_naive_new_frame_replaces_row(tmp_path):
    ds = _legacy(tmp_path, "UTC")
    new = pd.DataFrame({"date": pd.to_datetime(["2024-01-02", "2024-01-03"]), "symbol": ["A", "A"], "v": [20, 3]})
    assert store.write(ds, new, now=NOW) == 1
    df = pd.read_parquet(ds.path)
    assert list(df["v"]) == [1, 20, 3]
    assert str(df["date"].dt.tz) == "UTC"


def test_incompatible_dtype_raises_store_error_naming_column(tmp_path):
    ds = _legacy(tmp_path, None)
    before = ds.path.read_bytes()
    new = pd.DataFrame({"date": [datetime(2024, 1, 2).date()], "symbol": ["A"], "v": [20]})
    with pytest.raises(StoreError, match="date"):
        store.write(ds, new, now=NOW)
    assert ds.path.read_bytes() == before


def test_nat_timestamps_are_dropped_and_logged(ds, caplog):
    frame = rows((1, "2024-01-01", 1), (2, "2024-01-02", 2))
    frame.loc[1, "ts"] = pd.NaT
    with caplog.at_level(logging.WARNING):
        assert store.write(ds, frame, now=NOW) == 1
    assert list(stored(ds)["id"]) == [1]
    assert "NaT" in caplog.text


def test_old_file_missing_key_columns_raises_store_error(ds):
    ds.path.parent.mkdir(parents=True)
    pd.DataFrame({"other": [1]}).to_parquet(ds.path)
    with pytest.raises(StoreError, match="id"):
        store.write(ds, rows((1, "2024-01-01", 1)), now=NOW)
