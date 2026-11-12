# Recorder runbook

The recorder (`tp.collect`) is one daemon plus one daily QA job, both launchd user agents on this Mac. It writes under
`data/`, serves Prometheus metrics on `127.0.0.1:9120` and alerts through quantstack's Prometheus and Alertmanager
(Telegram). Run every command below from the repo root.

## Install

The agents run the project venv's interpreter directly (`.venv/bin/python -m tp.collect ...`), with no `uv` in between,
so the process launchd tracks is the daemon itself. Build that venv first, then check without changing anything:

```sh
uv sync --frozen --no-dev
uv run python -m tp.collect.tools.local_stack install --dry-run
```

It prints the preflight result (errors stop the install, warnings do not), then the two plists it would write and the
`launchctl` commands it would run. Preflight checks that `.venv/bin/python` exists and is executable (otherwise it says to run `uv sync --frozen --no-dev` first), the data directory is writable, at least 10 GB
is free (20 GB warns), port 9120 is free, and `.env` has `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` and
`SEC_USER_AGENT`. It reports a missing key by name only and never prints a value. `APIFY_API_KEY` is only required while
`congress_trades` is enabled. The plists contain no secrets: the tools read `.env` themselves and the only environment
variable set is `PATH`.

Then install:

```sh
uv run python -m tp.collect.tools.local_stack install
```

| Agent | What it does | Log |
| --- | --- | --- |
| `com.sift.recorder` | `.venv/bin/python -m tp.collect run`, restarted by launchd whenever it exits (KeepAlive, Interactive) | `data/logs/collect-recorder.log` |
| `com.sift.qa` | `.venv/bin/python -m tp.collect qa` every day at 06:15 local time (Background) | `data/logs/collect-qa.log` |

Installing again is safe: loaded agents are stopped and loaded again.

After pulling new code or changing dependencies, rebuild the venv and restart the daemon (the daemon is the launchd pid,
so this restarts exactly it):

```sh
uv sync --frozen --no-dev
launchctl kickstart -k gui/$(id -u)/com.sift.recorder
```

Check that no `uv` parent remains: `pgrep -f 'tp.collect run'` must print exactly one pid, and
`ps -o ppid= -p <that pid>` must print `1` (its parent is launchd).

## Status

```sh
uv run python -m tp.collect.tools.local_stack status   # launchd state of both agents
uv run python -m tp.collect status                      # per source: last success, failures, next due time
curl -s 127.0.0.1:9120/metrics | grep '^sift_'          # the exported series
```

## Uninstall

```sh
uv run python -m tp.collect.tools.local_stack uninstall
```

Stops both agents and deletes their plists. `data/` (datasets, state, QA reports, logs) is kept.

## Alerts

All rules are in `deploy/sift_alerts.yml`.

| Alert | Severity | Meaning | First thing to check |
| --- | --- | --- | --- |
| `SiftTargetDown` | critical | Prometheus cannot scrape `127.0.0.1:9120` for 2 minutes: the daemon is stopped or crash-looping. | `local_stack status`, then the tail of `data/logs/collect-recorder.log`. If the agent is loaded but misbehaving, `launchctl kickstart -k gui/$(id -u)/com.sift.recorder` restarts it. kickstart only works on a loaded service: after a `bootout` or `uninstall`, run `local_stack install` instead. |
| `SiftSourceStale` | warning | A source's last success is older than its allowed age (`sift_source_stale_after_seconds`, derived from its schedule) for 10 minutes. | `python -m tp.collect status`, then the source's error lines in the log. |
| `SiftSourceErrors` | warning | More than 3 failed runs of one source in an hour. | The error text in `data/logs/collect-recorder.log` (rate limit, changed page layout, network). |
| `SiftQaFailing` | warning | A QA check has failed for 30 minutes. | The newest `data/qa/<date>.json`: each failed check lists its offending rows. |
| `SiftQaStale` | warning | The newest scheduled QA report is over two days old, or none exists, for 30 minutes. Only evaluated while the daemon is up, so a stopped daemon pages once (`SiftTargetDown`), not twice. | `launchctl print gui/$(id -u)/com.sift.qa` and `data/logs/collect-qa.log`. It also fires on a fresh install until the first 06:15 run; run `uv run python -m tp.collect qa` once to clear it. |
| `SiftDiskLow` | warning | Under 10 GB free where `data/` lives. | `df -h data`; free space or move the data directory. |
| `SiftApifySpendHigh` | warning | Apify spend this month is over $4 (the $5 credit minus headroom); the daemon reads it from `data/collect/apify_spend.json` every tick, even while `congress_trades` is disabled (no ledger means 0). | Set `enabled = false` for `congress_trades` in `config/collect.toml`, restart the agent, and check the Apify console. |

## After the Mac slept

Nothing to do. The daemon computes what is due from `data/collect/state.json` when it wakes, so each source runs once
to catch up, within its own `lag_minutes` rule (it never asks for data newer than now minus the lag). Expect brief
`SiftSourceStale` or `SiftTargetDown` alerts while it catches up. The 06:15 QA job runs on wake if the Mac was asleep at
06:15. If a source is still stale a few minutes after wake, run `python -m tp.collect once <name>` (see below).
Prometheus and Alertmanager sleep with the Mac, so no alert can arrive while it is asleep.

## Running a source by hand

A disabled source stays off until you turn it on:

1. Set `enabled = true` under `[sources.<name>]` in `config/collect.toml`.
2. `uv run python -m tp.collect once <name>` runs it once and prints the new row count. It takes the same lock as the
   daemon and refuses to run while the daemon holds it, so stop the daemon first (`local_stack uninstall`;
   `launchctl stop` alone is not enough because launchd restarts it).
3. Check the rows with the QA job (`uv run python -m tp.collect qa --no-advance`, which changes no baseline).
4. Start the daemon again (`local_stack install`) so it picks up the config.

The manual scripts (`scripts/fetch_*.py`) that write under `data/` also refuse to run while the daemon runs; stop it first.

### Before enabling congress_trades (Apify, costs money)

1. In the Apify console set a monthly usage limit of $4. The daemon's own guard reads that limit and refuses to run
   without it.
2. Check the actor's real input schema and the field names the guard reads: the actor id, the input names
   (`lookbackDays`, `maxItems`) and the output field mapping all live in `[sources.congress_trades]` in
   `config/collect.toml`; the limits response must contain `data.current.monthlyUsageUsd` and
   `data.limits.maxMonthlyUsageUsd` (`GET /v2/users/me/limits`). Change the TOML if the actor differs. Every run is
   capped by `maxTotalChargeUsd` = `daily_run_cap_usd`.

### Before enabling wikipedia_pageviews

`scripts/build_wikipedia_map.py` writes `config/wikipedia_articles.candidates.toml`. Review every line (a name can match
a product, a person or a disambiguation page), copy the accepted ones under `[articles]` into the reviewed
`config/wikipedia_articles.toml`, and only then set `enabled = true`.

## Wiring Prometheus (needs the user's approval; nothing here is applied automatically)

quantstack's `deploy/local/prometheus.yml` (the file its launchd agent runs; under
`/Users/m6l9k/quantstack-data/app/p2-recorder/deploy/local/`) gets two additions: a `rule_files` entry and a scrape job.
The job must be named `sift`, because the alert rules match `up{job="sift"}`.

```diff
 rule_files:
   - ../alerts.yml
+  - /Users/m6l9k/.t3/projects/trading-pipeline/deploy/sift_alerts.yml
...
 scrape_configs:
   - job_name: recorder
     ...
+  - job_name: sift
+    static_configs:
+      - targets: ["127.0.0.1:9120"]
```

After applying it, restart quantstack's Prometheus agent (or `curl -X POST localhost:9090/-/reload` if lifecycle reload
is enabled), then:

```sh
curl -s localhost:9090/api/v1/targets | grep -o '"job":"sift"[^}]*"health":"[a-z]*"'   # health "up"
curl -s 'localhost:9090/api/v1/query?query=sift_disk_free_bytes'                        # a sample appears
promtool check rules deploy/sift_alerts.yml
```

## Testing the dead-man alert

Do not use `launchctl stop com.sift.recorder`: the agent has KeepAlive, so launchd relaunches it within seconds and
Prometheus never sees `up == 0`. Freeze the process instead, so the scrape hangs and `up` goes to 0. The daemon is the
launchd-tracked process, so the signal reaches it. Verify that before relying on the alert:

```sh
pgrep -f 'tp.collect run'        # exactly one pid, whose parent is launchd (ps -o ppid= -p <pid> prints 1)
launchctl kill SIGSTOP gui/$(id -u)/com.sift.recorder     # scrape hangs; SiftTargetDown fires after its 2m `for`
curl -s -m 5 http://127.0.0.1:9120/metrics                # must time out; if it still answers, the stop did not reach the daemon
# ... wait for the Telegram alert (about 3 to 4 minutes) ...
launchctl kill SIGCONT gui/$(id -u)/com.sift.recorder     # the daemon resumes; the alert resolves by itself
curl -s -m 5 http://127.0.0.1:9120/metrics | head -3      # answers again
```

`launchctl bootout gui/$(id -u)/com.sift.recorder` also triggers the alert, but it unloads the agent, so nothing brings
it back until `uv run python -m tp.collect.tools.local_stack install`. A frozen daemon may also raise `SiftSourceStale`
for every enabled source once the freeze outlasts their allowed ages; that is expected.

## Crash loops, respawns and alert grouping

- The recorder plist sets `ThrottleInterval` to 30, so a daemon that exits at startup (another instance holds
  `data/.collect.lock`, a bad config, a crash) is respawned at most every 30 seconds instead of launchd's default 10.
  Each respawn still writes a traceback to `data/logs/collect-recorder.log`, which is not rotated.
- There is no Sift equivalent of quantstack's `RecorderCrashLoop` alert: the custom metrics registry has no
  `process_start_time_seconds`. A crash loop shows up as a log file that keeps growing and as `SiftTargetDown`
  flapping (down for the `for: 2m`, up again, down). If you see that, read the tail of the log, fix the cause, or run
  `uninstall`.
- Alertmanager groups by `alertname` only for these alerts (the other group_by labels do not exist on Sift series), so
  one `SiftSourceStale` message lists every stale source. A hung but still serving daemon yields one `SiftSourceStale`
  alert per enabled source, all in that one message.

## 7-day acceptance checklist

Install, then touch nothing for 7 days apart from the one deliberate dead-man test. Accepted when all of these hold:

- [ ] `python -m tp.collect status` shows every enabled source fresh (a recent last success, 0 failures).
- [ ] `data/qa/*.json` has one report per day and no unexplained failure.
- [ ] The dead-man path works (see "Testing the dead-man alert" above): a hung daemon produced a Telegram
      `SiftTargetDown` alert, and after `SIGCONT` the alert resolved and the daemon was healthy again.
- [ ] No `SiftSourceStale` or `SiftQaStale` alert stayed open without a known cause.

Record the result here, with the dates, when done:

```text
Acceptance: not started
```
