"""Registry of the recorder's sources; each source task appends its class to build_sources."""
from __future__ import annotations

from tp.collect.source import Source
from tp.collect.sources.alpaca_bars import AlpacaBars
from tp.collect.sources.finra import FinraShortInterest, FinraShortVolume
from tp.collect.sources.political import DodAwards, TrumpPosts
from tp.collect.sources.sec import SecFilings, SecForm4, SecXbrlShares
from tp.collect.sources.sp500 import Sp500Changes
from tp.collect.sources.wikipedia import WikipediaPageviews


def source_settings(settings: dict, name: str) -> dict:
    """The `[sources.<name>]` table, or a clear exit when config/collect.toml lacks it."""
    table = settings.get("sources", {}).get(name)
    if table is None:
        raise SystemExit(f"config/collect.toml is missing [sources.{name}]")
    return table


REGISTRY: tuple[tuple[str, type[Source]], ...] = (
    ("alpaca_bars", AlpacaBars),
    ("sec_filings", SecFilings),
    ("sec_form4", SecForm4),
    ("sec_xbrl_shares", SecXbrlShares),
    ("finra_shortvol", FinraShortVolume),
    ("finra_short_interest", FinraShortInterest),
    ("dod_awards", DodAwards),
    ("trump_posts", TrumpPosts),
    ("sp500_changes", Sp500Changes),
    ("wikipedia_pageviews", WikipediaPageviews),
)


def build_sources(settings: dict) -> list[Source]:
    """Every registered source built from its settings table, except those whose table says `enabled = false`."""
    sources: list[Source] = []
    for name, cls in REGISTRY:
        cfg = source_settings(settings, name)
        if cfg.get("enabled", True):
            sources.append(cls(cfg["schedule"], cfg["lag_minutes"]))
    return sources
