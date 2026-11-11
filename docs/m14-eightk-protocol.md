# M14 protocol: 8-K bad-news items, as one event study (pre-registered)

Committed before any M14 return exists. One question, one hypothesis, tested as a plain event study: if there is no
average move after the filing, no trading rule built on it can work.

## Why, and what we expect

Companies must file an 8-K within four business days of certain events. Six item codes are bad news by definition:
1.02 termination of a material agreement, 2.05 exit or disposal costs (restructuring), 2.06 material impairments,
3.01 notice of delisting, 4.01 change of auditor, 4.02 non-reliance on past financial statements. The thought is that
the market absorbs such news slowly, so the stock keeps falling after the filing.

Evidence is thin and mixed. [Lerman and Livnat (2010)](https://ideas.repec.org/a/spr/reaccs/v15y2010i4d10.1007_s11142-009-9114-7.html)
find abnormal volume and volatility around every 8-K item and some drift after filing; I could not identify which
items or how large (abstract only). For Item 4.02 specifically, an Audit Analytics summary of 5,111 restatement filings
(2005-2016) found no abnormal decline afterwards and a bounce months later, which is evidence against shorting. Bad news
in large caps is usually priced within minutes, the same pattern that left nothing after presidential posts and
Pentagon awards. Prior of passing: about 4%. Source: `docs/research/ideas-events.md`, E4.

## Data (`scripts/fetch_eightk.py`, free, already cached)

Every 8-K for the 393 universe symbols with a CIK, from SEC EDGAR submission files: acceptance time (UTC, to the second)
and item codes. Nothing new is downloaded. Filings from 2025 on are stored but **not analysed here: they are the
holdout.**

## Events

An 8-K is an event when it carries at least one of the six codes and does **not** carry Item 2.02 (an earnings release the
same day would confound the reaction). Within a symbol, a filing less than 5 calendar days after the last kept one is
dropped. Period: filings accepted 2016-01-04 to 2024-12-31. **879 events, 289 symbols** (2016-2024: 110, 86, 114, 107,
114, 106, 75, 83, 84 per year). By item: 1.02 574, 2.05 158, 2.06 94, 3.01 45, 4.01 23, 4.02 7.

**What was looked at before this protocol:** the number of 8-Ks per item code, and the event counts above. No returns.
Item 5.02 (officer changes) is left out on purpose: it mixes pay-plan votes with real departures and separating them
needs the filing text. The six codes and the 2.02 exclusion were fixed here, not tuned.

## Trade timing and return

Daily bars, split-adjusted. A filing accepted before 09:30 ET on a session day is first tradable at that open; any other
filing at the next session's open (so an intraday filing's own-day reaction is skipped, which errs against finding an
effect). For each event: the stock's return from that open to the close of the fifth session, minus SPY's over the same
dates, **signed short** (an event is profitable if the stock falls more than the market), minus **10 bps** round trip.
Informational only, not judged: holds of 1 and 20 sessions, the long side (the sign flipped), and each item code alone.

## Pass criteria: all four

1. At least 100 events with measurable returns. Fewer means **inconclusive, not passed**.
2. Mean net signed return above zero with the lower bound of its **95%** interval above zero (one study; clustering of
   events is ignored, so the interval is optimistic).
3. Positive mean in at least two thirds of the calendar years that have at least 8 events.
4. Positive mean in both halves of the events (earlier half and later half by date).

## If it passes

One run on the 2025+ filings, once, reported whatever it shows. Only then would a monitor and paper trading follow.

## Limits

- **Stocks listed today.** Companies that were delisted after bad news are missing, which hides short-side edges rather
  than flattering them.
- **One basket of six items.** Pooling blurs any single item; splitting multiplies trials, so each item is informational.
- **Daily bars cannot see the first minutes**, where most of a reaction happens. Short-selling costs (borrow fees) are
  not modelled beyond the flat 10 bps.
- **Not tested:** 5.02 officer departures, 8-K items outside the six, 10-K/10-Q text.
