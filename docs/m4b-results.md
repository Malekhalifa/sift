# M4b results: the breakout does not survive a wider universe

Sweep `m4b-wide-v1`, run once under `docs/m4b-protocol.md`: the identical 54-configuration breakout grid on 50
stocks chosen by Q1-2016 dollar volume (none of them seen in M4). Development period 2016-2024, test years
2019-2024. **The 2025+ holdout was never touched.** 137 trials are in the registry (83 from M4, 54 grid
configurations here, 1 regime check; the Deflated Sharpe count uses all of them).

## Verdict: not eligible

| Check | Result |
|---|---|
| At least 300 out-of-sample trades | pass (4168) |
| 95% CI lower bound of expectancy above 0 | **fail** (-0.046R +-0.028) |
| Deflated Sharpe at least 0.95 | **fail** (0.000; P(Sharpe > 0) = 0.6%) |
| Positive in at least 4 of 6 test years | **fail** (0 of 6) |
| Still positive at double slippage | **fail** (-0.068R) |
| At least 70% of neighbours positive | **fail** (0 of 7) |

## What it says

- **Not just "no edge": significantly negative.** With 4168 trades the interval is -0.074R to -0.018R, so after
  costs this strategy loses money. Every test year is negative, the best of the 54 configurations is -0.028R and
  none of them is positive out of sample (median -0.070R).
- **The M4 tilt did not replicate.** On ten stocks the breakout looked faintly positive (+0.065R, 59% of
  configurations positive, long side +0.122R). On 50 fresh stocks long and short are both -0.046R. The most
  likely explanation is that the M4 result was noise, helped by a universe of stocks that were hindsight winners.
  The protocol listed that universe bias as a risk, and this is what it looks like when it bites.
- **The SPY trend filter made it worse** (informational): -0.064R against -0.041R for the same configuration.

## Diagnostic: it is not the costs

I first guessed that a one-cent spread against tiny five-minute stops explained the loss. `scripts/cost_diagnostic.py`
re-simulates exactly the configurations the walk-forward chose, in the years it chose them, at different costs
(informational only: nothing is selected or tuned):

| Cost level | Trades | Win % | Expectancy | 95% CI | Profit factor |
|---|---|---|---|---|---|
| Zero cost | 4168 | 44.7 | -0.020R | +-0.028 | 0.95 |
| Half slippage | 4168 | 44.3 | -0.034R | +-0.028 | 0.92 |
| Backtest (1 cent) | 4168 | 44.0 | -0.046R | +-0.028 | 0.89 |
| Double (2 cents) | 4168 | 43.1 | -0.070R | +-0.028 | 0.84 |

The median stop is 1.31% of the price, so a penny each way takes about 2% of one R, and no trade loses a quarter
of an R to slippage. **The guess was wrong.** Costs take about 0.026R off a gross result that is already zero:
-0.020R with an interval that includes zero. The breakout has no gross edge on these stocks.

## Consequence

The protocol says a failure here ends the opening-range breakout as a candidate in this form. It is closed. With
M4 (fade and breakout) that is every strategy tested so far, and none has an edge after realistic costs.

## What this does not show

That no intraday strategy can work. It shows that a fixed 1:1.5 opening-range breakout on liquid large caps has
no gross edge to begin with (zero-cost expectancy is -0.020R +-0.028), so cheaper execution would not rescue it.
