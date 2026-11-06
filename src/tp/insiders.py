"""Insider trades from SEC Form 4: parsing the quarterly bulk files, telling routine from opportunistic insiders, and
turning purchases into events (see docs/m10-insider-protocol.md).

The bulk files carry the filing date but no clock time, so every event is known as of its filing date and is traded at
the next session's open. The routine/opportunistic split follows Cohen, Malloy and Pomorski (2012): an insider is
*routine* if they traded in the same calendar month in each of the three previous years, *opportunistic* if they traded
in each of those years but not that month, and *thin* if a year had no trade at all (too little history to tell).
Classification only looks at filings made before the purchase being classified.
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd

from tp import config

CLASS_SETS = {"opportunistic": {"opportunistic"}, "opportunistic+thin": {"opportunistic", "thin"}}
TRADE_COLUMNS = ["trade_id", "accession", "filing_date", "issuer_cik", "owner_cik", "trade_date", "code", "shares", "price", "value"]
MAX_REPORT_LAG = pd.Timedelta(days=365)  # a trade dated more than a year before its filing is almost surely a typo


def trades_path():
    return config.DATA_DIR / "insider" / "trades.parquet"


def symbol_map_path():
    return config.DATA_DIR / "insider" / "symbol_cik.csv"


def parse_quarter(submission: pd.DataFrame, owners: pd.DataFrame, trans: pd.DataFrame) -> pd.DataFrame:
    """One quarter's open-market trades (code P bought, S sold) by officers and directors, original Form 4 only.

    One row per trade per reporting owner (joint filings repeat the trade, so `trade_id` identifies the trade itself).
    """
    sub = submission[submission["DOCUMENT_TYPE"] == "4"][["ACCESSION_NUMBER", "FILING_DATE", "ISSUERCIK"]]
    rel = owners["RPTOWNER_RELATIONSHIP"].fillna("")
    own = owners[rel.str.contains("Officer|Director")][["ACCESSION_NUMBER", "RPTOWNERCIK"]].drop_duplicates()
    tr = trans[
        ((trans["TRANS_CODE"] == "P") & (trans["TRANS_ACQUIRED_DISP_CD"] == "A"))
        | ((trans["TRANS_CODE"] == "S") & (trans["TRANS_ACQUIRED_DISP_CD"] == "D"))
    ].copy()
    tr["shares"] = pd.to_numeric(tr["TRANS_SHARES"], errors="coerce")
    tr["price"] = pd.to_numeric(tr["TRANS_PRICEPERSHARE"], errors="coerce")
    tr = tr[(tr["shares"] > 0) & (tr["price"] > 0)]
    out = tr.merge(sub, on="ACCESSION_NUMBER").merge(own, on="ACCESSION_NUMBER")
    out["trade_id"] = out["ACCESSION_NUMBER"] + "-" + out["NONDERIV_TRANS_SK"].astype(str)
    out["filing_date"] = pd.to_datetime(out["FILING_DATE"], format="%d-%b-%Y", errors="coerce")
    out["trade_date"] = pd.to_datetime(out["TRANS_DATE"], format="%d-%b-%Y", errors="coerce")
    out["issuer_cik"] = pd.to_numeric(out["ISSUERCIK"], errors="coerce")
    out["owner_cik"] = pd.to_numeric(out["RPTOWNERCIK"], errors="coerce")
    out = out.rename(columns={"ACCESSION_NUMBER": "accession", "TRANS_CODE": "code"})
    out["value"] = out["shares"] * out["price"]
    out = out.dropna(subset=["filing_date", "trade_date", "issuer_cik", "owner_cik"])
    lag = out["filing_date"] - out["trade_date"]
    out = out[(lag >= pd.Timedelta(0)) & (lag <= MAX_REPORT_LAG)]
    out = out.astype({"issuer_cik": "int64", "owner_cik": "int64"})
    return out[TRADE_COLUMNS].drop_duplicates(["trade_id", "owner_cik"]).reset_index(drop=True)


def classify_purchases(trades: pd.DataFrame) -> pd.DataFrame:
    """The purchases among one issuer's trades, with a `klass` column: routine, opportunistic or thin."""
    buys = trades[trades["code"] == "P"]
    by_owner = {k: g for k, g in trades.groupby("owner_cik")}
    klass = []
    for row in buys.itertuples():
        past = by_owner[row.owner_cik]
        past = past[past["filing_date"] < row.filing_date]
        years, months = past["trade_date"].dt.year.to_numpy(), past["trade_date"].dt.month.to_numpy()
        y, m = row.trade_date.year, row.trade_date.month
        every_year = all((years == y - k).any() for k in (1, 2, 3))
        same_month = all(((years == y - k) & (months == m)).any() for k in (1, 2, 3))
        klass.append("routine" if same_month else "opportunistic" if every_year else "thin")
    return buys.assign(klass=klass)


def buy_events(buys: pd.DataFrame, classes: str | set[str], min_insiders: int, min_value: float,
               window_days: int = 10, cooldown_days: int = 30) -> list[pd.Timestamp]:
    """Filing dates on which a cluster of qualifying purchases is complete.

    `buys` is classify_purchases() output; `classes` is a CLASS_SETS key or an explicit set of class names. A day fires
    when the qualifying purchases filed in the last `window_days` calendar days (this day included) come from at least
    `min_insiders` distinct insiders and total at least `min_value` dollars; after a firing the issuer is quiet for
    `cooldown_days`. Uses only filings up to that day.
    """
    keep = buys[buys["klass"].isin(CLASS_SETS[classes] if isinstance(classes, str) else classes)]
    if keep.empty:
        return []
    fired: list[pd.Timestamp] = []
    for day in sorted(keep["filing_date"].unique()):
        day = pd.Timestamp(day)
        if fired and (day - fired[-1]).days <= cooldown_days:
            continue
        window = keep[(keep["filing_date"] <= day) & (keep["filing_date"] > day - pd.Timedelta(days=window_days))]
        if window["owner_cik"].nunique() >= min_insiders and window.drop_duplicates("trade_id")["value"].sum() >= min_value:
            fired.append(day)
    return fired


@lru_cache(maxsize=4)
def _trades(path_str: str, mtime: float) -> pd.DataFrame:
    return pd.read_parquet(path_str)


@lru_cache(maxsize=1024)
def _classified(cik: int, mtime: float) -> pd.DataFrame:
    df = _trades(str(trades_path()), mtime)
    return classify_purchases(df[df["issuer_cik"] == cik])


def classified_purchases(cik: int) -> pd.DataFrame:
    """Classified purchases for one issuer (empty if there are none or the table is missing)."""
    path = trades_path()
    if not path.exists():
        return pd.DataFrame(columns=[*TRADE_COLUMNS, "klass"])
    return _classified(int(cik), path.stat().st_mtime)


@lru_cache(maxsize=4)
def _symbol_ciks(path_str: str, mtime: float) -> dict[str, int]:
    df = pd.read_csv(path_str)
    return dict(zip(df["symbol"], df["cik"].astype(int), strict=True))


def symbol_ciks() -> dict[str, int]:
    """Universe symbol -> SEC company ID, one symbol per company (written by scripts/fetch_insider.py), in universe order."""
    path = symbol_map_path()
    if not path.exists():
        raise SystemExit(f"{path} is missing; run scripts/fetch_insider.py first.")
    return _symbol_ciks(str(path), path.stat().st_mtime)
