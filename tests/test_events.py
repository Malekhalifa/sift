import httpx
import numpy as np
import pandas as pd
import pytest

from conftest import dbars
from tp import edgar, events
from tp.strategies import EarningsDrift


def ts(day, hhmm, tz="America/New_York"):
    return pd.Timestamp(f"{day} {hhmm}", tz=tz).tz_convert("UTC")


# ---- EDGAR parsing and the client --------------------------------------------------------------------------------
RECENT = {
    "filings": {
        "recent": {
            "accessionNumber": ["a1", "a2", "a3", "a4"],
            "form": ["8-K", "8-K", "10-Q", "8-K/A"],
            "items": ["2.02,9.01", "5.02", "", "2.02"],
            "acceptanceDateTime": ["2024-02-01T21:30:23.000Z", "2024-02-10T14:00:00.000Z", "2024-02-02T12:00:00.000Z", "2024-02-03T13:00:00.000Z"],
        },
        "files": [{"name": "CIK0000000001-submissions-001.json"}],
    }
}
OLDER = {"accessionNumber": ["a0", "a1"], "form": ["8-K", "8-K"], "items": ["2.02", "2.02,9.01"],
         "acceptanceDateTime": ["2023-10-31T20:05:00.000Z", "2024-02-01T21:30:23.000Z"]}


def test_parse_keeps_only_earnings_8k_across_pages_and_dedupes():
    out = edgar.parse_earnings([RECENT, OLDER])
    assert out["accession"].tolist() == ["a0", "a1"]  # not the 5.02 8-K, the 10-Q or the amendment; a1 once
    assert str(out["filed_at"].dt.tz) == "UTC" and out["filed_at"].is_monotonic_increasing
    assert edgar.parse_earnings([{"filings": {"recent": {}}}]).empty


def test_client_caches_and_follows_extra_pages(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=RECENT if "CIK0000000001.json" in request.url.path else OLDER)

    client = edgar.EdgarClient(tmp_path, http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.earnings_filings(1)["accession"].tolist() == ["a0", "a1"]
    assert len(calls) == 2
    client.earnings_filings(1)
    assert len(calls) == 2  # second call served from the disk cache


def test_client_stops_on_rate_limit(tmp_path):
    client = edgar.EdgarClient(tmp_path, http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, text="Request Rate Threshold Exceeded"))))
    with pytest.raises(edgar.EdgarBlocked):
        client.earnings_filings(1)


# ---- which session reacts ------------------------------------------------------------------------------------------
SESSIONS = dbars([(100, 101, 99, 100)] * 12, start="2024-03-04").index  # Mon 4 Mar .. Tue 19 Mar


def react(*stamps):
    return events.reaction_positions(pd.Series([pd.Timestamp(s) for s in stamps]), SESSIONS)


def test_classification_by_eastern_time():
    f = pd.Series([ts("2024-03-05", "08:00"), ts("2024-03-05", "09:29"), ts("2024-03-05", "09:30"), ts("2024-03-05", "15:59"), ts("2024-03-05", "16:00")])
    assert events.classify(f).tolist() == ["pre", "pre", "intraday", "intraday", "post"]


def test_pre_market_release_reacts_the_same_day_and_after_close_the_next():
    out = react(ts("2024-03-06", "07:30"), ts("2024-03-12", "16:30"))
    assert out["pos"].tolist() == [2, 7]  # Wed 6 Mar is row 2; a Tue 12 Mar evening release reacts Wed 13 Mar, row 7
    assert out["klass"].tolist() == ["pre", "post"]


def test_friday_evening_and_weekend_releases_react_at_monday_open():
    assert react(ts("2024-03-08", "17:00"))["pos"].tolist() == [5]  # Friday after the close -> Monday 11 Mar
    assert react(ts("2024-03-09", "10:00"))["pos"].tolist() == [5]  # Saturday 10:00 is "intraday" by the clock, but no session was open
    assert react(ts("2024-03-10", "20:00"))["pos"].tolist() == [5]
    assert react(ts("2024-03-08", "17:00"), ts("2024-03-09", "10:00"), ts("2024-03-10", "20:00"))["pos"].tolist() == [5]  # one announcement


def test_intraday_release_is_excluded_as_ambiguous():
    assert react(ts("2024-03-06", "11:00")).empty


def test_duplicate_filings_of_one_announcement_collapse():
    out = react(ts("2024-03-06", "17:00"), ts("2024-03-07", "08:00"), ts("2024-03-12", "07:00"))
    assert out["pos"].tolist() == [3, 6]  # the Thursday filing is a repeat; the Tuesday one is 6 days later, a new event


def test_events_without_a_previous_session_or_a_reaction_session_are_dropped():
    assert react(ts("2024-03-03", "07:00"), ts("2024-03-04", "07:00")).empty  # row 0 has no previous close to compare with
    assert react(ts("2024-03-19", "17:00")).empty  # the reacting session is after the data ends


# ---- the strategy --------------------------------------------------------------------------------------------------
R = 30  # row of the reacting session


def flat_rows(n, level=100.0):
    return [(level, level + 0.5, level - 0.5, level)] * n


def make_bars(event_close=106.0, after=10):
    rows = flat_rows(R) + [(100.0, max(event_close, 100.0) + 0.5, min(event_close, 100.0) - 0.5, event_close)] + flat_rows(after, event_close)
    return dbars(rows, start="2024-01-02")


def spy_for(bars, event_move=0.0):
    c = np.full(len(bars), 100.0)
    c[R:] = 100.0 * (1 + event_move)
    return dbars(list(zip(c, c + 0.5, c - 0.5, c)), start="2024-01-02")


def set_events(monkeypatch, bars, kind="post"):
    day = (bars.index[R - 1] if kind == "post" else bars.index[R]).tz_convert("America/New_York").strftime("%Y-%m-%d")
    stamp = ts(day, "17:00" if kind == "post" else "07:30")
    monkeypatch.setattr(events, "load_earnings", lambda symbol: pd.DataFrame({"accession": ["x"], "filed_at": [stamp]}))


def gen(monkeypatch, bars=None, spy=None, kind="post", **params):
    bars = make_bars() if bars is None else bars
    set_events(monkeypatch, bars, kind)
    return EarningsDrift(**params).generate("AAA", bars, None, spy_for(bars) if spy is None else spy)


def test_drift_follows_and_fade_opposes_a_big_positive_reaction(monkeypatch):
    from tp import swing

    bars = make_bars()
    (s,) = gen(monkeypatch, bars, thr_atr=3.0)
    assert s.side == "long" and s.ts == swing.decision_ts(bars.index)[R] and s.entry_ref == 106.0 and s.hold_days == 10
    assert s.stop < s.entry_ref < s.target and s.target - s.entry_ref == pytest.approx(1.5 * s.risk)
    (f,) = gen(monkeypatch, bars, thr_atr=3.0, mode="fade")
    assert f.side == "short" and f.target < f.entry_ref < f.stop


def test_negative_reaction_and_side_filter(monkeypatch):
    bars = make_bars(event_close=94.0)
    assert gen(monkeypatch, bars, thr_atr=3.0)[0].side == "short"
    assert gen(monkeypatch, bars, thr_atr=3.0, sides="long") == []


def test_threshold_is_measured_in_pre_event_atrs(monkeypatch):
    # a 6% move on a stock whose normal daily range is about 1% is 6 ATRs, even though the event day's own range is wide
    assert len(gen(monkeypatch, thr_atr=5.5)) == 1
    assert gen(monkeypatch, thr_atr=6.5) == []


def test_the_market_move_is_subtracted(monkeypatch):
    bars = make_bars()
    assert gen(monkeypatch, bars, spy=spy_for(bars, 0.06), thr_atr=1.0) == []  # SPY rose the same 6%: no stock-specific news


def test_pre_market_release_uses_the_same_session_and_intraday_is_skipped(monkeypatch):
    assert len(gen(monkeypatch, kind="pre", thr_atr=3.0)) == 1
    bars = make_bars()
    stamp = ts(bars.index[R].tz_convert("America/New_York").strftime("%Y-%m-%d"), "11:00")
    monkeypatch.setattr(events, "load_earnings", lambda symbol: pd.DataFrame({"accession": ["x"], "filed_at": [stamp]}))
    assert EarningsDrift(thr_atr=3.0).generate("AAA", bars, None, spy_for(bars)) == []


def test_signal_never_depends_on_bars_after_the_decision(monkeypatch):
    calm = gen(monkeypatch, make_bars(after=10), thr_atr=3.0)
    wild_rows = flat_rows(R) + [(100.0, 106.5, 99.5, 106.0)] + [(106.0, 900.0, 1.0, 5.0)] * 10  # same event session, wild afterwards
    wild = gen(monkeypatch, dbars(wild_rows, start="2024-01-02"), thr_atr=3.0)
    assert [(x.ts, x.side, x.entry_ref, x.stop) for x in calm] == [(x.ts, x.side, x.entry_ref, x.stop) for x in wild]


def test_guards(monkeypatch):
    bars = make_bars()
    set_events(monkeypatch, bars)
    with pytest.raises(ValueError):
        EarningsDrift().generate("AAA", bars, None, None)
    with pytest.raises(ValueError):
        EarningsDrift(mode="bogus")
    monkeypatch.setattr(events, "load_earnings", lambda symbol: pd.DataFrame(columns=["accession", "filed_at"]))
    assert EarningsDrift().generate("AAA", bars, None, spy_for(bars)) == []


def test_market_excess_subtracts_what_the_index_paid_in_the_same_direction():
    from tp import metrics

    spy = dbars([(100, 100, 100, 100), (100, 100, 100, 100), (100, 100, 100, 102), (100, 100, 100, 102)], start="2024-03-04")
    sess = spy.index.tz_convert("America/New_York")
    raw = pd.DataFrame({
        "side": ["long", "short"],
        "entry_ts": [ts(sess[1].strftime("%Y-%m-%d"), "09:30")] * 2,
        "exit_ts": [ts(sess[2].strftime("%Y-%m-%d"), "16:00")] * 2,  # SPY rises 2% over the hold
        "entry_px": [100.0, 100.0], "risk_per_share": [2.0, 2.0], "pnl_R": [1.0, -1.0],
    })
    ex = metrics.market_excess_R(raw, spy)
    # holding SPY long for 2% on a $100, $2-risk position is +1.0R; the short side lost 1.0R to the same move
    assert ex.tolist() == pytest.approx([0.0, 0.0])
