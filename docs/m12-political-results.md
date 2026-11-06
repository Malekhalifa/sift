# M12 results: political news gives nothing a slower trader can catch

Two event studies, run once under `docs/m12-political-protocol.md`: presidential posts that name a listed company
(P1) and large Pentagon contract awards to listed primes (P2), on daily bars, entering at the first open after the
news could be known, holding five sessions, market-adjusted, net of 10 bps round trip. **The 2025+ holdout was never
touched.** No trials were added to the registry (298), since these are event studies, not strategy sweeps.

## Verdict: neither passes

| Check | P1 presidential posts | P2 Pentagon awards |
|---|---|---|
| At least 100 events | pass (133) | pass (933) |
| Mean net return above 0, interval lower bound above 0 | **fail** (-0.053% +-0.600) | **fail** (-0.098% +-0.265) |
| Positive in 2/3 of years with 8+ events | **fail** (2 of 6 years) | **fail** (5 of 9 years) |
| Positive in both halves | **fail** (-0.47%, then +0.36%) | **fail** (-0.21%, then +0.01%) |

Add the 10 bps of costs back and the gross averages are about +0.05% (posts) and 0.00% (awards): zero within noise.

## What it says

- **Posts.** 133 events (83 positive, 50 negative by the word-list tone). The mean is -0.05% with a +-0.60% interval, so
  anything from -0.65% to +0.55% is consistent. By tone: positive posts -0.01%, negative posts -0.12% (both signed
  so a positive number means the trade direction was right). Without Facebook and Amazon, which are 53 of the 133, it is
  -0.44%. The two eras disagree (2016-2018 negative, 2022-2024 positive), which is what noise looks like. The test
  starts at the first open after the post, so it measures what remains once the market has opened, not the first
  minutes.
- **Awards.** 933 events across seven primes, nine years. The mean is -0.10% +-0.27%, and the 1-session and 20-session
  holds are also slightly negative (-0.13% +-0.10, -0.34% +-0.54). Even sorted by year, the sign flips back and forth
  (2020 is -1.78%, driven by the COVID crash). Large contracts to large primes are expected and small against their
  revenue, as the protocol guessed.
- **The thesis is untested in the one place it lives.** "The stock sky-rockets when he says it" is about the first
  seconds to minutes. Daily bars cannot see that, and so cannot a retail trader's tools, which is why the test started at
  the open. The published same-day reaction for negative tweets on non-media firms
  ([Ajjoub, Walker and Zhao](https://econpapers.repec.org/RePEc:eme:ijmfpp:ijmf-02-2020-0068)) is in that window.
  What the data shows is that after the first session opens, there is nothing left to trade.
- **A correction.** An earlier note of mine said Ajjoub et al. found next-day reversals. I could not confirm that; their
  abstract reports same-day declines after negative tweets, so the protocol cites it that way.

## What was not tested

Intraday entry on the 60 names with minute-level data (a handful of events), the 2019-2021 tweets (the CSV archive's
clock is inconsistent), the president's own disclosed trades, Donald Trump Jr.'s trades (no public per-trade source) and
politicians' STOCK Act filings. The 2025+ posts, when the president was in office and named companies more often, are the
holdout; they would be read once, and only if a study had passed.

## Where the project stands

Twelve ideas have now been tested under pre-registered rules: opening-range breakout and fade, RSI(2) reversion, the
20/200-day pullback, earnings drift (plus a failed confirmation), UT Bot + STC, Supertrend + Waddah, insider buying,
volume-dry-up reversal, high-volume continuation, presidential posts and Pentagon awards. None has an edge after costs
and after the market. 298 trials are logged, the 2025+ holdout is untouched, nothing has been paper traded for evidence,
and no money has been at risk.
