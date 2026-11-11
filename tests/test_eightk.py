import pandas as pd

from tp import eightk
from tp.edgar import parse_eightk


def _filings(rows):
    return pd.DataFrame([{"symbol": s, "accession": f"a{i}", "filed_at": pd.Timestamp(t, tz="UTC"), "items": it} for i, (s, t, it) in enumerate(rows)])


LO, HI = pd.Timestamp("2016-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")


def test_parse_eightk_keeps_only_8k_with_items():
    page = {"form": ["8-K", "10-Q", "8-K/A", "8-K"], "items": ["1.02, 9.01", "", "2.05", "8.01"],
            "acceptanceDateTime": ["2020-01-02T21:30:00.000Z"] * 4, "accessionNumber": ["a", "b", "c", "d"]}
    out = parse_eightk([{"filings": {"recent": page}}])
    assert out["accession"].tolist() == ["a", "d"] and out["items"].tolist() == ["1.02,9.01", "8.01"]


def test_bad_news_selects_codes_drops_earnings_days_and_holdout():
    f = _filings([("A", "2020-03-02T21:00:00Z", "1.02,9.01"), ("A", "2020-06-01T21:00:00Z", "2.02,2.06"),
                  ("A", "2020-07-01T21:00:00Z", "5.02"), ("A", "2025-02-01T21:00:00Z", "1.02")])
    ev = eightk.bad_news_events(f, LO, HI)
    assert ev["items"].tolist() == ["1.02"] and len(ev) == 1


def test_bad_news_dedupes_within_five_days_per_symbol():
    f = _filings([("A", "2020-03-02T21:00:00Z", "1.02"), ("A", "2020-03-05T21:00:00Z", "2.05"),
                  ("B", "2020-03-03T21:00:00Z", "2.05"), ("A", "2020-03-09T21:00:00Z", "2.06")])
    ev = eightk.bad_news_events(f, LO, HI)
    assert ev.groupby("symbol").size().to_dict() == {"A": 2, "B": 1}
