"""Daily QA: freshness, duplicates, future timestamps, schema drift and row counts per dataset source, plus
trading-calendar completeness and one-session price jumps for the price store. Writes data/qa/<date>.json."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from tp import bars, config
from tp.collect import store
from tp.collect.datasets import DATASETS
from tp.collect.metrics import Metrics
from tp.collect.source import parse_schedule
from tp.collect.state import State
from tp.collect.store import INGESTED_AT, StoreError

log = logging.getLogger(__name__)

PRICE_SOURCE = "alpaca_bars"
# Source name in config/collect.toml -> datasets it keeps current.
SOURCE_DATASETS: dict[str, tuple[str, ...]] = {
    "sec_filings": ("eightk", "earnings", "tenk_index"),
    "sec_form4": ("form4",),
    "sec_xbrl_shares": ("xbrl_shares",),
    "finra_shortvol": ("finra_shortvol",),
    "finra_short_interest": ("finra_short_interest",),
    "dod_awards": ("dod_awards",),
    "trump_posts": ("trump_posts",),
    "sp500_changes": ("sp500_changes",),
    "wikipedia_pageviews": ("wikipedia_pageviews",),
    "congress_trades": ("congress_trades",),
}

STALE_AFTER_INTERVALS = 2
FUTURE_SLACK = timedelta(days=1)
ROW_COUNT_FLOOR = 0.3
ROW_COUNT_HISTORY = 14
ROW_COUNT_MIN_HISTORY = 3
ROW_COUNT_MIN_WINDOW = timedelta(days=7)
ROW_COUNT_WINDOW_INTERVALS = 4
LOOKBACK_SESSIONS = 10
JUMP_UP = 1.0
JUMP_DOWN = -0.5
MAX_DETAIL_ITEMS = 10
DEFAULT_INTERVAL_S = 86400


@dataclass(frozen=True)
class _Check:
    ok: bool
    detail: str
    failures: int = 0


def _pass(detail: str = "ok") -> _Check:
    return _Check(True, detail)


def _fail(detail: str, failures: int = 1) -> _Check:
    return _Check(False, detail, failures)


def qa_dir() -> Path:
    return config.DATA_DIR / "qa"


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _load_schemas() -> tuple[dict[str, list[str]], bool]:
    """The recorded column sets, and whether the record exists but cannot be read."""
    path = qa_dir() / "schemas.json"
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}, False
    except (OSError, ValueError) as e:
        log.warning("unreadable schema record %s (%s); rewriting it from this run", path, e)
        return {}, True
    if not isinstance(data, dict):
        return {}, True
    return data, False


def _items(entries: list[str], limit: int | None = MAX_DETAIL_ITEMS) -> str:
    shown = ", ".join(entries if limit is None else entries[:limit])
    extra = 0 if limit is None else len(entries) - limit
    return f"{shown} (+{extra} more)" if extra > 0 else shown


def _interval_seconds(cfg: dict) -> int:
    try:
        return parse_schedule(cfg["schedule"]).interval_seconds
    except (KeyError, ValueError):
        return DEFAULT_INTERVAL_S


def _freshness(last: datetime | None, interval_s: int, now: datetime) -> _Check:
    if last is None:
        return _fail("never succeeded")
    age = (now - last).total_seconds()
    limit = STALE_AFTER_INTERVALS * interval_s
    detail = f"last success {last.astimezone(timezone.utc).isoformat(timespec='seconds')}, {age / 3600:.1f}h ago, limit {limit / 3600:.1f}h"
    return _fail(detail) if age > limit else _pass(detail)


def _absent(df: pd.DataFrame, cols: tuple[str, ...]) -> list[str]:
    return [c for c in cols if c not in df.columns]


def _duplicates(ds, df: pd.DataFrame) -> _Check:
    absent = _absent(df, ds.key)
    if absent:
        return _fail(f"missing key columns {absent}")
    n = int(df.duplicated(list(ds.key)).sum())
    return _fail(f"{n} rows repeat the key {list(ds.key)}", n) if n else _pass("no duplicate keys")


def _future(ds, df: pd.DataFrame, now: datetime) -> _Check:
    if ds.ts_col not in df.columns:
        return _fail(f"missing timestamp column {ds.ts_col!r}")
    ts = pd.to_datetime(df[ds.ts_col], utc=True, errors="coerce")
    late = ts[ts > pd.Timestamp(now) + FUTURE_SLACK]
    if late.empty:
        return _pass("no future timestamps")
    return _fail(f"{len(late)} rows with {ds.ts_col} after {(now + FUTURE_SLACK).date()}, latest {late.max().date()}", len(late))


def _schema(ds, df: pd.DataFrame, previous: dict[str, list[str]], unreadable: bool) -> _Check:
    cols = sorted(df.columns)
    if unreadable:
        return _fail("schema baseline unreadable")
    if ds.name not in previous:
        return _pass("first run, schema recorded")
    before = set(previous[ds.name])
    removed, added = sorted(before - set(cols)), sorted(set(cols) - before)
    if not removed and not added:
        return _pass(f"{len(cols)} columns unchanged")
    parts = ([f"missing {removed}"] if removed else []) + ([f"new {added}"] if added else [])
    return _fail("columns changed since the previous QA run: " + ", ".join(parts), len(removed) + len(added))


def _row_count(df: pd.DataFrame, interval_s: int, now: datetime) -> _Check:
    """Rows ingested in the trailing window (max of 7 days and 4 schedule intervals) against the median of the
    earlier windows since the first ingest, empty ones included, so a sparse source has median 0 and cannot fail."""
    if INGESTED_AT not in df.columns:
        return _pass("no history")
    ingested = pd.to_datetime(df[INGESTED_AT], utc=True, errors="coerce").dropna()
    if ingested.empty:
        return _pass("no history")
    window = max(ROW_COUNT_MIN_WINDOW, ROW_COUNT_WINDOW_INTERVALS * pd.Timedelta(seconds=interval_s))
    age = pd.Timestamp(now) - ingested
    index = (age - pd.Timedelta(1, "ns")) // window  # 0 = (now - window, now], 1 = the window before, ...
    index = index[age >= pd.Timedelta(0)]
    counts = index.value_counts()
    full_windows = int(age.max() // window) - 1  # earlier windows that lie wholly after the first ingest
    prior = counts.reindex(range(1, min(full_windows, ROW_COUNT_HISTORY) + 1), fill_value=0)
    if len(prior) < ROW_COUNT_MIN_HISTORY:
        return _pass("no history")
    current, median = int(counts.get(0, 0)), float(prior.median())
    detail = f"{current} new rows in the last {window.days}d against a trailing median of {median:g}"
    return _fail(detail) if current < ROW_COUNT_FLOOR * median else _pass(detail)


def _dataset_checks(
    ds, df: pd.DataFrame, interval_s: int, now: datetime, previous: dict, unreadable: bool
) -> dict[str, _Check]:
    return {
        "duplicates": _duplicates(ds, df),
        "future_timestamps": _future(ds, df, now),
        "schema": _schema(ds, df, previous, unreadable),
        "row_count": _row_count(df, interval_s, now),
    }


def _merge(parts: dict[str, _Check]) -> _Check:
    """One check for a source that keeps several datasets: fails if any does, detail names the dataset."""
    if len(parts) == 1:
        return next(iter(parts.values()))
    shown = {n: c for n, c in parts.items() if not c.ok} or parts
    ok = all(c.ok for c in parts.values())
    return _Check(ok, "; ".join(f"{n}: {c.detail}" for n, c in shown.items()), sum(c.failures for c in parts.values()))


def _dataset_source(
    name: str, cfg: dict, state: State, now: datetime, schemas: dict[str, list[str]], unreadable: bool,
    recorded: dict[str, list[str]], advance: bool,
) -> dict[str, _Check]:
    interval_s = _interval_seconds(cfg)
    fresh = _freshness(state.last_success(name), interval_s, now)
    problems: list[str] = []
    per_check: dict[str, dict[str, _Check]] = {}
    for dname in SOURCE_DATASETS.get(name, ()):
        ds = DATASETS[dname]
        if not ds.path.exists():
            problems.append(f"{dname}: dataset not found")
            continue
        try:
            df = store.read(ds, holdout=True)
        except StoreError as e:
            problems.append(f"{dname}: unreadable: {e}")
            continue
        if advance or unreadable or dname not in schemas:
            recorded[dname] = sorted(df.columns)
        for check, result in _dataset_checks(ds, df, interval_s, now, schemas, unreadable).items():
            per_check.setdefault(check, {})[dname] = result
    checks = {"freshness": fresh}
    if problems:
        checks["freshness"] = _Check(False, "; ".join([*problems, *([] if fresh.ok else [fresh.detail])]), len(problems) + (not fresh.ok))
    checks.update({check: _merge(parts) for check, parts in per_check.items()})
    return checks


def _sessions(df: pd.DataFrame) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(_dates(df).unique())


def _dates(df: pd.DataFrame) -> pd.DatetimeIndex:
    return df.index.tz_convert(bars.ET).normalize().tz_localize(None)


def _sample_symbols() -> list[str]:
    """Every recorded universe, core first."""
    universes = (
        config.core_symbols(), config.wide_symbols(), config.events_symbols(), config.confirm_symbols(),
        config.sf_symbols(),
    )
    return list(dict.fromkeys(s for universe in universes for s in universe))


def _price_checks(now: datetime, ignore_gaps: set[str], ignore_jumps: set[str], full: bool) -> tuple[_Check, _Check]:
    """Daily bars of every recorded symbol, as of now. Holes and jumps count only inside the last LOOKBACK_SESSIONS
    SPY sessions (all history when full, reported but never failing), so each event alerts and then ages out."""
    end = pd.Timestamp(now)
    spy = bars.load_bars("SPY", timeframe="1Day", end=end)
    if spy.empty:
        none = _fail("no daily SPY bars")
        return none, none
    calendar = _sessions(spy)
    recent = calendar if full else calendar[-LOOKBACK_SESSIONS:]
    core = set(config.core_symbols())
    limit = None if full else MAX_DETAIL_ITEMS
    gaps: list[str] = []
    jumps: list[str] = []
    gap_total = 0
    for symbol in _sample_symbols():
        df = spy if symbol == "SPY" else bars.load_bars(symbol, timeframe="1Day", end=end)
        if df.empty:
            if symbol in core:
                gaps.append(f"{symbol}: no daily bars")
                gap_total += 1
            continue
        dates = _dates(df)
        days = pd.DatetimeIndex(dates.unique())
        missing = recent[(recent > days.min()) & ~recent.isin(days)]
        if (calendar > days.max()).sum() > LOOKBACK_SESSIONS:  # delisted: its trailing sessions are not holes
            missing = missing[missing < days.max()]
        missing = [d.date().isoformat() for d in missing if f"{symbol}:{d.date()}" not in ignore_gaps]
        if missing:
            gap_total += len(missing)
            gaps.append(f"{symbol} missing {_items(missing, limit)}")
        pos = calendar.get_indexer(dates)
        move = df["close"].pct_change(fill_method=None).to_numpy()
        consecutive = np.r_[False, (pos[1:] - pos[:-1] == 1) & (pos[:-1] >= 0)]
        in_window = pos >= len(calendar) - len(recent)
        for i in np.flatnonzero(((move > JUMP_UP) | (move < JUMP_DOWN)) & consecutive & in_window):
            day = dates[i].date()
            if f"{symbol}:{day}" not in ignore_jumps:
                jumps.append(f"{symbol} {day} {move[i]:+.0%} (probable missing split, spin-off or special dividend)")
    if full:
        note = "full scan, informational: "
        cal = _pass(note + "; ".join(gaps) if gaps else "full scan: no holes")
        jmp = _pass(note + _items(jumps, None) if jumps else "full scan: no jumps")
        return cal, jmp
    cal = _fail("; ".join(gaps), gap_total) if gaps else _pass(f"{len(calendar)} SPY sessions, all sampled series complete")
    jmp = _fail(_items(jumps), len(jumps)) if jumps else _pass("no one-session move above +100% or below -50%")
    return cal, jmp


def run_qa(
    now: datetime, state: State, settings: dict, metrics: Metrics | None = None, full: bool = False
) -> dict:
    """Run every check as of now, write data/qa/<date>.json atomically and return the report.

    The schema baseline moves on only when metrics is given (the daemon's run), so a CLI re-run cannot erase drift.
    full=True scans all price history for holes and jumps, reports them without failing or feeding the gauges, and
    writes <date>-full.json so the daily report is left alone."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    schemas, unreadable = _load_schemas()
    recorded = dict(schemas)
    advance = metrics is not None
    allow = settings.get("qa", {})
    ignore_gaps, ignore_jumps = set(allow.get("ignore_gaps", ())), set(allow.get("ignore_jumps", ()))
    results: dict[str, dict[str, _Check]] = {}
    for name, cfg in settings.get("sources", {}).items():
        if not cfg.get("enabled", True):
            continue
        if name == PRICE_SOURCE:
            fresh = _freshness(state.last_success(name), _interval_seconds(cfg), now)
            calendar, jumps = _price_checks(now, ignore_gaps, ignore_jumps, full)
            results[name] = {"freshness": fresh, "calendar_completeness": calendar, "price_jumps": jumps}
        else:
            results[name] = _dataset_source(name, cfg, state, now, schemas, unreadable, recorded, advance)
    report = {
        "date": now.date().isoformat(),
        "sources": {
            name: {"checks": {c: {"ok": r.ok, "detail": r.detail} for c, r in checks.items()}}
            for name, checks in results.items()
        },
    }
    _atomic_json(qa_dir() / f"{report['date']}{'-full' if full else ''}.json", report)
    if unreadable or recorded != schemas:
        _atomic_json(qa_dir() / "schemas.json", recorded)
    if metrics is not None:
        for name, checks in results.items():
            for check, r in checks.items():
                if full and check in ("calendar_completeness", "price_jumps"):
                    continue
                metrics.set_qa(name, check, r.failures)
    return report
