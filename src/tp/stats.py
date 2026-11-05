"""Selection-bias statistics: Probabilistic and Deflated Sharpe Ratio (Bailey & Lopez de Prado).

Picking the best of N tried configurations inflates the best Sharpe even when none has an edge. The Deflated
Sharpe Ratio is the probability the observed Sharpe beats what the best of N *luckless* trials would show.
All Sharpe ratios here are per period (e.g. daily), not annualised.
"""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd

_N = NormalDist()
EULER_GAMMA = 0.5772156649015329


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """Expected best Sharpe among n_trials independent trials whose true Sharpe is zero."""
    if n_trials <= 1 or sr_variance <= 0:
        return 0.0
    return math.sqrt(sr_variance) * (
        (1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / n_trials) + EULER_GAMMA * _N.inv_cdf(1 - 1 / (n_trials * math.e))
    )


def probabilistic_sharpe(sr: float, sr_benchmark: float, n_obs: int, skew: float, kurt: float) -> float:
    """P(true Sharpe > sr_benchmark) given the estimate, sample size and return shape. kurt is raw (normal = 3)."""
    if n_obs < 2:
        return float("nan")
    denom_sq = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    if denom_sq <= 0:
        return float("nan")
    return _N.cdf((sr - sr_benchmark) * math.sqrt(n_obs - 1) / math.sqrt(denom_sq))


def sharpe(returns: pd.Series) -> float:
    sd = float(returns.std(ddof=1))
    return float(returns.mean()) / sd if sd > 0 else float("nan")


def deflated_sharpe(returns: pd.Series, n_trials: int, sr_variance: float) -> dict:
    """returns: per-period series of the selected strategy. sr_variance: variance of the per-period Sharpe
    across all n_trials configurations that were tried."""
    r = returns.dropna()
    sr0 = expected_max_sharpe(n_trials, sr_variance)
    sr = sharpe(r)
    skew, kurt = float(r.skew()), float(r.kurt()) + 3.0  # pandas reports excess kurtosis
    return {
        "sharpe_per_period": sr,
        "sharpe_annualised": sr * math.sqrt(252) if math.isfinite(sr) else float("nan"),
        "n_obs": len(r),
        "n_trials": n_trials,
        "benchmark_sharpe": sr0,
        "psr_vs_zero": probabilistic_sharpe(sr, 0.0, len(r), skew, kurt),
        "dsr": probabilistic_sharpe(sr, sr0, len(r), skew, kurt),
    }


def daily_r_series(raw: pd.DataFrame, sessions: list[pd.Timestamp]) -> pd.Series:
    """Sum of trade R per exit session, zero on days without exits. A sizing-free daily return stream."""
    if raw.empty:
        return pd.Series(0.0, index=pd.DatetimeIndex(sessions))
    day = raw["exit_ts"].dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    return raw.groupby(day)["pnl_R"].sum().reindex(sessions, fill_value=0.0)


def across_trials_sharpe_variance(series: list[pd.Series]) -> float:
    srs = [sharpe(s) for s in series]
    srs = [x for x in srs if math.isfinite(x)]
    return float(np.var(srs, ddof=1)) if len(srs) > 1 else 0.0
