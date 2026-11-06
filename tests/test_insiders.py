import pandas as pd
import pytest

from conftest import dbars
from tp import insiders
from tp.strategies import REGISTRY, InsiderBuys


# ---- parsing the SEC bulk tables ----------------------------------------------------------------------------------
def tables():
    sub = pd.DataFrame({
        "ACCESSION_NUMBER": ["a1", "a2", "a3", "a4"],
        "FILING_DATE": ["05-MAR-2024", "05-MAR-2024", "05-MAR-2024", "05-MAR-2024"],
        "DOCUMENT_TYPE": ["4", "4", "4/A", "3"],
        "ISSUERCIK": ["0000000100", "0000000100", "0000000100", "0000000100"],
    })
    owners = pd.DataFrame({
        "ACCESSION_NUMBER": ["a1", "a1", "a2", "a3", "a4"],
        "RPTOWNERCIK": ["0000000007", "0000000008", "0000000009", "0000000007", "0000000007"],
        "RPTOWNER_RELATIONSHIP": ["Officer", "TenPercentOwner", "Director,Officer", "Officer", "Officer"],
    })
    trans = pd.DataFrame({
        "ACCESSION_NUMBER": ["a1", "a2", "a2", "a2", "a3", "a4", "a1"],
        "NONDERIV_TRANS_SK": ["1", "2", "3", "4", "5", "6", "7"],
        "TRANS_DATE": ["04-MAR-2024"] * 7,
        "TRANS_CODE": ["P", "S", "A", "P", "P", "P", "P"],
        "TRANS_SHARES": ["100", "50", "10", "20", "5", "5", "0"],
        "TRANS_PRICEPERSHARE": ["10", "20", "1", "", "1", "1", "10"],
        "TRANS_ACQUIRED_DISP_CD": ["A", "D", "A", "A", "A", "A", "A"],
    })
    return sub, owners, trans


def test_parse_keeps_officer_and_director_purchases_and_sales_only():
    out = insiders.parse_quarter(*tables())
    # a1 keeps only its Officer owner (the 10% holder is dropped); a2's purchase has no price, its award (A) is not a trade;
    # amendments (4/A), Form 3 and zero-share rows are dropped.
    assert out[["trade_id", "owner_cik", "code", "value"]].to_dict("records") == [
        {"trade_id": "a1-1", "owner_cik": 7, "code": "P", "value": 1000.0},
        {"trade_id": "a2-2", "owner_cik": 9, "code": "S", "value": 1000.0},
    ]
    assert out["filing_date"].iloc[0] == pd.Timestamp("2024-03-05") and out["issuer_cik"].iloc[0] == 100


def test_parse_drops_trades_dated_after_filing_or_over_a_year_before():
    sub, owners, trans = tables()
    trans.loc[0, "TRANS_DATE"] = "06-MAR-2024"  # after the filing date
    trans.loc[1, "TRANS_DATE"] = "04-MAR-2022"  # two years before
    assert insiders.parse_quarter(sub, owners, trans).empty


# ---- routine / opportunistic ---------------------------------------------------------------------------------------
def row(owner, trade, filed=None, code="P", value=200_000.0, tid=None, issuer=100):
    trade = pd.Timestamp(trade)
    return {"trade_id": tid or f"{owner}-{trade:%Y%m%d}-{code}", "accession": "x", "filing_date": pd.Timestamp(filed or trade + pd.Timedelta(days=2)),
            "issuer_cik": issuer, "owner_cik": owner, "trade_date": trade, "code": code, "shares": 1.0, "price": value, "value": value}


def frame(*rows):
    return pd.DataFrame(rows)


def klass_of(trades, target_trade_date):
    out = insiders.classify_purchases(trades)
    return out.loc[out["trade_date"] == pd.Timestamp(target_trade_date), "klass"].iloc[0]


def test_same_month_in_each_of_three_prior_years_is_routine():
    t = frame(row(1, "2021-11-10"), row(1, "2022-11-12"), row(1, "2023-11-08"), row(1, "2024-11-11"))
    assert klass_of(t, "2024-11-11") == "routine"


def test_trading_every_year_but_another_month_is_opportunistic():
    t = frame(row(1, "2021-11-10"), row(1, "2022-11-12"), row(1, "2023-05-08", code="S"), row(1, "2024-11-11"))
    assert klass_of(t, "2024-11-11") == "opportunistic"  # a sale counts as trading, but not in November 2023


def test_a_missing_year_is_thin_and_first_purchase_is_thin():
    t = frame(row(1, "2021-11-10"), row(1, "2023-11-08"), row(1, "2024-11-11"))
    assert klass_of(t, "2024-11-11") == "thin"  # nothing in 2022
    assert klass_of(frame(row(2, "2024-11-11")), "2024-11-11") == "thin"


def test_classification_ignores_filings_made_after_the_purchase_was_reported():
    # the 2023 trade was only filed in 2025, so on the 2024 filing date it was unknown: the insider looks thin, not routine
    t = frame(row(1, "2021-11-10"), row(1, "2022-11-12"), row(1, "2023-11-08", filed="2025-01-15"), row(1, "2024-11-11"))
    assert klass_of(t, "2024-11-11") == "thin"


def test_other_insiders_history_does_not_count():
    t = frame(row(1, "2021-11-10"), row(1, "2022-11-12"), row(1, "2023-11-08"), row(2, "2024-11-11"))
    assert klass_of(t, "2024-11-11") == "thin"


# ---- events --------------------------------------------------------------------------------------------------------
def opp(owner, filed, value=200_000.0, tid=None):
    return {"trade_id": tid or f"{owner}-{filed}", "filing_date": pd.Timestamp(filed), "owner_cik": owner, "value": value, "klass": "opportunistic"}


def test_event_waits_for_enough_insiders_and_value_within_the_window():
    buys = pd.DataFrame([opp(1, "2024-03-01"), opp(2, "2024-03-08"), opp(3, "2024-04-20")])
    two = insiders.buy_events(buys, "opportunistic", 2, 100_000.0)
    assert two == [pd.Timestamp("2024-03-08")]  # the pair completes on the 8th; the lone 20 April buyer never joins them
    assert insiders.buy_events(buys, "opportunistic", 1, 100_000.0) == [pd.Timestamp("2024-03-01"), pd.Timestamp("2024-04-20")]
    assert insiders.buy_events(buys, "opportunistic", 2, 100_000.0, window_days=5) == []  # 7 days apart: outside a 5-day window


def test_value_threshold_and_joint_filings_counted_once():
    joint = pd.DataFrame([opp(1, "2024-03-01", 60_000.0, "t1"), opp(2, "2024-03-01", 60_000.0, "t1")])  # one trade, two owners
    assert insiders.buy_events(joint, "opportunistic", 1, 100_000.0) == []
    two_trades = pd.DataFrame([opp(1, "2024-03-01", 60_000.0, "t1"), opp(2, "2024-03-01", 60_000.0, "t2")])
    assert insiders.buy_events(two_trades, "opportunistic", 1, 100_000.0) == [pd.Timestamp("2024-03-01")]


def test_cooldown_and_class_filter():
    buys = pd.DataFrame([opp(1, "2024-03-01"), opp(2, "2024-03-20"), opp(3, "2024-05-10")])
    assert insiders.buy_events(buys, "opportunistic", 1, 1.0) == [pd.Timestamp("2024-03-01"), pd.Timestamp("2024-05-10")]
    buys.loc[:, "klass"] = ["routine", "thin", "opportunistic"]
    assert insiders.buy_events(buys, "opportunistic", 1, 1.0) == [pd.Timestamp("2024-05-10")]
    assert insiders.buy_events(buys, "opportunistic+thin", 1, 1.0) == [pd.Timestamp("2024-03-20"), pd.Timestamp("2024-05-10")]


# ---- the strategy --------------------------------------------------------------------------------------------------
@pytest.fixture
def one_company(tmp_path, monkeypatch):
    monkeypatch.setattr(insiders.config, "DATA_DIR", tmp_path)
    (tmp_path / "insider").mkdir()
    insiders._trades.cache_clear(), insiders._classified.cache_clear(), insiders._symbol_ciks.cache_clear()
    pd.DataFrame({"symbol": ["AAA"], "cik": [100]}).to_csv(insiders.symbol_map_path(), index=False)
    frame(row(1, "2024-03-18", filed="2024-03-19")).to_parquet(insiders.trades_path())  # Tue 19 Mar: first-time (thin) purchase


def test_signal_is_decided_at_the_filing_days_close_with_atr_stop(one_company):
    bars = dbars([(100, 102, 98, 100)] * 40, start="2024-02-01")  # constant range 4 -> ATR 4
    sigs = InsiderBuys(classes="opportunistic+thin").generate("AAA", bars)
    assert len(sigs) == 1
    s = sigs[0]
    assert s.side == "long" and s.entry_ref == 100.0 and s.stop == pytest.approx(92.0)  # 2 x ATR below
    assert s.target == pytest.approx(112.0)  # 1.5R
    assert s.ts == pd.Timestamp("2024-03-19 16:00", tz="America/New_York").tz_convert("UTC")  # close of the filing day
    assert InsiderBuys(classes="opportunistic").generate("AAA", bars) == []  # thin buyers are excluded by default
    assert InsiderBuys(classes="opportunistic+thin").generate("BBB", bars) == []  # not an SEC-mapped symbol


def test_registry_and_validation():
    assert REGISTRY["insider"] is InsiderBuys
    with pytest.raises(ValueError):
        InsiderBuys(classes="everyone")
