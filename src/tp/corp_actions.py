"""Stock splits, stored in data/corp_actions/splits.parquet and applied at read time (bars stay raw)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import pandas as pd

from tp import config
from tp.alpaca_data import AlpacaClient

SPLIT_COLUMNS = ["symbol", "ex_date", "ratio"]


def splits_path():
    return config.DATA_DIR / "corp_actions" / "splits.parquet"


def sync_splits(client: AlpacaClient, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
    """Refetch all splits for the symbols and overwrite the store. ratio = new_rate / old_rate."""
    rows = [
        {
            "symbol": r["symbol"],
            "ex_date": pd.Timestamp(r["ex_date"]),
            "ratio": float(r["new_rate"]) / float(r["old_rate"]),
        }
        for r in client.splits(symbols, start, end)
    ]
    df = pd.DataFrame(rows, columns=SPLIT_COLUMNS).sort_values(["symbol", "ex_date"]).reset_index(drop=True)
    splits_path().parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(splits_path(), index=False)
    return df


def load_splits(symbol: str | None = None) -> pd.DataFrame:
    if not splits_path().exists():
        return pd.DataFrame(columns=SPLIT_COLUMNS)
    df = pd.read_parquet(splits_path())
    return df if symbol is None else df[df["symbol"] == symbol].reset_index(drop=True)
