# M15 result: nearness to the 52-week high has no edge on large caps

Run as pre-registered in [m15-high52-protocol.md](m15-high52-protocol.md) (`scripts/high52_study.py`; raw output in
`data/logs/m15-high52.txt`, first run in `data/logs/m15-high52-first-run.txt`). Bars from 2025 on were not read.

**Primary universe, 150 stocks, 95 months (2017-01 to 2024-11), net of costs:**

| Measure | Result |
|---|---|
| Mean long-short return | **-0.37% a month**, 95% interval ±1.52% |
| Before cost | -0.30% (cost 0.07% a month; turnover 1.4 a month) |
| Months above zero | 49% |
| First half / last half | +0.04% / -0.76% |
| Years positive | 4 of 8 |

**Replication, 250 unseen stocks:** -0.75% a month (±1.34%) after dropping four stocks with a data error (below); both halves
negative. **Verdict: not eligible.** Only criterion 1 (enough months) passes; the primary run already fails 2, 3 and 4.

Informational, primary: the long leg beat SPY by -0.14% a month; the short leg alone gained +1.33% a month (shorting
the stocks farthest below their high lost money because they rebounded); beta of the long-short series to SPY -0.87
(the basket is net short the market's risk, so 2020-21 and 2023, rising markets with a rebound in laggards, hurt);
January -3.9%, in line with the "January is negative" note in the literature.

**What it means.** The anchoring effect documented on all US stocks since 1963 is not there in the 400 largest in
2017-2024: the nearest-to-high stocks did not outrun the farthest. This matches the literature's caution that the effect
is small in large caps and decayed after publication. Ninety-five months give low power, so this rules out an edge big
enough to trade after costs, not an effect of a few basis points. The industry version and a three-month hold were not tested.

## A data problem found along the way

The first replication run returned -4.4% a month with a -19.9% year, which is not plausible. Cause: four stocks in the
replication set (EXE, HRI, VAL, OVV) went through a reverse split that is missing from Alpaca's split list, so their
adjusted prices jump +200% to +12,000% in one session. I dropped any stock with a one-session gain above +100% and reran:
this affects only the replication set (the primary has none). The fix was decided after seeing the first replication,
which is a deviation from the protocol; both runs are logged. It does not change the verdict because the primary run
fails regardless. Other price discontinuities (spin-offs and special dividends such as KDP 2018, AA 2016, IR 2017, and a
wrong split ratio for NVS 2019) are not adjusted either and remain in the data: they add noise but do not point
one way. **Follow-up:** audit the earlier confirmation runs (M8, M11) for events that straddle these bars; the four
stocks are about 1.6% of that universe, so a flipped verdict is very unlikely.

Trials logged: the study ran twice (original and the data-hygiene rerun), both counted. Holdout still untouched.
