# M6 results: neither daily-bar swing strategy has an edge

Sweep `m6-swing-v1`, run under `docs/m6-swing-protocol.md`: 24 RSI(2) and 16 moving-average-pullback
configurations on the 50-stock universe, daily bars 2016-2024, test years 2019-2024. **The 2025+ holdout was never
touched.** 177 trials are in the registry (137 earlier, 40 here). The first run crashed in the analysis step on a
bug in the sweep script after all 40 configurations had been simulated and logged, before any result was printed;
the fix changed analysis code only and the rerun did not log trials twice.

## Verdict: neither is eligible

| Check | RSI(2) reversion | MA pullback |
|---|---|---|
| At least 300 out-of-sample trades | pass (6324) | pass (3219) |
| 95% CI lower bound of expectancy above 0 | **fail** (-0.026R +-0.021) | **fail** (-0.032R +-0.028) |
| Deflated Sharpe at least 0.95 | **fail** (0.000; P(Sharpe > 0) = 6%) | **fail** (0.000; 5%) |
| Positive in at least 4 of 6 test years | **fail** (1 of 6) | **fail** (1 of 6) |
| Still positive at double slippage | **fail** (-0.033R) | **fail** (-0.038R) |
| At least 70% of neighbours positive | **fail** (0 of 5) | **fail** (0 of 4) |

## What it says

- **Both are significantly negative, not just flat.** The intervals sit entirely below zero. Only 2021 was
  positive for either. Across the whole grid, 21% of RSI(2) configurations and 0% of pullback configurations were
  positive out of sample (medians -0.009R and -0.040R).
- **Costs are not the story, again.** Doubling slippage moves the result by under 0.01R. The edge is absent before
  costs, as with the breakout.
- **Longs near zero, shorts clearly negative.** RSI(2) long +0.022R (2737 trades) against short -0.063R (3587);
  pullback long +0.006R against short -0.081R. One reading is a market that drifted up, plus a universe made of
  stocks that are still listed today, which punishes shorts and flatters longs. That is a hypothesis, not a
  finding. A long-only variant would be a new idea chosen after seeing this split, so it would need its own
  pre-registration and fresh data.
- **Mean reversion did not pay on these stocks in 2019-2024.** The published RSI(2) evidence is from the 2008 book
  and its decay was never measured; this is the first measurement here, and it is negative.

## Where the project stands

Four strategy families have now been tested properly (opening-range breakout, its failed-breakout fade, RSI(2)
reversion, 20/200-day pullback), on 60 stocks, intraday and daily, under pre-registered rules with 177 trials
counted. None has an edge after costs, and the cost diagnostic shows the opening-range breakout has none before
costs either. The 2025+ holdout is untouched, nothing has gone to paper trading for evidence, and no money has
been at risk.

The infrastructure (data, two engines, walk-forward, Deflated Sharpe, paper loop) works and is verified. What
this says is that plain price-pattern rules on liquid large caps look like an empty search space at this level.
The next idea should change the information source or the market segment, not tune these further.
