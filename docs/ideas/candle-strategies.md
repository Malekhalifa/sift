# Candle and price-action strategies: what the evidence supports, and what to test

Written from the literature and from reasoning only. No backtest was run, no project data was read, and the 2025+
holdout is untouched. Sources are linked; anything I could not verify online is marked "recollection, verify".
By the brief's rule I did not read anything dated 2025 or later, so one relevant 2026 benchmark is excluded
(see the last section).

## Summary in five lines

1. Classic candlestick patterns (hammer, doji, engulfing, stars, harami) have been tested properly on large US
   stocks at least four times and never survived costs; they are a kill list, not a research programme.
2. The only candle-adjacent ideas with replicated, economically grounded evidence on large caps are
   **volume-conditioned reversal** (a stock that fell against its peers on falling volume tends to bounce) and the
   **high-volume return premium** (a volume spike is followed by a few weeks of drift up). Both are old and have
   probably decayed.
3. I propose three pre-registered hypotheses, 44 configurations in total, ranked by my prior of passing all six
   criteria: volume-dry-up relative reversal (~12%), high-volume continuation (~8%), low-volume gap fade (~6%).
   The honest expectation is that all three fail; the point is that each failure closes a real family.
4. Charts read by a pretrained vision or language model have no credible pre-2025 evidence of beating simple rules,
   and a model can recall how a famous chart ended. A self-trained image model (Jiang, Kelly and Xiu) does have
   strong evidence, but on a universe fifty times ours. Not now; an honest leakage test is designed below.
5. The first two hypotheses are different bets (liquidity provision vs attention) but all three share the same
   trading horizon, market and universe, so they diversify the idea space, not the risk. Test them in order, one
   sweep each, and stop at the first gross-edge failure within a family rather than retuning.

## The arithmetic every rule has to beat

Expectancy in R is roughly (expected move in the direction of the trade, net of costs) divided by the stop
distance. One cent each way on a $100 stock is 2 basis points (bps; 1 bp = 0.01%) per round trip, plus the
one-cent trade-through on the target. The M4b cost diagnostic showed costs took about 0.026R off a gross result
that was already zero. So the question for any candle idea is: **does the published conditional drift exceed the
budget below, in liquid large caps, in 2019-2024?**

| Stop as % of price | Typical engine | Drift needed for +0.05R net (cost-adjusted) |
|---|---|---|
| 0.5% (tight 5-minute stop) | intraday | ~5 bps per trade |
| 1.3% (M4b median) | intraday | ~9 bps |
| 2-4% (1-2 ATR, daily) | swing | ~12-25 bps over the hold |

Most candlestick findings, where positive at all, report 10-30 bps **gross** over one to three days, before
spreads, in older or retail-heavy markets. That is the whole story in one table.

## A and B. Landscape and evidence

Terms used below. *Bootstrap / data-snooping test*: a check that the best of many rules beats what luck alone
would produce. *Reversal*: a move that gives back. *Continuation* or *drift*: a move that keeps going.
*Liquidity provision*: being paid a small premium for taking the other side of an impatient trader.

| Family | What credible evidence says | Replicated? Decayed? | Who loses on the other side | Cost sensitivity |
|---|---|---|---|---|
| **Single-candle shapes** (hammer, shooting star, doji, marubozu, long wicks) | [Marshall, Young & Rose 2006](https://econpapers.repec.org/RePEc:eee:jbfina:v:30:y:2006:i:8:p:2303-2323): 28 Nison patterns on DJIA stocks 1992-2002, bootstrap, "no evidence that any candlestick signals predict price movements" (per [Marshall's thesis](https://mro.massey.ac.nz/handle/10179/1604)). [Marshall, Young & Cahan 2008](https://ideas.repec.org/a/kap/rqfnac/v31y2008i2p191-207.html): same answer in Japan 1975-2004. [Horton 2009](https://econpapers.repec.org/RePEc:eee:quaeco:v:49:y:2009:i:2:p:283-294): 349 stocks, no value. [Duvinage, Mazza & Petitjean 2013](https://econpapers.repec.org/RePEc:taf:quantf:v:13:y:2013:i:7:p:1059-1070): 83 rules on 5-minute DJIA bars; "limited predictive power", nothing beats buy-and-hold after costs and snooping. | Replicated as a null, four times. Nothing to decay. | Nobody identifiable. A long lower wick is a within-day bounce, which [Heston, Korajczyk & Sadka 2010](https://arxiv.org/abs/1005.3535) attribute to bid-ask bounce and liquidity imbalances lasting under an hour. | Fatal. [Atkins & Dyl 1990](https://ideas.repec.org/a/cup/jfinqa/v25y1990i04p535-547_00.html) and [Cox & Peterson 1994](https://econpapers.repec.org/RePEc:bla:jfinan:v:49:y:1994:i:1:p:255-67): reversal after a big one-day move exists but is smaller than the spread. |
| **Two- and three-candle reversals** (engulfing, harami, piercing, morning/evening star) | The one positive: [Caginalp & Laurent 1998](https://econpapers.repec.org/RePEc:taf:apmtfi:v:5:y:1998:i:3-4:p:181-205), all S&P 500 stocks 1992-96, eight three-day reversal patterns, ~0.9% gross over two days (0.56-0.76% after their cost estimate). Marshall et al. 2006 then found nothing on DJIA stocks over 1992-2002 with a bootstrap. [Lu, Chen & Hsu 2015](https://ideas.repec.org/a/eee/jbfina/v61y2015icp172-183.html) show the answer flips with the exit rule: Caginalp's exit "profitable" at 0.5% cost on DJIA data, Marshall's exit not. [Tharavanij et al. 2017](https://journals.sagepub.com/doi/10.1177/2158244017736799) (Thailand, both exits): most patterns indistinguishable from zero. Taiwan/China positives ([Lu 2014](https://econpapers.repec.org/RePEc:eee:pacfin:v:26:y:2014:i:c:p:65-78), [Zhu, Atri & Yegen 2016](https://ideas.repec.org/a/eee/pacfin/v37y2016icp116-127.html)) come from retail-heavy markets and, in Zhu et al., from small liquid stocks. | Not replicated on US large caps; result depends on a researcher degree of freedom (the exit). The 1992-96 window predates decimalisation and HFT market making. | Retail traders reacting to the same picture; plausible in 1990s Taiwan, implausible in 2020s AAPL. | Fatal at our cost level: the claimed 0.9% gross over two days is the kind of number that was later found to be inside bid-ask bounce on the same data era. |
| **Inside bars, NR4, NR7, volatility compression** | No peer-reviewed test found. The source is [Crabel 1990](https://store.traders.com/-v07-c05-orb-pdf.html) (trade-magazine series) and vendor backtests. Range expansion after a 7-day minimum range is near-mechanical (regression to the mean of range), but direction is not predicted. | Never replicated in a journal. | None stated. | The directional leg is a breakout; we measured that family at zero gross edge on 50 stocks (M4b). |
| **Gaps: fills and continuation** | [Plastun, Sibande, Gupta & Wohar 2020](https://repository.up.ac.za/handle/2263/78336) on DJI/S&P/NASDAQ 1928-2018: prices continue in the gap direction on the gap day; "against the common belief that gaps tend to be filled". At the stock level, [Berkman, Koch, Tuttle & Zhang 2012](https://kuscholarworks.ku.edu/bitstream/1808/10965/1/Koch_Paying%20Attention.pdf) (3,000 largest US stocks 1996-2008): high opens followed by intraday reversal, concentrated in stocks with recent retail attention, hard to value, costly to arbitrage. [Lou, Polk & Skouras 2019](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf): overnight and intraday returns pull in opposite directions; [Akbas, Boehmer, Jiang & Koch 2022](https://econpapers.repec.org/RePEc:eee:jfinec:v:145:y:2022:i:3:p:850-875): daytime reversal of overnight moves, driven by arbitrageurs offsetting noise traders. Earnings gaps drift (post-earnings-announcement drift, [Bernard & Thomas 1989](https://econpapers.repec.org/RePEc:bla:joares:v:27:y:1989:i::p:1-36)). | The overnight/intraday split is replicated across many strategies and years; gross of costs; weakest in large caps. | Retail buyers at the open (fade) or slow institutional reaction to news (continuation). | High: the per-day reversal in large caps is a few bps. Only extreme gaps on non-news days could clear the budget. |
| **Close location, internal bar strength (IBS)** | IBS = (close − low)/(high − low). [Pagonidis 2013](https://jonathankinlay.com/?p=2199) (practitioner paper, seen only via secondary sources): low IBS predicts next-day gains in **index ETFs**, ~0.35% average next-day when IBS < 0.2 (secondary figure, verify), and "only on high-volume days". [Pandey & Joshi 2023](https://arxiv.org/abs/2306.12434) corroborate on country ETFs, note borrow costs erode the short side. | ETF-level only. On single stocks IBS is one-day mean reversion, the cousin of RSI(2), which we measured at −0.026R. | Index-level liquidity demand at the close. | Stocks only in our mandate; on stocks the evidence is absent. |
| **Wick-to-body ratio with volume** | None found. | - | - | Same as single candles. |
| **Breaks of prior-day or N-day highs/lows** | Within-day: same family as the opening-range breakout ([Zarattini, Barbon & Aziz 2024](https://econpapers.repec.org/RePEc:chf:rpseri:rp2498) need the "stocks in play" volume selection from thousands of names). Longer: [George & Hwang 2004](https://doi.org/10.1111/j.1540-6261.2004.00695.x) nearness to the 52-week high predicts 6-12-month returns (anchoring). | 52-week high replicated internationally; the horizon is months, not weeks. | Slow reaction to good news (anchoring on the old high). | Low turnover at monthly horizon, but it is not a bracket trade with a 1.5R target. |
| **Volume climax and dry-up** | This is where real evidence is. [Gervais, Kaniel & Mingelgrin 2001](https://econpapers.repec.org/RePEc:bla:jfinan:v:56:y:2001:i:3:p:877-919) (NYSE 1963-96): a stock whose daily volume is the highest of the trailing ten days appreciates over the next 10-20 days; in the [working paper](https://rodneywhitecenter.wharton.upenn.edu/wp-content/uploads/2014/04/9901.pdf) the large-firm zero-investment premium is +0.46% at 10 days and +0.50% at 20 days (t ≈ 3.5), stronger when the formation-day return is ordinary; net profits after spreads only for small and medium firms. [Kaniel, Ozoguz & Starks 2012](https://ideas.repec.org/a/eee/jfinec/v103y2012i2p255-279.html): present in 41 countries, not explained by risk or liquidity; attributed to visibility. **Dry-up before a reversal**: [Conrad, Hameed & Niden 1994](https://econpapers.repec.org/RePEc:bla:jfinan:v:49:y:1994:i:4:p:1305-29) and [Cooper 1999](https://econpapers.repec.org/RePEc:oup:rfinst:v:12:y:1999:i:4:p:901-35): weekly reversals are larger when volume is falling, and Cooper reports they survive costs for large-cap NYSE/AMEX 1962-93. | Replicated across countries. Post-publication decay is the norm: [McLean & Pontiff](https://ivey.uwo.ca/media/3775549/pontiff.pdf) measure a 35% average post-publication decline across 82 predictors in the working paper (the published 2016 version reports 26% out-of-sample and 58% post-publication: recollection, verify). The trader's "climax = exhaustion" reading is the **opposite sign** of the evidence. | Investors who only notice a stock when it is loud (Merton's investor-recognition story); for the dry-up reversal, impatient sellers paying for liquidity. | GKM: large-firm premium of ~45 bps over 10 days is well above the budget if even a third survives. Cooper's net profits are at 1990s spreads. |
| **Short-term reversal, relative to peers** (not on the brief's list; the credible cousin of "hammer after a sell-off") | [Lehmann 1990](https://www.nber.org/papers/w2533), [Jegadeesh 1990](https://econpapers.repec.org/RePEc:bla:jfinan:v:45:y:1990:i:3:p:881-98): weekly and monthly reversals. [Hameed & Mian 2015](https://web2-bschool.nus.edu.sg/wp-content/uploads/media_rp/publications/BwXb81392625636.pdf): reversal measured against industry peers is larger, stable, present in large liquid stocks, driven by order imbalances. [Nagel 2012](https://www.nber.org/papers/w17653): reversal profits are liquidity-provision pay and spike when VIX is high. [de Groot, Huij & Zhou 2012](https://repub.eur.nl/pub/25718): with real institutional costs, reversal is the most cost-constrained style but still nets 30-50 bps per week in a long-short portfolio when implemented carefully. [Chordia, Subrahmanyam & Tong 2014](https://core.ac.uk/download/35453733.pdf): anomaly returns roughly halved after decimalisation. [Novy-Marx & Velikov 2016](https://mysimon.rochester.edu/novy-marx/research/ToAatTC.pdf): high-turnover anomalies rarely survive costs. | Heavily replicated; clearly decayed; concentrated in volatile periods. | Funds forced to sell (outflows, risk limits). | High. This is the one family where a liquidity-constrained, patient implementation can still pay in large caps, and the one our RSI(2) test already brushed against and lost. |
| **Heikin-Ashi** | Heikin-Ashi bars are a lagged average of open/close, i.e. a trend-smoothing transform. Only an [MPRA working paper](https://mpra.ub.uni-muenchen.de/89594/) on four months of USD/INR and vendor backtests. | None. | - | Equivalent to a slow trend filter; we tested a trend-pullback family (M6) at −0.032R. |
| **Pattern recognition in general** (context) | [Lo, Mamaysky & Wang 2000](https://web.mit.edu/~alo/www/Papers/techanal.html): patterns have some informational content but "need not be optimal for trading profits". [Sullivan, Timmermann & White 1999](https://econpapers.repec.org/RePEc:bla:jfinan:v:54:y:1999:i:5:p:1647-1691) and [Bajgrowicz & Scaillet 2012](https://archive-ouverte.unige.ch/unige:79889) (7,846 rules, DJIA 1897-2011): nothing selectable in advance, and "even in-sample, performance is completely offset by low transaction costs". | The deflation we already apply ([Bailey & López de Prado 2014](https://papers.ssrn.com/abstract=2460551)) is the right response. | - | - |

Intraday momentum (first half-hour predicts last half-hour, [Gao, Han, Li & Zhou 2018](https://econpapers.repec.org/RePEc:eee:jfinec:v:129:y:2018:i:2:p:394-414)) is real but is an ETF phenomenon; for single stocks Heston et al. find periodicity at daily lags with small effect sizes. Stocks only is the mandate, so it is out of scope.

## B2. Charts read by a vision or language model

**What the evidence says.** The strong result is [Jiang, Kelly & Xiu 2023](https://economics.yale.edu/sites/default/files/2023-11/The%20Journal%20of%20Finance%20-%202023%20-%20JIANG%20-%20Re%25E2%2580%2590%20Imag%20in%20ing%20Price%20Trends_0.pdf): a small convolutional network trained on 20-day OHLC images with volume bars and a moving average, trained on 1993-2000 and held fixed over 2001-2019 on all US stocks. Weekly decile spreads earn gross equal-weight Sharpe 7.2 (value-weight 1.7); restricted to the largest 500 stocks it stays above 1.0; net of a 10-20 bp cost model it is 4.0 weekly, 1.5 monthly, 0.9 quarterly (equal weight). The authors say the weekly strategy's turnover makes it "mostly accessible to investors who behave as market makers", and the signal is distinct from momentum and reversal. [Cohen, Balch & Veloso 2020](https://arxiv.org/abs/1907.10046) show image classifiers can recover rule-based labels from chart pictures (a representation result, not an edge). [Chen & Tsai 2020](https://arxiv.org/abs/1901.05237) classify eight candle patterns at 90.7% accuracy, again recognition, not profit. For **pretrained** vision or language models reading charts I found no credible pre-2025 evidence of beating a simple rule out of sample.

**The leakage danger, specifically.** A pretrained model has read price histories, news, and backtest blogs about these exact stocks. Shown NVDA's 2023 chart with dates, it does not forecast, it remembers. Remove the ticker and dates and the danger is only reduced: a 20-day window containing March 2020 or January 2021 is identifiable from its shape, and mega-caps' episodes are the most written-about charts in existence. [Glasserman & Lin 2023](https://arxiv.org/abs/2309.17322) show the mechanism with news headlines: anonymising company names changes GPT's trading results, and the difference measures the model's use of outside knowledge (in their case it hurt; the point is that it is measurable). The general problem is named in [Sarkar & Vafa 2024, "Lookahead bias in pretrained language models"](https://papers.ssrn.com/abstract=4754678) (seen only as a citation; recollection, verify).

**An honest test, built from what we have.** The model's output is a signal that goes through the same bracket engine and the same six criteria; nothing about the model changes the protocol.

1. *Anonymise fully.* Images or candle lists with no ticker, no dates, prices rescaled to start at 100, volume rescaled to a trailing average, no axis labels. Fixed prompt, temperature 0, raw outputs logged.
2. *Three arms on identical windows.* (a) named and dated, (b) anonymised, (c) anonymised and **mirrored** (every return negated, so the chart is upside down). A chart-reading skill should give symmetric calls on (b) and (c); memory cannot. Any accuracy gain of (a) over (b), or asymmetry between (b) and (c), is leakage and is disqualifying.
3. *Famous-window control.* Pre-register a list of widely written-about episodes (the COVID crash, the 2021 meme period, the 2022 bear market) and compare accuracy inside and outside them. Recall shows up as accuracy that jumps on famous windows.
4. *Synthetic control.* Block-bootstrapped series from our own bars, with a planted drift the model could in principle read. A model that is good on real anonymised charts and useless on synthetic ones with the same statistical structure is reading memory, not pictures.
5. *Count every trial.* Each prompt version, model version and image format is a registry trial; the Deflated Sharpe check pays for all of them.
6. *Post-cutoff data is the only clean test* of a pretrained model, and for this project that is the 2025+ holdout. So the final, single, pre-registered holdout run is the real test; everything above is the entry ticket to it.

**Verdict.** A self-trained CNN on our 60-150 names over nine years has roughly one fiftieth of Jiang-Kelly-Xiu's data and every architecture choice is a trial; prior of passing under five percent. A pretrained model has no evidence behind it and a leakage problem in front of it. Not now. If curiosity wins, run step 2 on at most 2,000 windows as a cheap diagnostic first; a named-beats-anonymised result ends it.

## C. Three hypotheses to pre-register, ranked by prior

Common to all three: decision at a closed bar, entry at the next bar's open, stop and 1.5R target set from the
signal bar's close, one open trade per symbol, `sides` symmetric unless stated, `min_risk_pct` as in the existing
strategies, the six pass criteria unchanged, the universe widened to 120-150 daily names by Q1-2016 dollar volume
(cheap to add; still survivor-biased, which is reported by side as before).

### H1. Volume-dry-up relative reversal (daily swing engine). Prior ~12%

*Rule.* At session close t, with `ATR = ATR(14)` (average true range: the average daily price range) and
`atrp = ATR / close`:

- `ex5 = close_t / close_{t-5} − 1 − (spy_t / spy_{t-5} − 1)` (the stock's 5-session return minus SPY's).
- `vr = mean(volume_{t-4..t}) / mean(volume_{t-24..t-5})` (last week's volume over the prior four weeks').
- Long if `ex5 <= −mult × atrp` and (`vol_max` is off or `vr <= vol_max`). Short if `ex5 >= +mult × atrp` with the same volume condition.
- Stop `stop_atr × ATR` from the close; target 1.5R; time exit after `max_hold` sessions.

*Engine.* Daily swing: the effect is a one-to-two-week reversal and `generate()` already receives `spy_daily`.

*Grid (16).* `mult ∈ {2, 3}` (a 5-day lag of two or three daily ranges against the market), `vol_max ∈ {off, 1.0}`
(the Cooper/Conrad condition versus none, which doubles as the test of whether volume adds anything),
`stop_atr ∈ {1.5, 2.5}`, `max_hold ∈ {5, 10}`.

*Story.* Someone had to sell a large cap faster than the market could absorb; falling volume says it was not
news; liquidity providers are paid to take the other side (Hameed & Mian, Nagel). *Why it fails:* in 2019-2024
mega-caps that liquidity is supplied by HFT market makers at a fraction of a cent, and what is left after them is
below our one-cent cost; RSI(2), its absolute-return cousin, already measured −0.026R here.

*Trades.* A −2 ATR five-day lag against the market is roughly a 1.5-sigma event; after the volume filter and one
trade per hold, about 4-8 signals per stock per year per side, so 1,000-2,500 a year on 120 stocks. 300 is easy.

*Abandon if* any criterion fails, as always; and specifically, if the zero-cost expectancy interval includes zero
(no gross edge), do not try a long-only or volatility-conditioned variant: that is the same bet with a parameter
chosen after the fact.

### H2. High-volume continuation (daily swing engine). Prior ~8%

*Rule.* At close t: `vol_rank` = rank of today's volume among the last `window` sessions (1 = highest).
`day_ret = |close_t / close_{t-1} − 1|`.

- Long if `vol_rank == 1` and (`ret_max` is off or `day_ret <= ret_max × atrp`).
- Long only. Pre-registered from the literature, not from our side splits: in GKM's large-firm panel the
  high-volume leg carries the effect and the low-volume short leg is near zero. Reported, as always, by side
  would be moot; instead report the mirrored short rule **informationally** without counting it as a trial.
- Stop `stop_atr × ATR`; target 1.5R; time exit after `max_hold` sessions.

*Engine.* Daily swing; the documented horizon is 10-20 sessions.

*Grid (16).* `window ∈ {20, 50}`, `ret_max ∈ {off, 1.0}` (GKM: the premium is stronger when the formation-day
return is ordinary, i.e. volume without a big move), `stop_atr ∈ {1.5, 2.5}`, `max_hold ∈ {10, 20}`.

*Story.* A volume shock puts a stock on screens; buyers who were not paying attention arrive over the following
weeks, and short-selling constraints make the demand one-sided (Merton's investor recognition; Kaniel et al.).
*Why it fails:* mega-caps are already universally visible, so there is no recognition to gain; the effect is
24 years post-publication; and today's volume spikes are often index rebalances and option expiries, not news.

*Trades.* A new 50-day volume maximum happens 3-5 times per stock per year after de-duplication; 400-700 a year
on 120 stocks long-only. 300 out of sample is comfortable.

*Abandon if* any criterion fails; or if the result is positive only in `max_hold = 20` with `stop_atr = 2.5`,
which is the configuration that most resembles "buy and hold a rising market".

### H3. Low-volume opening-gap fade (5-minute intraday engine). Prior ~6%

*Rule.* Decided at the close of the first 5-minute bar (9:35 ET), using the prior session's daily bar and ATR(14):

- `gap = open_{9:30} / close_{prev} − 1`, in ATR units: `gap_atr_units = |gap| / atrp`.
- `rvol1 = volume_{9:30-9:35} / mean over the prior 20 sessions of volume_{9:30-9:35}`.
- Short if `gap >= +gap_atr × atrp` and `rvol1 <= rvol_max`; long if `gap <= −gap_atr × atrp` and the same.
- Stop at the first bar's extreme on the gap side plus `stop_pad × ATR`; target 1.5R toward the prior close;
  flat at 15:55 as the engine already enforces.

*Engine.* Intraday; it is a same-day reversal and the relative-volume and gap filters already exist in `tp.filters`.

*Grid (12).* `gap_atr ∈ {0.75, 1.25}`, `rvol_max ∈ {0.7, 1.0, off}` ("off" tests whether low volume is doing the
work; the literature says a quiet gap is a retail/attention gap and a loud gap is news), `stop_pad ∈ {0, 0.25}`.

*Story.* Attention-driven overnight buying inflates the open and daytime arbitrageurs fade it (Berkman et al.;
Akbas et al.). *Why it fails:* the effect is concentrated in small, hard-to-value stocks; in large caps the big
gaps are earnings gaps that drift (PEAD) and index-level evidence says gap days continue (Plastun et al.); and the
M4 failed-breakout fade on the same bars measured about 0R.

*Trades.* Gaps over 0.75 ATR on large caps occur perhaps 10-20 times per stock-year; the volume filter roughly
halves that; 300-600 a year on the 62 names with 5-minute bars. 300 out of sample is reachable but not by a wide
margin at `gap_atr = 1.25` with `rvol_max = 0.7`; that corner may be ineligible for lack of training trades.

*Abandon if* any criterion fails; or if the "off" volume setting is as good as the filtered ones, which would
mean the mechanism is not the one claimed and the result is a fade-anything artefact.

## D. Kill list

- **Hammer, shooting star, doji, marubozu, long wicks:** four independent null results on US large caps and Japan; the within-day reversal they encode is bid-ask bounce.
- **Engulfing, harami, piercing, morning and evening star:** the single positive (1992-96) did not replicate on 1992-2002 and depends on the exit rule; survivors are in retail-heavy Asian markets.
- **Inside bars, NR4, NR7:** no peer-reviewed evidence; the directional leg is a breakout, which we measured at zero gross edge on 50 stocks.
- **Prior-day and N-day high/low breaks intraday:** the opening-range breakout under another name; the 52-week-high effect is a six-month anchoring effect, not a bracket trade.
- **Unconditional gap fills:** index evidence says gap days continue; our opening-range fade was 0R.
- **Unconditional gap continuation:** the drift that exists is earnings drift, which needs earnings dates we do not have.
- **IBS / close location on single stocks:** evidence is ETF-only; on stocks it is RSI(2) with a different name.
- **Volume-climax reversal:** the only credible volume evidence has the opposite sign (volume spikes are followed by appreciation).
- **Wick-to-body ratio with volume:** no evidence of any kind.
- **Heikin-Ashi:** a smoothing transform of the data we already have; equals a slow trend filter, which lost.
- **Candle rules on the short side generally:** every short leg we measured was clearly negative, the literature's short legs are the weak ones, and borrow is not modelled; H2 is long-only for this reason, stated in advance.
- **Any rule whose published edge is under ~10 bps gross per trade:** it cannot clear the cost table above, whatever the chart looks like.

## E. Order of work

1. **H1 first.** Highest prior, cheapest (daily engine, `spy_daily` already supplied, universe expansion is daily
   bars only), and it answers the question the M6 side split raised without peeking: does reversal pay in large
   caps when measured against the market and conditioned on volume, or was RSI(2) the whole answer?
2. **H2 second**, in its own sweep. It is the only continuation bet and the only one with a different economic
   driver (attention rather than liquidity), so its result is informative whatever H1 shows.
3. **H3 last, and only if H1 shows a gross edge** (zero-cost interval above zero even if the net test fails).
   H3 is a same-day version of the same liquidity-provision bet; if two-week reversal has no gross edge in these
   names, a one-day version at tighter stops and larger relative costs has less.

*Interaction with the 177 trials.* Each sweep adds 12-16 trials to the registry; the Deflated Sharpe hurdle grows
with the expected maximum of N tries, roughly with sqrt(2 ln N): from 177 to 221 trials that is a 2% increase.
The statistical cost of three more families is small. The real cost is the temptation to read H1's side split and
"fix" H2 or H3 before they run; write all three protocols before H1 is run, in one commit.

*Are they the same bet?* H1 and H3 are: both are paid for providing liquidity against impatient flow, both pay most
in volatile years (Nagel; 2020 and 2022 in our test window) and lose in calm uptrends. H2 is the opposite exposure
(it buys what is loud). But all three share the horizon, the market and a survivor-biased large-cap universe, and
all three would have been flattered by 2019-2024's upward drift on their long sides. Three passes would not be
three independent edges; one pass would not be a diversified book. The protocol's by-side and by-year reporting
is the right instrument; add a by-VIX-tercile split, informational only, to H1 and H3.

## What I am unsure about or could not verify

- The published McLean & Pontiff (2016) decay figures (26% out of sample, 58% post-publication) are from memory;
  the working paper I could read says 10% and 35%.
- Pagonidis's IBS numbers (0.35% next-day at IBS < 0.2, high-volume-day condition) come from secondary summaries;
  I could not open the original.
- Sarkar & Vafa (2024) on look-ahead bias in language models was seen only as a citation in later papers.
- Caginalp & Laurent's cost estimate (0.1-0.3% per trade) is theirs for 1990s execution; I did not re-derive it.
- GKM's large-firm premium of +0.46%/+0.50% at 10/20 days is from the 1998 working paper tables, not the journal
  version; the journal version may differ slightly.
- One benchmark of commercial vision-language models on candlestick charts exists but is dated 2026
  (arXiv 2604.12659) and was excluded by the brief's date rule; its abstract suggests the models do well only in
  persistent trends. Nothing here depends on it.
- Trades-per-year figures are back-of-envelope from volatility arithmetic, not counted from data (by design).
- Whether H3's `rvol1` carries over from SIP to the live IEX feed is untested; the README notes IEX carries ~4% of
  volume, so a ratio should, but that is an assumption until the paper loop checks it.
