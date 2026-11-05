# M9 results: the indicator strategies from the videos have no edge

Sweep `m9-indicators-v1`, run once under `docs/m9-indicators-protocol.md`: 18 UT Bot + STC configurations and 12
Supertrend + Waddah Attar configurations on 5-minute bars of the 50-stock universe, 2016-2024, test years 2019-2024.
**The 2025+ holdout was never touched.** 250 trials are in the registry.

## Verdict: neither is eligible

| Check | UT Bot + STC | Supertrend + Waddah |
|---|---|---|
| At least 300 out-of-sample trades | pass (102,245) | pass (100,946) |
| Expectancy CI lower bound above 0 | **fail** (-0.038R +-0.006) | **fail** (-0.042R +-0.005) |
| Deflated Sharpe at least 0.95 | **fail** (0.000) | **fail** (0.000) |
| Positive in at least 4 of 6 years | **fail** (0 of 6) | **fail** (0 of 6) |
| Still positive at double slippage | **fail** (-0.084R) | **fail** (-0.075R) |
| At least 70% of neighbours positive | **fail** (0 of 5) | **fail** (0 of 4) |

## What it says

- **Clearly and precisely negative.** With about 100,000 simulated trades per family the intervals are tiny (+-0.005R).
  Every test year is negative for both families; none of the 30 configurations is positive out of sample (best -0.038R).
- **The STC confirmation did not help.** The best UT Bot configuration is the one with STC switched off; every STC
  setting only removed entries from a family that already lost money.
- **Both sides lose.** UT Bot + STC: long -0.030R, short -0.045R. Supertrend + Waddah: long -0.035R, short -0.049R.
- **They trade constantly.** About 17,000 simulated trades a year across 50 stocks, so costs bite hard: doubling the
  slippage from one cent to two moves the result by roughly 0.035R. Extrapolating that line back to zero cost gives
  roughly -0.01R. That is an extrapolation, not a measured zero-cost run, but it points to no gross edge.
- **The video's asymmetric two-copy setup (ATR 300 for longs, ATR 1 for shorts) did no better** than the standard
  versions.
- **Portfolio view is not meaningful here.** Position caps let only about a tenth of the signals through, so the
  -66% and -83% account results mostly reflect the cap and compounding on a losing rule, not the strategy's quality.
  The pass criteria use every simulated trade in R, as always.

## What was and was not tested

Tested: UT Bot with and without STC, and Supertrend with Waddah Attar and an ADX or Choppiness gate, as specified in the
protocol. Not tested: the other bots of video 1, whose indicators and parameters the transcript does not give.
Indicator definitions are the common open-source ones and may differ slightly from the videos' copies.

## Where the project stands

Seven strategy families have now been tested under pre-registered rules on up to 400 stocks: opening-range breakout and
fade, RSI(2) reversion, the 20/200-day pullback, earnings drift (including a failed confirmation), UT Bot + STC, and
Supertrend + Waddah. None has an edge after costs. 250 trials are logged, the 2025+ holdout is untouched, nothing has
been paper traded for evidence, and no money has been at risk.
