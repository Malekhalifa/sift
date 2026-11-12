# M18 result: Lazy Prices is inconclusive in large caps, and shows no edge where it can be read

Run once, as pre-registered in [m18-lazyprices-protocol.md](m18-lazyprices-protocol.md) (`scripts/lazyprices_study.py`; raw
output in `data/logs/m18-lazyprices.txt`). 10-Ks and bars from 2025 on were not read.

**Data gate (checked before any return):** 3,770 10-Ks for 386 stocks, 2015-2024. Item 1A parsed in **91.2%**; **89.1%** of
2016-2024 filings had a valid section and a valid previous-year section (gate 70%, passed). Parse rate was 89-93% in every year.

Long the 20% of stocks whose Item 1A changed least from the previous year (highest cosine similarity), short the 20% that
changed most, monthly, months with at least 20 ranked stocks, net of 5 bps a side:

| | Primary, 146 stocks | Replication, 246 unseen stocks |
|---|---|---|
| Months in the book | **45** (needed 48) | 78 |
| Mean net long-short return | +0.25% a month, 95% interval ±0.85% | +0.12% a month, ±0.75% |
| First half / last half | -0.03% / +0.52% | +1.06% / -0.83% |
| Years positive | 4 of 9 | 6 of 9 |
| Beta to SPY | -0.15 | -0.02 |

**Verdict: inconclusive.** Criterion 1 fails: the primary universe filled only 45 months with 20 or more stocks (all in
March to July, 9 each; 10-Ks cluster in February and March, so the book is empty for the rest of the year), below the
pre-registered 48. By the protocol that is "inconclusive, not passed". It would not have passed anyway: the interval spans
zero, the primary first half is negative, and the replication's two halves have opposite signs.

**What it means.** The signal was never going to be well powered here: one observation per stock per year, bunched in one
season, in a universe of firms that rewrite their risk factors every year (median similarity 0.986, so the ranking is
among small differences). The few months we can read show a small positive average that is indistinguishable from zero.
This is not evidence that Lazy Prices does not work in smaller firms or in the full text, and it is not evidence that it does.
Not tested: the whole document, Item 7, 10-Qs, tone measures, and smaller stocks, which would need delisted history.

Trials logged: one run of one setting (304 in total). Holdout still untouched.
