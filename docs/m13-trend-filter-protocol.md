# M13 protocol: does a 200-day trend filter make holding the market safer? (pre-registered)

Committed before any M13 number exists. This is not a trading-edge test. Twelve earlier tests found that what looked
like an edge was mostly the market rising, so the honest question left is about the market itself: can a simple rule
cut the damage of the bad years without costing much of the good ones?

## The one rule

Hold SPY when its close is above its 200-session simple average (including that day); otherwise hold cash. Decided at the
close, executed at the next open. **No parameter is chosen or tuned: 200 is the textbook value and is the only one
run.** Buy-and-hold SPY is the benchmark.

## Data and period

SIP daily bars of SPY, split-adjusted, open-to-open returns for both the rule and the benchmark. Evaluation window
**2017-01-03 to 2024-12-31** (the first 200 sessions of 2016 warm up the average). The 2025+ holdout is not read.

Costs: 1 basis point per switch. Cash earns 0% and neither side includes dividends, so total returns are understated
equally for time in the market and the rule's out-of-market years look slightly worse than they would with cash
yield; a gap smaller than about 1 point a year is therefore not meaningful.

## Pass criteria: all three

1. **Max drawdown at least 10 percentage points shallower** than buy-and-hold over the window.
2. **CAGR no more than 2 points a year below** buy-and-hold.
3. **Not one episode:** inside each of calendar 2020 and 2022 the rule's max drawdown is at least 5 points shallower than
   buy-and-hold's within that year.

Also reported, not judged: total return, annualised volatility, Sharpe (rf = 0), share of days invested, number of
switches and how many of them lost money, return by calendar year, and the same rule on QQQ.

## What a pass would and would not mean

A pass would say the filter made the 2017-2024 ride smoother at an affordable price in return. It would not say it
earns more than holding, would not predict the next decline, and rests on eight years that contain essentially two
crashes (2020 and 2022) and a bull market. The 200-day rule is known to whipsaw in choppy markets (late 2018 is one
such case in this window). Nothing here is financial advice.
