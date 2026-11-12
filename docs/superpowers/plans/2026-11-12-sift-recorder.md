# Sift Recorder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A launchd-run daemon that keeps Sift's free data current, QA-checks it daily, exports Prometheus metrics, and starts recording the sources that have no free history.

**Architecture:** One asyncio daemon runs `Source` objects on schedules, one rate group at a time. A source returns pandas frames; one `Writer` merges them into atomic Parquet datasets. A daily QA job and a Prometheus endpoint watch the result. Existing scripts' logic moves into sources; existing data paths do not change, so finished studies keep working.

**Tech Stack:** Python 3.12+ with uv, asyncio, httpx, pandas and pyarrow (all already used), plus the new dependencies `prometheus-client` and `lxml` (the latter only for `pandas.read_html`). pytest. launchd. quantstack's existing Prometheus and Alertmanager.

**Spec:** `docs/superpowers/specs/2026-11-12-sift-recorder-design.md`

## Global Constraints

- Free data only. Apify runs stay under 80% of the $5 monthly credit, with `maxTotalChargeUsd` set on every run.
- No NATS. Collectors and the writer share one process.
- Never ask for data newer than now minus the source's `lag` (the Alpaca 403 lesson in `tp.recorder.fetch_end`).
- 2025+ is the sealed holdout: the recorder stores later data, but `store.read` raises unless `holdout=True` (`config.HOLDOUT_START`).
- Secrets (`ALPACA_*`, `APIFY_API_KEY`, `SEC_USER_AGENT`) come from `.env`; never log, print, or store them.
- One daemon per data directory (lock file `data/.collect.lock`). Metrics on `127.0.0.1:9120`.
- SEC sources share one rate group and at most 3 requests a second (`tp.edgar.MIN_INTERVAL_S` stays).
- `ingested_at` (UTC) is stored on every new row of every dataset the recorder creates.
- New code lives in `src/tp/collect/`, tests in `tests/collect/`. Follow the repo style: type hints, short docstrings, no comments that restate code.
- Spec deviation, decided here: datasets are single Parquet files rewritten atomically (each is under about 1M rows), not hive partitions. Revisit if a dataset passes 5M rows.

## Review Focus

1. **Mac wakes after a long sleep with many sources overdue:** each runs once, not once per missed slot; the scheduler never fires a storm. Pinned in Task 4.
2. **A source returns an empty frame, or rows with future timestamps:** an empty frame is a success that rewrites nothing; future `ts` rows are rejected and counted by QA. Tasks 2 and 7.
3. **HTTP 429/403/500, a truncated download, or a crash mid-write:** the store is never left with a half file, one failing source does not block other rate groups, and SEC's 429 backs off only the SEC group. Tasks 2, 4, 9.
4. **Daylight-saving change on a 18:00 ET schedule:** the next run is 18:00 America/New_York wall-clock on both sides of the change. Task 3.
5. **The Apify key or a response body containing it reaches a log line or an exception message:** it does not. Task 14.

---

## File Structure

```
src/tp/collect/__init__.py
src/tp/collect/datasets.py      Dataset descriptor (name, path, key, ts_col) and the registry of all datasets
src/tp/collect/store.py         Writer (atomic merge + dedupe) and read() with the holdout guard
src/tp/collect/source.py        Source base class, RunContext, schedules, SourceError
src/tp/collect/state.py         per-source state file (last success, failures, backoff)
src/tp/collect/scheduler.py     due-time logic, rate groups, retry/backoff, catch-up
src/tp/collect/metrics.py       Prometheus metrics and the /metrics server
src/tp/collect/daemon.py        the asyncio run loop, lock, signal handling
src/tp/collect/qa.py            daily QA checks and the JSON report
src/tp/collect/cli.py           python -m tp.collect run | once <source> | qa | status
src/tp/collect/sources/         alpaca_bars.py sec.py finra.py political.py wikipedia.py sp500.py congress.py
src/tp/collect/tools/local_stack.py   launchd install/status/uninstall
config/collect.toml             schedules, ports, spend cap, article map path
config/wikipedia_articles.toml  reviewed company-to-article map
deploy/sift_alerts.yml          Prometheus alert rules
tests/collect/                  one test module per source module
```

Existing `scripts/fetch_*.py` keep their command lines; their logic moves into the sources and the scripts become thin callers.

---

### Task 1: Package scaffold, config, dependencies

**Files:**
- Create: `src/tp/collect/__init__.py`, `src/tp/collect/datasets.py`, `config/collect.toml`, `tests/collect/__init__.py`, `tests/collect/test_datasets.py`
- Modify: `pyproject.toml` (add `prometheus-client>=0.20`, `lxml>=5`)

**Interfaces:**
- Produces: `@dataclass(frozen=True) Dataset(name: str, path: Path, key: tuple[str, ...], ts_col: str)`; `DATASETS: dict[str, Dataset]`; `dataset(name: str) -> Dataset`; `load_settings() -> dict` (parses `config/collect.toml`).

- [ ] **Step 1: Write failing tests** in `tests/collect/test_datasets.py`: `test_registry_has_every_planned_dataset` asserts `set(DATASETS)` equals `{"eightk", "earnings", "tenk_index", "form4", "xbrl_shares", "finra_shortvol", "finra_short_interest", "dod_awards", "trump_posts", "sp500_changes", "wikipedia_pageviews", "congress_trades"}`; `test_existing_datasets_keep_their_legacy_paths` asserts `dataset("eightk").path == config.DATA_DIR / "events" / "eightk.parquet"`, `dataset("earnings").path == config.DATA_DIR / "events" / "earnings.parquet"`, `dataset("form4").path == config.DATA_DIR / "insider" / "trades.parquet"`, `dataset("finra_shortvol").path == config.DATA_DIR / "finra" / "shortvol.parquet"`, `dataset("dod_awards").path == political.awards_path()`, `dataset("trump_posts").path == political.posts_path()`, `dataset("xbrl_shares").path == config.DATA_DIR / "xbrl" / "shares.parquet"`; `test_new_datasets_live_under_store` asserts the others are under `config.DATA_DIR / "store"`; `test_settings_have_ports_and_cap` asserts `load_settings()["metrics"]["port"] == 9120` and `["apify"]["monthly_cap_usd"] == 4.0`.
- [ ] **Step 2: Run** `uv run pytest tests/collect/test_datasets.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement** `datasets.py` with keys: eightk `("accession",)` ts `filed_at`; earnings `("accession",)` `filed_at`; tenk_index `("accn",)` `filed_at`; form4 `("trade_id", "owner_cik")` `filing_date`; xbrl_shares `("accn", "symbol")` `filed`; finra_shortvol `("date", "symbol")` `date`; finra_short_interest `("settlement_date", "symbol")` `settlement_date`; dod_awards `("award_id", "action_date", "amount")` `action_date`; trump_posts `("source", "id")` `ts`; sp500_changes `("effective_date", "added", "removed")` `effective_date`; wikipedia_pageviews `("date", "article")` `date`; congress_trades `("source_id",)` `ts`. Write `config/collect.toml` with `[metrics] port = 9120`, `[apify] monthly_cap_usd = 4.0 daily_run_cap_usd = 0.05`, and a `[sources.<name>]` table per source holding `schedule` text (`daily 18:30 America/New_York`, `weekly sun 09:00`, `every 1d`) and `lag_minutes`.
- [ ] **Step 4: Run** the tests → PASS; run `uv sync` and `uv run pytest -q` → all green.
- [ ] **Step 5: Commit** `git commit -m "Scaffold tp.collect: dataset registry and settings"`.

---

### Task 2: Writer and store with the holdout guard

**Files:**
- Create: `src/tp/collect/store.py`, `tests/collect/test_store.py`

**Interfaces:**
- Consumes: `Dataset` from Task 1.
- Produces: `write(ds: Dataset, frame: pd.DataFrame, now: datetime | None = None) -> int` returns the number of NEW rows; `read(ds: Dataset, since: pd.Timestamp | None = None, until: pd.Timestamp | None = None, holdout: bool = False) -> pd.DataFrame`; `class HoldoutError(Exception)`.

- [ ] **Step 1: Failing tests** in `tests/collect/test_store.py` (use `tmp_path` and a `Dataset` pointing into it): `test_write_dedupes_on_key_and_new_rows_win` (write 3 rows, write 2 overlapping with a changed value → file has 4 rows, overlapping row holds the new value, return value 1); `test_empty_frame_writes_nothing` (no file created, returns 0); `test_write_is_atomic` (monkeypatch `os.replace` to raise; afterwards no `*.tmp` file and the previous file is unchanged); `test_ingested_at_is_added_once` (old rows keep their original `ingested_at`, new rows get `now`); `test_future_timestamps_are_rejected` (rows with `ts_col` after `now + 1 day` are dropped and logged, return counts only kept rows); `test_read_refuses_holdout` (`read(ds, until=Timestamp("2025-01-01"))` raises `HoldoutError`; `read(ds)` with no `until` also raises when the data reaches 2025 unless `holdout=True`; with data only to 2024 `read(ds)` works); `test_read_filters_since_until`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `store.py`. Merge = concat old and new, `drop_duplicates(ds.key, keep="last")`, sort by `ts_col`, write to `<path>.tmp` then `os.replace`. A missing or unreadable (corrupt) existing file: raise `StoreError` rather than overwrite it. `read` applies the holdout rule against `config.HOLDOUT_START` using `ts_col`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the atomic dataset writer and holdout-guarded reader`.

---

### Task 3: Source protocol, schedules, state

**Files:**
- Create: `src/tp/collect/source.py`, `src/tp/collect/state.py`, `tests/collect/test_source.py`

**Interfaces:**
- Consumes: `Dataset`, `store.write`.
- Produces:
  - `class SourceError(Exception)`; `class RateLimited(SourceError)` (carries `retry_after_s: float`).
  - `@dataclass RunContext: now: datetime; settings: dict; writer: Callable[[Dataset, pd.DataFrame], int]`.
  - `class Source` with attributes `name: str`, `rate_group: str`, `schedule: Schedule`, `lag: timedelta`, and `def run(self, ctx: RunContext) -> int` (default: calls `self.fetch(ctx)` which returns `dict[Dataset, pd.DataFrame]`, writes each via `ctx.writer`, returns total new rows). Subclasses override `fetch` (or `run`).
  - `parse_schedule(text: str) -> Schedule`; `Schedule.next_after(t: datetime) -> datetime`; kinds `Daily(at, tz)`, `Weekly(weekday, at, tz)`, `Every(timedelta)`.
  - `State` (`load(path)`, `record_success(name, now, rows)`, `record_failure(name, now, error)`, `last_success(name) -> datetime | None`, `failures(name) -> int`, `backoff_until(name) -> datetime | None`), persisted atomically as JSON at `data/collect/state.json`.

- [ ] **Step 1: Failing tests:** `test_parse_schedule_kinds` (the three texts in Task 1 parse); `test_daily_next_after_is_wall_clock_across_dst` (`Daily(18:30, America/New_York)`: the run after 2026-03-07 19:00 UTC is 2026-03-08 18:30 EDT = 22:30 UTC, and after 2026-11-01 23:00 UTC is 2026-11-02 18:30 EST = 23:30 UTC); `test_weekly_next_after`; `test_every_next_after`; `test_source_run_writes_every_frame_and_sums_rows` (fake source returning two datasets; fake writer returns len); `test_state_roundtrip_and_atomic` (write, reload equal; monkeypatched `os.replace` failure keeps the old file).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the three modules. Use `zoneinfo` for DST-correct wall-clock times.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the Source protocol, schedules, and run state`.

---

### Task 4: Scheduler

**Files:**
- Create: `src/tp/collect/scheduler.py`, `tests/collect/test_scheduler.py`

**Interfaces:**
- Consumes: `Source`, `State`, `RunContext`, `RateLimited`.
- Produces: `class Scheduler(sources: list[Source], state: State, settings: dict, clock: Callable[[], datetime], sleep: Callable[[float], Awaitable[None]], writer)` with `def due(self) -> list[Source]` and `async def tick(self) -> list[RunResult]` (runs everything due; one source at a time per `rate_group`, different groups concurrently); `@dataclass RunResult(source: str, ok: bool, rows: int, seconds: float, error: str | None)`.
  Backoff: after a failure the next try is `min(60 * 2**failures, 6 * 3600)` seconds later; `RateLimited.retry_after_s` overrides when larger.

- [ ] **Step 1: Failing tests** with a fake clock and fake sources: `test_never_run_source_is_due`; `test_source_runs_once_after_a_long_sleep` (clock jumps 3 days past a daily schedule: one run, not three; next due is the next future slot); `test_one_failure_does_not_block_other_sources`; `test_same_rate_group_runs_serially` (two sources in group `sec` never overlap, recorded by an event log); `test_rate_limit_backs_off_only_its_group` (a `RateLimited(retry_after_s=600)` from an `sec` source delays other `sec` sources but a `finra` source still runs); `test_backoff_grows_and_caps`; `test_success_resets_failures`; `test_exception_inside_source_is_caught_and_recorded`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `Scheduler`. Sources run in worker threads (`asyncio.to_thread`) because they use blocking `httpx`; the group lock is an `asyncio.Lock` per group.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the scheduler with rate groups, backoff, and catch-up`.

---

### Task 5: Metrics

**Files:**
- Create: `src/tp/collect/metrics.py`, `tests/collect/test_metrics.py`

**Interfaces:**
- Consumes: `RunResult`, `State`.
- Produces: `class Metrics(registry=None)` with `record_run(result: RunResult)`, `set_age(source: str, seconds: float)`, `set_qa(source: str, check: str, failures: int)`, `set_disk_free(bytes: int)`, `set_apify_spend(usd: float)`, `serve(port: int)`; metric names exactly `sift_source_last_success_age_seconds{source}`, `sift_source_rows_total{source}`, `sift_source_errors_total{source}`, `sift_source_run_seconds{source}`, `sift_qa_failures{source,check}`, `sift_disk_free_bytes`, `sift_apify_spend_usd_month`.

- [ ] **Step 1: Failing tests** on a private `CollectorRegistry`: `test_record_run_counts_rows_and_errors` (ok run adds rows; failed run adds one error and no rows); `test_age_and_qa_gauges_are_labelled`; `test_metric_names_match_the_alert_rules` (every `sift_*` name used in `deploy/sift_alerts.yml`, once Task 15 creates it, exists in the registry; skip with a clear message if the file is absent so this task passes alone).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** with `prometheus_client`. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add Prometheus metrics for the recorder`.

---

### Task 6: Daemon and CLI

**Files:**
- Create: `src/tp/collect/daemon.py`, `src/tp/collect/cli.py`, `src/tp/collect/__main__.py`, `tests/collect/test_daemon.py`

**Interfaces:**
- Consumes: Scheduler, Metrics, store.write, `load_settings`, a `build_sources(settings) -> list[Source]` registry function in `src/tp/collect/sources/__init__.py` (returns `[]` until later tasks add sources; each source task appends itself).
- Produces: `async def run(settings, sources, *, clock, sleep, stop: asyncio.Event) -> None` (tick every 30 s, update age gauges, disk gauge, flush on stop); `acquire_lock(path) -> IO` raising `AlreadyRunning`; CLI commands `run`, `once <source>`, `qa [--date]`, `status` (prints each source's last success, failures, next due).

- [ ] **Step 1: Failing tests:** `test_second_daemon_refuses_to_start` (two `acquire_lock` on one path: second raises `AlreadyRunning`); `test_stop_event_ends_the_loop_after_the_current_tick`; `test_once_runs_a_single_named_source_and_updates_state`; `test_status_lists_every_registered_source`; `test_unknown_source_name_exits_with_a_message`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** SIGTERM/SIGINT set the stop event (launchd sends SIGTERM). **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the recorder daemon and CLI`.

---

### Task 7: QA

**Files:**
- Create: `src/tp/collect/qa.py`, `tests/collect/test_qa.py`

**Interfaces:**
- Consumes: `DATASETS`, `store.read` (with `holdout=True` for QA only, which never feeds a study), `tp.store`/`tp.bars.load_bars` for price series, `State`, `Metrics`.
- Produces: `run_qa(now: datetime, state: State, settings: dict) -> dict` returning `{"date": str, "sources": {name: {"checks": {check: {"ok": bool, "detail": str}}}}}` and writing `data/qa/<YYYY-MM-DD>.json`; check names exactly `freshness`, `duplicates`, `future_timestamps`, `schema`, `row_count`, and for the price store `calendar_completeness`, `price_jumps`.

- [ ] **Step 1: Failing tests with seeded defects:** `test_stale_source_fails_freshness` (last success older than 2× the schedule interval); `test_duplicate_keys_are_caught`; `test_future_timestamp_is_caught`; `test_schema_drift_is_caught` (column missing versus the dataset's previous schema stored in the QA state); `test_row_count_collapse_is_caught` (today's rows under 30% of the trailing median); `test_missing_trading_day_fails_calendar_completeness` (a bar series missing one SPY session); `test_jump_above_100_percent_is_flagged_as_probable_missing_split` (+200% close-to-close) and `test_drop_below_minus_50_percent_is_flagged`; `test_clean_data_passes_everything`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** reusing the +100%/−50% rule from the spec; write the report atomically. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the daily QA job`.

---

### Task 8: `alpaca_bars` source

**Files:**
- Create: `src/tp/collect/sources/alpaca_bars.py`, `tests/collect/test_alpaca_bars.py`
- Modify: `src/tp/collect/sources/__init__.py` (register)

**Interfaces:**
- Consumes: `tp.recorder.build_plan`, `run_plan`, `corp_actions.sync_splits`, `AlpacaClient`.
- Produces: `class AlpacaBars(Source)` named `alpaca_bars`, rate group `alpaca`, schedule `daily 21:00 America/New_York`, lag 20 min; `run(ctx)` syncs `universe="all"` with 4 workers and returns the number of bars added; raises `SourceError` listing failures when any series failed. It always uses `universe="all"` because `sync_splits` overwrites the splits store with only the planned symbols (a documented hazard in the Task notes of `tp.recorder`).

- [ ] **Step 1: Failing tests** with a fake `AlpacaClient` (as in `tests/test_recorder.py`): `test_run_always_plans_the_full_universe` (asserts `build_plan` was called with `"all"` and splits were synced for every universe symbol); `test_failed_series_raise_source_error_with_names`; `test_does_not_request_past_now_minus_lag` (asserts the end passed equals `fetch_end(...)`); `test_returns_bars_added`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the Alpaca bars source`.

---

### Task 9: SEC filings source (8-K, earnings, 10-K index)

**Files:**
- Create: `src/tp/collect/sources/sec.py`, `tests/collect/test_sec_filings.py`
- Modify: `src/tp/edgar.py` (add `refresh: bool = False` to `EdgarClient._get_json`, which then ignores the cache and rewrites it); `scripts/fetch_eightk.py`, `scripts/fetch_earnings.py` (call the shared functions); `sources/__init__.py`

**Interfaces:**
- Consumes: `EdgarClient`, `parse_eightk`, `parse_earnings`, `parse_tenk`, `Dataset`s `eightk`, `earnings`, `tenk_index`.
- Produces: `class SecFilings(Source)` named `sec_filings`, rate group `sec`, schedule `daily 07:30 America/New_York`; refreshes each universe symbol's submissions JSON (one request per CIK, 3 a second), then returns frames for the three datasets (`symbol`, `cik`, plus each parser's columns). A 429/403 raises `RateLimited(retry_after_s=600)`.

- [ ] **Step 1: Failing tests** on a fake HTTP client with recorded submission JSON fixtures: `test_new_8k_appears_after_refresh` (cache holds old JSON, fake server returns one more 8-K → the frame contains it); `test_cache_is_replaced_when_refreshing`; `test_http_429_raises_rate_limited_with_retry_after`; `test_symbol_without_cik_is_skipped_and_reported_not_fatal`; `test_scripts_still_produce_the_same_8k_columns` (columns equal `["symbol","accession","filed_at","items"]`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the SEC filings source with submission refresh`.

---

### Task 10: SEC Form 4 and XBRL share counts

**Files:**
- Modify: `src/tp/collect/sources/sec.py`; `scripts/fetch_insider.py`, `scripts/fetch_shares.py` (call shared functions); `sources/__init__.py`
- Test: `tests/collect/test_sec_bulk.py`

**Interfaces:**
- Produces: `class SecForm4(Source)` named `sec_form4`, group `sec`, `daily 08:00 America/New_York`: downloads any finished quarter's `form345.zip` not yet parsed (404 = not published yet, a normal skip), returns the `form4` frame (reuses `insiders.parse_quarter`). `class SecXbrlShares(Source)` named `sec_xbrl_shares`, group `sec`, `weekly sun 09:00 America/New_York`: re-reads company facts per symbol, returns the `xbrl_shares` frame with columns `symbol, cik, accn, form, filed, end, val`.

- [ ] **Step 1: Failing tests:** `test_unpublished_quarter_is_skipped_without_error` (fake 404); `test_parsed_quarters_are_not_downloaded_again`; `test_truncated_zip_raises_source_error_and_writes_nothing`; `test_xbrl_rows_keep_only_10k_10q`; `test_xbrl_404_for_a_symbol_gives_empty_frame_not_failure`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the Form 4 and XBRL share-count sources`.

---

### Task 11: FINRA short volume and short interest

**Files:**
- Create: `src/tp/collect/sources/finra.py`, `tests/collect/test_finra.py`
- Modify: `scripts/fetch_finra.py` (calls `fetch_day` from the new module); `sources/__init__.py`

**Interfaces:**
- Produces: `fetch_day(http, day, symbols) -> pd.DataFrame | None` (moved from the script, unchanged behavior); `class FinraShortVolume(Source)` named `finra_shortvol`, group `finra`, `daily 18:30 America/New_York`, lag 0 (files post by 18:00 ET): fetches weekdays after the stored max date through yesterday, skipping known no-file days; `class FinraShortInterest(Source)` named `finra_short_interest`, group `finra`, `daily 09:00 America/New_York`: for each settlement date (15th and last business day of each month, from 2017-12-29) not yet stored and at least 10 business days old, downloads `https://cdn.finra.org/equity/otcmarket/biweekly/shrt{YYYYMMDD}.csv`, keeps universe symbols, adds `settlement_date`.

- [ ] **Step 1: Failing tests:** `test_fetch_day_returns_none_on_403_and_404`; `test_fetch_day_filters_to_universe_symbols_and_parses_date`; `test_shortvol_fetches_only_missing_weekdays`; `test_shortvol_records_no_file_days_so_they_are_not_retried`; `test_short_interest_waits_ten_business_days`; `test_short_interest_skips_stored_settlement_dates`; `test_short_interest_missing_file_is_not_an_error_before_it_is_due`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the FINRA short volume and short interest sources`.

---

### Task 12: DoD awards, posts, S&P 500 changes

**Files:**
- Create: `src/tp/collect/sources/political.py`, `src/tp/collect/sources/sp500.py`, `tests/collect/test_political_sources.py`, `tests/collect/test_sp500.py`
- Modify: `scripts/fetch_political.py` (calls the shared functions); `sources/__init__.py`

**Interfaces:**
- Produces: `class DodAwards(Source)` `dod_awards`, group `usaspending`, `weekly mon 06:00 America/New_York`, uses the incremental `fetch_awards(http, since)` moved from the script; `class TrumpPosts(Source)` `trump_posts`, group `posts`, `daily 07:00 America/New_York`, re-fetches the CNN Truth Social parquet (tweets 2016–2018 come once from the bpb27 archive and are not re-fetched); `class Sp500Changes(Source)` `sp500_changes`, group `wikipedia`, `weekly sun 10:00 America/New_York`: parses table `id="changes"` of `Historical_components_of_the_S&P_500` with `pandas.read_html`, columns `effective_date, added, removed, reason`; announcement dates are not available yet (documented in the module docstring, left for a later task).

- [ ] **Step 1: Failing tests** on fixtures: `test_awards_since_refetches_from_the_last_month_and_dedupes`; `test_posts_drop_reposts_and_empty_text`; `test_sp500_parses_added_and_removed_tickers_from_fixture_html`; `test_sp500_layout_change_raises_source_error_not_empty_success` (a page without the table must fail loudly).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add DoD awards, posts, and S&P 500 change sources`.

---

### Task 13: Wikipedia pageviews

**Files:**
- Create: `src/tp/collect/sources/wikipedia.py`, `config/wikipedia_articles.toml`, `scripts/build_wikipedia_map.py`, `tests/collect/test_wikipedia.py`
- Modify: `sources/__init__.py`

**Interfaces:**
- Produces: `class WikipediaPageviews(Source)` `wikipedia_pageviews`, group `wikimedia`, `daily 06:30 UTC`: for each `symbol -> article` in the reviewed map, fetches daily user views up to the previous UTC day from `https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{article}/daily/{start}/{end}`, start 2015-07-01 on the first run, then from the last stored date; returns columns `date, symbol, article, views`. `build_wikipedia_map.py` proposes articles from `asset` names for the sf universe and writes a CANDIDATE file for human review; the source reads only the reviewed `config/wikipedia_articles.toml` and ignores symbols without an entry.

- [ ] **Step 1: Failing tests:** `test_first_run_starts_2015_07_01_and_later_runs_start_after_last_date`; `test_never_requests_today_or_future_days`; `test_404_article_is_reported_and_skipped_not_fatal`; `test_unmapped_symbols_are_ignored`; `test_rate_stays_under_ten_requests_a_second`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (initial map: the 150 `events` symbols; the human reviews it before the source is enabled in `collect.toml`). **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the Wikipedia pageviews source`.

---

### Task 14: Congress trades via Apify, with a spend guard

**Files:**
- Create: `src/tp/collect/sources/congress.py`, `tests/collect/test_congress.py`
- Modify: `sources/__init__.py`

**Interfaces:**
- Consumes: `docs/research/data-sources.md` (the actor names tested on 2026-11-12), settings `apify.monthly_cap_usd`, `apify.daily_run_cap_usd`.
- Produces: `class CongressTrades(Source)` `congress_trades`, group `apify`, `daily 08:30 America/New_York`; `class SpendLedger(path)` with `month_total(now) -> float`, `add(now, usd)`, `allowed(now, planned_usd) -> bool` (False once `month_total + planned_usd > 0.8 * 5.0`); the source starts the actor with `maxTotalChargeUsd = daily_run_cap_usd`, reads the dataset, records the actual cost from the run object, and raises `SourceError` (never logs the key or response headers) on any failure.

- [ ] **Step 1: Failing tests** with a fake Apify HTTP client: `test_run_is_refused_when_the_month_would_pass_80_percent_of_the_credit` (no HTTP call made); `test_every_run_sets_a_max_charge`; `test_actual_cost_is_added_to_the_ledger`; `test_api_key_never_appears_in_logs_or_exception_text` (capture logging at DEBUG, raise a failure whose body contains the key, assert the key string is absent everywhere); `test_rows_get_ingested_at_and_no_backfill_is_attempted`; `test_ledger_persists_across_restarts`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** using `httpx` and the Bearer header from `Settings`, with a log filter that redacts the key. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the Congress trades source with an Apify spend guard`.

---

### Task 15: launchd install, alert rules, acceptance

**Files:**
- Create: `src/tp/collect/tools/local_stack.py`, `deploy/sift_alerts.yml`, `docs/recorder-runbook.md`, `tests/collect/test_local_stack.py`, `tests/collect/test_alerts.py`
- Modify: `README.md` (a short "Recorder" section linking the runbook)

**Interfaces:**
- Consumes: Metrics names from Task 5.
- Produces: `local_stack.py install [--dry-run] | status | uninstall` creating `com.sift.recorder` (KeepAlive, Interactive, `uv run python -m tp.collect run`) and `com.sift.qa` (daily 06:15 local, Background, `uv run python -m tp.collect qa`) in `~/Library/LaunchAgents`, logs in `data/logs/`; `deploy/sift_alerts.yml` rules `SiftSourceStale` (`sift_source_last_success_age_seconds > 2 * <schedule seconds>` per source via a labelled threshold metric or per-rule constants), `SiftSourceErrors` (`increase(sift_source_errors_total[1h]) > 3`), `SiftQaFailing` (`sift_qa_failures > 0`), `SiftDiskLow` (`sift_disk_free_bytes < 10e9`), `SiftTargetDown` (`up{job="sift"} == 0` for 2m), `SiftApifySpendHigh` (`sift_apify_spend_usd_month > 4.0`).

- [ ] **Step 1: Failing tests:** `test_plists_have_keepalive_label_and_working_directory_and_no_secrets` (plist dicts built in memory, no `launchctl`; asserts no value contains `APIFY` or `ALPACA` strings); `test_dry_run_writes_nothing`; `test_every_alert_metric_exists_in_metrics_module`; `test_alert_rules_parse_as_yaml_with_required_fields`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** modelled on `quantstack-data/app/p2-recorder/tools/local_stack.py` (read it; do not import it). The runbook covers install, status, uninstall, what each alert means, and what to do when the Mac was asleep.
- [ ] **Step 4: Run** the full suite: `uv run pytest -q` → all green.
- [ ] **Step 5: Commit** `Add the launchd installer, alert rules, and runbook`.
- [ ] **Step 6: Wire the monitoring (needs the user's go-ahead):** show the user the exact diff for quantstack's `prometheus.yml` (a `sift` scrape job targeting `127.0.0.1:9120`) and `rule_files` line (`<repo>/deploy/sift_alerts.yml`), apply it only after a yes, then `curl -s localhost:9090/api/v1/targets` shows the job `up` and `sift_*` series appear.
- [ ] **Step 7: Acceptance (a week, not a single run):** `local_stack.py install --dry-run`, then install; after 7 days with no human action, `status` shows every enabled source fresh, `data/qa/*.json` has no unexplained failure, and one deliberately stopped daemon (`launchctl stop com.sift.recorder`) produced a Telegram alert and recovered by itself. Record the result in `docs/recorder-runbook.md`.

---

## Self-Review

- **Spec coverage:** daemon/scheduler (3, 4, 6), Source protocol (3), store and holdout guard (2), QA incl. +100%/−50% (7), metrics and alerts (5, 15), launchd (15), Apify guard (14), all nine sources (8–14), quantstack monitoring reuse (15 step 6), testing section (fault tests inside tasks 2, 4, 9–11, 14), phases (tasks 1–8 = phase 1, 9–12 = phase 2, 11 short interest + 12 S&P + 13 = phase 3, 14 = phase 4). The `lag` rule is in Tasks 3 and 8. Gap: no Grafana (explicitly out of scope).
- **Type consistency:** `Dataset`, `RunContext`, `RunResult`, `Source.run/fetch`, `State` methods, `Metrics` method names are defined once and reused unchanged.
- **Proportion:** the plan lists signatures and test names; no function bodies except where the spec fixes values.
