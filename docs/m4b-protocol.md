# M4b protocol: the breakout on a wider universe (pre-registered)

Committed before the sweep runs. It tests the one idea from M4 that showed a faint, unproven tilt, on stocks it
has never seen. Same rules as `docs/m4-protocol.md`; only what is listed here differs.

## Why

M4 found no strategy that passed (`docs/m4-results.md`). The breakout was positive in 59% of its 54
configurations out of sample, but the filters left about 70 trades a year across ten stocks, so the result could
not be told apart from chance. More stocks means more trades and room for the relative-volume filter to select.
The fade is dropped: only 1 of its 24 configurations was positive out of sample.

## What is different from M4

- **Universe:** 50 stocks, chosen by a rule fixed before any strategy touched them: highest median dollar volume
  in Q1 2016 among listed NASDAQ/NYSE common stocks, excluding ETFs, ETNs, trusts, funds, ADRs, preferreds,
  warrants, share-class symbols and the ten M4 stocks (`scripts/select_universe.py`,
  `config/universe_wide.toml`). Alpaca's free history starts in January 2016, so Q1 2016 is the earliest ranking
  window available; it overlaps the first months of the test period, but only liquidity is used, never returns.
- **Strategy:** breakout only, the identical 54-configuration grid.
- **Data:** SIP 5-minute bars downloaded directly. They matched 1-minute bars resampled to 5 minutes on every
  open, high, low, close and volume in three samples (AAPL 2024, MSFT 2018, NVDA 2022).

## Unchanged

Period 2016-01-04 to 2024-12-31 with the 2025+ holdout untouched, test years 2019-2024, selection by mean R minus
one standard error with at least 200 training trades, fixed costs, sizing and fills, and **the same six pass
criteria with the same thresholds** (300 trades, CI lower bound above 0, Deflated Sharpe at least 0.95, positive
in 4 of 6 years, positive at double slippage, 70% of neighbours positive).

The Deflated Sharpe trial count is every trial in the registry: the 83 from M4, these 54, and the one regime
check. M4 trials count even though the universe differs. That is deliberate, because we are still searching.

## Reporting

Results are reported alongside M4's, not merged with them. A pass here still needs the one-shot holdout run
(`--use-holdout`) on the frozen modal configuration before any paper trading for evidence. A fail ends the
opening-range breakout as a candidate in this form.

## Limits

- **Survivors only.** Every symbol is listed today, so companies that failed since 2016 are absent. That flatters
  long results a little.
- **Fill model, correlated trades, feed mismatch** apply as in M4.
- **Sparser edge per stock.** Liquid, widely followed names are the hardest place to find an intraday edge.
