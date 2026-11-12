"""M17: net share issuance from SEC cover-page share counts (docs/m17-issuance-protocol.md)."""

from __future__ import annotations

import numpy as np
import pandas as pd

STALE_DAYS = 135
PRIOR_MIN_DAYS, PRIOR_MAX_DAYS, PRIOR_TARGET_DAYS = 330, 400, 365


def by_filing(rows: pd.DataFrame) -> pd.DataFrame:
    """One row per filing (accn): filed date, count date `end`, and the share count summed over share classes."""
    g = rows.groupby("accn").agg(filed=("filed", "max"), end=("end", "max"), val=("val", "sum")).reset_index()
    return g[g["val"] > 0].sort_values(["filed", "end"]).reset_index(drop=True)


def issuance_by_filing(filings: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    """For each filing: log change in shares versus the filing ~365 days earlier, the older count first multiplied by
    every split ratio with an ex-date after the older count date and up to this one. Columns filed, issuance."""
    out = []
    ends = filings["end"].to_numpy()
    for f in filings.itertuples():
        gap = (f.end - filings["end"]).dt.days.to_numpy()
        ok = np.flatnonzero((gap >= PRIOR_MIN_DAYS) & (gap <= PRIOR_MAX_DAYS))
        if ok.size == 0:
            continue
        p = filings.iloc[ok[np.argmin(np.abs(gap[ok] - PRIOR_TARGET_DAYS))]]
        between = splits[(splits["ex_date"] > p.end) & (splits["ex_date"] <= f.end)]
        prior = p.val * float(between["ratio"].prod()) if len(between) else p.val
        out.append({"filed": f.filed, "issuance": float(np.log(f.val / prior))})
    return pd.DataFrame(out, columns=["filed", "issuance"])


def latest_known(values: pd.DataFrame, sessions: pd.DatetimeIndex, stale_days: int = STALE_DAYS) -> pd.Series:
    """For each session date: the `value` of the latest filing (column `filed`) filed strictly before that date and no
    more than `stale_days` earlier. NaN where none."""
    if values.empty:
        return pd.Series(np.nan, index=sessions)
    vals = values.assign(filed=values["filed"].astype("datetime64[ns]")).sort_values("filed").drop_duplicates("filed", keep="last")
    left = pd.DataFrame({"date": pd.DatetimeIndex(sessions).astype("datetime64[ns]")})
    m = pd.merge_asof(left, vals, left_on="date", right_on="filed", direction="backward", allow_exact_matches=False)
    fresh = (m["date"] - m["filed"]).dt.days <= stale_days
    return pd.Series(np.where(fresh, m["value"], np.nan), index=sessions)


def signal_at(issuance: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.Series:
    """For each session date: minus the issuance of the latest filing filed strictly before that date and no more than
    STALE_DAYS earlier (highest = fewest new shares). NaN where none."""
    return latest_known(issuance.rename(columns={"issuance": "value"}).assign(value=lambda d: -d["value"]) if not issuance.empty else issuance, sessions)
