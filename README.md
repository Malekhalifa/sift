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
| M3 backtest engine (signal -> bracket contract, costs, R-multiples) | done |
| M4 opening-range filters, failed-breakout fade, walk-forward sweep | done: no strategy passed, see [docs/m4-results.md](docs/m4-results.md) |
| M4b breakout on a wider universe (50 stocks) | done: failed, significantly negative, see [docs/m4b-results.md](docs/m4b-results.md) |
| M6 daily-bar swing (RSI(2) reversion, 20/200 pullback) | done: failed, significantly negative, see [docs/m6-results.md](docs/m6-results.md) |
| M7 earnings-announcement drift (150 stocks, SEC filing times) | done: passes 5 of 6, fails Deflated Sharpe, not eligible; about half the raw gain is market drift, see [docs/m7-results.md](docs/m7-results.md) |
| M8 confirm the earnings-drift setting on 250 unseen stocks | done: did not replicate (+0.025R +-0.077), the lead is closed, see [docs/m8-results.md](docs/m8-results.md) |
| M9 original indicator strategies (UT Bot + STC, Supertrend + Waddah) | done: failed, clearly negative (-0.04R +-0.005), see [docs/m9-results.md](docs/m9-results.md) |
| M5 paper loop on Alpaca | plumbing done and tested, not scheduled; nothing to run for evidence until a strategy passes |

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

### Daily schedule (installed)

`ops/launchd/com.tradingpipeline.recorder.plist` runs the recorder daily at 03:00 local time (CET, which is
21:00 ET, after the extended session and the SIP delay). If the Mac was asleep, launchd runs it on wake, and
the recorder catches up on anything missed. Log: `data/logs/recorder.log`.

```sh
launchctl print gui/$(id -u)/com.tradingpipeline.recorder      # status
launchctl kickstart gui/$(id -u)/com.tradingpipeline.recorder  # run now
# remove:
launchctl bootout gui/$(id -u)/com.tradingpipeline.recorder && rm ~/Library/LaunchAgents/com.tradingpipeline.recorder.plist
```

## Backtesting

```sh
uv run python scripts/run_backtest.py --strategy orb --symbols AAPL,MSFT,NVDA --cost-sweep
uv run python scripts/run_backtest.py --strategy orb --set or_minutes=15 --set stop_mode=atr
```

A strategy turns bars into `Signal(side, entry_ref, stop, target)` on closed bars. `tp.backtest` then simulates
each signal and sizes the survivors. Conventions, chosen so a backtest cannot flatter the strategy:

- Entry is a market fill at the **next** bar's open plus slippage. Stop and target come from the signal bar's close, like a live bracket order.
- Stop exits pay slippage, and gaps through the stop fill at the open. Targets are limit orders that need price to trade through them.
- A bar touching both stop and target counts as a loss. Everything is flat by 15:55 ET.
- Slippage and trade-through are as-traded dollars, scaled by the split factor (bars are split-adjusted).
- Strategy quality is measured in R over every simulated trade. Portfolio results (return, drawdown, Sharpe) use the trades left after sizing (1% risk of compounding equity), the leverage cap and the position cap.

Overfitting guards:

- **Trial registry.** Every run is appended to `data/trials.sqlite`. The count per strategy feeds the Deflated Sharpe check.
- **Holdout.** Data from `config.HOLDOUT_START` (2025-01-01) is refused unless `--use-holdout` is passed, and such runs are flagged. Keep it for the final validation only.

Verification: 61 tests, plus an independent re-derivation of 300 random trades from raw bars with a separate loop (all matched).

### Baseline result (plumbing check, not a finding)

Unfiltered 5-minute ORB on AAPL, MSFT and NVDA, 2016-2024: expectancy +0.008R +-0.025 (95% CI), profit factor 1.02,
so no edge after costs, as expected before any filter. Zero slippage gives +0.024R and 3 cents gives -0.024R, so
costs decide it. The first run (trial 1) is in the registry with a slippage-scaling bug that overstated
costs on split-adjusted prices; trial 2 is the corrected run.

## Paper trading (plumbing only)

`tp.paper` runs the same strategy code as the backtest on live IEX bars and sends bracket orders to the Alpaca
**paper** account. No strategy has passed the protocol, so `config/paper/plumbing.toml` is a **machinery test**:
its trades are flagged `evidence = 0` and say nothing about any edge.

```sh
uv run python -m tp.paper --once      # one decision cycle on the current bar, then exit
uv run python -m tp.paper             # the full loop; DRY RUN by default (logs, sends nothing)
uv run python -m tp.paper --live      # sends orders to the paper account
uv run python scripts/paper_report.py # decisions, fills, slippage vs the backtest's assumption
touch data/KILL                       # kill switch: stops entries, flattens, exits (rm to re-arm)
```

How a cycle works: ~8 seconds after each 5-minute bar closes, it loads stored IEX history plus today's live bars,
runs `strategy.generate()` and keeps only signals decided on the bar that just closed. Each goes through guards
(kill file, daily loss cap, one position per symbol, max positions, max trades a day, no entries near flat time,
skip a stock for 20 days after a split), then sizing (fixed fraction of equity at the stop, leverage cap), then a
market order with an attached take-profit and stop-loss. Client order ids are deterministic, so a restart cannot
double-submit. At 15:55 ET it cancels working orders and closes positions. Everything goes to `data/paper.sqlite`.

What was verified, not just unit-tested:

- Replaying 30 real sessions on 5 symbols bar by bar (`scripts/paper_replay_check.py`): 135 signals, 0 differences from the backtest.
- Alpaca accepts our bracket format (`scripts/paper_smoke_order.py`, a limit order that cannot fill, placed and cancelled).
- A real 1-share paper round trip through the runner: fill, attached legs, flatten, and the exit recorded as `flat`.

Scheduling is a template, not installed: `ops/launchd/com.tradingpipeline.paper.plist` starts the loop on weekdays
at 14:00 local time (always before the open) and exits on holidays.

Free-feed caveat: live bars are IEX, which has gaps on quieter names (see the validator results). Names such as
AVGO, NFLX and GOOGL would miss bars; the live universe should be restricted to well-covered tickers.

## M1 findings (AAPL, 2026-11-05)

- SIP 1m/5m history reaches 2016 with 100% bar coverage at yearly anchor weeks, free.
- IEX starts 2020-07-27 and carries about 4% of consolidated volume. One sample week (Mar 2025) was missing a day.
- Free-tier live latency was not tested; the assumption is IEX real time and SIP delayed 15 minutes.
- Decision: backtest on SIP, run the free paper loop on IEX with price-only triggers, and validate volume filters on IEX data.
