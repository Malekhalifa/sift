# M4 results: no strategy passed

Sweep `m4-v1`, run once under `docs/m4-protocol.md` with the grid in `config/sweeps/m4.toml`. Development period
2016-2024, ten large-cap symbols, test years 2019-2024. **The 2025+ holdout was never touched.** 83 trials are in
the registry (2 exploratory runs, 78 grid configurations, 1 regime check per family, plus one run that crashed
in the analysis step before any numbers were printed; its grid trials were not logged twice).

## Verdict

| Check | Fade | Breakout (ORB) |
|---|---|---|
| At least 300 out-of-sample trades | pass (2948) | pass (435) |
| 95% CI lower bound of expectancy above 0 | **fail** (-0.000R +-0.042) | **fail** (+0.065R +-0.114) |
| Deflated Sharpe at least 0.95 | **fail** (0.000) | **fail** (0.000) |
| Positive in at least 4 of 6 test years | **fail** (2 of 6) | pass (4 of 6) |
| Still positive at double slippage | **fail** (-0.013R) | pass (+0.055R) |
| At least 70% of neighbours positive | **fail** (0 of 5) | **fail** (4 of 7, 57%) |
| **Eligible for the holdout** | **no** | **no** |

## What the numbers say

- **Fade: no edge.** Expectancy is zero, profit factor 1.00, and only 1 of 24 configurations (4%) is positive out
  of sample, with a median of -0.045R, which is roughly the cost drag. The stitched record is dominated by one
  fold: the 2022 choice (no volume filter) produced 2223 of the 2948 trades.
- **Breakout: a faint, unproven tilt.** 59% of the 54 configurations are positive out of sample (median +0.016R,
  best +0.148R), it is positive in 4 of 6 years and survives double costs. But the filters leave only about 70
  trades a year across ten symbols, so the confidence interval runs from about -0.05R to +0.18R, and the chance
  the true Sharpe is above zero is 85%, short of the 95% we required even before deflating for 83 trials.
  The modal configuration on its own is -0.024R over the test years.
- **Costs decide everything.** Zero-cost results sit near +0.02R; one cent of slippage removes most of it.
- **Short side is weaker** for the breakout (-0.016R vs +0.122R long), which is the direction a hindsight-picked
  universe of recent winners would flatter.
- The SPY trend filter did not help either strategy (informational, evaluated on the same test years).

## Reading it honestly

Nothing here is tradeable. The breakout result is the kind of number that looks tempting (+0.065R, four winning
years, survives costs) and is exactly what chance produces when you try 54 variants. The protocol exists to
stop us trading it.

## What this does not show

Only that these two ideas, on these ten stocks, with 5-minute bars and a 1:1.5 target, show no provable edge.
Ten large-cap stocks leave little cross-section for relative volume to select from, and the breakout was starved
of trades. A wider universe is the obvious next test, as a new pre-registered sweep, not a retune of this one.
