# New idea candidates: public events and information sources

Prepared 12 November 2026 for Sift. Scope: twelve candidates built on a public, free, timestamped information source that a slow trader (entering at the next open) could still use. Nothing here was backtested. No Sift file other than this one was changed.

A sibling report, `docs/research/ideas-academic.md`, was written the same day from the anomaly literature. It overlaps with this one on Lazy Prices, FINRA short volume, 8-K items, 13D filings, S&P additions and pre-FOMC drift. I read it after finishing my own research; where I agree, that is an independent second opinion, and where I add something (data checks, extra evidence, new candidates) I say so.

## 0. How to read this report

**Source tags.** Each citation carries one tag.

- **[opened]**: I fetched the page and read it. Usually an abstract or a secondary summary, not the full paper.
- **[snippet]**: the claim appears in a search-result summary only.
- **[recollection]**: from memory, no source seen.

Several PDFs (Brav et al. 2008, the Wang-Yan-Zheng PDF) came back as unreadable binary, so the evidence is abstract-level throughout.

**Data tests.** Everything below marked "confirmed" was fetched with `curl` using the User-Agent `sift-research <contact email>`, no login, no payment. Test files went to `/tmp`, nothing was stored in the repo, and the temp files were deleted afterwards. Two things to disclose: (1) one test pulled the full 2021 Q1 EDGAR `form.idx` (56 MB, larger than intended); (2) the AAPL submissions JSON I fetched lists filings up to November 2026, and one 10-K I probed is from 2025. I read only counts, field names and one header, and did no analysis on post-2024 data, but it is worth saying given the sealed holdout.

**Local facts re-verified read-only** from `data/edgar` (submissions index for 408 issuers), counts for 1 Jan 2016 to 31 Dec 2024:

| Form or item | Count | Note |
|---|---:|---|
| 8-K total | 48,517 | |
| 10-K / 10-Q | 3,392 / 10,204 | |
| SC 13D / SC 13D/A | 340 / 1,826 | 21 to 58 initial filings a year |
| SC 13G / SC 13G/A | 7,101 / 20,332 | passive holders |
| NT 10-K / NT 10-Q | 25 / 25 | late-filing notices |
| Form 144 | 9,838 | only 36 to 78 a year to 2022, then 3,514 (2023) and 5,936 (2024): electronic filing became mandatory in April 2023 |
| Form 4 | 251,004 | |
| 10-12B (spin-off registration) | 3 | |
| 8-K item 5.02 / 1.01 / 1.02 / 2.05 / 2.06 / 3.01 / 4.01 / 4.02 | 8,926 / 4,991 / 587 / 236 / 111 / 45 / 24 / 20 | |

These match the sibling report. Two consequences: NT notices and 8-K 4.02 are far too rare to test alone, and Form 144 has only two usable years before the holdout.

**Cross-cutting cautions.**

1. **Survivor bias cuts differently for shorts.** The universe is stocks liquid in 2016 and still listed. For bad-news events, the worst outcomes (delisting, bankruptcy) are missing, so a short-side test is biased against finding an effect and a long-side "recovery" is biased toward one. A bad-news idea that works here is more believable than a good-news idea; one that fails here is not proof it fails in general. Whether Alpaca serves bars for delisted tickers is untested here.
2. **Use acceptance time, not filing date.** EDGAR dates a filing by acceptance time (`acceptanceDateTime` in the submissions API; `ACCEPTANCE-DATETIME` in the SGML header). A 13D accepted at 17:12 ET on 25 Jan 2021 carried filing date 25 Jan; later-evening acceptances roll to the next day. The Sift convention from M12 (before 09:30 ET trades that day's open, otherwise next open) applies.
3. **Small N is the binding constraint.** Sift's strategy criteria need 300 trades. Several event ideas below have 100 to 1,000 events. For those, use the M12 event-study criteria (at least 100 events, 97.5% interval above zero, positive in two thirds of years, positive in both halves) and say up front that "inconclusive" is the likely outcome.
4. **Priors are my judgment**, scaled to the 2 to 12 percent range the pipeline has used before. They are not estimated from data.

---

## 1. Candidates

### E1. Lazy Prices: year-over-year change in 10-K risk-factor text

- **Hypothesis.** When a company quietly rewrites its annual report, especially the risk-factor section, the change carries news that investors do not read; changers underperform non-changers over the following months.
- **Evidence.**
  - Cohen, Malloy and Nguyen (2020, Journal of Finance), 10-K and 10-Q filings 1995 to 2014: shorting "changers" and buying "non-changers" earns up to 188 bp a month of alpha; no announcement-date effect, so the return arrives gradually [opened: https://www.nber.org/papers/w25084]. Note "up to": it is the best cell of many specifications.
  - Large-cap replication, self-reported by a student repository, 495 current S&P 500 firms, 9,035 year-over-year pairs: full-document cosine similarity gives -10 bp a month (t = -1.19), nothing. Item 1A alone gives +21 bp a month (t = 2.08), six-factor alpha +15 bp (t = 1.74), 12 bp after costs (t = 1.31); post-2015 +31 bp (t = 2.11), pre-2015 +7 bp (t = 0.59). The author concludes it misses a pre-registered bar. Survivor bias acknowledged [opened: https://github.com/Shardul-Pandit/Lazy-Prices]. Unreviewed, so treat as a hint only.
- **Free data.** Full 10-K text from `https://www.sec.gov/Archives/edgar/data/<cik>/<accession-no-dashes>/<primaryDocument>`. **Confirmed**: Apple's 10-K main document downloaded, HTTP 200, 1.52 MB. `primaryDocument` names are already in the local `data/edgar` index. Raw HTML for 3,392 annual reports is about 5 GB.
- **History and events.** 3,392 10-Ks (about 3,000 usable pairs once 2015 supplies the first lag) in the local index. Monthly calendar-time portfolios give about 108 observations.
- **Timestamp.** Good: acceptance time to the second.
- **How it differs.** The signal is text, which Sift has never used (earlier EDGAR work used filing dates only).
- **Main way it fails.** Large caps change their risk factors a little every year (boilerplate churn), so the full-document score saturates near 0.99 (reported by a second student repo [snippet: https://github.com/iqueipopg/lazy-prices]); only the risk-factor section showed any spread above, and only after 2015, which is a subperiod split, not a replication. Survivors also flatter the long side. The short leg needs borrow.
- **Prior 8%. Testability 0.6. Score 4.8.**
- **Pre-registration suggestion.** One section (Item 1A), one measure (cosine on word counts), one rule (long top quintile of similarity, short bottom quintile, hold 3 months, monthly rebalance), market-neutral by construction. Do not test the full document as well; that is a second trial and the evidence says it is empty.

### E2. FINRA daily short-sale volume ratio (long-horizon version)

- **Hypothesis.** Stocks where short sellers account for an unusually high share of volume over weeks underperform, because short sellers process public information that prices absorb slowly.
- **Evidence.**
  - Wang, Yan and Zheng (2020, Journal of Financial Economics 135): over 2010 to 2015 shorting flows predict lower returns, effect decays slowly over about a year; *long-term* flows are more informative, and abnormal *short-term* flows do not predict returns or anticipate bad news; the 2005 to 2007 predictability was much shorter term [opened: https://ideas.repec.org/a/eee/jfinec/v135y2020i1p191-212.html]. This tells Sift to use a long window (for example 60-day average), not a one-day spike.
  - Diether, Lee and Werner (2009, RFS), 2005 data: heavy short selling followed by negative abnormal returns; costs wiped out profits for a daily strategy [snippet via search summary, not opened]. Predictability in later FINRA-era data reported to have vanished for the daily measure in a Wharton working paper [snippet; unverified].
  - FINRA's own page warns the files only cover trades reported to the TRFs, ADF or ORF (off-exchange, media-reported) [opened: https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data/daily-short-sale-volume-files]. A vendor note says a high ratio can reflect dealer hedging [snippet].
- **Free data.** `https://cdn.finra.org/equity/regsho/daily/CNMSshvolYYYYMMDD.txt`, pipe-delimited `Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market`. **Confirmed**: 2024-01-02 downloaded in full, 332,699 bytes, 9,927 rows; 2018-08-01, 2018-08-06, 2018-12-31, 2019 to 2023 sample dates return 200; 2018-07-31, 2017-01-03, 2016-01-04 and earlier return 403 (AccessDenied). So history starts 2018-08-01, matching FINRA's page. About 1,600 files, roughly 530 MB.
- **History and events.** About 6.4 years to the end of 2024; about 650,000 stock-days in 410 names; a weekly long-short basket gives roughly 330 observations. Walk-forward test years 2019 to 2024 still fit, but with only one year of training before 2020.
- **Timestamp.** FINRA states files post no later than 18:00 ET on the trade date [opened, same FINRA page], so next-open entry is honest. Rare "Updated" files can appear later.
- **How it differs.** Flow data from a regulatory feed, not price, volume or filings.
- **Main way it fails.** Mixed market-maker and informed shorting, a ratio near 40 to 50 percent for most stocks, short window, and no way to separate retail from institutions.
- **Prior 6%. Testability 0.8. Score 4.8.**

### E3. Net share issuance and executed buybacks from XBRL (point in time)

- **Hypothesis.** Companies that shrink their share count (net repurchasers) outperform companies that grow it, and the market underreacts to the share count that each 10-Q or 10-K reveals.
- **Evidence.**
  - Pontiff and Woodgate (2008, Journal of Finance): after 1970, share issuance predicts cross-sectional returns more significantly than size, book-to-market or momentum individually; no predictive power before 1970 [opened: https://ideas.repec.org/a/bla/jfinan/v63y2008i2p921-945.html].
  - McLean, Pontiff and Watanabe (2009, JFE) report the effect holds for both small and large firms internationally [snippet: https://econpapers.repec.org/RePEc:eee:jfinec:v:94:y:2009:i:1:p:1-17].
  - Peyer and Vermaelen (2009, RFS) reject that the buyback anomaly has disappeared; open-market buybacks follow investor overreaction to bad news [opened: https://econpapers.repec.org/RePEc:oup:rfinst:v:22:y:2009:i:4:p:1693-1745]. Contrary: a study cited in a search summary finds the long-run buyback drift gone for recent repurchases [snippet, Fu and Huang 2015, not opened].
  - Decay risk: this is a standard factor input (net issuance sits in five-factor model investment/CMA family) [recollection], so some of it is already priced.
- **Free data.** SEC XBRL "frames" API, cross-section of all filers per period. **Confirmed**: `https://data.sec.gov/api/xbrl/frames/us-gaap/PaymentsForRepurchaseOfCommonStock/USD/CY2019.json` returned 2,411 companies, 364 KB; `https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/CY2019Q4I.json` returned 2,903 companies, 381 KB. Each row has `accn` (accession number), `cik`, `end`, `val`. Frames lack the filing date; join `accn` to the submissions index (already local) for acceptance time. This is an unofficial-looking but documented SEC endpoint, free, rate-limited to 10 requests a second.
- **History and events.** XBRL for large filers starts about 2009 to 2011, so 2016 to 2024 is fully covered. Quarterly: 410 stocks by 36 quarters, about 14,000 stock-quarters; portfolio-level about 36 quarterly or 108 monthly observations.
- **Timestamp.** Good once joined to acceptance time. Beware that the cover-page share count (`dei`) is as of a date after the period end, near the filing date; the balance-sheet count is as of period end. Use only filing-date-known values.
- **How it differs.** A point-in-time fundamentals feed instead of price; "buyback" tested as actual execution rather than the announcement (the sibling report dropped buybacks because announcement dates are not structured; this route avoids that).
- **Main way it fails.** Slow, low-turnover signal with about 100 independent observations; strong overlap with known factors, so a market-adjusted spread may be small; stock-based compensation and share-count noise from splits and acquisitions; large caps show the weakest effect in most factor work [recollection].
- **Prior 5%. Testability 0.7. Score 3.5.**
- **Pre-registration suggestion.** One signal (change in split-adjusted shares outstanding over four quarters, known at filing), long the bottom quintile (net repurchasers), short the top, hold 3 months, rebalance monthly; check that repurchase dollars (the XBRL tag above) agree in sign as a sanity condition, not as a second trial.

### E4. 8-K "bad news" items as one family

- **Hypothesis.** Specific 8-K items (agreement termination 1.02, exit costs 2.05, impairments 2.06, delisting notice 3.01, auditor change 4.01, non-reliance 4.02, and text-confirmed abrupt CEO or CFO exits under 5.02) are negative news the market absorbs slowly; stocks drift down.
- **Evidence.**
  - Lerman and Livnat (2010, Review of Accounting Studies): 8-K items carry abnormal volume and volatility and some show post-filing drift [snippet via the sibling report; I could not identify which items].
  - Item 4.02 specifically: a restatement study with 5,111 non-reliance filings (2005 to 2016) found *no* abnormal negative returns after the restated financials date, and positive abnormal returns of about 1 to 1.8 percent at days 31 to 60 and 271 to 300; only long-process restatements showed a short-lived negative window at days 61 to 90. The authors caution these are buy-and-hold results without costs [opened: https://blog.auditanalytics.com/long-term-capital-market-consequences-of-financial-restatements/]. That is evidence *against* shorting after a restatement.
  - I found no usable event study for Item 5.02 CEO or CFO departures; the search returned nothing on it.
- **Free data.** Already local. **Confirmed live** too: `https://data.sec.gov/submissions/CIK##########.json` returns `form`, `acceptanceDateTime` (UTC, for example `2026-11-09T21:30:40.000Z`) and `items` (for example `8.01,9.01`) per filing, 163 KB for Apple, with older pages in `filings.files`. Eight sample large caps had 81 to 284 8-Ks each in 2016 to 2024 (Apple 81, JPMorgan 284). Items 4.02, 4.01 and 1.05 were absent in all eight, confirming how rare they are.
- **History and events.** 1.02 + 2.05 + 2.06 + 3.01 + 4.01 + 4.02 is about 1,020 events in the universe; true CEO or CFO exits perhaps 1,000 to 2,000 after parsing 5.02 text (sibling estimate, not checked).
- **Timestamp.** Excellent.
- **How it differs.** First use of non-earnings 8-K items.
- **Main way it fails.** Large-cap bad news is priced in minutes (the Pentagon-award outcome); the 4.02 evidence points the other way after the first weeks; pooling items blurs any single effect while splitting them multiplies trials. Heavy survivor bias, but in the direction that hides a short edge.
- **Prior 4%. Testability 0.8. Score 3.2.**

### E5. FINRA bi-monthly short interest

- **Hypothesis.** Stocks with high short interest relative to float or volume (days to cover) underperform, because shorts are informed or because crowded shorts signal overpricing.
- **Evidence.**
  - Rapach, Ringgenberg and Zhou (2016): aggregate short interest predicts lower *market* returns in and out of sample (cited in a search summary [snippet]).
  - Stock-level evidence is concentrated in high-fee, smaller stocks; one 2004 to 2008 monthly study found -0.7% a month for heavy short interest, mostly in high-borrow-cost names, and the summary flags adaptation to published results [snippet: https://www.cxoadvisory.com/short-selling/exploitability-of-monthly-short-interest-for-individual-stocks/]. I found nothing on bi-monthly data in large caps after 2015.
- **Free data.** `https://cdn.finra.org/equity/otcmarket/biweekly/shrtYYYYMMDD.csv` (date is the settlement date). **Confirmed**: 2023-01-31 downloaded in full, 1.97 MB, 20,189 rows, columns `symbolCode`, `currentShortPositionQuantity`, `previousShortPositionQuantity`, `averageDailyVolumeQuantity`, `daysToCoverQuantity`, `stockSplitFlag`, `revisionFlag`, `settlementDate`. Earliest file I found is 2017-12-29 (200/206); 2017-12-15, 2017-11-30, 2017-10-31, 2017-09-29 and earlier return 403. The FINRA API only keeps five rolling years, but these historical files go further back than that [opened: https://www.finra.org/finra-data/browse-catalog/equity-short-interest]. About 165 files, about 330 MB.
- **History and events.** 2018 to 2024, 24 releases a year, so about 168 cross-sections; 410 stocks each.
- **Timestamp.** Weak on its own: files carry only the settlement date. FINRA publishes on the 7th business day after settlement [opened, same page], so entry must be at least that late; I recommend an assumed lag of 9 business days (an assumption, not tested) unless FINRA's annual publication calendar is parsed. The FINRA calendar page was not fetched.
- **How it differs.** Position data from a regulator, a slow information source rather than a price rule.
- **Main way it fails.** Staleness (data are about two weeks old at settlement plus seven business days), weak large-cap spread, and a short window. Better used as the long-horizon companion to E2 than as its own trial.
- **Prior 4%. Testability 0.8. Score 3.2.**

### E6. Schedule 13D filings by known activists

- **Hypothesis.** When a known activist reveals a 5 percent stake with intent to push for change, the stock jumps and holds the gain; a trader entering after public filing may keep a slice.
- **Evidence.**
  - Brav, Jiang, Partnoy and Thomas (2008), 888 events 2001 to 2005 [opened, via a CXO Advisory summary: https://www.cxoadvisory.com/mutual-hedge-funds/chumming-with-sharks/]: average excess return about 7.2% around filing; about 3.2 points of it came in the ten days before the filing; about 2 points on the filing day and the next; the summary says about 4 points came after filing and that gains did not typically reverse over the following year. These pieces do not add to 7.2, so the summary is unreliable on the split. Annual average fell from 10.6% (2001) to 4.8% (2005).
  - Bebchuk, Brav and Jiang (2015, Columbia Law Review): no long-term decline after the initial jump over five years [opened: https://econpapers.repec.org/RePEc:nbr:nberwo:21227]; I could not confirm sample details from that page.
  - Rule change: the 13D deadline moved from 10 calendar days to five business days (effective about February 2024), and amendments are due in two business days [snippet: https://www.sullivanlaw.com/viewpoints/sec-amends-deadlines-and-other-rules-for-reporting-beneficial-ownership-on-schedules-13d-and-13g]. That shortens the pre-filing run-up window but falls in the holdout year.
- **Free data.** EDGAR indexes plus filing headers. **Confirmed**: the 2021 Q1 `form.idx` listed 747 `SC 13D` (initial), 2,433 `SC 13D/A` and 342 `NT 10-K` entries; the per-day index (`https://www.sec.gov/Archives/edgar/daily-index/2021/QTR1/form.20210125.idx`, 666 KB) works; and a filing's `.txt` header (`https://www.sec.gov/Archives/edgar/data/1827824/0001104659-21-007258.txt`) shows `ACCEPTANCE-DATETIME`, `SUBJECT COMPANY` and `FILED BY`, so subject company and filer are in the header. EDGAR full-text search also answered (about 5,300 to 5,700 `SC 13D` hits a year including amendments across all issuers), but that endpoint is unofficial.
- **History and events.** Local: 340 initial 13Ds and 1,826 amendments for 408 issuers over nine years, of which perhaps 100 to 150 are real activists (sibling estimate; I could not verify). I would define "activist" by a fixed list of about 30 filer names written into the protocol before looking.
- **Timestamp.** Good. Filer identity must be parsed from headers (not yet in the local index).
- **How it differs.** Outsider ownership-and-intent filing, not insider trades.
- **Main way it fails.** Under 300 events, front-loaded return, mid-cap focus under-represented in a 410 large-cap universe, and the decay from 10.6% to 4.8% in five years. The honest outcome is "inconclusive".
- **Prior 6%. Testability 0.5. Score 3.0.**

### E7. Reporting-integrity red flags: NT 10-K, NT 10-Q (with 4.01 and 4.02)

- **Hypothesis.** A company that files a late-filing notice, changes auditors or says its past numbers cannot be relied on has an accounting or liquidity problem that the market only partly prices on day one; the stock keeps falling for months.
- **Evidence.** Bartov and Konchitchki (2017, Accounting Horizons), 2,115 NT filings over nine years, firms averaging about $2.3 billion in assets (so mid caps, not microcaps): five-day risk-adjusted returns of -2.93% (NT 10-Q) and -1.96% (NT 10-K); a further decline averaging about 13% over the next three quarters, about five times the initial drop; 16.2% of sample firms delisted for non-merger reasons within two years versus 6.9% of listed companies [opened: https://www.cpapracticeadvisor.com/2017/11/30/study-shows-investors-punish-companies-for-late-financial-statements/28096/]. Secondary summary, not the paper.
- **Free data.** Form types in the EDGAR indexes. **Confirmed**: Q1 2021 `form.idx` lists 342 NT 10-K entries; EDGAR full-text search counts NT 10-K filings at about 740 to 1,230 a year across all issuers (2016: 1,227, 2020: 738, 2024: 978); acceptance times in the submissions API.
- **History and events.** Local universe: 25 NT 10-K and 25 NT 10-Q, plus 24 auditor-change and 20 non-reliance 8-Ks, about 95 events across nine years. Far too few for Sift as built.
- **Timestamp.** Excellent.
- **How it differs.** A negative-information filing type no prior test used.
- **Main way it fails.** Sample size, and the largest losses are delistings, which the universe omits (survivor bias works against the idea, as noted in section 0). To test it properly Sift would need a wider universe including delisted or inactive tickers, which may not be free. The 4.02 evidence in E4 also cuts against it.
- **Prior 10% if testable on a wide universe. Testability 0.3. Score 3.0.**
- **Practical use.** Fold the 8-K and NT items into E4 as a single "reporting stress" family and accept that it mostly measures large-cap behaviour; treat a wide-universe version as a separate project if delisted price data can be found free.

### E8. Form 4 open-market sales and 10b5-1 flags

- **Hypothesis.** Opportunistic (non-routine) insider sales, or clusters of sales by several officers, precede weak returns; sales under pre-arranged 10b5-1 plans were historically timed ahead of declines.
- **Evidence.**
  - Cohen, Malloy and Pomorski (2012, Journal of Finance): opportunistic trades earn about 82 bp a month of value-weighted abnormal returns, routine trades about zero [snippet; the page I tried returned 403]. Their effect is mainly on buys; a later paper notes that recent efforts to filter sales for informativeness find no reliable evidence that a large subset of insider sales predicts negative abnormal returns [snippet].
  - Jagolinzer (2009, Management Science): 10b5-1 plan sales follow price rises and precede declines, with about 6% over six months in one summary [snippet]. After the 2022 SEC amendments, plan sales are less associated with later negative returns [snippet: Kim, Kim and Rajgopal].
- **Free data.** Form 4 is already parsed (`data/insider/trades.parquet`, 251,004 Form 4 filings in the local index). I did not inspect whether sale rows were kept; check that first. The 10b5-1 checkbox exists only on forms filed since April 2023 [recollection], so the plan flag is unusable before the holdout; use opportunistic-versus-routine sales only.
- **History and events.** Thousands of sales; clusters of three or more insiders in 30 days perhaps a few hundred (not counted).
- **Timestamp.** Excellent (Form 4 due within two business days, acceptance time known; Sift already uses this).
- **How it differs.** Same filing as M10 but the sell side, a different hypothesis. Sift's insider-buying result was -0.079R after the market, which warns that the long side was beta.
- **Main way it fails.** Most sales are diversification or compensation; the published edge is on buys; a short-side test needs borrow.
- **Prior 3%. Testability 0.9. Score 2.7.**
- **Form 144 (planned sales) dropped as a standalone.** The local index shows only 36 to 78 Form 144 filings a year through 2022 and 3,514 and 5,936 in 2023 and 2024. A two-year window cannot pass walk-forward, and 2025 onward is sealed.

### E9. Buyback authorization announcements (8-K text)

- **Hypothesis.** A large authorization announced by a mid or large cap signals management's view that the stock is cheap; the stock drifts up.
- **Evidence.** Ikenberry, Lakonishok and Vermaelen (1995): about 3.5% announcement effect and 12.1% four-year abnormal return, 1980 to 1990; no long-run abnormal return for large firms in a footnote of a secondary paper [snippet: https://www.nber.org/papers/w7325.pdf]. Peyer and Vermaelen (2009) reject disappearance [opened, see E3]; announcement-window returns are smaller in 2002 to 2014 subsamples [snippet]. Large-cap recent evidence: none found.
- **Free data.** 8-K item 8.01 or exhibit 99.1 text. **Confirmed**: EDGAR full-text search returned 256 (2018) and 343 (2022) 8-K hits for the phrase pair "share repurchase program" and "board of directors authorized", which indicates scale, not a clean list. Local index has 11,740 item 8.01 filings, most unrelated. Needs a text classifier and an amount-over-market-cap measure.
- **History and events.** About 150 to 350 announcements a year across all issuers; maybe 40 to 100 a year in the universe (my estimate).
- **Timestamp.** Excellent, but many authorizations ride along with earnings (2.02), which confounds with idea 5.
- **How it differs.** Corporate-action announcement not used before.
- **Main way it fails.** Priced at the announcement open; coincident earnings news; messy text extraction.
- **Prior 4%. Testability 0.5. Score 2.0.**

### E10. 13F holdings changes ("best ideas" and large-manager new positions)

- **Hypothesis.** New large positions in a stock by concentrated, skilled managers are information the market has not fully used by the time of the 13F filing.
- **Evidence.** Cohen, Polk and Silli ("Best Ideas") argue managers' highest-conviction holdings outperform [snippet: https://quantpedia.com/strategies/alpha-cloning-following-13f-fillings]; one secondary source claims top-holding replication stayed profitable after the 45-day filing delay, under a different title, so attribution is shaky [snippet]. A practitioner article argues blind 13F cloning almost universally underperforms the originals [snippet: https://13foresight.com/blog/why-13f-copycats-underperform].
- **Free data.** SEC Form 13F Data Sets, quarterly zips from 2013 Q2. **Confirmed**: the page `https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets` lists 54 zips; a `HEAD` on `https://www.sec.gov/files/structureddata/data/form-13f-data-sets/2016q1_form13f.zip` returned 200 and 41.7 MB (not downloaded). Older file names follow `YYYYqN_form13f.zip`, newer ones use date ranges.
- **History and events.** 2016 to 2024: 36 quarterly filing waves; very high event counts.
- **Timestamp.** Acceptance time per filing is in the indexes, but the information is up to 45 days stale at the deadline.
- **How it differs.** Third-party ownership as signal, not insider or activist.
- **Main way it fails.** Staleness, crowding, and the need to define which managers are "skilled" without hindsight.
- **Prior 3%. Testability 0.6. Score 1.8.**

### E11. Spin-offs

- **Hypothesis.** Spun-off companies (and sometimes their parents) are mispriced because of forced index and fund selling and little analyst coverage; buying a few weeks after the distribution captures a drift over months.
- **Evidence.** Mixed and mostly thesis-level for 2000 to 2022: one 196-event US study reports outperformance over five years; one 609-event Copenhagen thesis calls it an "unrelenting anomaly" but shows early negative abnormal returns from supply and demand pressure; a meta-analysis of 26 event studies finds the long-run superior performance disappears in later studies with refined tests [snippet via search summary; none opened].
- **Free data.** Form 10-12B registrations on EDGAR. **Confirmed**: EDGAR full-text search counts 183 (2016), 78 (2018), 35 (2020), 65 (2022), 50 (2024) `10-12B` filings across all issuers, but most are shells and amendments. The local universe holds only 3 10-12B filings, so spin-offs of interest are not in the universe at all and would need fresh price downloads and a hand-built list.
- **History and events.** Perhaps 10 to 25 meaningful US spin-offs a year (recollection); 100 to 200 in nine years.
- **Timestamp.** Registration is public months ahead; the investable date is the distribution date, which is in later 8-Ks.
- **How it differs.** Corporate restructuring event with horizon of months.
- **Main way it fails.** Small N, long horizon, price data for new tickers, and spun-off entities that later disappear (survivor bias flatters the long side).
- **Prior 5%. Testability 0.3. Score 1.5.**

### E12. Congressional trade disclosures (STOCK Act)

- **Hypothesis.** Members of Congress trade on information not yet public; copying their disclosed trades at the next open earns an edge.
- **Evidence (against).**
  - Belmont, Sacerdote, Sehgal and Van Hoek (2022, Journal of Public Economics 207), trades 2012 to 2020: "no evidence of superior investment performance"; stocks House members bought underperformed by about 26 bp over six months and stocks sold by about 11 bp; results at the 95th and 99th percentiles consistent with random picking [opened: https://ideas.repec.org/a/eee/pubeco/v207y2022ics0047272722000044.html].
  - NBER w35041, trades 2012 to 2023: after the STOCK Act legislators' portfolios underperform or at best match the market; timing follows retail sentiment and does not anticipate price moves [opened: https://www.nber.org/papers/w35041].
- **Free data.** The weakest of the twelve. **Confirmed**: House Clerk index zips download (`https://disclosures-clerk.house.gov/public_disc/financial-pdfs/2016FD.zip`, also 2018, 2020, 2023; the 2023 file is 85 KB and lists 460 periodic transaction reports, filing type `P`, with filing dates) but the trades themselves sit in per-report PDFs (a sample PDF of 69 KB downloaded; I did not test text extraction, no PDF tool was available). The Senate eFD portal (`efdsearch.senate.gov`) returned 403 to `curl` and needs a browser session. The community Senate dataset on GitHub downloads (8,350 rows) but ends in 2020 (last push 2021). The House Stock Watcher bucket now returns 403. LuxAlgo's free "market-trackers-data" republishes congress trades as CC0 JSON but holds only 175 rows, all 2025 to 2026 (manifest read 7 Sep 2026): no 2016 to 2024 history [opened: https://github.com/LuxAlgo/market-trackers-data].
- **History and events.** Thousands of trades a year, but extraction is a PDF-parsing project.
- **Timestamp.** Filing date only, with lags of up to 45 days after the trade. Entry at next open after filing is honest.
- **How it differs.** Political-information source, but close to idea 7 and 8 in spirit.
- **Main way it fails.** The published studies find nothing; tested ideas 7 and 8 found nothing after the first open.
- **Prior 2%. Testability 0.4. Score 0.8.**

---

## 2. Ranking

Score = prior of surviving a market-adjusted, replication-checked test (percent) times testability with free data now (0.3 to 0.9).

| Rank | Candidate | Prior | Testability | Score |
|:-:|---|:-:|:-:|:-:|
| 1 | E1 Lazy Prices, Item 1A | 8% | 0.6 | 4.8 |
| 2 | E2 FINRA short-sale volume, long horizon | 6% | 0.8 | 4.8 |
| 3 | E3 Net issuance and executed buybacks (XBRL) | 5% | 0.7 | 3.5 |
| 4 | E4 8-K bad-news items family | 4% | 0.8 | 3.2 |
| 5 | E5 FINRA short interest | 4% | 0.8 | 3.2 |
| 6 | E6 13D activist filings | 6% | 0.5 | 3.0 |
| 7 | E7 NT and integrity red flags | 10% | 0.3 | 3.0 |
| 8 | E8 Form 4 sales | 3% | 0.9 | 2.7 |
| 9 | E9 Buyback announcements | 4% | 0.5 | 2.0 |
| 10 | E10 13F changes | 3% | 0.6 | 1.8 |
| 11 | E11 Spin-offs | 5% | 0.3 | 1.5 |
| 12 | E12 Congress trades | 2% | 0.4 | 0.8 |

Ties are broken by how different the signal is from what Sift has already tested.

## 3. Recommended top four

1. **E1, Lazy Prices on Item 1A only.** Most orthogonal information source, about 3,000 filing pairs, free text, exact timestamps. One section, one similarity measure, one holding rule (see E1). Expect a small spread; the large-cap replication hint is a t of about 2 at best, which is the reason to pre-register a single specification.
2. **E2, FINRA short-sale volume, with E5 (short interest) as the long-horizon companion.** One primary signal: 60-day average short-volume share minus its own trailing 250-day average, held about 20 days, long-short basket. Short interest is a secondary feature in the same protocol only if it is declared in advance; otherwise it is a separate trial. Report the 2018-08 start and use no pre-2019 data for training beyond what exists.
3. **E3, net share issuance and buyback execution from XBRL frames.** New free data type (point-in-time fundamentals) with a stronger academic record than most; the aim is to see whether it survives subtracting SPY and replicating on unseen stocks. A one-signal, three-month-hold, quarterly-information design keeps the trial count low.
4. **E4, 8-K bad-news family as a single hypothesis**, with E7's NT notices folded in as extra events. The data are local, so it is the cheapest of the four. Expect the Pentagon-award pattern (nothing left at the next open); the 4.02 restatement evidence even points toward a bounce. It is worth running mainly to close the 8-K item category.

Not in the top four but worth keeping: **E6 (13D)** is the clearest "information changes hands" event. It becomes testable only if the universe is widened to mid caps or the activist list yields at least 100 events; otherwise it reads "inconclusive". **E7** has the strongest academic effect (about -13% over three quarters) but cannot be tested without delisted tickers.

## 4. Considered and dropped

| Idea | Reason |
|---|---|
| Pre-FOMC drift | Kurov, Wolfe and Gilbert (2021): drift essentially disappeared after 2015, with and without press conferences [opened: https://ideas.repec.org/a/eee/finlet/v40y2021ics1544612320315956.html]. Lucca and Moench (2015) found it for 1994 to 2011 [opened: https://econpapers.repec.org/RePEc:bla:jfinan:v:70:y:2015:i:1:p:329-371]. Martello and Ribeiro: drift concentrated in high-uncertainty periods, about 109 bp when implied volatility is above its median [opened: https://quantpedia.com/fomc-equity-drift-occurs-in-periods-of-high-uncertainty/]. About 70 meetings in the window: inconclusive by construction. Federal Reserve calendar page is free (`https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm`, confirmed 200; shows 2021 to 2027, older years on archive pages not checked). Single-asset timing, not stock selection. |
| S&P 500 additions | Greenwood and Sammon: abnormal return 3.4% (1980s), 7.6% (1990s), 0.8% (last decade) [opened: https://www.nber.org/papers/w30748]. About 200 to 250 events with announcement dates only from S&P press releases (`press.spglobal.com` loads, 200, but I did not build a list); the Wikipedia constituents table (via the MediaWiki API, 200) shows only current members' `Date added`, so it is survivor-biased and the old changes table was not found on that page. Timestamp quality is poor without press-release scraping. |
| Form 144 | Only electronic from April 2023; local counts 36 to 78 a year to 2022 (see E8). |
| SEC comment letters | Released at least 20 business days after review closes [recollection]; no evidence found of tradable drift; I did not test the data feed. |
| FDA and clinical calendars | The names are mostly small caps outside the universe; the PDUFA calendar is not a clean free structured feed [recollection]. LuxAlgo lists openFDA approvals but their history depth was not checked. |
| Reddit and Google Trends | Bradley, Hanousek, Jame and Xiao (RFS 2024): WSB due-diligence posts predicted returns before the GameStop episode and the predictability is eliminated afterwards [snippet via search summary: https://econpapers.repec.org/RePEc:oup:rfinst:v:37:y:2024:i:5:p:1409-1459.]. No free, timestamped, historical mention data (Pushshift is gone; I did not test alternatives). Google Trends is rescaled and sampled, which breaks point-in-time use [recollection]. |
| Going-concern warnings | Large and mid caps almost never carry them; no structured free flag. EDGAR full-text search finds "substantial doubt" text (confirmed: 655 hits for a one-quarter 10-K query) but mostly microcaps. |
| Russell reconstitution | Not tested; free rank-day lists for 2016 to 2024 not confirmed (sibling report agrees). |

## 5. Data-test log

| Source | URL pattern | Result |
|---|---|---|
| FINRA daily short volume | `cdn.finra.org/equity/regsho/daily/CNMSshvolYYYYMMDD.txt` | 200 from 2018-08-01; 403 before |
| FINRA short interest | `cdn.finra.org/equity/otcmarket/biweekly/shrtYYYYMMDD.csv` | 200 or 206 from 2017-12-29; 403 earlier tested dates |
| SEC submissions API | `data.sec.gov/submissions/CIK##########.json` | 200; `acceptanceDateTime`, `items` present |
| SEC full index | `www.sec.gov/Archives/edgar/full-index/YYYY/QTRn/form.idx` | 200, 56 MB (too big for a probe) |
| SEC daily index | `.../daily-index/YYYY/QTRn/form.YYYYMMDD.idx` | 200, 666 KB |
| SEC full-text search | `efts.sec.gov/LATEST/search-index?q=...&forms=...` | 200; unofficial endpoint |
| SEC XBRL frames | `data.sec.gov/api/xbrl/frames/...` | 200, about 360 to 380 KB per frame |
| SEC 13F data sets | `www.sec.gov/files/structureddata/data/form-13f-data-sets/YYYYqN_form13f.zip` | HEAD 200 (2016q1, 41.7 MB); not downloaded |
| SEC 13D header | `www.sec.gov/Archives/edgar/data/<cik>/<accession>.txt` | 200; `ACCEPTANCE-DATETIME`, subject and filer present |
| SEC 10-K main document | `www.sec.gov/Archives/edgar/data/<cik>/<accession>/<doc>.htm` | 200, 1.52 MB |
| House Clerk disclosures | `disclosures-clerk.house.gov/public_disc/financial-pdfs/YYYYFD.zip` | 200 or 206 for 2016, 2018, 2020, 2023; trades are in PDFs |
| Senate eFD | `efdsearch.senate.gov` | 403 to `curl` |
| Community Senate JSON | `raw.githubusercontent.com/timothycarambat/senate-stock-watcher-data/...` | 200; rows 2012 to 2020 only |
| LuxAlgo market-trackers-data | `github.com/LuxAlgo/market-trackers-data` | 200; congress 175 rows (2025 to 2026) |
| Federal Reserve FOMC calendar | `federalreserve.gov/monetarypolicy/fomccalendars.htm` | 200 |
| House Stock Watcher bucket | `house-stock-watcher-data.s3...` | 403 |

## 6. What I could not establish

- No post-2015 large-cap evidence for E4's 5.02 CEO or CFO departures, E9 buybacks, E10 and E11 beyond theses and secondary summaries.
- Whether Alpaca serves delisted tickers (needed for E7 and for any widened bad-news universe).
- Exact FINRA short-interest publication calendar for 2018 to 2024; the 9-business-day lag is an assumption.
- Event counts for activist 13D filers, CEO and CFO exits, and buyback announcements in the universe are estimates, not measured.
- Sources that failed to open or read: the Brav et al. PDF (binary), Wang-Yan-Zheng PDF (binary), the Cohen-Malloy-Pomorski HBS page (403), the Skidmore Kurov PDF (404), FINRA short interest landing URLs at two paths (404).
