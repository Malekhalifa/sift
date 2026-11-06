# M10 protocol: insider buying, routine versus opportunistic (pre-registered)

Committed before any M10 return exists. Same discipline as M4 to M9; only what is listed here differs.

## Why, and what we expect

Company officers and directors must report their trades to the SEC within two business days (Form 4), and the
filings are public. The idea: when an insider buys shares with their own money, they may know something the market
does not. The catch is that many insider trades carry no information (scheduled purchases, tax-year habits), so the
strongest published version separates them.

Cohen, Malloy and Pomorski call an insider **routine** if they traded in the same calendar month in each of the
previous three years, and **opportunistic** otherwise. They report that a portfolio of opportunistic trades earned
value-weighted abnormal returns of about 82 basis points a month, while routine trades earned about nothing
([Journal of Finance 67(3), 2012](https://econpapers.repec.org/RePEc:bla:jfinan:v:67:y:2012:i:3:p:1009-1043);
[NBER digest](https://www.nber.org/digest/apr11/w16454.html)). Their sample ended in 2007.

**The honest prior is about 10%.**

- The effect is reported as stronger in small stocks, and some older studies find no size difference
  ([summary of the literature](https://www.insidearbitrage.com/academic-research/)). Our free price history covers
  large and mid caps only (below), so we test the part of the market where the effect is probably weakest.
- A blog summary of newer work says returns "are not as easy to come by as they were 50 years ago"; that is a
  secondary source and not a measured decay, so we do not lean on it either way.
- A monthly portfolio held for a year is not our trade. We hold 20 to 60 sessions with a stop and a 1.5R target.
- We enter after the filing, not at the insider's trade. Filings arrive up to two business days late.

We run it because the data is free and verifiable, not because we expect a pass.

## What is tested

One family, `insider`, long only (insider selling is a weaker, noisier signal and a short leg has leaked in earlier
tests).

- **Source:** SEC "Insider Transactions Data Sets", Form 4 quarterly files 2013 Q1 to 2024 Q4. Original Form 4 only
  (not amendments). Non-derivative rows with transaction code `P` (open-market purchase, acquired) and `S`
  (open-market sale, disposed), by reporting owners whose relationship includes Officer or Director. Owners that are
  only 10% holders (funds, investors) are excluded. A row needs a positive price and share count.
- **When it is known:** the data carries the filing *date* but no clock time. The signal is decided at the close of
  the filing date and filled at the **next session's open**. That is safe whenever on that day the filing arrived.
- **Classification of each purchase** (per insider and issuer, using only filings made before this one, so no
  look-ahead). Let the purchase's trade date fall in year Y, month M. Look at the insider's open-market trades
  (`P` or `S`) in the three calendar years Y-1, Y-2, Y-3.
  - **routine:** a trade in month M in each of the three years.
  - **opportunistic:** a trade in each of the three years (any month), but not routine.
  - **thin:** a year with no trade at all. These are first-time or occasional buyers, which the paper leaves
    unclassified. First purchases are arguably the strongest signal, so the grid decides whether to include them.
  Routine purchases are never traded.
- **Event:** a day when qualifying purchases (by the chosen classes) filed in the last 10 calendar days include at
  least `min_insiders` distinct insiders and at least `min_value` dollars in total (shares x price). One event per
  issuer per 30 calendar days (later purchases inside the cooldown belong to the same cluster).
- **Trade:** long at the next open; stop at 2.0 x ATR(14) (measured through the filing day), target at 1.5R, time exit
  after `max_hold` sessions. Same daily-bar fill model as M6 to M8 (`tp.swing`).
- **Grid** (`config/sweeps/m10-insider.toml`, frozen by this commit): `classes` (opportunistic;
  opportunistic + thin) x `min_insiders` (1, 2) x `min_value` ($100,000; $500,000) x `max_hold` (20, 60) = **16
  configurations**. Walk-forward selection as in M6 and M7: for each test year choose the configuration with the best
  mean R minus one standard error on the years before it, needing at least **100** training trades (lower than M7's
  200 because insider events are rarer than earnings events).

## Universe and data

The 10 original, 150 events (which contain the 50 wide) and 250 confirmation stocks, pooled: 410 names ranked by
median Q1-2016 dollar volume (`config/universe_*.toml`). Symbols without full 2016-2024 daily history are dropped. Issuers are
matched to symbols by SEC company ID (CIK, from the SEC's current ticker list), so a ticker change does not break
the match. When two share classes of one company are both in the universe, only the first is traded.

These stocks appeared in earlier tests, but those tested price patterns and earnings; insider filings are new
information. They did live through the same 2016-2024 market, so the intervals are optimistic about independence.

The 2025+ holdout stays untouched. Insider files are downloaded only through 2024 Q4.

**What was looked at before this protocol:** one quarter of the file (2016 Q1) was counted, to see whether the
universe has enough purchase filings: 206 purchase filings across 84 of our symbols (all insider types, before any
classification). No returns were computed.

**Amendment, committed before any return exists:** after the download, events were counted per year for all 16
configurations (filing data and the classification only, no prices). Purchases by our 408 matched companies from 2016
on split into 7,222 thin, 889 opportunistic and 704 routine. Events in the test years 2019-2024:

| classes | insiders | min value | events 2019-24 |
|---|---|---|---|
| opportunistic | 1 | $100k / $500k | 139 / 68 |
| opportunistic | 2 | $100k / $500k | 16 / 8 |
| opportunistic + thin | 1 | $100k / $500k | 1,080 / 534 |
| opportunistic + thin | 2 | $100k / $500k | 306 / 218 |

Consequence, stated now so it cannot be argued later: the four pure-opportunistic configurations cannot reach the
300-trade floor on their own, and the grid is **not changed**. A pass can only come from configurations that include
thin (first-time or occasional) buyers, and the verdict then speaks to "cluster purchases by officers and directors",
not to the routine/opportunistic split.

## Costs

Two cents per share each way (mid-cap level, as in M8); the stress test uses four cents.

## Pass criteria: all seven must hold (the M8 list, with the Deflated Sharpe taken over the whole registry)

1. At least 300 out-of-sample trades (2019-2024).
2. Raw expectancy: the 95% confidence interval's lower bound is above 0R.
3. Deflated Sharpe at least 0.95, counting every trial in the registry (250 before this test, 16 added here).
4. Positive in at least 4 of the 6 test years.
5. Still positive at four cents of slippage.
6. At least 70% of the chosen configuration's neighbours (one parameter away) are positive out of sample.
7. Market-adjusted expectancy (each trade's R minus what holding SPY the same way over the same dates would have
   paid) has a 95% interval whose lower bound is above 0R.

If fewer than 300 trades result, the test is **inconclusive, not passed**, and we do not trade it.

## Informational: does routine versus opportunistic show up at all?

Not part of the pass criteria and not tradable, but it tests the paper's claim directly on our data. For each class
(routine, opportunistic, thin) every purchase event (one insider is enough, at least $100,000, same 10-day window
and 30-day cooldown) gets one number: the return from the next open to the close 20 sessions later, minus SPY's over the
same dates, no costs. We report the mean, its 95% interval and the count per class, over 2016-2024 and over
2019-2024. `scripts/insider_event_study.py`. It adds no trials; the result is a description, not a selection.

## If it passes

The chosen setting earns one run on the 2025+ holdout (`--use-holdout`), once, reported whatever it shows. Only then
does paper trading for evidence start. **If it fails, insider buying on large and mid caps is closed in this form.**
It does not rule out small caps, which we cannot test honestly: free price history lacks delisted stocks, and
insiders at failing companies buy the dips that go to zero.

## Limits

- **Large and mid caps only,** where the published effect is weakest. Small caps are untested.
- **Survivors.** Stocks listed today; companies that failed since 2016 are absent.
- **Day-level timing.** We cannot see when on the filing day the news arrived; entering at the next open gives up
  any same-day move.
- **Scheduled trades.** Pre-arranged 10b5-1 purchase plans look opportunistic to this rule. The filing flag for them
  only exists from 2023, so we do not use it.
- **Clustering.** Insider buying clusters in market selloffs (2016 Q1, 2020, 2022), so the intervals understate the
  uncertainty and the market-adjusted check matters.
- **History edge.** Events in 2016 have exactly three years of look-back (2013-2015); classification is fine but the
  thin class is larger in early years.
