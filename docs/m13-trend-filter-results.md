# M13 results: the 200-day trend filter smooths the ride but costs too much return

One fixed rule, run once under `docs/m13-trend-filter-protocol.md`: hold SPY while it closes above its 200-session average,
otherwise cash. 2017-01-03 to 2024-12-31, open-to-open, 1 bp per switch, cash 0%, no dividends on either side. The 2025+
holdout was not read. No trials were added to the registry (298).

## Verdict: does not pass (2 of 3)

| | Buy and hold | Trend filter |
|---|---|---|
| Total return | +162.1% | +96.2% |
| CAGR | +12.84% | +8.81% |
| Volatility | 17.4% | 12.3% |
| Sharpe (rf 0) | 0.78 | 0.75 |
| Max drawdown | -32.4% | -21.8% |
| Days invested | 100% | 81% |

| Check | Result |
|---|---|
| Max drawdown at least 10 points shallower | **pass** (+10.6) |
| CAGR no more than 2 points a year below | **fail** (4.0 below) |
| 2020 and 2022 each at least 5 points shallower | **pass** (2020: +13.1, 2022: +9.8) |

## What it says

- **It does what it claims, at a price.** In 2020 the drawdown was -19% instead of -32%, and in 2022 -17% instead of -27%.
  But the rule sat out the rebounds: 2019 +14% vs +32%, 2020 +7% vs +16%, 2023 +9% vs +23%. Risk-adjusted, the two are
  about equal (Sharpe 0.75 against 0.78).
- **It whipsawed.** 26 round trips, 18 of them lost money. The wins were few and large (the two crashes); the cost was
  many small losses and late re-entries.
- **The gap is not an artefact of the assumptions.** Zero interest on cash and no dividends on the out-of-market days
  would cost the rule roughly one point a year at most (a back-of-envelope figure: 19% of days out of the market times a
  yield of 2% to 3.5%, not a measured run); the shortfall is four.
- **QQQ, informational and not judged:** drawdown -23% vs -37%, CAGR 18.8% vs 20.2% (1.4 below), Sharpe 1.08 vs 0.94. That
  looks better, but it is a second asset looked at after seeing SPY, on a tech-heavy index that fell hard in 2022 and
  recovered. Picking it now would be choosing the better of two outcomes after the fact, so it is not a finding.
- **Eight years, two crashes.** Whether a filter helps over a full cycle, with a longer bear market, cannot be settled from
  this window.

## What it means

This does not touch the trading result: there is still no edge for a short-term trader. For a long-term holder the choice
is a trade-off, not a free lunch. A filter like this buys shallower drawdowns by giving up return, and the evidence in our
data says the price was too high for SPY. Holding the index through the falls beat the filtered version on total return here
(regular purchases over time were not tested). That is a statement about eight past years, not a prediction and not financial advice;
how much of a drop you could sit through matters more than any of these numbers.
