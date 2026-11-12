import numpy as np
import pandas as pd

from tp import issuance


def _rows(items):
    return pd.DataFrame([{"accn": a, "filed": pd.Timestamp(f), "end": pd.Timestamp(e), "val": v} for a, f, e, v in items])


def test_by_filing_sums_share_classes():
    f = issuance.by_filing(_rows([("a", "2020-02-01", "2020-01-25", 100), ("a", "2020-02-01", "2020-01-25", 50)]))
    assert f["val"].tolist() == [150]


def test_issuance_is_log_change_versus_a_year_earlier():
    f = issuance.by_filing(_rows([("a", "2019-02-01", "2019-01-25", 100), ("b", "2020-02-01", "2020-01-25", 110)]))
    out = issuance.issuance_by_filing(f, pd.DataFrame(columns=["ex_date", "ratio"]))
    assert np.isclose(out["issuance"].iloc[0], np.log(1.1))


def test_split_between_counts_is_not_issuance():
    f = issuance.by_filing(_rows([("a", "2019-02-01", "2019-01-25", 100), ("b", "2020-02-01", "2020-01-25", 200)]))
    splits = pd.DataFrame({"ex_date": [pd.Timestamp("2019-08-01")], "ratio": [2.0]})
    assert abs(issuance.issuance_by_filing(f, splits)["issuance"].iloc[0]) < 1e-12


def test_no_prior_year_filing_means_no_signal():
    f = issuance.by_filing(_rows([("a", "2020-02-01", "2020-01-25", 110)]))
    assert issuance.issuance_by_filing(f, pd.DataFrame(columns=["ex_date", "ratio"])).empty


def test_signal_uses_filings_strictly_before_the_date_and_expires():
    iss = pd.DataFrame({"filed": [pd.Timestamp("2020-02-03")], "issuance": [0.1]})
    days = pd.DatetimeIndex(["2020-02-03", "2020-02-04", "2020-06-10", "2020-06-20"])
    s = issuance.signal_at(iss, days)
    assert np.isnan(s.iloc[0]) and np.isclose(s.iloc[1], -0.1)
    assert np.isclose(s.iloc[2], -0.1) and np.isnan(s.iloc[3])  # 138 days after filing is stale
