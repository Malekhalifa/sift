# M12 protocol: political news events, as two event studies (pre-registered)

Committed before any M12 return exists. Two questions, each tested as a plain event study first: if there is no
average move after the news, no trading rule built on it can work.

## Why, and what we expect

The thought is that politics moves stocks: a presidential post praising or attacking a company, or a large Pentagon
contract. Both are public, timestamped, and free to get. The catch is speed. Algorithms read these within seconds, so
what is left for a slower trader is the question.

- **P1, presidential posts naming a company.** [Ajjoub, Walker and Zhao](https://econpapers.repec.org/RePEc:eme:ijmfpp:ijmf-02-2020-0068)
  (tweets May 2016 to August 2018, International Journal of Managerial Finance 2021) find that negative tweets are
  followed by significant price declines for non-media firms and positive tweets for media firms; that is a same-day
  reaction, which our daily test, entering at the next open, cannot capture. A Mannheim paper titled
  ["Heroes, just for one day"](https://madoc.bib.uni-mannheim.de/62106/) (seen only through a search summary) is about
  such effects being short-lived, and I did not verify that it measures the same thing. No peer-reviewed firm-level
  study of Truth Social turned up. Prior of passing: about 3%.
- **P2, large Pentagon contract awards to listed contractors.** Large primes receive such awards constantly and they are
  small against their revenue, and awards are often expected. Prior: about 2%.

We run them because they are the one place your politics idea can be checked with data, and a clean "nothing" closes
it.

## Data (`scripts/fetch_political.py`, free)

- **Posts:** tweets from the bpb27 archive for 2016-2018 (timestamps carry a UTC offset; the later CSV archive's clock
  is inconsistent, so **2019-2021 is left out**), Truth Social posts from CNN's archive for 2022-02 on. Reposts dropped.
  Posts that start with a quoted supporter tweet (`"@name: ...`) are skipped, as they are not the president's words.
- **Awards:** Department of Defense contract transactions of at least $100 million from the official USAspending.gov API,
  2016-2024. Recipient names are mapped to seven listed primes by the fixed fragments in `tp.political.PRIMES`
  (LMT, NOC, GD, RTX, BA, LHX, TXT).
- **Development period:** posts 2016-2018 and 2022-2024; awards 2016-2024. **The 2025+ posts and awards are the holdout and
  are not analysed here.** (The post file already holds posts after 2024 so that the holdout needs no second download.)

## Events

- **P1:** a post that names a listed company (whole word, any case) using the frozen alias table
  `config/political_aliases.toml` (full cleaned SEC name plus a short hand-written list; written before any return
  was computed) and has a clear tone by the fixed word lists in `tp.political` (more positive than negative words gives +1,
  the reverse -1, tied or none is dropped). One event per company per 5 calendar days (the first post).
  **134 events** in the development period (84 positive, 50 negative); Facebook and Amazon account for 53 of them.
- **P2:** the largest qualifying award per prime per day; one event per prime per 5 days. **935 events.**

**What was looked at before this protocol:** text only. The match counts per alias and a sample line each, to cut
false matches (the first draft matched "home", "under", "citizens"); the number of events per year; the number of
awards per prime. No returns.

## Trade timing and return

Daily bars, split-adjusted. A post before 09:30 ET on a session is first tradable at that session's open; any other post at
the next session's open. An award announced on action date D is first tradable at the open of the **second** session after
D (announcements come after the close, and USAspending's dates can lag the news; this errs against finding an effect).

For each event: the stock's return from that open to the close of the fifth session (a five-session hold), minus
SPY's over the same dates, signed by the event's direction (the post's tone; long for awards), minus **10 bps** round
trip for costs. Informational only, not judged: holds of 1 and 20 sessions.

## Pass criteria: each study separately, all four

1. At least 100 events with measurable returns. Fewer means **inconclusive, not passed**.
2. Mean net signed return above zero with the lower bound of its **97.5%** interval above zero (the 5% error budget split
   over the two studies; clustering of events is ignored, so the interval is optimistic).
3. Positive mean in at least two thirds of the calendar years that have at least 8 events.
4. Positive mean in both halves of the events (earlier half and later half by date).

Reported for P1 but not judged: positive posts alone, negative posts alone, and the result without Facebook and Amazon.

## If one passes

One run on the 2025+ holdout, once, reported whatever it shows (for posts, Truth Social from 2025 on, which is the
presidency; for awards, a new pull for 2025). Only then would a live monitor be built and paper trading for evidence start.

## Limits

- **Daily bars cannot test the first minutes,** where the thesis ("the stock sky-rockets when he says it") lives. A trader
  with a minute-level feed and a fast bot may do differently; this study measures what remains after the first session
  opens. Intraday data exists only for 60 of our names and there would be a handful of events.
- **Crude tone.** A fixed word list on posts full of sarcasm; a post naming several companies gives them all the same tone.
- **Few events.** 134 posts, concentrated in two companies, and the 2019-2021 gap. Cluster and market-wide days inflate the
  apparent precision.
- **Awards are mostly expected,** and the dollar threshold is for the whole award, not its size relative to the firm.
- **Survivors,** as always: stocks listed today.
- **Not tested:** the president's disclosed stock trades (OGE 278-T filings arrive weeks late), Donald Trump Jr.'s trades
  (no public per-trade source), and politicians' STOCK Act filings.
