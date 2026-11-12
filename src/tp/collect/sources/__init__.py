"""Registry of the recorder's sources; each source task appends its class to build_sources."""
from __future__ import annotations

from tp.collect.source import Source
from tp.collect.sources.alpaca_bars import AlpacaBars
from tp.collect.sources.finra import FinraShortInterest, FinraShortVolume
from tp.collect.sources.sec import SecFilings, SecForm4, SecXbrlShares


def source_settings(settings: dict, name: str) -> dict:
    """The `[sources.<name>]` table, or a clear exit when config/collect.toml lacks it."""
    table = settings.get("sources", {}).get(name)
    if table is None:
        raise SystemExit(f"config/collect.toml is missing [sources.{name}]")
    return table


def build_sources(settings: dict) -> list[Source]:
    sources: list[Source] = []
    cfg = source_settings(settings, "alpaca_bars")
    sources.append(AlpacaBars(cfg["schedule"], cfg["lag_minutes"]))
    cfg = source_settings(settings, "sec_filings")
    sources.append(SecFilings(cfg["schedule"], cfg["lag_minutes"]))
    cfg = source_settings(settings, "sec_form4")
    sources.append(SecForm4(cfg["schedule"], cfg["lag_minutes"]))
    cfg = source_settings(settings, "sec_xbrl_shares")
    sources.append(SecXbrlShares(cfg["schedule"], cfg["lag_minutes"]))
    cfg = source_settings(settings, "finra_shortvol")
    sources.append(FinraShortVolume(cfg["schedule"], cfg["lag_minutes"]))
    cfg = source_settings(settings, "finra_short_interest")
    sources.append(FinraShortInterest(cfg["schedule"], cfg["lag_minutes"]))
    return sources
