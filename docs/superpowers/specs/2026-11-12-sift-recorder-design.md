# Sift recorder: design

Status: draft for review, 2026-11-12. Nothing in this spec is built yet.

## Goal

Keep Sift's free data current and complete without anyone running scripts, and start collecting the data that has no free
history. The recorder is the same kind of system as the quantstack P2 recorder (collectors, one atomic Parquet writer,
daily QA, Prometheus metrics, Alertmanager to Telegram, launchd), scaled to Sift's volume: a few thousand rows a day, not
four hundred a second.

**Success:** (1) after a week with no human action every source is fresh, QA reports no unexplained gap, and a stopped or
failing source raises a Telegram alert within an hour; (2) the sealed 2025+ holdout stays sealed (the recorder stores later
data, but its read API refuses it); (3) the forward-only sources have a continuous record from the day they start.

## Decisions already made

- Reuse quantstack's Prometheus, Alertmanager and Telegram route on this Mac. Sift adds one scrape job and one rules file.
- No NATS. Collectors and the writer run in one process joined by an in-memory queue (quantstack's `recorder run` mode).
- Forward-only sources included: Congress trades via Apify, Wikipedia pageviews, FINRA short interest, S&P 500 index changes.
- Free only. Apify stays inside its $5 monthly credit with a hard cap in code.

## Architecture

```
scheduler daemon (asyncio, launchd KeepAlive)
  +- source: alpaca_bars        daily bars, splits (wraps tp.recorder)
  +- source: sec_filings        submissions refresh -> 8-K items, 10-K list; Form 4 quarterly; XBRL shares weekly
  +- source: finra_shortvol     daily after 18:00 ET
  +- source: finra_short_interest   twice a month, published ~7 business days after settlement
  +- source: dod_awards         weekly (USAspending)
  +- source: trump_posts        daily
  +- source: wikipedia_pageviews    daily, previous UTC day, per mapped article
  +- source: sp500_changes      weekly (Wikipedia table; announcement dates added later from press releases)
  +- source: congress_trades    daily, Apify, capped spend
        |  rows (pandas frames)
        v
   writer: one process, atomic Parquet (temp file then rename), zstd, hive partitions
        |
        +-> data store     data/store/<source>/<partition>/part.parquet
        +-> metrics        Prometheus /metrics on 127.0.0.1:9120
        +-> QA job (daily) per-source freshness, completeness, duplicates, anomalies -> data/qa/<date>.json
```

Package `tp.collect` in this repo (the existing `tp.recorder` stays and is called by the `alpaca_bars` source). Modules:
`daemon.py` (scheduler loop, signals, lock file), `source.py` (the Source protocol), `sources/*.py`, `writer.py`,
`store.py` (read API with the holdout guard), `qa.py`, `metrics.py`, `cli.py` (`run`, `once <source>`, `qa`, `status`),
`tools/local_stack.py` (launchd install, status, uninstall; a twin of quantstack's).

### The Source protocol

Every source is a small class: `name`, `schedule` (cron-like or interval), `lag` (never request data newer than now minus
this, the lesson from the Alpaca 403), `fetch(since) -> DataFrame` (idempotent; returns only rows after what the store
already holds, with a short overlap for late corrections), and `key` (columns that make a row unique, for dedupe).
The scheduler runs due sources one at a time per rate-limit group (SEC shares one budget), retries with backoff, and a
failed run leaves the store untouched. A catch-up after the Mac slept is the normal case, not an error.

### Store and the holdout guard

Parquet, zstd, one canonical frame per source with `ts` (when the event happened or the filing was accepted, UTC) and
`ingested_at` (when the recorder saw it). The second column is what makes forward-only sources point in time: it records
what was knowable when. `store.read(source, until=...)` raises if `until` reaches `config.HOLDOUT_START` unless the caller
passes the explicit holdout flag, so no new analysis can read 2025+ by accident. Writes of later data are allowed.

### QA (daily, like quantstack's `recorder qa`)

Per source: rows, duplicates (must be 0), freshness against the schedule, row-count anomalies, schema drift. Per price
series: completeness against the SPY trading calendar, and **one-session moves above +100% or below -50% flagged** as a
probable missing split, spin-off or special dividend (the M15 bug). Per event source: timestamps in the future, filings
with no acceptance time. A failed check is written to the QA report and exported as a metric.

### Metrics and alerts

`sift_source_last_success_age_seconds{source}`, `sift_source_rows_total`, `sift_source_errors_total`,
`sift_source_run_seconds`, `sift_qa_failures{source,check}`, `sift_disk_free_bytes`, `sift_apify_spend_usd_month`.
Alert rules (`deploy/sift_alerts.yml`, loaded by quantstack's Prometheus): source stale beyond twice its schedule, errors
rising, QA failing, disk under 10 GB, daemon target down, Apify spend above 80% of the cap. They reach Telegram through
the existing Alertmanager route. The always-firing `Watchdog` already pings healthchecks.io, which also covers a sleeping Mac.

### Operations

launchd agents `com.sift.recorder` (KeepAlive, Interactive) and `com.sift.qa` (daily, Background), installed by
`tp/collect/tools/local_stack.py install` after a `--dry-run`. The existing quantstack keep-awake agent keeps the Mac
awake. Secrets (`ALPACA_*`, `APIFY_API_KEY`, `SEC_USER_AGENT`) come from `.env` and are never logged or printed.
The one edit outside this repo is a scrape job and a `rule_files` line in quantstack's Prometheus config, made only
with your go-ahead and shown as a diff first.

## Apify safety

One actor run per day with `maxTotalChargeUsd` and item limits, a monthly spend counter stored next to the data, and a
refusal to start any run once 80% of $5 is spent. The `congress_trades` source checks the actor's current price before the
first run and stops if it exceeds the budget. Output is stored with its `ingested_at`; there is no backfill (no free history).

## Testing

- Unit tests per source on captured fixtures (FINRA file, SEC JSON, USAspending page, Wikipedia pageviews JSON).
- Scheduler tests with a fake clock: catch-up after sleep, backoff, rate-limit groups, one failure not blocking others.
- Fault tests: HTTP 403/429/500, truncated or partial downloads, a crash mid-write (no half file ever visible), a source
  returning duplicates or future timestamps.
- Store tests: dedupe, atomic writes, holdout guard.
- QA tests with seeded defects (missing day, +200% jump, duplicate rows, stale source) that must be caught.
- Plist and alert-rule consistency tests (every alert references a metric that exists), as in quantstack.

## Phases

1. **Core and bars:** daemon, writer, store, metrics, QA, launchd install, and the `alpaca_bars` source. Prove it with a
   week of unattended running.
2. **Existing event sources:** SEC filings, FINRA short volume, DoD awards, posts.
3. **New free sources:** FINRA short interest, S&P changes, Wikipedia pageviews.
4. **Apify Congress feed,** last, because it is the only one that costs anything.

## Out of scope

Live order flow, intraday tick storage, a database server, Grafana dashboards (quantstack's Grafana can read the same
Prometheus later), and any paid data source.

## Risks

- A sleeping or lid-closed Mac records nothing; the age metric and the healthchecks watchdog show it, catch-up recovers
  daily data, forward-only data from the missed window is lost.
- FINRA's file page states no licence: data stays local (`data/` is not committed).
- SEC rate limits are shared by all SEC sources, hence one rate group.
- Wikipedia article names change; the company-to-article map is a reviewed config file, not a guess.
