"""Registry of the recorder's sources; each source task appends its class to build_sources."""
from __future__ import annotations

from tp.collect.source import Source
from tp.collect.sources.alpaca_bars import AlpacaBars


def build_sources(settings: dict) -> list[Source]:
    sources: list[Source] = []
    cfg = settings["sources"]["alpaca_bars"]
    sources.append(AlpacaBars(cfg["schedule"], cfg["lag_minutes"]))
    return sources
