# M8 results: the earnings-drift result did not replicate

Confirmation `m8-confirm-v1`, run once under `docs/m8-confirmation-protocol.md`: the one setting M7 chose in every
fold (follow the reaction, at least 3 ATRs, stop 1.5 ATR, hold up to 20 sessions) on 250 stocks it had never seen
(ranks 151-400 by Q1-2016 liquidity), 2016-2024, test years 2019-2024, slippage two cents (stress four).
**The 2025+ holdout was never touched.** 220 trials are in the registry.

## Verdict: not eligible, and the lead is closed

| Check | M7 (149 liquid stocks) | M8 (250 fresh stocks) |
|---|---|---|
| At least 300 out-of-sample trades | pass (551) | pass (855) |
| Raw expectancy CI lower bound above 0 | pass (+0.156R +-0.099) | **fail** (+0.025R +-0.077) |
| Deflated Sharpe at least 0.95 | fail (0.006) | **fail** (0.734; P(Sharpe > 0) = 73%) |
| Positive in at least 4 of 6 years | pass (6 of 6) | **fail** (3 of 6) |
| Positive at double slippage | pass | pass, barely (+0.011R) |
| At least 70% of neighbours positive | pass (83%) | **fail** (17%) |
| Market-adjusted CI lower bound above 0 | (not a check; excess was +0.090R +-0.094) | **fail** (+0.023R +-0.072) |

Two of seven checks pass, and the 2x-cost pass is a technicality (+0.011R, indistinguishable from zero).

## What it says

- **The effect shrank to nothing.** Raw +0.156R became +0.025R, and the market-adjusted +0.090R became +0.023R. Neither
  interval separates from zero. Years: +0.06, -0.06, -0.07, +0.12, +0.20, -0.07R, with no pattern.
- **The pattern that made M7 look coherent is gone.** In M7 the fade variants all lost, and drift improved with the
  threshold. Here only 2 of 7 settings are positive (median -0.010R), and the neighbours do not follow the frozen one.
- **The event study agrees.** In M7's stocks the gap between the 10-day drift after big up-reactions and big
  down-reactions was +1.13% in 2019-2024 (naive t 3.69). On the fresh stocks it is **+0.06% (t 0.21)**. Big movers of
  both signs drifted slightly down (-0.56% after reactions below -3 ATRs, -0.54% after above +3), which is not drift
  in the direction of the news.
- **The one echo:** the short leg again carried what excess there was (+0.116R; the long leg was -0.079R), the same
  direction as M7. At +-0.07R on the whole record it is not evidence on its own, and we do not build a short-only
  variant from a split we only noticed after the fact.

## What this means

M7's pass of five checks was most likely selection luck, plus a favourable run of liquid large caps in 2019-2024. The
confirmation did what it was designed to do: it separated a result that looked coherent from one that holds.
Earnings-announcement drift, measured from the price reaction, is closed on large and mid caps in this form. That
matches the published work that finds it gone in non-micro-cap stocks.

## Where the project stands

Six strategy families have now been tested properly under pre-registered rules (opening-range breakout and fade,
RSI(2) reversion, 20/200-day pullback, earnings drift) on up to 400 stocks, intraday and daily. None has an edge after
costs. 220 trials are logged. The 2025+ holdout is untouched, nothing has been paper traded for evidence, and no money
has been at risk. The infrastructure works.
