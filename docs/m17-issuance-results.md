# M17 result: net share issuance has no edge on large caps

Run once, as pre-registered in [m17-issuance-protocol.md](m17-issuance-protocol.md) (`scripts/issuance_study.py`; raw output in
`data/logs/m17-issuance.txt`). Filings and bars from 2025 on were not read. The first attempt crashed on a datetime
precision mismatch before producing any result; I fixed the join and ran again, so one result exists and one trial is logged.

Long the quintile of strongest net repurchasers (log change in cover-page share count over a year, split-adjusted), short the
heaviest issuers, rebalanced monthly, 106 months (2016-02 to 2024-11), net of 5 bps a side:

| | Primary, 146 stocks | Replication, 246 unseen stocks |
|---|---|---|
| Mean net long-short return | **-0.22% a month**, 95% interval ±0.56% | **+0.18% a month**, ±0.59% |
| Months above zero | 49% | 49% |
| First half / last half | -0.41% / -0.03% | -0.03% / +0.38% |
| Years positive | 3 of 9 | 5 of 9 |
| Beta to SPY | +0.09 | +0.26 |

**Verdict: not eligible.** One of five criteria passes (enough months). The primary run is negative, the two universes
disagree in sign, and neither interval excludes zero. Turnover is low (0.3 a month), so costs are not the story.

**What it means.** In the 400 largest US stocks, 2016-2024, how fast a company grew or shrank its share count told a slower
trader nothing about the following month. This fits the literature's note that the effect is weakest in large caps and
partly priced into factor models. The long leg earned the same as SPY in both universes (-0.02% and +0.03% a month);
what little spread there is comes from the short leg, which is noise at this sample size. Not tested: repurchase dollars,
a three-month hold, and smaller stocks.

Trials logged: one run of one setting. Holdout still untouched.
