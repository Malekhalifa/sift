"""Political news events for M12 (docs/m12-political-protocol.md): which listed companies a presidential post names, how
positive or negative the post is, which Pentagon contract awards go to which listed company, and when each becomes
tradable. Everything here is fixed text rules, written down before any return was computed.
"""

from __future__ import annotations

import re
import tomllib
from functools import lru_cache

import pandas as pd

from tp import config

MIN_AWARD = 100_000_000  # DoD contract transactions of at least this many dollars

# Trailing words dropped from SEC company titles; first words too generic to identify a company on their own.
SUFFIXES = {"inc", "corp", "corporation", "co", "company", "companies", "ltd", "limited", "plc", "holdings", "holding", "group",
            "the", "nv", "n.v.", "sa", "ag", "se", "llc", "lp", "l.p.", "new", "de", "international", "incorporated", "&"}
GENERIC_FIRST = {"american", "united", "general", "first", "national", "international", "global", "southern", "western", "public",
                 "pacific", "northern", "great", "target", "capital", "bank", "health", "energy", "financial", "union", "state",
                 "texas", "best", "gap", "visa", "delta", "total", "mosaic", "ball", "chubb", "target", "aon", "key", "ross", "ice",
                 "gen", "doc", "well", "mac", "sun", "one", "us", "usa", "new", "royal", "universal", "johnson", "williams", "newell",
                 "progressive", "hershey", "intel", "cigna", "match", "apple hospitality", "booking", "tapestry", "acuity"}
MANUAL = {  # names people actually use that the cleaned SEC title does not give
    "GOOGL": ["Google"], "META": ["Facebook"], "XOM": ["Exxon", "ExxonMobil"], "T": ["AT&T"], "JPM": ["JPMorgan", "J.P. Morgan"],
    "KO": ["Coca-Cola", "Coca Cola"], "DIS": ["Disney"], "BA": ["Boeing"], "F": ["Ford Motor"],  # bare "Ford" is mostly people (a President, Dr. Ford)
    "INTC": ["Intel Corp", "@Intel"], "GM": ["General Motors", "G.M."],
    "WMT": ["Walmart", "Wal-Mart"], "MCD": ["McDonald's", "McDonalds"], "HD": ["Home Depot"], "LMT": ["Lockheed"],
    "NOC": ["Northrop"], "CMCSA": ["Comcast"], "AMZN": ["Amazon"], "BAC": ["Bank of America"], "WFC": ["Wells Fargo"],
    "GS": ["Goldman Sachs", "Goldman"], "VZ": ["Verizon"], "CVX": ["Chevron"], "IBM": ["IBM"], "FDX": ["FedEx"],
    "HOG": ["Harley-Davidson", "Harley Davidson", "Harley"], "BMY": ["Bristol-Myers", "Bristol Myers"], "MRK": ["Merck"],
    "PG": ["Procter & Gamble", "Procter and Gamble"], "AXP": ["American Express"], "AAL": ["American Airlines"], "UAL": ["United Airlines"],
    "DAL": ["Delta Air Lines", "Delta Airlines"], "LUV": ["Southwest Airlines"], "MS": ["Morgan Stanley"], "C": ["Citigroup", "Citibank"],
    "TMUS": ["T-Mobile"], "CAT": ["Caterpillar"], "DE": ["John Deere", "Deere"], "NKE": ["Nike"], "ORCL": ["Oracle"], "TSLA": ["Tesla"],
}


def posts_path():
    return config.DATA_DIR / "political" / "posts.parquet"


def awards_path():
    return config.DATA_DIR / "political" / "dod_awards.parquet"


def clean_name(title: str) -> list[str]:
    """Words of an SEC company title with legal suffixes removed: 'LOCKHEED MARTIN CORP' -> ['lockheed', 'martin']."""
    words = [w for w in re.sub(r"[^\w&' .-]", " ", title.split("/")[0]).lower().split() if w]
    while words and words[-1].strip(".") in SUFFIXES:
        words.pop()
    return words


def auto_aliases(titles: dict[str, str]) -> dict[str, list[str]]:
    """Symbol -> surface strings to look for: the full cleaned SEC name (when at least five letters and not a generic
    word) plus the hand-written names in MANUAL. No first-word shortcuts: they match 'home', 'under' and 'citizens'."""
    out: dict[str, list[str]] = {}
    for sym, title in titles.items():
        words = clean_name(title)
        names = []
        full = " ".join(words)
        if len(full) >= 5 and full not in GENERIC_FIRST:
            names.append(full)
        names += [m.lower() for m in MANUAL.get(sym, [])]
        out[sym] = list(dict.fromkeys(names))
    return {k: v for k, v in out.items() if v}


@lru_cache(maxsize=1)
def aliases() -> dict[str, list[str]]:
    """The frozen alias table, config/political_aliases.toml."""
    with open(config.ROOT / "config" / "political_aliases.toml", "rb") as f:
        return {k: list(v) for k, v in tomllib.load(f)["aliases"].items()}


@lru_cache(maxsize=1)
def _patterns() -> dict[str, re.Pattern]:
    return {sym: re.compile(r"(?<![\w])(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")(?![\w])", re.I)
            for sym, names in aliases().items()}


def mentioned(text: str) -> list[str]:
    """Symbols whose names appear in the text (whole words, any case)."""
    return [sym for sym, pat in _patterns().items() if pat.search(text)]


POSITIVE = {"great", "greatest", "tremendous", "fantastic", "amazing", "incredible", "wonderful", "congratulations", "congrats",
            "proud", "thank", "thanks", "love", "best", "strong", "winning", "win", "boom", "record", "jobs", "invest", "investing",
            "investment", "building", "beautiful", "terrific", "success", "successful", "bringing back", "welcome"}
NEGATIVE = {"terrible", "horrible", "disaster", "disgrace", "disgraceful", "bad", "worst", "failing", "failed", "fake", "boycott",
            "crooked", "ripoff", "rip off", "corrupt", "shameful", "pathetic", "stupid", "weak", "lose", "losing", "loser",
            "out of control", "cancel", "canceled", "cancelled", "fire", "fired", "sad", "unfair", "dishonest"}


def tone(text: str) -> int:
    """+1 if the post has more positive than negative words from the fixed lists, -1 if more negative, 0 if tied or neither."""
    low = " " + re.sub(r"[^a-z' ]+", " ", text.lower()) + " "
    pos = sum(low.count(f" {w} ") for w in POSITIVE)
    neg = sum(low.count(f" {w} ") for w in NEGATIVE)
    return (pos > neg) - (neg > pos)


PRIMES = {  # recipient-name fragments (upper case) -> listed company in our universe, fixed before any return was computed
    "LMT": ["LOCKHEED MARTIN", "SIKORSKY"],
    "NOC": ["NORTHROP GRUMMAN"],
    "GD": ["GENERAL DYNAMICS", "ELECTRIC BOAT", "BATH IRON WORKS", "NATIONAL STEEL AND SHIPBUILDING", "GULFSTREAM"],
    "RTX": ["RAYTHEON", "UNITED TECHNOLOGIES", "PRATT & WHITNEY", "PRATT AND WHITNEY", "ROCKWELL COLLINS", "COLLINS AEROSPACE"],
    "BA": ["BOEING"],
    "LHX": ["L3HARRIS", "L3 HARRIS", "HARRIS CORP", "L3 TECHNOLOGIES", "L-3 COMMUNICATIONS"],
    "TXT": ["TEXTRON", "BELL HELICOPTER", "BELL TEXTRON", "CESSNA"],
}


def prime_of(recipient: str) -> str | None:
    name = str(recipient).upper()
    for sym, fragments in PRIMES.items():
        if any(f in name for f in fragments):
            return sym
    return None


COOLDOWN_DAYS = 5  # one event per company per this many calendar days: the first post or award starts it


def _thin(events: pd.DataFrame) -> pd.DataFrame:
    keep, last = [], {}
    for row in events.sort_values("ts").itertuples():
        if row.symbol not in last or (row.ts - last[row.symbol]).days > COOLDOWN_DAYS:
            keep.append(row.Index)
            last[row.symbol] = row.ts
    return events.loc[keep].reset_index(drop=True)


def post_events(posts: pd.DataFrame) -> pd.DataFrame:
    """One row per (company, post): symbol, ts (UTC), tone (+1 or -1), source. Posts that start with a quoted supporter
    tweet ('"@name: ...') are not the president's own words and are skipped, as are posts with no clear tone."""
    rows = []
    for post in posts.itertuples():
        if post.text.startswith('"@'):
            continue
        t = tone(post.text)
        if t == 0:
            continue
        rows += [{"symbol": sym, "ts": post.ts, "tone": t, "source": post.source} for sym in mentioned(post.text)]
    if not rows:
        return pd.DataFrame(columns=["symbol", "ts", "tone", "source"])
    return _thin(pd.DataFrame(rows))


def award_events(awards: pd.DataFrame) -> pd.DataFrame:
    """One row per (listed prime, award day): symbol, ts (the action date, midnight UTC), amount (largest that day)."""
    df = awards.assign(symbol=awards["recipient"].map(prime_of)).dropna(subset=["symbol"])
    df = df.groupby(["symbol", "action_date"], as_index=False)["amount"].max().rename(columns={"action_date": "ts"})
    df["ts"] = pd.to_datetime(df["ts"]).dt.tz_localize("UTC")
    return _thin(df)
