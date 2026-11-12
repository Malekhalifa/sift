"""Registry of the recorder's sources; each source task appends its class to build_sources."""
from __future__ import annotations

from tp.collect.source import Source


def build_sources(settings: dict) -> list[Source]:
    return []
