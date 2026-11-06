# M11 protocol: volume-conditioned reversal and continuation (pre-registered)

Committed before any M11 result exists. Hypotheses H1 and H2 come from `docs/ideas/candle-strategies.md` (Fable 5.1's
literature review), written before any of our data was read for them. Same discipline as M4 to M10.

## Why, and what we expect

Two ideas about volume survive in the research literature on large US stocks:

- **H1, volume-dry-up reversal (`volrev`).** A stock that fell (or rose) sharply against the market over five
  sessions on *falling* volume tends to bounce back, because the move was impatient selling, not news, and someone is paid
  to take the other side (Conrad, Hameed and Niden 1994; Cooper 1999; Hameed and Mian 2015). Prior of passing: about 12%.
- **H2, high-volume continuation (`volspike`).** A stock whose volume is the highest in weeks tends to drift up over the
  next 10 to 20 days as inattentive buyers notice it (Gervais, Kaniel and Mingelgrin 2001, in 41 countries per Kaniel,
  Ozoguz and Starks 2012). Prior of passing: about 8%.

Both are old, both have probably decayed (post-publication declines of a third or more are the norm), and our
RSI(2) test, H1's price-only cousin, measured -0.026R. We run them because each failure closes a real family.

## What is tested

Daily bars, decided at a session's close, filled at the next open, bracket with a stop at `stop_atr` x ATR(14), a
1.5R target and a time exit (`tp.swing`, as in M6 to M10). Full definitions in `src/tp/strategies/volume.py`.

- **H1 `volrev`.** `ex5` = the stock's 5-session return minus SPY's. `vr` = mean volume of the last 5 sessions over mean
  volume of the 20 sessions before them. Long if `ex5 <= -mult x (ATR/close)`, short if `ex5 >= +mult x (ATR/close)`,
  and, when `vol_max > 0`, only if `vr <= vol_max`. Grid (16): `mult` {2, 3} x `vol_max` {0 = off, 1.0} x `stop_atr`
  {1.5, 2.5} x `max_hold` {5, 10}.
- **H2 `volspike`.** Long only (the effect is carried by the high-volume leg; a short leg is not run and not counted).
  Long when today's volume is strictly the highest of the last `window` sessions and, when `ret_max > 0`, today's move is
  at most `ret_max` x (ATR/close). Grid (16): `window` {20, 50} x `ret_max` {0 = off, 1.0} x `stop_atr` {1.5, 2.5} x
  `max_hold` {10, 20}.

32 configurations, walk-forward selection over test years 2019 to 2024 (best mean R minus one standard error on the
earlier years, at least 200 training trades), as in M6 and M7. Config: `config/sweeps/m11-volume.toml`.

## Universe and costs

The 410 stocks with daily bars (original ten, the 150 events list, which contains the wide 50, and the 250
confirmation stocks), by the fixed Q1-2016 dollar-volume rule. This is wider than the 120 to 150 names Fable suggested,
to get more trades; it is chosen now, not from results. Symbols without full 2016-2024 history are dropped. Two cents per
share each way (mid-cap level), four cents for the stress test. They are the same stocks as earlier tests, but volume
conditions are new information; they lived through the same 2016-2024 market.

## Pass criteria: all seven (the M10 list)

1. At least 300 out-of-sample trades (2019-2024).
2. Expectancy 95% interval lower bound above 0R.
3. Deflated Sharpe at least 0.95, counting every trial in the registry (266 before, 32 added: 298).
4. Positive in at least 4 of 6 test years.
5. Positive at four cents of slippage.
6. At least 70% of the chosen configuration's neighbours (one parameter away) positive out of sample.
7. Market-adjusted expectancy (trade R minus holding SPY the same way over the same dates) interval lower bound above 0R.

Each family is judged separately against all seven. Fewer than 300 trades means inconclusive, not passed.

**Extra abandon rules from the brief, fixed now.** H2 is **not eligible** if it is positive only at `max_hold = 20` with
`stop_atr = 2.5`, the setting that most resembles holding a rising market. For H1, if the zero-cost interval (reported
for every family as an informational line) includes zero there is no gross edge, and we try **no** long-only or
volatility-conditioned variant: that would be the same bet with a parameter chosen after the fact.

## H3 (low-volume opening-gap fade)

Not part of this run. Fable's order of work says to run it only if H1 shows a gross edge: the zero-cost 95% interval of
H1's chosen configurations lies above 0R. If that happens we write H3's own protocol and config first, then run it. If
not, H3 is closed unrun.

## If one passes

One run on the 2025+ holdout (`--use-holdout`), reported whatever it shows; only then does paper trading for evidence
start. If both fail, volume-conditioned daily rules on large and mid caps are closed.

## Limits

- **Same bet, same years.** H1 is a liquidity-provision bet that pays in volatile years and loses in calm uptrends; both
  families' long legs are flattered by 2019-2024's rising market, which is why the market-adjusted check exists.
- **Survivors.** Stocks listed today; failures since 2016 are absent.
- **Volume is consolidated SIP volume,** which includes index rebalance and option-expiry days; H2 has no filter for them.
- **Clustering.** Reversal signals bunch in selloffs (2020, 2022), so intervals understate the uncertainty.
