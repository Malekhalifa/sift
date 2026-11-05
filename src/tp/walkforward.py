"""Walk-forward selection over a parameter grid.

For each test year, pick the configuration with the best score on all EARLIER years only, then record how it
does in the test year. Stitching those test years gives an out-of-sample record that no parameter ever saw.
Score = mean R minus one standard error, so a configuration with few trades cannot win on luck.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from tp.bars import ET


@dataclass(frozen=True)
class Fold:
    test_year: int
    config_id: str | None
    train_score: float
    train_n: int
    oos_n: int
    oos_expectancy_R: float


def with_year(raw: pd.DataFrame) -> pd.DataFrame:
    out = raw.copy()
    out["year"] = out["entry_ts"].dt.tz_convert(ET).dt.year if len(out) else pd.Series(dtype="int64")
    return out


def score(r: pd.Series, min_trades: int) -> float:
    n = len(r)
    if n < min_trades:
        return -math.inf
    return float(r.mean() - r.std(ddof=1) / math.sqrt(n))


def walk_forward(raws: dict[str, pd.DataFrame], test_years: list[int], min_trades: int) -> list[Fold]:
    """raws: config id -> every simulated trade over the whole dev period (needs `year` and `pnl_R`)."""
    folds = []
    for year in test_years:
        scores = {cid: score(df.loc[df["year"] < year, "pnl_R"], min_trades) for cid, df in raws.items()}
        best = max(scores.values())
        if not math.isfinite(best):
            folds.append(Fold(year, None, float("nan"), 0, 0, float("nan")))
            continue
        cid = sorted(c for c, s in scores.items() if s == best)[0]  # deterministic tie-break
        df = raws[cid]
        oos = df.loc[df["year"] == year, "pnl_R"]
        folds.append(Fold(year, cid, best, int((df["year"] < year).sum()), len(oos), float(oos.mean()) if len(oos) else float("nan")))
    return folds


def stitch(raws: dict[str, pd.DataFrame], folds: list[Fold]) -> pd.DataFrame:
    """The out-of-sample trades: each test year taken from the configuration chosen for it."""
    parts = []
    for f in folds:
        if f.config_id is None:
            continue
        df = raws[f.config_id]
        part = df[df["year"] == f.test_year].copy()
        part["config_id"] = f.config_id
        parts.append(part)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def grid_diagnostics(raws: dict[str, pd.DataFrame], test_years: list[int]) -> pd.DataFrame:
    """Per-configuration out-of-sample picture over the test years. Diagnostic only: never used to select."""
    rows = []
    for cid, df in raws.items():
        oos = df[df["year"].isin(test_years)]
        by_year = oos.groupby("year")["pnl_R"].mean()
        n = len(oos)
        rows.append(
            {
                "config_id": cid,
                "oos_n": n,
                "oos_expectancy_R": float(oos["pnl_R"].mean()) if n else float("nan"),
                "oos_se_R": float(oos["pnl_R"].std(ddof=1) / math.sqrt(n)) if n > 1 else float("nan"),
                "positive_years": int((by_year > 0).sum()),
                "years_traded": int(len(by_year)),
            }
        )
    return pd.DataFrame(rows).set_index("config_id")


def neighbors(cid: str, params_by_id: dict[str, dict], grid_keys: list[str], joint_axes: tuple[tuple[str, ...], ...] = ()) -> list[str]:
    """Configurations that differ from `cid` along exactly one axis. Each grid key is its own axis unless listed
    together in `joint_axes` (e.g. stop_mode and atr_mult form a single "stop" axis)."""
    axis_of = {k: k for k in grid_keys}
    for group in joint_axes:
        for k in group:
            axis_of[k] = group[0]
    base = params_by_id[cid]
    out = []
    for other, p in params_by_id.items():
        if other != cid and len({axis_of[k] for k in grid_keys if p.get(k) != base.get(k)}) == 1:
            out.append(other)
    return out


def neighbor_stability(
    cid: str,
    params_by_id: dict[str, dict],
    grid_keys: list[str],
    diag: pd.DataFrame,
    joint_axes: tuple[tuple[str, ...], ...] = (),
) -> dict:
    nb = neighbors(cid, params_by_id, grid_keys, joint_axes)
    if not nb:
        return {"n_neighbors": 0, "share_positive": float("nan")}
    exp = diag.loc[nb, "oos_expectancy_R"]
    return {"n_neighbors": len(nb), "share_positive": float(np.mean(exp > 0))}
