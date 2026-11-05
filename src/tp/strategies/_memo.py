"""Small cache for indicator arrays that many sweep configurations share (same symbol, same indicator settings)."""

from __future__ import annotations

_CACHE: dict = {}


def memo(key: tuple, compute):
    if key not in _CACHE:
        if len(_CACHE) > 4000:
            _CACHE.clear()
        _CACHE[key] = compute()
    return _CACHE[key]


def frame_key(symbol: str, bars) -> tuple:
    return (symbol, len(bars), bars.index[0], bars.index[-1])
