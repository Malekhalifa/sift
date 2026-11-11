# New idea candidates from the academic and quant literature

Prepared 12 November 2026 for Sift. Scope: 12 candidate anomalies that are not among the twelve ideas already tested, testable on free data, with honest post-publication decay notes. Nothing here was backtested. No Sift file other than this one was changed.

## 0. How to read this report

**Source status tags.** Every citation carries one of three tags.

- **[opened]**: I fetched the page and read what it says (an abstract or summary page, not always the full paper).
- **[snippet]**: the claim appears in a search-result summary but I did not open the page myself.
- **[recollection]**: from memory, no source opened. Check before relying on it.

Several journal and SSRN pages returned 403 or unreadable PDFs, so most evidence below is abstract-level. Effect sizes are what the authors report in sample, usually before costs.

**Local data facts checked read-only in the repo.**

- `data/bars/sip/1Day` holds 412 symbols, including SPY, QQQ and TQQQ. No sector ETFs (XLK, XLF and so on) are stored. They would need a fresh Alpaca download, free tier, history from 2016.
- `data/edgar` holds the SEC submissions index for 408 issuers. It includes form type, filing date, acceptance time and the **8-K item numbers** for every filing, plus SIC industry codes. Counts for 1 Jan 2016 to 31 Dec 2024: 48,517 8-Ks, 10,204 10-Qs, 3,392 10-Ks, 340 SC 13D, 1,826 SC 13D/A, 25 NT 10-K, 25 NT 10-Q.
- 8-K item counts for the same period: 2.02 (earnings) 14,474; 5.02 (officer or director changes and pay) 8,926; 1.01 (new material agreement) 4,991; 1.02 (agreement terminated) 587; 2.05 (exit costs) 236; 2.06 (impairments) 111; 3.01 (delisting notice) 45; 4.02 (non-reliance on financials) 20; 1.03 (bankruptcy) 8.
- Also present: `data/events/earnings.parquet`, `data/insider`, `data/political`, `data/corp_actions/splits.parquet`.

**Three cautions that apply to everything below.**

1. **Large liquid stocks are where decay is worst.** A Fortune summary of McLean and Pontiff reports the average predictor decays about 35 percent after publication (an earlier draft) and that decay is "particularly severe" for strategies trading large, liquid stocks [opened: https://fortune.com/2012/11/02/academics-academia-destroys-stock-picking-strategies/]. From memory the published Journal of Finance version reports about 26 percent lower out of sample and 58 percent lower post-publication [recollection; search tool echoed the same numbers but I could not confirm them]. The Sift universe is about 410 of the most liquid US stocks. Treat every in-sample number as an upper bound.
2. **Most published anomalies are weak under strict tests.** Hou, Xue and Zhang find 65 percent of 452 anomalies fail a t of 1.96 with NYSE breakpoints and value-weighted returns, 82 percent fail at a multiple-testing hurdle of 2.78, and replicated ones are "much smaller than originally reported" [opened: https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2019-2133..html]. Welch and coauthors argue that is too pessimistic and that most replicate under other construction choices [snippet: https://cfr.ivo-welch.info/published/papers/chen2021open.pdf]. Expect the truth between the two.
3. **Statistical power is the binding constraint, not ideas.** 2016 to 2024 is nine years. A monthly long-short portfolio has about 108 observations, or 72 in the 2019 to 2024 walk-forward window. The standard error of an annualised Sharpe ratio over 6 years is about 0.4. Under Sift's rule (95 percent interval above zero, at least 300 trades, Deflated Sharpe 0.95), a true Sharpe of 0.3 cannot be confirmed. Market-level calendar ideas (candidates 2 and 3) have under 110 independent events and will come back "inconclusive" whatever the truth.

**Engine fit.** The 1:1.5 bracket suits single-name event trades poorly when the signal is a slow cross-sectional rank (candidates 1, 4, 5, 8, 9). For these I recommend a fixed hold of N days (or 1 to 3 months), measured as a market-neutral or sector-neutral basket return, with the stop and target dropped. The justification is that these effects accrue over weeks to months and the bracket truncates the winners that produce the average. Pre-register one holding period and one feature definition, not a grid, to keep the trial count (and the Deflated Sharpe penalty) low.

---

## 1. Candidates

### C1. 52-week-high momentum (stock level, with an industry variant)

- **Hypothesis in plain words.** Traders anchor on the 52-week high, so stocks trading close to it are under-priced for good news and keep drifting up, while stocks far below it keep drifting down.
- **Key citations.**
  - George and Hwang (2004), Journal of Finance 59(5): nearness to the 52-week high beats past returns and industry momentum, and does not reverse long-run. Reported return about 0.45 percent a month, 1963 to 2001 [snippet only: https://www.bauer.uh.edu/tgeorge/papers/gh5-paper.pdf; figures from a search summary].
  - Hong, Jordan and Liu (2015), Pacific Basin Finance Journal 32: industry version, 20 industries, long top 6 and short bottom 6, 0.60 percent a month in the abstract, 0.93 percent in the Quantpedia table, 1963 to 2009, Sharpe about 0.7 [opened: https://quantpedia.com/strategies/52-weeks-high-effect-in-stocks].
- **Effect size and decay.** Quantpedia (opened) rates confidence "Moderate", calls out-of-sample results "slightly negative", says most gains come from the long side, says January is negative, and notes a 20-country study found profits in 18 markets but mostly insignificant after transaction costs. No costs are deducted in the source numbers. Not independently checked by me beyond that page.
- **Free data needed.** Daily adjusted bars only: price over the trailing 252-day high. Sift has this (`data/bars/sip/1Day`, split-safe). Industry grouping from SIC codes in the local EDGAR index.
- **Testable events 2016 to 2024.** About 410 stocks by 108 months, roughly 44,000 stock-months. A top-decile long leg is about 41 names a month, so about 2,900 stock-months over the 72 walk-forward months. Portfolio-level observations: about 108 monthly returns.
- **How it differs from the 12 tested.** Closest relative is high-volume continuation (idea 12) and the 20/200 pullback (idea 4), but those were single-stock entry rules. This is a cross-sectional rank held as a long-short basket, scored against the market. The 200-day trend filter was a market-timing question.
- **Main way it fails.** Large-cap decay: the effect was documented on all CRSP stocks. In 410 mega and large caps the spread may be a fraction of 0.45 percent a month, below the noise of a 72-month test. Also momentum crashes (rebounds after drawdowns, 2009 style; 2020 and 2022 in the test window) can dominate nine years.
- **Prior of surviving the full test:** about 10 percent. **Testability now:** high (1.0).

### C2. Pre-FOMC announcement drift

- **Hypothesis.** US stocks rise in the 24 hours before scheduled Fed rate decisions, before the news arrives, as uncertainty is priced and then resolved.
- **Key citations.**
  - Lucca and Moench (2015), Journal of Finance; NY Fed Staff Report 512: large excess returns in the 24 hours before scheduled FOMC announcements, 1994 to 2011 [snippet only; the PDF at https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr512.pdf did not render, so I could not read the figures; the "about 49 bp per drift window, over half the annual equity premium" in my memory is a recollection].
  - NY Fed Liberty Street 2018: in April 2011 to June 2018, about 40 basis points from the open of the day before to lunchtime on announcement day, only at meetings with a press conference, positive from the day-before morning; no significance test is given and the sample is about seven years [opened: https://libertystreeteconomics.newyorkfed.org/2018/11/the-pre-fomc-announcement-drift-more-recent-evidence.html].
  - Kurov, Wolfe and Gilbert (2021), Finance Research Letters 40: the drift "essentially disappeared" after 2015, with and without press conferences, explained by lower market uncertainty [opened: https://ideas.repec.org/a/eee/finlet/v40y2021ics1544612320315956.html].
- **Effect and decay.** Published-then-gone: the clearest decay case in this list. Their sample ends 2019, so 2020 to 2024 is untested by them.
- **Data.** FOMC dates are public on federalreserve.gov (free). Prices: SPY daily bars (open and close), which Sift has. The "open the day before to the announcement day close" window uses daily bars only. A lunchtime exit would use the 5-minute store.
- **Events.** About 8 scheduled meetings a year, so about 70 meetings in 2016 to 2024. A stock-level panel gives 410 by 70, about 29,000 trades, but they are fully correlated and are really 70 observations.
- **How it differs.** A calendar and macro-timing effect on one asset; none of the 12 is market timing except the 200-day filter on SPY.
- **Main way it fails.** Already disappeared per the follow-up. With 70 events a 40 bp drift against a daily SPY standard deviation near 1 percent has a standard error of about 12 bp, so detection needs the effect to be real and large. Will likely be "inconclusive".
- **Prior:** about 3 percent. **Testability:** moderate-low (0.5), because of low N.

### C3. Turn-of-the-month (and pre-holiday)

- **Hypothesis.** Stocks earn most of their return around the last trading day of a month through the first three days of the next, when institutions and households receive and invest cash.
- **Key citations.**
  - McConnell and Xu (turn-of-month in equity indexes, Financial Analysts Journal) and the Quantpedia strategy: buy one day before month-end, sell at the close of the third trading day; the four days accounted for all DJIA gains 1897 to 1986; persisted in 19 of 20 indices [snippet: https://quantpedia.com/strategies/turn-of-the-month-in-equity-indexes]. Quantpedia warns calendar effects "tend to vanish or rotate".
  - Etula, Rinne, Suominen and Vaittinen (2020), Review of Financial Studies 33(1), "Dash for Cash": institutions sell before month-end settlement (T-3) and the market rebounds after; 26 markets, 1980 to 2013; reversal stronger in mutual-fund-held, liquid stocks [snippet: https://academic.oup.com/rfs/article/33/1/75/5494694; the fetched page held no abstract].
  - Cost warning: a CXO Advisory turn-of-month close-to-open variant with 0.06 percent friction per round trip netted 0.0 percent CAGR [snippet: https://www.cxoadvisory.com/guides/intraday-overnight/].
- **Effect and decay.** Mixed. Theses and working papers cited in search results find the effect weaker in recent subsamples in many countries [snippet]; a 241-anomaly study found the turn-of-month effect persistent and unlike post-discovery decay [snippet]. I did not open any of these.
- **Data.** SPY or equal-weight of the 410 stocks, daily bars. Sift has this. NYSE trading calendar is derivable from the bars.
- **Events.** 108 months, so 108 turn-of-month windows. Pre-holiday: about 9 a year, so 80 windows.
- **How it differs.** Calendar timing of the market, not a stock-selection idea.
- **Main way it fails.** Exposure is only about 4 of 21 days. The market-adjusted comparison is "excess over what SPY earned the same days", which is zero by construction for a long-SPY window, so the only meaningful test is "turn-of-month days versus all other days", a market-neutral spread. With 108 windows, that spread is hard to separate from zero, and 2016 to 2024 had large single-day gaps (March 2020) that dominate any nine-year sum.
- **Prior:** about 5 percent. **Testability:** moderate-low (0.5).

### C4. Industry momentum (sector rotation)

- **Hypothesis.** Entire industries trend for 3 to 12 months because news diffuses slowly across firms in the same industry, so buying last quarter's winning industries and avoiding the losers earns more than the market.
- **Key citation.** Moskowitz and Grinblatt (1999), Journal of Finance 54(4): industry momentum explains much of individual-stock momentum; buying winning industries and selling losing ones stays highly profitable after controls for size, book-to-market and stock momentum [opened: https://econpapers.repec.org/RePEc:bla:jfinan:v:54:y:1999:i:4:p:1249-1290; the abstract gives no magnitudes and I did not verify any].
- **Effect and decay.** Not verified by me. The 52-week-high industry paper above reports out-of-sample results as "slightly negative" for its industry variant (Quantpedia, opened). From memory, industry momentum is stronger at 1-month (a short-horizon variant exists) and decays in the long run [recollection].
- **Data.** Two routes. (a) The ten or eleven SPDR sector ETFs, free from Alpaca, daily 2016 onward (not stored yet, easy). (b) SIC codes from local EDGAR files mapped to 12 to 17 groups, then equal-weighted baskets of the 410 stocks. Sift has (b) now.
- **Events.** About 100 monthly portfolio observations. Unusually low power: this is the idea most likely to read "inconclusive".
- **How it differs.** Rank across groups, not across stocks; the 200-day SPY filter was a single-asset rule.
- **Main way it fails.** Eleven sector ETFs give very few degrees of freedom. 2016 to 2024 was dominated by one sector (technology) so a "winners keep winning" rule looks good as a market-cap tilt, not as skill. Market-adjusted tests against SPY will mostly measure the tech overweight.
- **Prior:** about 7 percent. **Testability:** high (0.8) for data, but low power.

### C5. Earnings announcement premium (EAP)

- **Hypothesis.** Stocks earn higher average returns in the days around their scheduled earnings date than on other days, because the announcement draws buying attention and uncertainty.
- **Key citations.**
  - Frazzini and Lamont (NBER WP 13090, 2007): premium is "large, robust" and strongly tied to the volume surge around announcements; high-volume stocks earn the most; attributed to small-investor buying [opened: https://www.nber.org/papers/w13090; the abstract gives no magnitude].
  - "The Disappearing Earnings Announcement Premium" (working paper, authors not identified): says the premium has disappeared in US markets in recent years and shifted to 8-K filing periods [snippet: https://www.iimb.ac.in/ARC2020/Papers/The_Disappearing_Earnings_Announcement_Premium.pdf; fetch returned 403].
  - A separate working paper reports average announcement returns fell from +0.30 percent in the 1990s to -0.30 percent in the 2010s [snippet: https://papers.ssrn.com/abstract=3853030].
- **Effect and decay.** Per those two snippets it has largely vanished for US stocks since the 2000s.
- **Data.** Announcement dates from `data/events/earnings.parquet` and 8-K item 2.02 (14,474 filings). The trade must be entered before the date is known to the market, so use the prior-year or prior-quarter date plus a rule; the signal is "scheduled date," with no outcome needed. Sift has everything.
- **Events.** About 14,000 earnings events (about 35 per stock). Plenty of power.
- **How it differs.** Earnings drift (idea 5) trades after the announcement on the size of the surprise. This trades before, regardless of surprise, so it is nearly independent of idea 5.
- **Main way it fails.** Already reported gone. For large caps the pre-announcement return of earnings windows looks like the market plus noise; and entering before the date means holding a binary gap risk the 1:1.5 bracket can't manage.
- **Prior:** about 4 percent. **Testability:** high (1.0).

### C6. Short-term reversal after news-free moves, conditioned on market stress

- **Hypothesis.** A stock that moves sharply for a week with no company news was pushed by flows, not information, and reverts; the payoff is a fee for supplying liquidity and is largest when market fear (VIX) is high.
- **Key citations.**
  - Chan (2003), Journal of Financial Economics 70(2): drift after bad headlines, reversal after extreme moves with no news; found mainly in small, illiquid stocks [metadata page opened: https://econpapers.repec.org/RePEc:eee:jfinec:v:70:y:2003:i:2:p:223-260, which shows no abstract; the findings are from search snippets].
  - Nagel (2012), Review of Financial Studies 25(7), "Evaporating Liquidity": reversal returns proxy for liquidity provision, are strongly predicted by VIX, and even industry-level reversal earns high Sharpe ratios at high VIX [opened: https://nber.org/papers/w17653].
- **Effect and decay.** Unconditional large-cap reversal has been weak for decades; Nagel's point is the conditional payoff, concentrated in crisis periods (2008 and 2020 in the sample).
- **Data.** Daily bars (Sift) and the 8-K item filings in the EDGAR index (Sift) to define "no news in the window". VIX history is free from FRED or Cboe (not stored; SPY realized volatility is a free proxy).
- **Events.** Rough estimate: weekly moves beyond two daily ranges on about 5 percent of stock-weeks, about 9,600 events, perhaps 6,000 with no 8-K in the window. The VIX-above-X subset is perhaps a third or less, and clustered in March 2020 and 2022.
- **How it differs.** RSI(2) and volume-dry-up reversal used price and volume only. This conditions on filings (news-free) and on a market regime.
- **Main way it fails.** Two reversal rules (ideas 3 and 11) already showed "no edge even before costs", so the base rate for this family in these stocks is poor. The VIX-conditioned effect leans on 2 or 3 crisis episodes, which cannot be replicated on unseen stocks, since all stocks share the same crisis days.
- **Prior:** about 5 percent. **Testability:** high (0.9).

### C7. Overnight versus intraday return split

- **Hypothesis.** Part of the return to many strategies sits entirely in the overnight (close to open) or intraday (open to close) piece, and each piece persists for itself while reversing across the two, so a stock's recent overnight return predicts further overnight return.
- **Key citations.**
  - Lou, Polk and Skouras (2019), Journal of Financial Economics 134: firm returns continue within the overnight and intraday periods for years, offset by cross-period reversal; 14 strategies earn profits entirely in one period, usually with opposite signs [opened: https://econpapers.repec.org/RePEc:eee:jfinec:v:134:y:2019:i:1:p:192-213].
  - Hendershott, Livdan and Rosch (2020), Journal of Financial Economics 138: returns rise with beta overnight and fall with beta intraday [opened: https://econpapers.repec.org/RePEc:eee:jfinec:v:138:y:2020:i:3:p:635-662].
  - Branch and Ma (2018), summarised by CXO Advisory: in 2011 to 2017 the overnight-intraday reversal had faded, and for S&P 500 stocks the relation looks positive; exploiting it needs two-way trading of many stocks [snippet: https://www.cxoadvisory.com/guides/intraday-overnight/]. Aboody et al. (JFQA 2018): overnight persistence stronger in hard-to-value firms [snippet: https://anderson-review.ucla.edu/wp-content/uploads/2021/03/Aboody-et-al_overnight_returns_and_firmspecific_investor_sentiment_JFQA2018.pdf].
- **Effect and decay.** Signals trade daily, and a half-spread paid twice a day on mid and large caps likely exceeds the gross edge. I found no after-cost large-cap evidence.
- **Data.** Daily open and close from Sift bars. Fills at the open and the close need the auction prices; the SIP daily bar open and close are the consolidated official prices, which are tradable only with market-on-open and market-on-close orders.
- **Events.** About 900,000 stock-days. A weekly rebalanced long-short basket gives about 470 weekly observations.
- **How it differs.** None of the 12 split the return into overnight and intraday. The bracket-based ORB test used the intraday piece only.
- **Main way it fails.** Turnover: a daily-rebalanced rank signal pays costs on every leg; Quantpedia's own GDX study warns open prices in OHLC data are often unrealistic to trade at [snippet: https://quantpedia.com/dangers-of-relying-on-ohlc-prices-the-case-of-overnight-drift-in-gdx-etf/]. The large-cap sign may already have flipped.
- **Prior:** about 4 percent after costs. **Testability:** high (1.0).

### C8. Lazy Prices: changes in 10-K and 10-Q wording

- **Hypothesis.** When a company quietly rewrites its annual or quarterly report (new risk factors, legal language, executive wording) the change carries bad news that investors do not read, so changers underperform non-changers over the next months.
- **Key citation.** Cohen, Malloy and Nguyen (2020), Journal of Finance 75(3); NBER WP 25084: shorting "changers" and buying "non-changers" earns up to 188 basis points a month of alpha (over 22 percent a year), filings 1995 to 2014, with no announcement-date effect; changes in CEO and CFO language, litigation language and risk factors matter most [opened: https://www.nber.org/papers/w25084]. A CXO summary says most of the alpha and all of its permanence come from the short side [snippet: https://www.cxoadvisory.com/?p=31233].
- **Effect and decay.** "Up to 188 bp" is the best-case cell across many specifications in an in-sample window ending in 2014. I found no independent post-publication replication on large caps. A QuantConnect research note exists but I did not open it [snippet: https://www.quantconnect.com/research/20966/filing-language-stability-as-a-selection-signal/].
- **Data.** EDGAR 10-K and 10-Q full text (free, 10 requests a second). Sift already has the filing index with `primaryDocument` file names for 10,204 10-Qs and 3,392 10-Ks in 2016 to 2024 (about 13,600 filings). Needs a text downloader and a similarity measure (cosine and Jaccard on word counts, as in the paper). Filings from 2015 are needed as the first lag.
- **Events.** About 13,000 filing pairs, about 32 per stock. Monthly calendar-time portfolios: about 108 months.
- **How it differs.** Uses filing text rather than price, volume, or filing timing. Insider-buying and earnings drift used EDGAR for dates only.
- **Main way it fails.** Alpha is probably smaller on the largest companies, whose filings change a little every quarter anyway (boilerplate churn). The 2016 to 2024 window is after the paper and after the data was widely sold, and the short side needs borrowing. Storage and compute are the cost: a few GB and a day of parsing, with the HTML-to-text step being the main source of bugs.
- **Prior:** about 8 percent. **Testability:** moderate (0.6), data pipeline work needed.

### C9. FINRA daily short-sale volume

- **Hypothesis.** Short sellers trade more after prices rise and their trading predicts the following negative abnormal returns, so a day or week of unusually high short-sale share of volume marks a stock that is about to underperform.
- **Key citation.** Diether, Lee and Werner (2009), Review of Financial Studies 22(2): 2005 data, short sales about 24 percent of NYSE and 31 percent of Nasdaq volume, short sellers trade more after positive returns and predict negative abnormal returns, robust to liquidity provision and risk-bearing; a strategy on daily short activity made significant profits in sample [opened: https://econpapers.repec.org/RePEc:oup:rfinst:v:22:y:2009:i:2:p:575-607].
- **Effect and decay.** The source is one year of data (2005), before the 2007 to 2008 short-sale rule changes and before high-frequency market makers dominated short volume. I found no post-2010 replication and do not know the current strength [recollection: many later papers find the raw short-volume ratio is noisy because market-making shorts dominate; unverified].
- **Data.** FINRA daily short-sale volume files, free direct downloads, URL pattern `https://cdn.finra.org/equity/regsho/daily/CNMSshvolYYYYMMDD.txt` [opened: https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data/daily-short-sale-volume-files]. Per that page the consolidated file starts 1 August 2018, covers only short trades reported to the trade-reporting facilities (off-exchange and media-reported), and has per-security volume. The page does not state a licence; check the terms. **Sift does not have this.** Usable window about 2018-08 to 2024-12, so about 6.4 years, a shorter test than the others.
- **Events.** About 1,600 trading days by 410 stocks, about 650,000 stock-days; weekly signals, about 330 weekly portfolio observations.
- **How it differs.** New information source that is not price, volume, or filings. The volume-dry-up and high-volume ideas used total volume.
- **Main way it fails.** The data covers only part of the tape (off-exchange reports), so the "short share" mixes market-making flow with informed shorting, and nearly every stock now shows a ratio near 40 to 50 percent, leaving little cross-sectional variation to rank [recollection]. Window starts after the first four test years of the other ideas, so it is not comparable to them.
- **Prior:** about 8 percent. **Testability:** moderate-high (0.7), a download of about 1,600 files.

### C10. 8-K event items (departures, terminations, restructurings)

- **Hypothesis.** Specific 8-K item types, such as a CEO or CFO departure (5.02), termination of a material agreement (1.02), restructuring (2.05) or impairment (2.06), are bad news that the market incorporates slowly, so stocks drift down after the filing.
- **Key citation.** Lerman and Livnat (2010), Review of Accounting Studies 15(4): all 8-K items are associated with abnormal volume and volatility around the event and the filing date, and some items show return drift after filing [snippet: https://ideas.repec.org/a/spr/reaccs/v15y2010i4d10.1007_s11142-009-9114-7.html; I could not identify which items or the drift sizes].
- **Effect and decay.** Unknown to me. The paper covers the first years after the August 2004 form change; no post-publication evidence was found.
- **Data.** Already in Sift: item numbers in `data/edgar` for all 408 issuers. Item counts 2016 to 2024: 5.02 8,926; 1.02 587; 2.05 236; 2.06 111; 3.01 45; 4.02 20. The 5.02 item mixes pay-plan approvals with CEO and CFO exits, so separating them needs the filing text (a few thousand small documents). Acceptance timestamps allow entry at the next open.
- **Events.** 1.02, 2.05 and 2.06 together are about 930, enough to test as one pre-registered group. True CEO or CFO departures are perhaps 1,000 to 2,000 after text parsing (my estimate). 4.02 (20) and 1.03 (8) are too rare.
- **How it differs.** Insider buying and earnings drift used Form 4 and item 2.02 only. This is the first use of the other item types.
- **Main way it fails.** Large-cap bad news is priced within minutes, and nothing is left at the next open (the same result as presidential posts and Pentagon awards). The group is also heterogeneous; pooling items dilutes any one effect, but testing them one by one multiplies the trial count.
- **Prior:** about 6 percent. **Testability:** moderate-high (0.7).

### C11. Schedule 13D activist filings

- **Hypothesis.** When a known activist investor discloses a stake of 5 percent or more with intent to push for change, the stock jumps and keeps its gains, and a trader entering after the public filing may still capture part of the move.
- **Key citations.**
  - Brav, Jiang, Partnoy and Thomas (2008), Journal of Finance 63(4): abnormal return of about 7 percent around the announcement, no reversal over the following year, 2001 to 2006, hand-collected data [opened: https://econpapers.repec.org/RePEc:bla:jfinan:v:63:y:2008:i:4:p:1729-1775].
  - Bebchuk, Brav and Jiang (2015), Columbia Law Review 115(5): about 2,000 interventions 1994 to 2007, no long-term decline and no reversal of the initial jump [snippet: https://dash.harvard.edu/bitstream/handle/1/29998414/HF_LTEffects.pdf].
- **Effect and decay.** The 7 percent is an event window that straddles the filing; much of it comes before filing as the activist builds the stake (the 5 percent threshold is crossed days before the filing), and I found no post-publication study of how much remains after the public filing. The filing deadline fell from 10 days to 5 business days in 2024 [recollection], which shortens the run-up window further.
- **Data.** SC 13D filings are in the local EDGAR index: 340 initial filings (and 2 under the new "SCHEDULE 13D" name) across 132 of the 408 issuers in 2016 to 2024, plus about 1,850 amendments. Filer identity needs the filing header or text; not yet parsed. Sift has the index but not the filer names.
- **Events.** About 340 filings, of which perhaps 100 to 150 are true activists (the rest are passive large holders, strategic buyers or insiders; my estimate). Activism concentrates in mid caps, which are under-represented in the 410-stock universe.
- **How it differs.** Informed-holder disclosure, but unlike Form 4 insider buying it is an ownership-and-intent filing by outsiders.
- **Main way it fails.** Small N: below the 300-trade bar, so likely "inconclusive". The move is front-loaded, and a 15-minute-delayed free feed plus next-open entry gets the tail only.
- **Prior:** about 5 percent. **Testability:** moderate-low (0.5).

### C12. S&P 500 index additions and deletions

- **Hypothesis.** Stocks added to the S&P 500 rise on forced buying by index funds, and deleted stocks fall.
- **Key citation.** Greenwood and Sammon (2022), NBER WP 30748 (later Journal of Finance): the average abnormal return of additions was 3.4 percent in the 1980s, 7.6 percent in the 1990s and 0.8 percent in the most recent decade; deletions about -0.6 percent in 2010 to 2020, despite much more index-linked money [opened: https://www.nber.org/papers/w30748]. A search summary of the published version gives 7.4 percent in the 1990s and under 1 percent (or 0.3 percent) recently, and attributes the decline to migrations from the S&P MidCap, which offset the forced buying [snippet: https://econpapers.repec.org/RePEc:bla:jfinan:v:80:y:2025:i:2:p:657-698].
- **Effect and decay.** The cleanest documented decay case: a 7 percent effect shrinking to roughly nothing.
- **Data.** S&P 500 change lists with announcement dates are free on Wikipedia (not verified by me; the page is not opened). Price bars via Alpaca. Sift has bars only for its 410 stocks, so added tickers would need a fresh download.
- **Events.** About 20 to 30 changes a year, so 200 to 250 in 2016 to 2024, mostly additions of stocks outside the current universe.
- **How it differs.** Index-flow event; none of the 12.
- **Main way it fails.** The effect is about 1 percent and falling, with N near 200: unprovable at Sift's bar. Included mainly as a decay benchmark.
- **Prior:** about 2 percent. **Testability:** moderate (0.6).

---

## 2. Considered but not shortlisted

| Idea | Why it is not in the twelve |
|---|---|
| Buyback announcements (Peyer and Vermaelen 2009, RFS 22(4): anomalies "have not disappeared", repurchases follow overreaction to bad news [opened: https://econpapers.repec.org/RePEc:oup:rfinst:v:22:y:2009:i:4:p:1693-1745]) | Reasonable literature, but no free structured announcement-date feed. Would need parsing of 8-K item 8.01 text (11,740 items, mostly unrelated). Worth revisiting after C10 builds the 8-K text parser. |
| Dividend initiations and changes (Michaely, Thaler, Womack 1995 [recollection]) | Alpaca's corporate-actions API lists a `cash_dividend` type, but I could not confirm that declaration dates are available on the free plan [snippet: https://docs.alpaca.markets/reference/CorporateActions]. Few initiations among large caps. |
| Stock-split announcements | Sift has only effective-date splits. About 50 to 80 events in the universe; too few. |
| Lottery (MAX), idiosyncratic volatility, betting-against-beta | MAX: highest-vs-lowest decile spread over 1 percent a month, 1962 to 2005, and it overturns the idiosyncratic-volatility result [opened: https://econpapers.repec.org/RePEc:eee:jfinec:v:99:y:2011:i:2:p:427-446]. Idiosyncratic-volatility evidence is contested and concentrated in small stocks [snippet]. Low-risk effects are mostly about small and illiquid names, and a long-short version in 410 large caps has little spread. Could be one combined "risk" feature if C1 passes. |
| Pairs trading | Profits were shrinking by the 2010 replication (about 1 percent a month falling) [snippet: https://econpapers.repec.org/RePEc:taf:ufajxx:v:66:y:2010:i:4:p:83-95]. Market-neutral by construction, so attractive on method, but high turnover and a crowded trade. |
| Same-calendar-month seasonality (Heston and Sadka; Keloharju et al.) [recollection] | Needs several years of per-stock history before the first signal; with data starting 2016, the first valid year is about 2019, leaving a 6-year test. |
| Intraday momentum (Gao et al., JFE 2018) [recollection] | Intraday horizon, outside the daily-or-slower scope. |
| NT 10-K and NT 10-Q late-filing notices | 25 events each; far too few. |
| Russell reconstitution | Membership and rank lists are not freely available for 2016 to 2024 [recollection]. |
| Post-earnings drift variants, insider variants | Already covered by ideas 5 and 6. |

---

## 3. Ranking

Score = prior of surviving a market-adjusted, replication-checked test (percent) times testability with free data now (0.5 to 1.0). Priors are my own judgment, scaled to the low priors the pipeline has used before (2 to 12 percent). They are not estimated from data.

| Rank | Candidate | Prior | Testability | Score | Note |
|:-:|---|:-:|:-:|:-:|---|
| 1 | C1 52-week-high momentum (with industry variant) | 10% | 1.0 | 10.0 | Daily bars only; high power; strongest published replication record in the momentum family |
| 2 | C9 FINRA short-sale volume | 8% | 0.7 | 5.6 | New data, new information; shorter window |
| 3 | C8 Lazy Prices | 8% | 0.6 | 4.8 | Most orthogonal signal; needs a text pipeline |
| 4 | C10 8-K item events | 6% | 0.7 | 4.2 | Data already local; heterogeneous items |
| 5 | C4 Industry momentum | 7% | 0.8 (low power) | 5.6 raw, 3.5 after power discount | Overlaps C1; best as its variant, not a separate trial |
| 6 | C6 No-news reversal with VIX | 5% | 0.9 | 4.5 raw | Family has two strikes already; regime depends on 2 to 3 episodes |
| 7 | C7 Overnight vs intraday | 4% | 1.0 | 4.0 | Costs likely kill it |
| 8 | C5 Earnings announcement premium | 4% | 1.0 | 4.0 | Reported gone in the US |
| 9 | C3 Turn-of-month | 5% | 0.5 | 2.5 | About 108 windows |
| 10 | C11 13D activists | 5% | 0.5 | 2.5 | About 340 filings, front-loaded |
| 11 | C2 Pre-FOMC drift | 3% | 0.5 | 1.5 | Gone after 2015 |
| 12 | C12 S&P 500 additions | 2% | 0.6 | 1.2 | Effect near 1% and falling |

C4 is ranked below C10 because its raw score is cut for power (about 100 monthly observations from 11 sector ETFs) and because it is a close cousin of C1, so testing both would spend two trials on one underlying bet. C6 is held back for the reason in its entry: two sibling reversal tests already showed no edge.

## 4. Recommended top four

1. **C1, 52-week-high momentum, stock and industry versions in one protocol.** One feature (price over 252-day high), one hold (about 3 months, monthly rebalance, a third of the book turning over each month), long top decile minus short bottom decile, beta-neutral against SPY, January reported but not excluded after the fact. Replicate on a second, unseen set of stocks (the earlier 250-stock expansion pattern). Expect a small spread and a likely "inconclusive" or "no edge" verdict; this is the cheapest, best-powered test of the group.
2. **C8, Lazy Prices.** Highest information gain: the signal is text that Sift has never used, the paper reports a large in-sample alpha with no announcement effect, and there are about 13,000 filing pairs. Pre-register one similarity measure (cosine on word counts) and one rule (short the lowest-similarity quintile, long the highest, hold 3 months, rebalance monthly). The cost is a downloader and a parser.
3. **C9, FINRA short-sale volume.** New free data with a clear published mechanism. Pre-register one signal (5-day average short-volume share minus its 60-day average) and one hold (5 days). Needs the 2018-08 onward files only, and the licence check. Report that the window is 6.4 years.
4. **C10, 8-K negative items as one group (1.02, 2.05, 2.06, and text-confirmed CEO or CFO exits).** Data is local, and the next-open entry matches the pipeline's existing convention. Pre-register the group as one hypothesis (bad-news items, short or avoid, 5-day hold). Expect the Pentagon-award outcome, nothing left at the first open, but it is cheap to confirm.

Reserve: C4 as a variant of C1, and C5 (earnings announcement premium) as a quick negative control because Sift already has every input.

## 5. Process notes

- None of these has a high prior. The honest expectation is that most return "no edge" or "inconclusive", which matches the pipeline's earlier record. The value is in cheap, pre-registered, well-powered tests, and in C8 and C9 adding data types Sift has not used.
- Unseen-stock replication: the 410-stock universe was built from Q1 2016 liquidity. Large-cap-only tests understate effects that live in mid caps (C11 especially). If any candidate shows a promising sign, widen to the next 250 by dollar volume before the holdout.
- The 2025 and later holdout stays sealed. FINRA files and filings after 2024 should not be downloaded into the analysis store until a candidate has passed everything else.
- Sources I could not open (403 or unreadable PDF): Lucca and Moench staff report, the McLean and Pontiff paper, the SSRN abstract for Greenwood and Sammon, Alpha Architect pages, the George and Hwang PDF, and the "Disappearing EAP" PDF. Claims resting on them are tagged [snippet] or [recollection].
