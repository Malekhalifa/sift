# M18 protocol: Lazy Prices, year-over-year change in the 10-K risk-factor text (pre-registered)

Committed before any M18 return exists, and before the 10-K text is downloaded. One signal, one holding rule, one
setting; replicated once on unseen stocks. It reuses the M15 basket engine (`tp.high52.monthly_spread`).

## Why, and what we expect

Companies change the wording of their annual report only when something changes in the business, but investors skim and
do not read the changes. [Cohen, Malloy and Nguyen, "Lazy Prices" (Journal of Finance 2020)](https://www.nber.org/papers/w25084)
report that firms whose reports changed most underperform firms whose reports changed least, up to 188 bp a month in
1995-2014, with no reaction on the filing date. I found no post-publication replication in large caps; one
student replication (self-reported, not peer reviewed) saw about +21 bp a month (t about 2) for Item 1A only and
nothing for the whole document, which is why this test uses **Item 1A (Risk Factors) only**. Prior of passing: about 8%.
It is the most different information source of the ideas on the list: text Sift has never used.
Sources: `docs/research/ideas-academic.md` C8, `docs/research/ideas-events.md` E1.

## Data (`scripts/fetch_riskfactors.py`, free)

Every 10-K (form `10-K`, not amendments) of the universe stocks with an EDGAR acceptance time from 2015-01-01 to
2024-12-31, from SEC EDGAR (the 2015 filings are only the "previous year" for 2016). For each: the Item 1A section is
cut out of the main document and reduced to word counts (the raw document is discarded). **10-Ks from 2025 on are not
downloaded: they are the holdout.**

- **Primary universe:** the 150 stocks of `config/universe_events.toml`. **Replication:** the 250 of `config/universe_confirm.toml`.
- **Data hygiene, declared up front:** drop any stock with a one-session gain above +100% in its daily closes.

### Item 1A extraction (frozen here, `tp.lazyprices`)

Tags are stripped, block tags become line breaks, entities decoded. Candidate sections run from a line matching
`item 1a` followed by `risk factors` to the next line matching `item 1b` or `item 2 properties`. The **longest** candidate
wins (this skips the table of contents). A section under 3,000 characters is rejected ("not required" statements and
broken matches). Words are lowercase runs of three or more letters, minus a fixed list of 120 common English words.

**Parse-rate gate, checked before any return is computed:** if fewer than 70% of the downloaded 10-Ks give a valid
Item 1A, or fewer than 70% of 2016-2024 filings have a valid previous-year section, the test is reported as
**inconclusive for data reasons** and the parser is fixed and re-registered before anything is run. Parse rate is a
data property and does not look at returns.

## Signal and rule (frozen here)

- **Similarity** of a 10-K: the cosine similarity between its word-count vector and the same company's previous 10-K
  (filed 300 to 430 days earlier, the closest to 365), both with a valid Item 1A.
- **Signal known at the close of session t:** the latest 10-K with an acceptance date strictly before t's date, if filed
  within the last 135 days. **Highest similarity = fewest changes = long.**
- **Rule:** as M15. Rebalance on the first session of each calendar month; trades at that open; held to the next month's
  first-session open. **Long the quintile with the highest similarity, short the lowest**, equal weight, dollar neutral,
  5 bps a side. A month needs at least **20 ranked stocks**; otherwise it is skipped (most 10-Ks are filed in February and
  March, so the book is only populated in about half the months).
- **Period:** monthly rebalances from February 2016 to November 2024.
- Not tuned or varied: the similarity measure, 135-day window, quintiles, minimum of 20, the stop-word list. Item 1 (business),
  Item 7 (management discussion), the 10-Qs and tone measures are **not tested**.

**What was looked at before this protocol:** the fields in the cached EDGAR submission files (form types, document
names). No 10-K text and no returns.

## Pass criteria: all five

1. At least 48 months of results on the primary universe. Fewer means **inconclusive, not passed**.
2. Mean net monthly long-short return above zero with the lower bound of its 95% interval above zero (plain t-interval).
3. Positive mean in at least 6 of the 9 calendar years 2016-2024 (years with no month in the book count as not positive).
4. Positive mean in both halves (earlier half and later half of the months).
5. **Replication:** on the 250 unseen stocks, a positive mean net monthly return, positive in both halves.

Reported, not judged: gross mean, long leg minus SPY, short leg alone, beta to SPY, parse rate by year, the number of
months in the book, results by change in Item 1A length.

## If it passes

One run on the 2025+ 10-Ks and bars (a new download), once, reported whatever it shows. Only then would paper trading follow.

## Limits

- **Large caps.** The paper's effect was strongest in smaller firms; firms in this universe change their risk factors
  every year, so there is less variation to rank.
- **Boilerplate.** A new risk factor about a pandemic or a rule change moves every firm's similarity at once (2020, 2022);
  the ranking is within each month, which absorbs it.
- **Parser errors.** Item 1A headings vary by filer. Some sections are cut wrong; the gate above limits this.
- **Annual and clustered.** Signals arrive once a year, mostly in February and March, so the observations are fewer than
  the months suggest and are not independent. The interval is optimistic.
- **Stocks listed today;** shorting costs are not modelled.
