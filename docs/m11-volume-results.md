# M11 results: volume-conditioned rules have no edge after the market

Sweep `m11-volume-v1`, run once under `docs/m11-volume-protocol.md`: 16 volume-dry-up reversal configurations (H1,
`volrev`) and 16 high-volume continuation configurations (H2, `volspike`, long only) on 409 stocks, daily bars,
2016-2024, test years 2019-2024. **The 2025+ holdout was never touched.** 298 trials are in the registry (32 added).

## Verdict: neither is eligible

| Check | H1 volume-dry-up reversal | H2 high-volume continuation |
|---|---|---|
| At least 300 out-of-sample trades | pass (22,996) | pass (13,288) |
| Expectancy interval lower bound above 0 | **fail** (-0.008R +-0.010) | pass (+0.100R +-0.019) |
| Deflated Sharpe at least 0.95 | **fail** (0.000) | **fail** (0.231; P(Sharpe > 0) = 0.996) |
| Positive in at least 4 of 6 years | **fail** (2 of 6) | pass (5 of 6; 2022 down) |
| Positive at double slippage | **fail** (-0.021R) | pass (+0.089R) |
| At least 70% of neighbours positive | **fail** (2 of 4) | pass (4 of 4) |
| Market-adjusted interval lower bound above 0 | **fail** (-0.010R +-0.009) | **fail** (-0.039R +-0.018) |

H1 passes 1 of 7, H2 passes 5 of 7.

## What it says

- **H1 is flat, and precisely so.** With 23,000 trades the interval is +-0.010R. The chosen setting never settled (three
  different ones across six folds), 56% of the grid is positive but the median is +0.004R, and the **zero-cost** result is
  +0.006R +-0.010: no gross edge. The volume condition did not help (the modal choice has it switched off). Longs
  +0.007R, shorts -0.019R. As the protocol says, no long-only or volatility-conditioned variant is tried.
- **H2 looks good until the market is subtracted.** Every one of its 16 configurations is positive out of sample (median
  +0.060R), it survives double costs, and the zero-cost number is +0.111R. It is also the setting the protocol warned
  about: the walk-forward's modal choice is `window 50, ret_max 1.0, stop 2.5, max_hold 20`, the one that most
  resembles holding a rising market, so it is **not eligible on that rule too**. Against SPY over the same dates it
  is -0.039R (negative in 2019, 2023 and 2024; positive in 2021 and 2022): these trades were roughly buying a rising
  market, not buying something the market was about to reward.
- **Third time the same pattern.** Earnings drift (M7), insider buying (M10) and now volume spikes all show a raw gain
  that disappears after the market. For the long-only families, 2019-2024's rising market does most of the work.
- **Deflated Sharpe.** H2's probability that the true Sharpe exceeds zero is 99.6%, but after paying for 298 tries
  the benchmark Sharpe is 0.090 a day against H2's 0.070, so it fails by design. That check exists for this situation.

## What happens to H3

Closed, unrun. The protocol ran it only if H1's zero-cost interval was above zero; it is +0.006R +-0.010.

## Where the project stands

Ten strategy families (counting ORB and fade separately) have been tested under pre-registered rules on up to 410
stocks: opening-range breakout and fade, RSI(2) reversion, the 20/200-day pullback, earnings drift (plus a failed
confirmation), UT Bot + STC, Supertrend + Waddah, insider buying, volume-dry-up reversal and high-volume
continuation. None has an edge after costs and after the market. 298 trials are logged, the 2025+ holdout is
untouched, nothing has been paper traded for evidence, and no money has been at risk.
