# M16 protocol: FINRA short-sale volume, as a monthly long-short basket (pre-registered)

Committed before any M16 return exists. One signal, one holding rule, one setting; replicated once on unseen stocks.
It reuses the M15 basket engine (`tp.high52.monthly_spread`) with a different signal, so timing, cost and ranking rules
are identical.

## Why, and what we expect

Short sellers trade on information, so a stock they have been selling heavily for weeks should do worse than one they
have left alone. [Wang, Yan and Zheng (2020, JFE)](https://ideas.repec.org/a/eee/jfinec/v135y2020i1p191-212.html) find that
short-selling flows predict lower returns over 2010-2015, with long-term flows more informative than short-term spikes,
which is why the signal below is a 60-day average. [Diether, Lee and Werner (2009, RFS)](https://econpapers.repec.org/RePEc:oup:rfinst:v:22:y:2009:i:2:p:575-607)
found the daily version predictive in 2005 but eaten by costs. FINRA's file covers only trades reported to its
facilities (off-exchange), so the "short share" mixes market-making hedges with informed shorting, and almost every
large stock sits near 40-50%, leaving little to rank. Prior of passing: about 6%.
Source: `docs/research/ideas-academic.md` C9, `docs/research/ideas-events.md` E2.

## Data (`scripts/fetch_finra.py`, free)

FINRA consolidated daily short-sale volume (`CNMSshvolYYYYMMDD.txt`), the first file is 2018-08-01. FINRA states each file
is posted by 18:00 ET on the trade date, so a signal built from day t's file is known before the next open. The page states
no licence, so the data stays local (`data/` is not committed). Files from 2025 on are stored but **not analysed
here: they are the holdout.** Because the history starts in August 2018, the test is shorter than the earlier ones.

- **Primary universe:** the 150 stocks of `config/universe_events.toml`. **Replication:** the 250 of `config/universe_confirm.toml`.
- **Data hygiene, declared up front** (from the M15 finding that four stocks have a reverse split missing from the split
  list): in both universes, drop any stock with a one-session gain above +100% in its daily closes.

## Signal and rule (frozen here)

- **Short share** of day d: `ShortVolume / TotalVolume` from the consolidated file.
- **Abnormal short share** at the close of day t: the mean short share over the last 60 sessions (at least 45 with data)
  minus the mean over the last 250 sessions (at least 200 with data). A stock needs both.
- **Rule:** as M15. Rebalance on the first session of each calendar month; the signal is the previous session's close;
  trades at that open; held to the next month's first-session open. **Long the lowest quintile of abnormal short share,
  short the highest quintile**, equal weight, dollar neutral, 5 bps a side on traded weight.
- **Period:** monthly rebalances from August 2019 (the first with 250 sessions of FINRA history) to November 2024,
  **64 months**. December 2024 is not held, so no return touches 2025.
- Not tuned or varied: the 60/250-session windows, quintiles, monthly horizon, equal weights, the short-volume
  definition. Short interest (bi-monthly) and shorter horizons are **not tested**.

**What was looked at before this protocol:** the file format and row counts, the date range, and which universe symbols are
present. No returns and no relation between short share and returns.

## Pass criteria: all five

1. At least 60 months of results on the primary universe. Fewer means **inconclusive, not passed**.
2. Mean net monthly long-short return above zero with the lower bound of its 95% interval above zero (plain t-interval).
3. Positive mean in at least 4 of the 6 calendar years 2019-2024 (2019 has 5 months, 2024 has 11).
4. Positive mean in both halves (first 32 months, last 32).
5. **Replication:** on the 250 unseen stocks, a positive mean net monthly return, positive in both halves.

Reported, not judged: gross mean, long leg minus SPY, short leg alone, beta to SPY, turnover.

## If it passes

One run on the 2025+ files, once, reported whatever it shows. Only then would paper trading follow.

## Limits

- **Six years, one regime of short-selling.** Sixty-four monthly observations give low power: a "no" reads as no edge
  big enough to trade, not as zero.
- **Off-exchange only and market-maker dominated,** the published predictability is for all short flow.
- **Stocks listed today,** and corporate actions other than splits (spin-offs, special dividends) are not adjusted.
- **Shorting costs are not modelled** (borrow fees, availability) beyond the 5 bps.
