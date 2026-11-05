# M4 protocol (pre-registered)

Written and committed **before** any M4 sweep was run. It fixes what counts as success so the result cannot be
argued after the fact. A negative result is a valid result.

## Question

Does an opening-range strategy on liquid US stocks have a positive expectancy after realistic costs, at a fixed
1:1.5 risk-to-reward, once it is chosen without seeing the data it is judged on?

Prior evidence is mixed. The unfiltered 5-minute breakout on AAPL, MSFT and NVDA (2016-2024) measured
+0.008R +-0.025, which is no edge. The published "Stocks in Play" result relies on a relative-volume filter and
a universe of thousands of stocks; our universe is ten mega-caps. We expect the answer may well be no.

## What is tested

Two strategies, each with the shared filters (relative volume, opening gap):

| Family | Idea |
|---|---|
| `orb` | Trade the first 5-minute close outside the opening range, in that direction |
| `fade` | Trade against an excursion outside the opening range once a bar closes back inside |

The grid is in `config/sweeps/m4.toml`: 54 `orb` configurations and 24 `fade` configurations. One extra
registered trial per family tests the SPY 200-day trend filter on the modal chosen configuration
(informational, see below). The grid is frozen by this commit. Changing it means a new sweep `name`, and every
trial already logged keeps counting.

## Fixed settings (not tuned)

- Data: Alpaca SIP 1-minute bars resampled to 5 minutes, regular hours, split-adjusted. Symbols: AAPL, MSFT,
  NVDA, AMD, TSLA, META, AMZN, GOOGL, NFLX, AVGO (SPY for the regime check).
- Development period 2016-01-04 to 2024-12-31. **2025-01-01 onward is a holdout and is not touched.**
- Risk-to-reward 1.5. Slippage $0.01 per share per market fill (as-traded dollars), limit targets need a
  $0.01 trade-through, 0.3 bps sell-side fees. Entry at the next bar's open, stop first when a bar touches both,
  flat at 15:55 ET.
- Sizing: 1% of compounding equity risked at the stop, leverage cap 2x, at most 5 open positions, one open
  trade per symbol.

## Selection rule

Walk-forward with an expanding window. For each test year 2019 to 2024, score every configuration on all earlier
years only, and take the best. Score = mean R minus one standard error; configurations with fewer than 200 trades
in the training years are ineligible. The six test years, each taken from the configuration chosen for it, are
stitched into one out-of-sample record. No parameter ever saw the year it is judged on.

## Pass criteria (all must hold, per strategy family)

1. At least 300 out-of-sample trades.
2. Out-of-sample expectancy has a 95% confidence interval whose lower bound is above 0R.
3. Deflated Sharpe Ratio of the stitched daily-R stream is at least 0.95. The trial count is every trial in the
   registry, including the earlier exploratory runs, and the variance of Sharpe across configurations is measured
   on the same test years.
4. Expectancy is positive in at least two thirds of the test years (4 of 6).
5. Expectancy is still positive at double the slippage ($0.02).
6. At least 70% of the modal configuration's grid neighbours (one parameter away) are positive out of sample.

Failing any one means the strategy is **not** eligible for paper trading in this form.

## What we report regardless

- Every fold's choice, the stitched record, the share of the whole grid that is positive out of sample, and the
  median and best configuration. A strategy that only works at one grid point is not a strategy.
- The SPY trend-filter comparison is **informational**. It is evaluated on the same test years, so adopting it
  would be a new choice made with out-of-sample knowledge. If it looks useful it needs its own validation.

## If a strategy passes

The modal configuration is frozen and run **once** on the holdout (`--use-holdout`). The result is reported
whatever it is. Only then does M5 start: paper trading for at least three months on the free IEX feed, with
disable rules written in advance. If the holdout run fails, the strategy stops here.

## Known limitations

- **Hindsight in the universe.** The ten symbols are today's mega-caps. Names that were large in 2026 were
  winners over 2016-2024, which can flatter long-biased results. Reported by side, and a reason to be cautious.
- **Small cross-section.** "Stocks in Play" selects a few names out of thousands each day. Ten liquid names
  leave little room for that selection to matter. Widening the universe is the obvious lever if results are
  borderline.
- **Correlated trades.** Mega-caps move together, so trades on the same day are not independent and the
  confidence intervals are tighter than the true uncertainty.
- **Fill model.** Five-minute bars cannot show order inside a bar. We assume the stop hit first, which is
  conservative, and we do not model queue position or market impact.
- **Feed mismatch.** Backtests use SIP. The free live feed is IEX. Relative volume is a ratio and should carry
  over, but this is checked before any live use.
