# M17 protocol: net share issuance, as a monthly long-short basket (pre-registered)

Committed before any M17 return exists. One signal, one holding rule, one setting; replicated once on unseen stocks.
It reuses the M15 basket engine (`tp.high52.monthly_spread`) with a different signal.

## Why, and what we expect

Companies that shrink their share count (net repurchasers) are said to outperform companies that grow it, and the market
is said to under-react to the share count that each 10-Q or 10-K reveals.
[Pontiff and Woodgate (2008, JF)](https://ideas.repec.org/a/bla/jfinan/v63y2008i2p921-945.html): after 1970, share
issuance predicts returns more significantly than size, book-to-market or momentum individually.
[McLean, Pontiff and Watanabe (2009, JFE)](https://econpapers.repec.org/RePEc:eee:jfinec:v:94:y:2009:i:1:p:1-17) report
it holds for large and small firms internationally (seen through a search summary).
[Peyer and Vermaelen (2009, RFS)](https://econpapers.repec.org/RePEc:oup:rfinst:v:22:y:2009:i:4:p:1693-1745) reject that
the buyback anomaly has disappeared; other work finds the drift gone for recent repurchases. Net issuance is now a
standard factor input, so some of it is likely priced already, and large caps show the weakest effect. Prior of passing:
about 5%. Source: `docs/research/ideas-events.md`, E3.

## Data (`scripts/fetch_shares.py`, free)

SEC XBRL company facts: the cover-page share count (`dei:EntityCommonStockSharesOutstanding`) of every 10-K and 10-Q,
with its **filing date** (`filed`) and the date of the count (`end`). The data is point in time: each value is what the
filing said when it was filed. Filings from 2025 on are stored but **not analysed here: they are the holdout.**

- **Primary universe:** the 150 stocks of `config/universe_events.toml`. **Replication:** the 250 of `config/universe_confirm.toml`.
- **Data hygiene, declared up front:** in both universes, drop any stock with a one-session gain above +100% in its daily
  closes (a reverse split missing from the split list, found in M15).

## Signal and rule (frozen here)

- **Share count known at the close of session t:** the stock's latest 10-K or 10-Q with a filing date strictly before
  t's date, if filed within the last 135 days; otherwise no signal. When a filing reports several classes, the counts are
  summed.
- **Prior count:** the same company's filing whose count date is 330 to 400 days before the latest's count date, the
  one nearest 365; none means no signal. The prior count is multiplied by every split ratio in `data/corp_actions/splits.parquet`
  with an ex-date after the prior count date and up to the latest count date.
- **Signal:** minus the natural log of (latest ÷ adjusted prior): highest = fewest new shares (net repurchasers).
- **Rule:** as M15. Rebalance on the first session of each calendar month; trades at that open; held to the next month's
  first-session open. **Long the quintile of strongest net repurchasers, short the quintile of heaviest issuers,** equal
  weight, dollar neutral, 5 bps a side on traded weight.
- **Period:** monthly rebalances from February 2016 to November 2024, **106 months**; December 2024 is not held.
- Not tuned or varied: the 135-day staleness limit, 365-day comparison, quintiles, monthly horizon, equal weights.
  Repurchase dollars, a three-month hold and size-adjusting are **not tested**.

**What was looked at before this protocol:** the structure of the downloaded files (columns, rows per filing, one symbol's
first rows). No returns and no relation between share counts and returns.

## Pass criteria: all five

1. At least 60 months of results on the primary universe. Fewer means **inconclusive, not passed**.
2. Mean net monthly long-short return above zero with the lower bound of its 95% interval above zero (plain t-interval).
3. Positive mean in at least 6 of the 9 calendar years 2016-2024 (2016 has 11 months).
4. Positive mean in both halves (first 53 months, last 53).
5. **Replication:** on the 250 unseen stocks, a positive mean net monthly return, positive in both halves.

Reported, not judged: gross mean, long leg minus SPY, short leg alone, beta to SPY, turnover.

## If it passes

One run on the 2025+ filings and bars, once, reported whatever it shows. Only then would paper trading follow.

## Limits

- **Large caps and mega caps.** The documented effect is weakest here, and the ranking is among stocks that mostly
  buy back shares. Share counts also move with employee stock plans, acquisitions and conversions.
- **Cover-page counts** are as of a date shortly before filing, and companies report different classes inconsistently, so
  some signals are noise. A wrong split ratio or a missing split makes a false issuer; the ranking limits the damage to
  the stocks that land in an extreme quintile by mistake.
- **Stocks listed today;** spin-offs and special dividends are not adjusted; shorting costs are not modelled.
