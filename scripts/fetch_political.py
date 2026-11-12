"""Download the free political data for M12 into data/political/ (docs/m12-political-protocol.md).

    uv run python scripts/fetch_political.py

- posts.parquet: Donald Trump's original posts with UTC timestamps. Tweets 2016-2018 from the bpb27 archive (timestamps
  carry a UTC offset; the later CSV archive's clock is inconsistent, so 2019-2021 is left out), Truth Social 2022-02 to
  today from CNN's archive. Reposts are dropped.
- dod_awards.parquet: Department of Defense contract transactions of at least $100 million, 2016 to date, from the official
  USAspending.gov API (action date, recipient, amount).

Nothing from 2025 on is read by any M12 analysis until the protocol's holdout rule allows it; the files hold later posts
so the holdout run does not need a second download.

The fetch functions live in tp.collect.sources.political, where the recorder's dod_awards and trump_posts sources use them.
This script rewrites the files whole (without the recorder's ingested_at column, which the recorder's writer tolerates).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx
import pandas as pd

from tp import config, political
from tp.collect.sources.political import (  # noqa: F401
    TRUTH,
    TWEETS,
    UA,
    USASPENDING,
    fetch_awards,
    fetch_truth,
    fetch_tweets,
)


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Replace the file via a pid-suffixed temp file, so an interrupted run never leaves a partial parquet."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        df.to_parquet(tmp, index=False)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    folder = config.DATA_DIR / "political"
    folder.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers=UA, timeout=120.0, follow_redirects=True) as http:
        posts = pd.concat([fetch_tweets(http), fetch_truth(http)], ignore_index=True).sort_values("ts").reset_index(drop=True)
        write_parquet(posts, political.posts_path())
        print(f"{len(posts):,} original posts ({posts['source'].value_counts().to_dict()}); {posts['ts'].min():%Y-%m-%d} to {posts['ts'].max():%Y-%m-%d}")
        old = pd.read_parquet(political.awards_path()) if political.awards_path().exists() else None
        new = fetch_awards(http, None if old is None else old["action_date"].max())
        awards = new if old is None else pd.concat([old, new]).drop_duplicates(["award_id", "action_date", "amount"])
        write_parquet(awards.sort_values("action_date"), political.awards_path())
        print(f"{len(awards):,} DoD contract transactions of at least ${political.MIN_AWARD:,}; {awards['action_date'].min():%Y-%m-%d} to {awards['action_date'].max():%Y-%m-%d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
