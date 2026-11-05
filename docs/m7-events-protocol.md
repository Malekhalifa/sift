# M7 protocol: earnings-announcement drift (pre-registered)

Committed before any M7 result exists. Same discipline as the earlier protocols; only what is listed here differs.

## Why, and what we expect

This is the "track what actually moves the price" idea: earnings are the most reliable scheduled catalyst a stock
has, and the exact moment a company releases results is public. The question is whether the stock keeps moving in
the direction of its reaction after the announcement (post-earnings announcement drift), or overreacts and
reverts.

**The honest prior is low.** The classic evidence says drift exists: Chan, Jegadeesh and Lakonishok (1996) found
that the return around an earnings announcement predicts returns for months afterwards
([Journal of Finance 51(5)](https://econpapers.repec.org/RePEc:bla:jfinan:v:51:y:1996:i:5:p:1681-1713), sample
ending in the 1990s). The most careful recent study, Martineau, argues the drift **has disappeared for all but
the smallest stocks, from about 2006** ([Critical Finance Review](https://nowpublishers.com/article/Details/CFR-0122);
[summary](https://anderson-review.ucla.edu/is-post-earnings-announcement-drift-a-thing-again/), which also notes a
2025 paper finding the picture depends on whether micro-caps are included). Our universe is liquid large caps, the
place where the drift is reported to be gone. We run the test because it is the cheapest honest way to find out, not
because we expect a pass.

## What is tested

One family, `ead`, with the reaction measured from the price, not from a consensus estimate (free earnings
estimates are not available point-in-time):

- **Event:** an SEC 8-K carrying Item 2.02 (results of operations). EDGAR records the exact second it accepted the
  filing, so the timestamp is point-in-time.
- **Reaction session:** a release before 09:30 ET reacts that day; one at or after 16:00 ET reacts the next
  session; a weekend or holiday release reacts at the next open. **Releases during the session (09:30 to 16:00)
  are excluded** as ambiguous. A second filing within 5 days of the first is the same announcement.
- **Reaction size:** the reaction session's return minus SPY's return, divided by the stock's ATR(14) as a
  percent of price measured over the sessions **before** the event. A move of at least `thr_atr` ATRs qualifies.
- **Trade:** decided at the reaction session's close, entered at the next open. `drift` goes with the reaction,
  `fade` goes against it. Bracket with a stop at `stop_atr` x ATR(14), a target at 1.5R and a time exit after
  `max_hold` sessions. Same daily-bar fill model as M6 (`tp.swing`).
- **Grid** (`config/sweeps/m7-events.toml`, frozen by this commit): mode (drift, fade) x `thr_atr` (1, 2, 3) x
  `stop_atr` (1.5, 3) x `max_hold` (5, 10, 20) = 36 configurations. `fade` is included because overreaction at
  announcements is plausible for large caps; it has less published support than drift, which is part of why the
  prior is low.

## Universe and data

The 150 most liquid stocks by median Q1-2016 dollar volume (excluding the original ten), chosen by the same fixed
rule as the 50-stock universe, which is the first 50 of this list (`config/universe_events.toml`,
`scripts/select_universe.py`). Daily SIP bars from 2016, SPY for the market adjustment, earnings times from SEC
EDGAR. About 36 events per stock gives roughly 5,000 events before filtering.

## Data hygiene (added before any M7 result existed)

Symbols whose daily history does not cover the whole 2016-2024 period are dropped, because the universe was ranked
on 2016 liquidity and a few tickers were reused after a delisting (found so far: APC, Anadarko, acquired in 2019).
Foreign filers such as BP and BIDU file no 8-K earnings releases and so produce no events. Neither rule looks at
returns. Both were decided after the earnings data arrived and before any sweep or event-study output was seen.

## Unchanged

Development period 2016-01-04 to 2024-12-31, **2025+ holdout untouched**, test years 2019-2024, walk-forward
selection on mean R minus one standard error with at least 200 training trades, and the same six pass criteria
with the same thresholds. The Deflated Sharpe trial count is every trial in the registry: 177 earlier trials
plus these 36.

## Alongside the sweep (descriptive, never used to select)

`scripts/event_study.py` reports the average market-adjusted return after the reaction session, by reaction size,
over 1 to 20 days. This shows whether drift exists in the data independent of the bracket mechanics. It is read
after the sweep and changes nothing about it.

## Limits

- **Price reaction is not surprise.** It mixes the earnings surprise, guidance and the market's mood that day.
- **Filing time can lag the press release.** Usually minutes; rarely longer. A late filing makes a release look
  later than it was, which could misclassify pre-market releases as after-close ones.
- **Earnings seasons are clustered.** Many events fall in the same few weeks and in the same market, so trades are
  not independent and the confidence intervals understate the uncertainty.
- **No text or news.** An LLM reading the release is deliberately left out: a model may know how those
  announcements turned out, which would contaminate a backtest. That needs its own test design.
- **Survivors, dividends, borrow fees:** as in M6.
