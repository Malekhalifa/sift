# M8 protocol: confirming one frozen earnings-drift setting on unseen stocks (pre-registered)

Committed before the confirmation universe's data is downloaded and before any M8 number exists.

## Why

M7 (`docs/m7-results.md`) tried 36 earnings-drift and fade configurations on 149 liquid stocks. It passed five of
six checks and failed the Deflated Sharpe check, which exists because the best of many tries looks good partly by
luck. The winning setting was the same in every walk-forward fold. About half of its raw gain was the rising market
(excess over the market +0.090R +-0.094), concentrated in the short leg.

The remedy for selection luck is not a looser test. It is a test of **one pre-chosen hypothesis on data that played no
part in choosing it**.

## What is frozen

Follow the earnings reaction (`mode = drift`) when the market-adjusted reaction is at least 3 ATRs (`thr_atr = 3.0`),
stop at 1.5 ATR (`stop_atr = 1.5`), hold at most 20 sessions (`max_hold = 20`), 1.5R target, both sides. Everything
else is exactly as in `docs/m7-events-protocol.md`: event timing from SEC 8-K Item 2.02 filing times, intraday
releases excluded, repeats within 5 days collapsed, daily-bar fill model `tp.swing`.

Nothing is chosen from the new data. The six settings one parameter away (fade; thresholds of 1 and 2 ATRs; stop of
3 ATR; holds of 5 and 10 sessions) are run only to judge robustness, as in M7.

## The fresh universe

Stocks ranked 151 to 400 by median Q1-2016 dollar volume, by the same fixed rule as the earlier universes
(`scripts/select_universe.py --skip 150 --n 250`, `config/universe_confirm.toml`). None of them appears in any
earlier test. Symbols without full 2016-2024 daily history are dropped, as in M7.

## Costs

Mid-sized stocks trade at wider spreads, so slippage is **two cents** per share each way (twice M7's) and the stress
test uses **four cents**.

## Pass criteria: all seven must hold

1. At least 300 out-of-sample trades (2019-2024).
2. Raw expectancy: the 95% confidence interval's lower bound is above 0R.
3. Deflated Sharpe at least 0.95. With one frozen hypothesis chosen on other data there is nothing to deflate for, so
   this is the probability that the true Sharpe exceeds zero (`n_trials = 1`). The earlier 213 trials do not enter,
   because none of them touched these stocks. The 7 trials added here are logged and count against any future sweep.
4. Positive in at least 4 of the 6 test years.
5. Still positive at four cents of slippage.
6. At least 70% of the six neighbouring settings are positive out of sample.
7. **New:** market-adjusted expectancy (each trade's R minus what holding SPY the same way over the same dates
   would have paid) has a 95% interval whose lower bound is above 0R. This removes the rising-market contribution.

If fewer than 300 trades result, the test is **inconclusive, not passed**, and we do not trade it.

## If it passes

The frozen setting earns one run on the 2025+ holdout (`--use-holdout`), once, reported whatever it shows. Only then
does paper trading for evidence start. **If it fails, earnings drift on large caps is closed in this form.**

## Limits

- **Same years, same market.** Fresh stocks are not fresh time: every stock lived through the same 2016-2024 market and
  the same earnings seasons, so a confirmation here is partly one regime seen through 250 windows. The holdout is what
  supplies new time.
- **Survivors.** Stocks listed today; failures since 2016 are absent.
- **Mid-cap costs.** Two cents may still be optimistic for the least liquid names.
- **Clustering.** Earnings fall in the same weeks, so the intervals understate the uncertainty.
- **Price reaction, not surprise**; filing time can lag the press release. As in M7.
