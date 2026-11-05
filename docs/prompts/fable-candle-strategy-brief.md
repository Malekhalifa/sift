# Brief for Fable 5.1 (high effort): candle and price-action strategy analysis

You are advising on a personal, self-funded research project that tests short-term US stock trading strategies
under strict anti-overfitting rules. I want your **analysis and design**, not code and not backtests. Your one
deliverable is a markdown file at

    /Users/m6l9k/.t3/projects/trading-pipeline/docs/ideas/candle-strategies.md

Write for a reader who is smart but not a quant: plain language, short paragraphs, tables where they help, every
technical term explained the first time.

## What the project is and what has already failed

A pipeline that records market data, backtests rules, and (much later, only after a rule survives) paper trades
and then trades real money. Start capital is $0 and nothing has been put at risk. Read these first, they are
short:

- /Users/m6l9k/.t3/projects/trading-pipeline/README.md
- /Users/m6l9k/.t3/projects/trading-pipeline/docs/m4-protocol.md, m4-results.md, m4b-results.md, m6-swing-protocol.md, m6-results.md (same folder)
- Skim /Users/m6l9k/.t3/projects/trading-pipeline/src/tp/backtest.py and src/tp/swing.py (module docstrings define the fill model), and src/tp/strategies/*.py for the style of rule we already test.

Already tested properly, with every pre-registered check failed, on 10 to 60 liquid large-cap stocks, 2016-2024:

| Family | Bars | Result out of sample (R = one unit of risk) |
|---|---|---|
| Opening-range breakout (5-minute) | intraday | -0.046R +-0.028 on 50 stocks; -0.020R at zero cost, so no gross edge |
| Failed-breakout fade of the opening range | intraday | about 0R, 4% of variants positive |
| RSI(2) mean reversion, with and without a 200-day trend filter | daily | -0.026R +-0.021 |
| 20/200-day moving-average pullback | daily | -0.032R +-0.028 |

177 trials are logged, and the significance check (Deflated Sharpe) counts every one. The 2025+ data is a
holdout nobody has looked at. Conclusion so far: plain price-pattern rules on liquid large caps look like an
empty search space at this level. Long sides were about zero and short sides clearly negative, which may reflect
a rising market and a universe of stocks that are still listed today.

## Hard constraints on any strategy you propose

1. Every rule must be computable from OHLCV bars that have **already closed**. Decision at a bar's close, entry at
   the next bar's open. No discretion, no "looks like a hammer to me", no look-ahead.
2. Every trade is a bracket: a stop, a target at **1.5 times the risk**, and a time exit. Short-term holding
   (minutes to a few weeks). Stocks only.
3. Data we have: Alpaca SIP consolidated bars from 2016. 1-minute for 12 tickers, 5-minute for 50 more, daily for
   about 60 (more can be added cheaply, daily only). No order book, no options, no fundamentals yet. Costs: one
   cent per share slippage each way is already charged; stop exits and gaps are modelled pessimistically.
4. Out-of-sample discipline: walk-forward selection, test years 2019-2024, six fixed pass criteria (300+ trades,
   expectancy interval above zero, Deflated Sharpe at least 0.95, positive in 4 of 6 years, positive at double
   slippage, 70% of neighbouring parameter settings positive).

## The questions I want answered

**A. The landscape.** Cover the families of candle and price-action ideas that traders actually use, grouped
sensibly. At minimum consider: single-candle shapes (hammer, shooting star, doji, marubozu, long wicks and
rejection), two- and three-candle patterns (engulfing, harami, piercing, morning and evening star), inside and
outside bars, volatility compression then expansion (narrow-range bars such as NR4 and NR7), gaps (fills and
continuation), close-location and internal bar strength, wick-to-body ratios combined with volume, breaks of the
prior day's high or low and of N-day highs and lows, volume climax and dry-up, and Heikin-Ashi. Add anything
credible I have missed.

**B. Evidence, honestly.** For each family: what does credible academic or quantitative evidence say, has it been
replicated, has it decayed since publication, what is the economic reason it could pay (who is on the other side
and why would they keep losing), and how sensitive is it to costs? Use web search. **Cite sources with URLs. Do
not invent citations. If you are recalling something from memory, label it "recollection, verify".** Say plainly
when the evidence is weak or when you found none. The classic candlestick-pattern literature is a good place to
start and I would like to know what it actually found.

**B2. Charts read by a vision or language model.** Is there any credible evidence that a model looking at chart
images or candle sequences adds value beyond simple rules? Explain the specific leakage danger (a model may have
memorised how a famous chart ended) and design a test that would be honest about it, using only what we can
build.

**C. Up to three hypotheses worth pre-registering**, ranked by your honest prior probability of surviving, not by
how interesting they are. For each give:

- the exact rule, written so that two people would code it identically, with every parameter named;
- which of our engines fits (5-minute intraday or daily swing) and why;
- a parameter grid of **at most 24 configurations**, justified (we pay for every trial);
- the economic story in two sentences, and the specific reason it might **fail**;
- a rough guess of trades per year on 50 to 150 stocks and whether the 300-trade criterion is reachable;
- what result would make you abandon it, stated in advance.

**D. A kill list.** The popular candle ideas you expect to be pure noise given the evidence and what we already
measured, each with one line of reasoning. Being told "do not bother with X" is as valuable as a new idea.

**E. Order of work.** Which one to test first and why, how it interacts with the 177 trials already counted, and
any risk that the three hypotheses are really the same bet and so inflate our apparent diversification.

## Rules for how you work

- **Do not run backtests and do not look at results from our data.** Looking at development-period results while
  designing multiplies the ways to fool ourselves; the design must come from the literature and from reasoning.
- **Do not modify any file except the single deliverable.** Do not edit code, configs, the trial registry or
  anything under `data/`. Do not read or ask for anything dated 2025 or later.
- Web search and page fetches for literature are fine. Nothing else leaves the machine.
- Be calibrated. If the honest answer is "most of this is noise and here is the one thing worth a test", say so
  and keep it short. Do not pad the document to look thorough, and do not recommend something because it is
  popular.

## Shape of the deliverable

1. A five-line summary of your conclusions (what is worth testing, what is not).
2. The landscape and evidence table (A and B), including sources.
3. The vision/language-model section (B2).
4. The up-to-three hypotheses (C), each in the format above.
5. The kill list (D) and the order of work (E).
6. A short list of what you are unsure about and could not verify.

Target roughly 1,500 to 2,500 words plus tables. Finish by replying with the file path and a five-line summary.
