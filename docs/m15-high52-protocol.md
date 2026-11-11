# M15 protocol: nearness to the 52-week high, as a monthly long-short basket (pre-registered)

Committed before any M15 return exists. One signal, one holding rule, one setting; replicated once on stocks that played
no part in the first run.

## Why, and what we expect

[George and Hwang (2004)](https://www.bauer.uh.edu/tgeorge/papers/gh5-paper.pdf) argue that traders anchor on the
52-week high: stocks trading near it are under-priced for good news and keep drifting up, while stocks far below it keep
drifting down. They report about 0.45% a month, 1963-2001 (figure from a search summary; I did not open the full text). The industry version
([Hong, Jordan and Liu 2015](https://quantpedia.com/strategies/52-weeks-high-effect-in-stocks)) reports about 0.6% a month
to 0.9% a month on 1963-2009. Quantpedia rates the out-of-sample results "slightly negative", says most of the gain is on
the long side and that January is negative, and a 20-country study found profits mostly insignificant after costs.
The effect was documented on all stocks; in large caps the spread is likely a fraction of that. Prior of passing: about
10% (`docs/research/ideas-academic.md`, C1). This is a ranking test, not a single-stock entry rule: it differs from
the volume-continuation and pullback tests, which were per-stock events.

## Data

Daily split-adjusted closes and opens from the Alpaca store, free. Nothing new is downloaded. Bars from 2025 on are
**not read** (the holdout).

- **Primary universe:** the 150 stocks of `config/universe_events.toml` (ranks 1-150 by Q1-2016 dollar volume).
- **Replication universe:** the 250 stocks of `config/universe_confirm.toml` (ranks 151-400), ranked on their own.

## Signal and rule (frozen here)

- **Nearness** at the close of day t: the close divided by the highest close of the last 252 sessions (including day t).
  A stock needs 252 sessions of history to be ranked.
- **Rebalance** on the first session of each calendar month. The signal is the previous session's close, trades happen
  at that session's open, and positions are held to the next month's first-session open.
- **Basket:** long the top quintile by nearness, short the bottom quintile, equal weight inside each leg, each leg
  scaled to 100% (dollar neutral). Quintile size = round(universe size ÷ 5) among ranked stocks that month; ties break by symbol.
- **Cost:** 5 bps per side on traded weight: each month `0.0005 × Σ|new weight − last month's weight|`, where weights are
  +1/n long and −1/n short.
- **Return per month:** mean open-to-open return of the long leg minus that of the short leg, minus cost.
- **Period:** monthly rebalances from January 2017 (the first with 252 sessions of bars) to November 2024 (exit at the
  December 2024 open), **95 months**. December 2024 is not held, so no return touches 2025.
- Not tuned or varied: the 252-day window, quintiles, monthly horizon, equal weights, close-based high. The industry
  version and a 3-month overlapping hold from the papers are **not tested**.

**What was looked at before this protocol:** universe sizes only. No returns.

## Pass criteria: all five

1. At least 60 months of results on the primary universe. Fewer means **inconclusive, not passed**.
2. Mean net monthly long-short return above zero with the lower bound of its 95% interval above zero (plain t-interval).
3. Positive mean in at least 6 of the 8 calendar years 2017-2024.
4. Positive mean in both halves (first 47 months and last 48).
5. **Replication:** on the 250 unseen stocks, the same frozen rule gives a positive mean net monthly return and positive in both halves.

Reported, not judged: long leg minus SPY, short leg alone, beta of the long-short series to SPY, January alone, gross
(before cost) mean, mean monthly turnover.

## If it passes

One run on the 2025+ bars, once, reported whatever it shows. Only then would paper trading follow.

## Limits

- **Stocks listed today.** Companies that fell out of the index or were delisted are missing. This flatters long legs of
  stocks that stayed, and penalizes short legs (the stocks that kept falling and died are not there).
- **Nine years, one momentum crash regime (2020-21, 2022).** Ninety-five monthly observations give low power; a "no"
  here reads as no edge large enough to matter, not as proof of zero.
- **Shorting costs are not modelled** (borrow fees, availability) beyond the 5 bps.
- **Large caps only;** the published effect is mostly in smaller stocks.
