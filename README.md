<img src="assets/icon.svg" width="64" height="64" alt="">

# Trading-Pipeline

Data -> signals -> backtest -> paper trading for short-term US stock strategies. Starts at $0: research and
paper trading only. Created in [T3 Code](https://t3.codes).

## Status

| Milestone | State |
|---|---|
| M0 decisions (universe, stack, accounts) | done |
| M1 data-depth probe | done, see below |
| M2 recorder (backfill + incremental sync, validation) | done |
| M3 backtest engine (signal -> bracket contract, costs, R-multiples) | next |
| M4 opening-range strategies | |
| M5 paper loop on Alpaca | |

## Setup

```sh
uv sync
cp .env.example .env        # then fill in the Alpaca paper keys; .env is gitignored
uv run pytest
```

## Data

Raw bars live in `data/bars/<feed>/<timeframe>/<symbol>/<utc year>.parquet` (gitignored). Bar timestamps are
the bar open, in UTC. Splits live in `data/corp_actions/splits.parquet`; prices are adjusted at read time so a
new split never invalidates stored history.

| Dataset | From | Why |
|---|---|---|
| `sip/1Min`, `sip/1Day` | 2016 | Consolidated tape. Backtest on this. Free tier, but the newest 15 minutes are withheld. |
| `iex/1Min` | 2020-07-27 | What a free real-time paper loop will see (about 4% of consolidated volume). Used to check that volume filters like RVOL still work on the live feed. |

```sh
uv run python -m tp.recorder                     # backfill + incremental sync (safe to re-run)
uv run python -m tp.recorder --symbols AAPL --specs sip:1Day
uv run python scripts/validate_bars.py           # integrity checks
uv run python scripts/probe_alpaca.py            # re-measure free-tier history depth
```

```python
from tp.bars import load_bars
df = load_bars("NVDA", feed="sip", timeframe="1Min", rth=True, resample="5min")  # split-adjusted by default
```

Coarser bars are derived from 1-minute bars (`resample="5min"`), not stored separately.

### Daily schedule (not installed)

`ops/launchd/com.tradingpipeline.recorder.plist` runs the recorder daily at 03:00 local time. To install:

```sh
cp ops/launchd/com.tradingpipeline.recorder.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.tradingpipeline.recorder.plist
```

To remove it: `launchctl unload ~/Library/LaunchAgents/com.tradingpipeline.recorder.plist`, then delete the file.

## M1 findings (AAPL, 2026-11-05)

- SIP 1m/5m history reaches 2016 with 100% bar coverage at yearly anchor weeks, free.
- IEX starts 2020-07-27 and carries about 4% of consolidated volume. One sample week (Mar 2025) was missing a day.
- Free-tier live latency was not tested; the assumption is IEX real time and SIP delayed 15 minutes.
- Decision: backtest on SIP, run the free paper loop on IEX with price-only triggers, and validate volume filters on IEX data.
