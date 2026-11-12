# How Sift decides whether a strategy works

A working guide to the testing workflow, written from what the first 17 tests taught. The aim is that any new idea
goes through the same gate, and that "it worked" and "it did not" mean the same thing every time.

**The rule everything hangs on:** no real money until an idea has proved itself on data it was not tuned on. Starting
capital is $0, data is free, and a missing result is more useful than a flattering one.

## 1. The lifecycle of one idea

```
idea -> research -> pre-register -> build -> run once -> verdict -> record -> (holdout -> paper trading)
```

| Stage | What happens | Where it lives |
|---|---|---|
| **Idea** | A belief about prices, from a paper, a book, a video, an intuition. | `docs/research/`, `docs/ideas/` |
| **Research** | What is the published evidence? How big, how much decay after publication? Is the data free, point in time, and long enough? Rank by (chance of surviving a fair test) × (can we test it today). | `docs/research/ideas-*.md` |
| **Pre-register** | Write the protocol and **commit it before any return exists**: hypothesis, data, exact signal and rule, one setting, pass criteria, what was looked at beforehand, limits. | `docs/mNN-<name>-protocol.md` |
| **Build** | Downloader, signal code, unit tests. Check plumbing only: row counts, date ranges, parse rates. Never look at returns while building. | `scripts/fetch_*.py`, `src/tp/`, `tests/` |
| **Run once** | One run of the frozen setting. Log it as a trial. | `scripts/*_study.py`, `data/logs/mNN-*.txt` |
| **Verdict** | Apply the criteria exactly as written. | results doc |
| **Record** | Write the result whatever it shows, including near misses and deviations. | `docs/mNN-<name>-results.md` |
| **Holdout and paper** | Only an idea that passes every criterion earns one run on the sealed 2025+ data, then paper trading. | see section 6 |

The git history is the proof of order: a protocol commit must precede the commit that records its result.

## 2. What "works" means: the checks

A single positive backtest means almost nothing. An idea counts as working only if it survives **all** of these.
Which exact checks apply depends on the kind of test; each protocol lists its own.

| Check | Question it answers | Typical bar |
|---|---|---|
| **Enough observations** | Is the sample large enough to tell skill from luck? | 100+ events, 300+ trades, or 60+ months. Fewer means **inconclusive, not passed**. |
| **Interval above zero** | Is the average gain bigger than noise? | Lower bound of the 95% interval (97.5% when two studies share the error budget) above zero. |
| **Costs included** | Does it survive realistic fills? | Next-bar open plus slippage, 5-10 bps per side; survives double slippage for trade-level tests. |
| **Beats the market** | Is it skill, or did stocks just rise? | Subtract SPY over the same dates, or use a dollar-neutral long-short basket. Long-only results need this. |
| **Consistent over time** | Is it one lucky year? | Positive in at least two thirds of the calendar years. |
| **Both halves** | Did it only work early (or late)? | Positive in the first half and the second half of the sample. |
| **Selection luck** | Did we find it by trying many things? | Deflated Sharpe Ratio against the full trial count (sweeps); for a single frozen setting there is nothing to deflate. |
| **Neighbours** | Is the winning setting a fluke of tuning? | At least 70% of settings one step away are also positive. |
| **Replication** | Does the same frozen rule work on stocks it never saw? | Positive mean and positive in both halves on a separate universe. |
| **Holdout** | Is it still there on data nobody looked at? | One run, once, on 2025+ data, reported whatever it shows. |

**Verdicts, only three:**

- **PASSES** every criterion: eligible for the one-shot holdout run. Nothing else.
- **NOT eligible:** at least one criterion failed. Close the idea, publish the result, do not relax the bar.
- **INCONCLUSIVE:** too little data to judge (too few events or months). Say so; it is not a pass and not a proof of no edge.

**Near misses are not passes.** M16 (short-sale volume) had a positive average on both universes and both halves, and
failed only because its interval touched zero. It stays "not eligible". The honest sentence is "the closest any idea has
come, and sixty-four months cannot tell it from luck", not "it almost works". A near miss can justify a *new*
pre-registered test (longer history, wider universe); it never justifies re-reading the old one.

## 3. How a backtest lies, and the guard for each lie

These are the ways a good-looking result is wrong, each with the case where Sift met it.

| Lie | What it looks like | Guard | Case |
|---|---|---|---|
| **The market's rise** | Long-only rules profit because stocks went up. | Market-adjusted check; dollar-neutral baskets. | Insider buying: +0.03R raw, -0.08R after subtracting the market. High-volume continuation: +0.10R raw, -0.04R adjusted. |
| **Selection luck** | The best of many tried settings fits the past by chance. | Pre-registered single setting; every run logged; Deflated Sharpe. | Earnings drift passed 5 of 6 checks, then failed Deflated Sharpe. |
| **Overfit universe** | A setting chosen on 10 mega caps. | Replicate on unseen stocks by a fixed rule (liquidity rank). | Earnings drift: +0.156R, then +0.025R on 250 fresh stocks. Opening-range breakout: +0.065R, then -0.046R. |
| **Look-ahead** | Using information before it was public. | Act at the next open after the timestamp; filings use acceptance time; signals use strictly earlier filing dates. | All event studies. |
| **Survivorship** | Only stocks that exist today are in the data. | Say it in the limits; know which direction it biases (long legs flattered, short legs penalized). | Every test. Small caps and delisted names untested. |
| **Bad data** | A reverse split missing from the split list looks like +12,000%. | Plausibility check on every new replication; one-session jumps above +100% are dropped by a declared rule. | M15 replication read -4.4% a month until EXE, HRI, VAL, OVV were found. |
| **Costs and speed** | A gain smaller than the spread, or one that is gone at the first open. | Realistic fills; entry only at the next open. | Presidential posts, Pentagon awards, 8-K bad news: nothing left at the first open. |
| **Clustering** | Events bunched in a few days look like many independent ones. | Report the caveat; dedupe within windows; do not oversell the interval. | 8-K events, Lazy Prices (annual, February-March). |
| **Small samples** | A big average from a handful of events. | Minimum counts; "inconclusive" is allowed. | Item 4.02 restatements (n=7). |
| **Peeking and re-running** | Looking at the result, then adjusting the rule. | Run once; any rerun is logged and any deviation is written down. | M15's data fix and rerun, disclosed in its results doc. |

## 4. Rules of conduct

1. **Protocol before data when you can, protocol before returns always.** Commit the protocol first. Build and plumbing
   checks are allowed before; looking at returns is not.
2. **One frozen setting per idea.** Variants (other windows, other horizons) are separate protocols and separate trials.
3. **Pre-declare the data hygiene.** If a data problem could hit any universe, write the rule in the protocol. If one is
   found after seeing a result, fix it mechanically, show both runs, and say the fix came after (M15).
4. **Count every run.** The trial registry (`data/trials.sqlite`) counts reruns, including wording-only reruns (301 in
   total after M15). Each future sweep is judged against that count.
5. **Do not relax criteria after the result.** A failed criterion is the finding.
6. **The holdout is sealed.** The code refuses data from 2025-01-01 on (`config.HOLDOUT_START`). Downloaders may store later
   data so a holdout run needs no second download, but no analysis reads it. Anyone who must touch it records why.
7. **Write the limits honestly,** especially the direction of each bias, and what was not tested.
8. **Report the failures publicly.** The negative results are the product.

## 5. The mechanics, so a new idea is fast to run

Pick the shape that fits and reuse the engine.

| If the idea is... | Reuse | Examples |
|---|---|---|
| A per-stock **event** (filing, post, award) | `political_event_study.py` / `eightk_event_study.py`: entry at next open, 5-session hold, minus SPY, signed, minus 10 bps, four criteria | M12, M14 |
| A **cross-sectional ranking** (a number per stock per month) | `tp.high52.monthly_spread(..., signal=...)`: monthly rebalance, long top fifth, short bottom fifth, 5 bps a side, five criteria with replication | M15, M16, M17, M18 |
| An **entry/exit rule with a stop and target** on intraday or daily bars | `scripts/sweep.py` with a grid in `config/sweeps/*.toml`: walk-forward 2019-2024, trial registry, Deflated Sharpe, neighbours | M4, M6, M9, M11 |
| A **market-timing** switch | `trend_filter_study.py` | M13 |

Universes are fixed by a rule, never by hand: ranks 1-150 by Q1-2016 dollar volume for the primary run
(`universe_events.toml`), ranks 151-400 as the unseen replication (`universe_confirm.toml`).

A new milestone's checklist:

1. Research note: evidence, effect size, decay, free data (URL, tested), point-in-time timestamp, event count, why it differs
   from what has been tested, main way it fails, prior of passing.
2. Protocol (`docs/mNN-*-protocol.md`): why, data, signal and rule (frozen), period, hygiene, criteria, holdout rule, limits,
   *what was looked at before the protocol*. Commit.
3. Downloader and signal code with unit tests (no look-ahead test, split or unit handling, a strictly-earlier test). Commit.
4. Plumbing check: counts, date ranges, parse rates. Fix bugs here, never after a result.
5. Run once. Save the raw log in `data/logs/`.
6. Results doc, with the verdict, the table, the caveats, deviations and the trial count. Commit.

## 6. What happens if something passes

Nothing has passed yet, but the path is fixed in advance:

1. One run on the sealed 2025+ data, once, with the frozen setting. Report it whatever it shows. If it fails, the idea is
   closed and the holdout for that idea is spent.
2. Only then paper trading on a broker practice account (the loop exists in `tp.paper`, dry-run by default,
   `touch data/KILL` stops it), with a pre-written plan: minimum duration (3+ months), expected range from the backtest, and
   a stop rule if live results fall outside it.
3. Only after paper results sit inside the expected range is real money discussed, starting small, with a hard loss limit.

A pass would still be a hypothesis: nine years is a short sample, and every published edge decays.

## 7. Scoreboard so far

| Ref | Idea | Result | Verdict |
|:-:|---|---|---|
| 1 | Opening-range breakout | +0.065R, then -0.046R on 50 fresh stocks | Not eligible |
| 2 | Failed-breakout fade | -0.000R | Not eligible |
| 3 | RSI(2) mean reversion | -0.026R | Not eligible |
| 4 | 20/200-day pullback | -0.032R | Not eligible |
| 5 | Earnings drift | 5 of 6 checks, then +0.025R on 250 unseen | Not eligible |
| 6 | Insider buying | +0.028R raw, -0.079R market-adjusted | Not eligible |
| 7 | Presidential posts | -0.05% per event | Not eligible |
| 8 | Pentagon awards | -0.10% per event | Not eligible |
| 9 | UT Bot + STC | -0.038R | Not eligible |
| 10 | Supertrend + Waddah | -0.042R | Not eligible |
| 11 | Volume-dry-up reversal | -0.008R | Not eligible |
| 12 | High-volume continuation | +0.100R raw, -0.039R adjusted | Not eligible |
| M13 | 200-day trend filter on SPY | smoother drawdowns, -4 points a year | Fails CAGR bar |
| M14 | 8-K bad-news items | +0.09% ±0.32% per event | Not eligible |
| M15 | 52-week-high momentum | -0.37% a month | Not eligible |
| M16 | FINRA short-sale volume | +0.38% / +0.34% a month, interval spans zero | Not eligible (closest yet) |
| M17 | Net share issuance | -0.22% / +0.18% a month | Not eligible |
| M18 | Lazy Prices (10-K risk-factor text) | pending | Pre-registered |

The pattern across the first seventeen: when something looked like an edge it was usually the market rising, luck that did
not repeat on new stocks, or news that was already in the price at the first open the trader could act on.
