"""    uv run python -m tp.paper                 # dry run (default): logs what it would do, sends nothing
    uv run python -m tp.paper --live          # sends bracket orders to the Alpaca PAPER account
    uv run python -m tp.paper --once          # one decision cycle for the current bar, then exit
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import replace
from datetime import UTC, datetime

import pandas as pd

from tp import config
from tp.alpaca_data import TradingClient
from tp.paper.db import PaperDB
from tp.paper.decide import load_config
from tp.paper.livedata import LiveData
from tp.paper.runner import PaperRunner


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(config.ROOT / "config" / "paper" / "plumbing.toml"))
    ap.add_argument("--live", action="store_true", help="send orders to the paper account (default: dry run)")
    ap.add_argument("--once", action="store_true", help="run a single decision cycle now and exit")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cfg = load_config(args.config)
    if args.live:
        cfg = replace(cfg, dry_run=False)
    client = TradingClient(config.Settings.from_env())
    runner = PaperRunner(cfg, client, LiveData(client, cfg), PaperDB())
    if args.once:
        now = pd.Timestamp(datetime.now(UTC))
        for w in runner.data.load_static(now):
            print("WARN", w)
        print(runner.cycle(now))
        return 0
    return runner.run()


if __name__ == "__main__":
    raise SystemExit(main())
