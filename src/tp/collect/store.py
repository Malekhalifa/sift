"""Atomic single-file Parquet dataset store with the sealed-holdout read guard."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype

from tp import config
from tp.collect.datasets import Dataset

log = logging.getLogger(__name__)

INGESTED_AT = "ingested_at"
FUTURE_SLACK = timedelta(days=1)


class StoreError(Exception):
    """An existing dataset file could not be read; it is never overwritten."""


class HoldoutError(Exception):
    """A read would touch data on or after config.HOLDOUT_START."""


def _utc(ts: pd.Timestamp | datetime) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _ts(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True)


def _keys(df: pd.DataFrame, key: list[str]) -> pd.Index:
    return pd.MultiIndex.from_frame(df[key]) if len(key) > 1 else pd.Index(df[key[0]])


def _align(ds: Dataset, old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Coerce the new frame's key and ts columns to the stored dtypes so merged keys compare equal."""
    cols = [*ds.key, ds.ts_col]
    absent = [c for c in cols if c not in old.columns]
    if absent:
        raise StoreError(f"{ds.name}: stored file {ds.path} lacks columns {absent}")
    new = new.copy()
    for col in dict.fromkeys(cols):
        o, n = old[col], new[col]
        o_dt, n_dt = is_datetime64_any_dtype(o.dtype), is_datetime64_any_dtype(n.dtype)
        if not (o_dt or n_dt):
            continue
        if not (o_dt and n_dt):
            raise StoreError(f"{ds.name}: column {col!r} is {n.dtype} in the new frame but {o.dtype} in the stored file")
        if o.dt.tz is None:
            new[col] = n if n.dt.tz is None else n.dt.tz_convert("UTC").dt.tz_localize(None)
        else:
            new[col] = n.dt.tz_localize("UTC") if n.dt.tz is None else n.dt.tz_convert(o.dt.tz)
    return new


def _load(ds: Dataset) -> pd.DataFrame | None:
    if not ds.path.exists():
        return None
    try:
        return pd.read_parquet(ds.path)
    except Exception as e:
        raise StoreError(f"cannot read {ds.path}: {e}") from e


def _atomic_write(ds: Dataset, df: pd.DataFrame) -> None:
    ds.path.parent.mkdir(parents=True, exist_ok=True)
    tmp = ds.path.with_suffix(ds.path.suffix + ".tmp")
    try:
        df.to_parquet(tmp, index=False)
        os.replace(tmp, ds.path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write(ds: Dataset, frame: pd.DataFrame, now: datetime | None = None) -> int:
    """Merge frame into the dataset (new rows win on key). Returns the number of new keys stored."""
    if frame.empty:
        return 0
    now_ts = _utc(now or datetime.now(timezone.utc))
    missing = [c for c in (*ds.key, ds.ts_col) if c not in frame.columns]
    if missing:
        raise ValueError(f"{ds.name}: frame lacks columns {missing}")
    ts = _ts(frame[ds.ts_col])
    if ts.isna().any():
        log.warning("%s: dropping %d rows with NaT %s", ds.name, int(ts.isna().sum()), ds.ts_col)
    future = ts > now_ts + FUTURE_SLACK
    if future.any():
        log.warning("%s: dropping %d rows with future %s", ds.name, int(future.sum()), ds.ts_col)
    frame = frame[ts.notna() & ~future]
    if frame.empty:
        return 0

    key = list(ds.key)
    new = frame.assign(**{INGESTED_AT: now_ts})
    old = _load(ds)
    if old is not None:
        new = _align(ds, old, new)
    merged = new if old is None else pd.concat([old, new], ignore_index=True)
    merged = merged.drop_duplicates(key, keep="last")
    merged = merged.sort_values(ds.ts_col, kind="stable", key=_ts).reset_index(drop=True)
    if old is None:
        added = len(merged)
    else:
        seen = _keys(merged, key).isin(_keys(old, key))
        added = int((~seen).sum())
        if INGESTED_AT in old.columns:
            prior = old.drop_duplicates(key, keep="last").set_index(key)[INGESTED_AT]
            prior = pd.Series(prior.reindex(_keys(merged, key)).to_numpy(), index=merged.index)
        else:
            prior = pd.Series(pd.NaT, index=merged.index, dtype=merged[INGESTED_AT].dtype)
        merged[INGESTED_AT] = merged[INGESTED_AT].where(~seen, prior)
    _atomic_write(ds, merged)
    return added


def read(
    ds: Dataset,
    since: pd.Timestamp | None = None,
    until: pd.Timestamp | None = None,
    holdout: bool = False,
) -> pd.DataFrame:
    """Rows with since <= ts_col <= until (both inclusive, unlike bars.load_raw where end is exclusive). Raises HoldoutError if the read reaches the holdout and holdout is False."""
    df = _load(ds)
    if df is None:
        return pd.DataFrame()
    cutoff = _utc(pd.Timestamp(config.HOLDOUT_START))
    ts = _ts(df[ds.ts_col])
    if not holdout:
        reaches = _utc(until) >= cutoff if until is not None else bool((ts >= cutoff).any())
        if reaches:
            raise HoldoutError(f"{ds.name}: read reaches the sealed holdout ({config.HOLDOUT_START}); pass holdout=True")
    mask = pd.Series(True, index=df.index)
    if since is not None:
        mask &= ts >= _utc(since)
    if until is not None:
        mask &= ts <= _utc(until)
    return df[mask].reset_index(drop=True)
