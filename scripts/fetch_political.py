"""Download the free political data for M12 into data/political/ (docs/m12-political-protocol.md).

    uv run python scripts/fetch_political.py

- posts.parquet: Donald Trump's original posts with UTC timestamps. Tweets 2016-2018 from the bpb27 archive (timestamps
  carry a UTC offset; the later CSV archive's clock is inconsistent, so 2019-2021 is left out), Truth Social 2022-02 to
  today from CNN's archive. Reposts are dropped.
- dod_awards.parquet: Department of Defense contract transactions of at least $100 million, 2016-2024, from the official
  USAspending.gov API (action date, recipient, amount).

Nothing after 2024 is read by any M12 analysis until the protocol's holdout rule allows it; the files hold later posts
so the holdout run does not need a second download.
"""

from __future__ import annotations

import io
import json
import re
import sys
import time
import zipfile

import httpx
import pandas as pd

from tp import config, political

TWEETS = "https://raw.githubusercontent.com/bpb27/trump_tweet_data_archive/master/condensed_{year}.json.zip"
TRUTH = "https://ix.cnn.io/data/truth-social/truth_archive.parquet"
USASPENDING = "https://api.usaspending.gov/api/v2/search/spending_by_transaction/"
UA = {"User-Agent": "trading-pipeline-research"}
TAG = re.compile(r"<[^>]+>")


def fetch_tweets(http: httpx.Client) -> pd.DataFrame:
    rows = []
    for year in (2016, 2017, 2018):
        r = http.get(TWEETS.format(year=year))
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            rows += json.loads(z.read(z.namelist()[0]))
    df = pd.DataFrame(rows)
    df = df[~df["is_retweet"].astype(bool) & ~df["text"].str.startswith("RT @")]
    return pd.DataFrame({
        "source": "twitter", "id": df["id_str"].astype(str),
        "ts": pd.to_datetime(df["created_at"], format="%a %b %d %H:%M:%S %z %Y", utc=True), "text": df["text"],
    })


def fetch_truth(http: httpx.Client) -> pd.DataFrame:
    r = http.get(TRUTH)
    r.raise_for_status()
    df = pd.read_parquet(io.BytesIO(r.content))
    text = df["content"].fillna("").map(lambda s: TAG.sub(" ", s).replace("&amp;", "&").strip())
    keep = ~text.str.startswith("RT") & (text.str.len() > 0)
    return pd.DataFrame({"source": "truth", "id": df["id"].astype(str), "ts": pd.to_datetime(df["created_at"], utc=True), "text": text})[keep]


def fetch_awards(http: httpx.Client) -> pd.DataFrame:
    rows = []
    for year in range(2016, 2025):
        for month in range(1, 13):
            start = f"{year}-{month:02d}-01"
            end = (pd.Timestamp(start) + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")
            page = 1
            while True:
                body = {
                    "filters": {
                        "agencies": [{"type": "awarding", "tier": "toptier", "name": "Department of Defense"}],
                        "award_type_codes": ["A", "B", "C", "D"],
                        "time_period": [{"start_date": start, "end_date": end}],
                        "award_amounts": [{"lower_bound": political.MIN_AWARD}],
                    },
                    "fields": ["Award ID", "Recipient Name", "Action Date", "Transaction Amount"],
                    "sort": "Transaction Amount", "order": "desc", "limit": 100, "page": page,
                }
                for attempt in range(4):
                    r = http.post(USASPENDING, json=body)
                    if r.status_code < 500:
                        break
                    time.sleep(2 * (attempt + 1))
                r.raise_for_status()
                data = r.json()
                rows += [x for x in data["results"] if (x.get("Transaction Amount") or 0) >= political.MIN_AWARD]
                # results are sorted by transaction amount, so stop once a page reaches transactions below the threshold
                small = [x for x in data["results"] if (x.get("Transaction Amount") or 0) < political.MIN_AWARD]
                if small or not data.get("page_metadata", {}).get("hasNext"):
                    break
                page += 1
            print(f"  awards {start[:7]}: {len(rows):,} so far", file=sys.stderr)
    df = pd.DataFrame(rows).rename(columns={"Award ID": "award_id", "Recipient Name": "recipient", "Action Date": "action_date",
                                            "Transaction Amount": "amount"})
    df["action_date"] = pd.to_datetime(df["action_date"])
    return df[["award_id", "recipient", "action_date", "amount"]].drop_duplicates(["award_id", "action_date", "amount"])


def main() -> int:
    folder = config.DATA_DIR / "political"
    folder.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers=UA, timeout=120.0, follow_redirects=True) as http:
        posts = pd.concat([fetch_tweets(http), fetch_truth(http)], ignore_index=True).sort_values("ts").reset_index(drop=True)
        posts.to_parquet(political.posts_path(), index=False)
        print(f"{len(posts):,} original posts ({posts['source'].value_counts().to_dict()}); {posts['ts'].min():%Y-%m-%d} to {posts['ts'].max():%Y-%m-%d}")
        if not political.awards_path().exists():
            awards = fetch_awards(http)
            awards.to_parquet(political.awards_path(), index=False)
        awards = pd.read_parquet(political.awards_path())
        print(f"{len(awards):,} DoD contract transactions of at least ${political.MIN_AWARD:,}; {awards['action_date'].min():%Y-%m-%d} to {awards['action_date'].max():%Y-%m-%d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
