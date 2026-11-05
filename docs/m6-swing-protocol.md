# M6 protocol: daily-bar swing strategies (pre-registered)

Committed before the sweep runs. Same discipline as `docs/m4-protocol.md` and `docs/m4b-protocol.md`; only what is
listed here differs.

## Why

Every intraday idea tried so far (opening-range breakout and fade, M4 and M4b) failed. The cost diagnostic showed
the breakout has no gross edge (zero-cost expectancy -0.020R +-0.028), so this is **not** a cost fix. It is a new
hypothesis from a different family: short-term mean reversion and trend pullbacks on daily bars, which are the
other ideas on the original list (RSI(2) reversion; the 20/200-day moving-average pullback). Published evidence
for these is old (RSI(2) is from 2008) and decay is unmeasured, so a null result is a live possibility.

## What is tested

Two strategies on the same 50 stocks as M4b (top by Q1-2016 dollar volume), 2016-2024 daily bars:

| Family | Rule (decided at the close, entered at the next open) |
|---|---|
| `rsi2` | Long when the 2-day RSI is at or below `rsi_low`, short when at or above 100 - `rsi_low`; optionally only with the 200-day trend (longs above the SMA, shorts below) |
| `pullback` | In an uptrend (20-day SMA above `sma_slow`, rising over 5 days, close above `sma_slow`), long on the first close back to the 20-day SMA (within `touch_atr` ATRs); mirrored for shorts |

Both use a stop at `stop_atr` x ATR(14), a target at 1.5R, and a time exit after `max_hold` sessions. The grid is
in `config/sweeps/m6-swing.toml`: 24 `rsi2` and 16 `pullback` configurations, 40 in all, frozen by this commit.

## The engine

`tp.swing`: next-session-open entry plus slippage, overnight gaps fill at the open, a session touching both stop and
target counts as a loss, targets need a trade-through, a time exit is market-on-close on the last session of the
hold, slippage is as-traded dollars scaled by the split factor. It matches an independent re-derivation of 400
random trades from real daily bars with zero differences.

## Unchanged

Development period 2016-01-04 to 2024-12-31, **2025+ holdout untouched**, test years 2019-2024, walk-forward
selection on mean R minus one standard error with at least 200 training trades, and **the same six pass criteria
with the same thresholds**, evaluated per family: 300 out-of-sample trades, expectancy CI lower bound above 0,
Deflated Sharpe at least 0.95, positive in 4 of 6 years, positive at double slippage, 70% of the modal
configuration's neighbours positive. The Deflated Sharpe trial count is every trial in the registry: the 137
earlier trials plus these 40.

## If a family passes

Its modal configuration is frozen and run once on the holdout (`--use-holdout`), reported whatever it shows. Only
then does the paper loop get a real strategy. A fail closes that family in this form.

## Limits

- **Dividends are not modelled.** Bars are split-adjusted only. An ex-dividend drop inside a hold counts against a
  long and for a short; this is small for week-long holds but it is a bias. Borrow fees on shorts are also not
  modelled.
- **Clustered signals.** Mean-reversion signals fire together in market sell-offs, so trades are not independent
  and the confidence intervals understate the uncertainty.
- **Survivors.** The universe is listed today; companies that failed since 2016 are absent.
- **Daily-bar fills.** A daily bar cannot show the order of events inside a session; the stop-first rule is
  conservative, but overnight gaps can be larger than any stop.
- **Universe reuse.** These stocks were used in M4b for a different strategy. That does not leak into this test,
  but it does mean they are no longer fresh data for the project as a whole.
