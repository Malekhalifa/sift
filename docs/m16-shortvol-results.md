# M16 result: abnormal short-sale volume points the right way, but not strongly enough to pass

Run once, as pre-registered in [m16-shortvol-protocol.md](m16-shortvol-protocol.md) (`scripts/shortvol_study.py`; raw output in
`data/logs/m16-shortvol.txt`). Short-volume files and bars from 2025 on were not read.

Long the lowest quintile of abnormal short share (60-session average minus 250-session average of short volume over total
volume), short the highest, rebalanced monthly, 64 months (2019-08 to 2024-11), net of 5 bps a side:

| | Primary, 150 stocks | Replication, 246 unseen stocks |
|---|---|---|
| Mean net long-short return | **+0.38% a month**, 95% interval ±0.59% | **+0.34% a month**, ±0.47% |
| Before cost | +0.44% | +0.41% |
| Months above zero | 48% | 56% |
| First half / last half | +0.65% / +0.10% | +0.44% / +0.25% |
| Years positive | 4 of 6 (2019 and 2023 negative) | 4 of 6 (2019 and 2024 negative) |
| Beta to SPY | +0.08 | -0.05 |

**Verdict: not eligible.** Four of five criteria pass (enough months, positive in 4 of 6 years, positive in both halves,
replicated on unseen stocks) and one fails: the lower end of the 95% interval is below zero on both universes (-0.21% and
-0.13% a month). This is the closest any of the idea families has come, and it is the first whose sign replicated on
stocks it was not run on. It is not a pass: with 64 observations, an effect of +0.35% a month cannot be told from luck, and
the pre-registered rule was that all five criteria must hold. Nothing was tuned or varied after the result.

**Caveats that cut both ways.** The data starts in August 2018, so the window is short and includes 2020-22, a regime of
unusual retail and short-selling activity. FINRA's file covers only off-exchange reports, so the signal is a noisy proxy
of true short selling, which could hide a real effect. The result is also long-short and dollar neutral, so it does not
depend on the market rising (beta near zero), which is the trap that caught the insider-buying and volume ideas. Borrow
fees are not modelled; the short leg is the high-short-share stocks, which are likelier to be expensive or hard to borrow,
so the real result would be lower than shown.

**What it means for next steps.** The 2025 and 2026 files are stored, which is exactly what a confirmation needs. But the
holdout rule says only ideas that pass all criteria earn the one-shot run, and this did not, so the holdout stays sealed.
A longer test would need more history than FINRA's free files offer (consolidated start 2018-08), or a broader universe.

Trials logged: one run of one setting. Holdout still untouched.
