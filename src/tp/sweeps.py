"""Parameter parsing and grid expansion shared by the CLI scripts."""

from __future__ import annotations

import itertools
import tomllib
from dataclasses import fields
from pathlib import Path


def coerce(default, raw: str):
    """Parse a command-line string into the type of the parameter's default. bool needs care: bool("False") is True."""
    if isinstance(default, bool):
        low = raw.strip().lower()
        if low in ("1", "true", "yes", "on"):
            return True
        if low in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"cannot read {raw!r} as a boolean")
    return type(default)(raw)


def param_defaults(params_cls) -> dict:
    return {f.name: f.default for f in fields(params_cls)}


def parse_sets(items: list[str], params_cls) -> dict:
    defaults = param_defaults(params_cls)
    out = {}
    for item in items:
        key, _, raw = item.partition("=")
        if key not in defaults:
            raise SystemExit(f"Unknown parameter {key!r}; choose from {sorted(defaults)}")
        try:
            out[key] = coerce(defaults[key], raw)
        except ValueError as e:
            raise SystemExit(f"--set {item}: {e}") from None
    return out


def expand_grid(strategy_cls, grid: dict[str, list]) -> list[dict]:
    """Cartesian product of the grid. Points that differ only in parameters that cannot matter are merged
    (strategy_cls.canonical), so the trial count is honest."""
    defaults = param_defaults(strategy_cls.params_cls)
    unknown = sorted(set(grid) - set(defaults))
    if unknown:
        raise ValueError(f"grid has unknown parameters {unknown}")
    keys = list(grid)
    seen, out = set(), []
    for values in itertools.product(*(grid[k] for k in keys)):
        for k, v in zip(keys, values, strict=True):
            if type(v) is not type(defaults[k]) and not (isinstance(defaults[k], float) and isinstance(v, int)):
                raise ValueError(f"grid value {k}={v!r} should be {type(defaults[k]).__name__}")
        params = strategy_cls.canonical(dict(zip(keys, values, strict=True)))
        key = tuple(sorted(params.items()))
        if key not in seen:
            seen.add(key)
            out.append(params)
    return out


def load_sweep_file(path: str | Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)
