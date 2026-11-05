# M9 protocol: the indicator strategies from the original list (pre-registered)

Committed before any M9 result exists. Same discipline as the earlier protocols; only what is listed here differs.

## Why

The project began from four trading videos built on TradingView indicators, charts and filters. Several of their
ideas have been tested already (the 4H range failed breakout as the opening-range fade; the 20/200-day pullback; RSI
and volume and trend filters inside other strategies). The indicator stacks themselves have not. This tests them
with the same rigor, so the belief that "indicators, charts and filters would be better" is settled by measurement.

**The prior is low, and it is stated before the test.** These indicators are transformations of price and volume,
which the earlier tests already used. Candlestick and technical-rule studies on US large caps found nothing that
survives costs and data-snooping corrections (for example
[Bajgrowicz and Scaillet, 7,846 rules on the DJIA](https://archive-ouverte.unige.ch/unige:79889),
[Sullivan, Timmermann and White 1999](https://econpapers.repec.org/RePEc:bla:jfinan:v:54:y:1999:i:5:p:1647-1691),
and the sources in `docs/ideas/candle-strategies.md`). The video performance figures are self-reported and were never
verifiable. My own prior that either family passes is about 3 to 5%.

## What is tested

Two families, on 5-minute bars of the 50-stock universe (`config/universe_wide.toml`), regular hours, split-adjusted,
2016-2024. All use the intraday engine: entry at the next bar's open, stop first when a bar touches both, target at
1.5R (the project's contract; the videos use 2R to 2.8R), flat by 15:55 ET, one open trade per symbol. Entries only
between 09:45 and 15:00 ET (decision time). Indicators run continuously across sessions.

**`utstc`: UT Bot Alerts with an optional Schaff Trend Cycle confirmation (video 4).**

- UT Bot: an ATR trailing stop that ratchets with price and flips when price crosses it (the common QuantNomad/HPotter
  open-source version). A buy is the close crossing above the stop, a sell is crossing below. The video runs two copies
  with different ATR periods for longs and shorts, so long and short settings are separate.
- STC: MACD(23, 50) through a 10-bar double stochastic with 0.5 smoothing (Doug Schaff; LazyBear's version). The
  video's "green and red lines" are ambiguous in the transcript. I read them as the 25 and 75 bands, flagged as my
  assumption. `strict`: a long needs STC below 25 and rising, a short above 75 and falling. `loose`: below or above 50.
  `off`: no confirmation.
- Stop beyond the lowest low (long) or highest high (short) of the last `swing_n` bars, as the video describes.
- Grid, 18 explicit configurations: three UT Bot settings (key 1 with ATR 10; key 2 with ATR 10; the video's key 2
  with ATR 300 for longs and ATR 1 for shorts) x STC mode (off, strict, loose) x `swing_n` (5, 10).

**`stack`: Supertrend + Waddah Attar Explosion, an NNFX-style stack (video 1, the "Algo Flex" bot).**

- Direction from Supertrend (ATR 10, multiplier `st_mult`). Confirmation from the Waddah Attar Explosion histogram
  being above both its explosion line and its dead zone (LazyBear's version: MACD 20/40, sensitivity 150, Bollinger
  20/2, dead zone 3.7 x ATR 100). The signal is the **first** bar on which both agree.
- Stop at `stop_atr` x ATR(14) from entry. The video quotes 3.6; 2.0 is tested as well.
- Optional regime gate, as in the other bots of that video: `adx20` (ADX 14 at least 20) or `chop50` (Choppiness 14 at
  most 50), or `none`.
- Grid, 12 configurations: `st_mult` (2, 3) x `stop_atr` (2.0, 3.6) x gate (none, adx20, chop50).

30 configurations in all, frozen by this commit (`config/sweeps/m9-indicators.toml`).

## What was not tested, and why

The other bots of video 1 depend on indicators whose parameters the transcript does not give or that are
community-proprietary (T3 baseline, JMA, Range Filter settings, zero-lag MACD, TDFI, Stiffness, "Trend IU", the JP
oscillator, Trendhoo, the two-pole Super Smoother). I will not guess them and then call the result a test of the
video. Turtle Ninja and Stiff Surge are therefore **not** covered. The Heikin-Ashi overlay is also left out. This is
a limit of the test: it covers the two strategies specified well enough to code, not the whole list.

## Unchanged

Development period 2016-01-04 to 2024-12-31, **2025+ holdout untouched**, test years 2019-2024, walk-forward selection
on mean R minus one standard error with at least 200 training trades, and the same six pass criteria with the same
thresholds. The Deflated Sharpe trial count is every trial in the registry: 220 earlier trials plus these 30.

## Limits

- **Indicator versions.** These are the common open-source definitions. The video authors may use tweaked copies, and
  TradingView's own numbers can differ slightly (smoothing seeds, session handling).
- **Timeframe.** 5 minutes only. Higher timeframes would be separate trials.
- **Overnight carry.** The indicators run across sessions, so the first bars of a day carry the previous day's state.
- **Universe.** Liquid large-cap survivors, as before. It is also the universe the opening-range tests used.
- **Self-reported video results.** Nothing from the videos is treated as evidence.
