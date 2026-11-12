"""Registry of the datasets the recorder keeps current, and the recorder settings."""
from __future__ import annotations

import tomllib
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from tp import config, political


@dataclass(frozen=True)
class Dataset:
    name: str
    path: Path
    key: tuple[str, ...]
    ts_col: str


def _under(*parts: str) -> Callable[[], Path]:
    return lambda: config.DATA_DIR.joinpath(*parts)


# name -> (path factory, dedup key, timestamp column). Paths resolve at access so TP_DATA_DIR overrides apply.
_SPECS: dict[str, tuple[Callable[[], Path], tuple[str, ...], str]] = {
    "eightk": (_under("events", "eightk.parquet"), ("symbol", "accession"), "filed_at"),
    "earnings": (_under("events", "earnings.parquet"), ("symbol", "accession"), "filed_at"),
    "tenk_index": (_under("store", "tenk_index.parquet"), ("symbol", "accn"), "filed_at"),
    "form4": (_under("insider", "trades.parquet"), ("trade_id", "owner_cik"), "filing_date"),
    "xbrl_shares": (_under("xbrl", "shares.parquet"), ("accn", "symbol", "end"), "filed"),
    "finra_shortvol": (_under("finra", "shortvol.parquet"), ("date", "symbol"), "date"),
    "finra_short_interest": (
        _under("store", "finra_short_interest.parquet"), ("settlement_date", "symbol"), "settlement_date",
    ),
    "dod_awards": (political.awards_path, ("award_id", "action_date", "amount"), "action_date"),
    "trump_posts": (political.posts_path, ("source", "id"), "ts"),
    "sp500_changes": (
        _under("store", "sp500_changes.parquet"), ("effective_date", "added", "removed"), "effective_date",
    ),
    "wikipedia_pageviews": (_under("store", "wikipedia_pageviews.parquet"), ("date", "symbol", "article"), "date"),
    "congress_trades": (_under("store", "congress_trades.parquet"), ("source_id",), "ts"),
}


def dataset(name: str) -> Dataset:
    path, key, ts_col = _SPECS[name]
    return Dataset(name=name, path=path(), key=key, ts_col=ts_col)


class _Registry(Mapping[str, Dataset]):
    def __getitem__(self, name: str) -> Dataset:
        return dataset(name)

    def __iter__(self) -> Iterator[str]:
        return iter(_SPECS)

    def __len__(self) -> int:
        return len(_SPECS)


DATASETS: Mapping[str, Dataset] = _Registry()


def load_settings() -> dict:
    with open(config.ROOT / "config" / "collect.toml", "rb") as f:
        return tomllib.load(f)
