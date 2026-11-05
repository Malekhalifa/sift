# M7 results: earnings drift passes 5 of 6 checks, and is not eligible

Sweep `m7-events-v1`, run once under `docs/m7-events-protocol.md`: 36 earnings-drift and fade configurations on 149
stocks (150 minus APC, dropped for incomplete history), 2016-2024, test years 2019-2024. **The 2025+ holdout was
never touched.** 213 trials are in the registry. The first attempt to run the chain stopped before any sweep
output because of SEC access (a declared contact is required) and a delisted symbol; neither involved results.

## Verdict: not eligible (Deflated Sharpe fails)

| Check | Result |
|---|---|
| At least 300 out-of-sample trades | pass (551) |
| 95% CI lower bound of expectancy above 0 | **pass** (+0.156R +-0.099) |
| Deflated Sharpe at least 0.95 | **fail** (0.006; observed 0.078 a day against a luck benchmark of 0.141; P(Sharpe > 0) = 99.9%) |
| Positive in at least 4 of 6 test years | **pass** (6 of 6) |
| Still positive at double slippage | **pass** (+0.150R) |
| At least 70% of neighbours positive | **pass** (5 of 6, 83%) |

By the protocol a single failed check means **not eligible** for the holdout or for paper trading as evidence. This
is not softened here.

## What the data says

- Walk-forward chose the same configuration in every fold: follow the reaction, reaction of at least 3 ATRs,
  stop 1.5 ATR, hold up to 20 sessions. Years: +0.22, +0.55, +0.11, +0.15, +0.11, +0.05R (declining; 2020 has only
  46 trades).
- **The pattern is coherent, which noise rarely is.** All 18 "fade" configurations lost out of sample (best -0.002R);
  the "drift" configurations averaged +0.046R and improve with the reaction threshold (+0.006, +0.049, +0.084R at
  1, 2 and 3 ATRs). Opposite signs for the opposite bet, ordered by strength, is what a real effect looks like.
- **Event study (descriptive).** After a reaction below -3 ATRs (438 events), stocks kept falling: -1.16% market-adjusted
  over 10 sessions (naive t = -4.5). After a reaction above +3 ATRs (424 events), drift was small (+0.23%, t = 1.0).
  Drift appears only recently: top-minus-bottom 10-day gap is +0.17% in 2016-2018 (t 0.45) and +1.13% in 2019-2024
  (t 3.69). Naive t-statistics ignore that earnings cluster in the same weeks, so they overstate certainty.

## The caveat that matters most: part of it is the rising market

The trades are not market-neutral. Splitting each trade into what holding SPY the same way would have paid and the
remainder (informational, computed after the sweep):

| | Trades | Raw | Market part | Excess over market |
|---|---|---|---|---|
| All | 551 | +0.156R | +0.067R | **+0.090R +-0.094** |
| Long | 275 | +0.279R | +0.242R | +0.037R +-0.132 |
| Short | 276 | +0.034R | -0.108R | +0.142R +-0.135 |

So the long side is nearly all market gain, and the stock-specific edge is about +0.09R with an interval that
touches zero. The real signal is the short leg, matching the event study (large negative reactions keep falling).
Excess by year: +0.15, +0.28, +0.08, +0.15, +0.13, **-0.04** (2024).

## Reading it honestly

This is the first result that is not a clean failure, and it is still not evidence of a tradeable edge: it fails
the multiple-testing check, about half of its raw return is market drift, the effect appears only from 2019, it
weakened in 2024, earnings seasons cluster, and the universe is large-cap survivors. It is also, by a wide margin,
the best-supported lead so far, and it points where the literature's small-stock version of drift would predict.

The right next step is not to relax a criterion. It is a new pre-registration that freezes this one configuration
and tests it on stocks it has never seen, with a market-adjusted criterion added. See the README roadmap.
