# M10 results: insider buying shows no edge on large and mid caps

Sweep `m10-insider-v1`, run once under `docs/m10-insider-protocol.md`: 16 configurations of long-only cluster purchases
by officers and directors (SEC Form 4, 2013-2024 files), 407 stocks, daily bars, 2016-2024, test years 2019-2024.
**The 2025+ holdout was never touched.** 266 trials are in the registry (16 added here).

## Verdict: not eligible

| Check | Result |
|---|---|
| At least 300 out-of-sample trades | pass (910) |
| Expectancy CI lower bound above 0 | **fail** (+0.028R +-0.078) |
| Deflated Sharpe at least 0.95 | **fail** (0.096; probability the Sharpe is above zero 0.68) |
| Positive in at least 4 of 6 years | **fail** (3 of 6: 2021, 2023, 2024 up; 2019, 2020, 2022 down) |
| Still positive at double slippage | pass (+0.016R) |
| At least 70% of neighbours positive | pass (4 of 4) |
| Market-adjusted expectancy CI lower bound above 0 | **fail** (-0.079R +-0.065) |

Three of seven. The walk-forward chose the same family of setting most years (any buyer, at least $100,000, hold 60
sessions); its record is a coin flip with a slightly positive mean.

## What it says

- **Positive raw, negative after the market.** 15 of the 16 configurations are positive on 2019-2024 taken one at a time
  (median +0.108R), but these are long-only holds in a market that rose over those years. Net of SPY over the same
  dates the stitched record is -0.079R, and the excess is negative in five of the six years (only 2022 is above zero).
  That is exactly what the seventh check exists to catch.
- **The event study agrees.** Market-adjusted return from the next open to the close 20 sessions later, no costs,
  2019-2024: thin buyers -0.34% +-0.64 (969 events), opportunistic -0.18% +-1.59 (139 events). Nothing separates
  insider buying from the market.

  | class | 2016-2024: events, mean | 2019-2024: events, mean |
  |---|---|---|
  | routine | 12, -4.14% +-2.88 | 10, -4.34% +-3.48 |
  | opportunistic | 198, +0.64% +-1.30 | 139, -0.18% +-1.59 |
  | thin | 1,514, -0.00% +-0.47 | 969, -0.34% +-0.64 |

- **The routine/opportunistic split could not be confirmed.** The direction matches Cohen, Malloy and Pomorski
  (routine worse than opportunistic), but there are only 12 routine events: routine purchases are tiny (median $2,300;
  1% reach the $100,000 floor, against 48% of opportunistic and 56% of thin purchases), which suggests small periodic
  buys rather than conviction. The opportunistic interval spans zero. We have too few events in 410 large and mid caps
  to say anything either way.
- **Costs are not the story.** Doubling slippage moves the result by 0.012R; the gross record is weak too.
- **Same pattern as M7.** A raw edge that looks real until the market is subtracted.

## What was and was not tested

Tested: purchases by officers and directors on 407 stocks that were liquid in 2016 and are listed today, entered at the
open after the filing date, with a 2 ATR stop, 1.5R target and 20 or 60 session limit.

Not tested, and the reason this does not close the whole idea: **small caps**, where the published effect is
strongest. We cannot test them honestly for free, because history for delisted companies is missing and insiders at
failing companies buy dips that go to zero. Sales (shorting) and the 10b5-1 flag (only available from 2023) were also
left out by the protocol.

## Where the project stands

Eight strategy families have now been tested under pre-registered rules on up to 400 stocks: opening-range breakout and
fade, RSI(2) reversion, the 20/200-day pullback, earnings drift (including a failed confirmation), UT Bot + STC,
Supertrend + Waddah, and insider buying. None has an edge after costs and after the market. 266 trials are logged, the
2025+ holdout is untouched, nothing has been paper traded for evidence, and no money has been at risk.
