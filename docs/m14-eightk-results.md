# M14 result: 8-K bad-news items leave nothing a slower trader can catch

Run once, as pre-registered in [m14-eightk-protocol.md](m14-eightk-protocol.md) (`scripts/eightk_event_study.py`, raw output in
`data/logs/m14-eightk.txt`). The 2025+ holdout was not read.

**879 events** on 289 stocks, 2016-2024. Shorting the stock against SPY for five sessions from the first open after the
filing, net of 10 bps:

| Measure | Result |
|---|---|
| Mean net return | **+0.092%** per event, 95% interval ±0.320% |
| Share of events above zero | 51% |
| Early half / later half | -0.22% / +0.41% |
| Years positive (all 9 have ≥ 8 events) | 5 of 9 |

**Verdict: not eligible.** One of four criteria passes (enough events). The interval spans zero, the result flips sign
between the two halves, and 2019 alone is -0.76%.

Informational: a 1-session hold -0.07%, a 20-session hold -0.19%, the long side -0.29%. By item, none is distinguishable
from zero: 1.02 (n=574) +0.14%, 2.05 (n=158) +0.29%, 2.06 -0.11%, 3.01 -0.12%, 4.01 -0.07%, 4.02 (n=7) -0.62%. The 4.02
sample is too small to read.

**What it means.** Same pattern as the Pentagon awards and presidential posts: by the time a slower trader can act at the
next open, large-cap bad news is already in the price. The short side shows nothing before costs either (mean excess
return of the stock over SPY is -0.19% over five sessions with an interval about ±0.32%). Survivorship hides short-side
edges (delisted companies are missing), so this is evidence against a large edge, not proof of none.

Trials logged: this is one study with one pre-declared setting. Holdout still untouched.
