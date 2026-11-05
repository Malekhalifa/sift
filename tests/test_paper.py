import pandas as pd
import pytest

from conftest import et, sess
from tp.alpaca_data import AlpacaError
from tp.backtest import Signal
from tp.paper import decide
from tp.paper.db import PaperDB
from tp.paper.decide import PaperConfig, Snapshot
from tp.paper.livedata import LiveData
from tp.paper.runner import PaperRunner
from tp.strategies import OpeningRangeBreakout

TODAY = "2024-03-14"  # a Thursday, daylight time
OR_BAR, INSIDE, BREAK = (100.0, 101.0, 99.0, 100.5), (100.5, 100.9, 99.2, 100.4), (100.4, 102.0, 100.3, 101.5)


def sig(symbol="AAA", side="long", ts="09:45", entry=101.5, stop=99.0, rr=1.5):
    return Signal.bracket(symbol, et(TODAY, ts), side, entry, stop, rr)


def snap(**kw):
    base = dict(equity=100_000.0, last_equity=100_000.0, open_symbols=frozenset(), open_notional=0.0, trades_today=0)
    return Snapshot(**{**base, **kw})


CFG = PaperConfig(symbols=["AAA"], dry_run=False, risk_per_trade=0.01, max_leverage=2.0, max_positions=2, max_trades_per_day=3)


# ---- pure decisions -------------------------------------------------------------------------------------------
def test_decision_time_floors_to_the_last_closed_bar():
    assert decide.decision_time(et(TODAY, "09:47") + pd.Timedelta(seconds=30)) == et(TODAY, "09:45")
    assert decide.decision_time(et(TODAY, "09:45")) == et(TODAY, "09:45")


def test_only_the_bar_that_just_closed_counts():
    old, new = sig(ts="09:40"), sig(ts="09:45")
    assert decide.signals_at([old, new], et(TODAY, "09:45")) == [new]


@pytest.mark.parametrize("kw,reason", [
    (dict(kill_switch=True), "kill_switch"),
    (dict(equity=98_900.0), "daily_loss_cap"),
    (dict(recent_split=frozenset({"AAA"})), "recent_split"),
    (dict(open_symbols=frozenset({"AAA"})), "symbol_busy"),
    (dict(open_symbols=frozenset({"X", "Y"})), "max_positions"),
    (dict(trades_today=3), "max_trades_per_day"),
])
def test_block_reasons(kw, reason):
    assert decide.block_reason(sig(), snap(**kw), CFG) == reason


def test_nothing_blocks_a_clean_signal_and_flat_time_does():
    assert decide.block_reason(sig(), snap(), CFG) is None
    assert decide.block_reason(sig(ts="15:50"), snap(), CFG) == "too_close_to_flat_time"
    assert decide.block_reason(sig(ts="15:40"), snap(), CFG) is None


def test_position_size_risks_a_fraction_and_respects_leverage():
    s = sig()  # risk 2.5 per share, entry 101.5
    assert decide.position_size(s, snap(), CFG) == (400, None)  # 1% of 100k / 2.5
    assert decide.position_size(s, snap(open_notional=150_000.0), CFG) == (400, None)  # 50k headroom fits 492, risk binds
    assert decide.position_size(s, snap(open_notional=190_000.0), CFG) == (98, None)  # 10k headroom / 101.5
    assert decide.position_size(s, snap(open_notional=200_000.0), CFG) == (0, "leverage_cap")  # no headroom left
    tiny = PaperConfig(risk_per_trade=0.00001, max_leverage=2.0)
    assert decide.position_size(s, snap(), tiny) == (0, "qty_below_1")


def test_order_payload_is_a_bracket_with_deterministic_id():
    s = sig(side="short", entry=100.0, stop=101.0)
    coid = decide.client_order_id(CFG, s)
    assert coid == decide.client_order_id(CFG, s) and coid.startswith("plumbing-AAA-0314")
    p = decide.order_payload(s, 10, coid)
    assert p["side"] == "sell" and p["order_class"] == "bracket" and p["type"] == "market" and p["qty"] == "10"
    assert p["take_profit"] == {"limit_price": "98.50"} and p["stop_loss"] == {"stop_price": "101.00"}
    assert decide.order_payload(sig(), 5, "x")["side"] == "buy"


def test_config_file_loads():
    from tp import config

    cfg = decide.load_config(config.ROOT / "config" / "paper" / "plumbing.toml")
    assert cfg.dry_run is True and cfg.evidence is False and cfg.params["or_minutes"] == 5 and "AAPL" in cfg.symbols


# ---- the live path against fakes ---------------------------------------------------------------------------
def api_rows(frame):
    return [{"t": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "o": r.open, "h": r.high, "l": r.low, "c": r.close, "v": 1000, "n": 5, "vw": r.close}
            for ts, r in frame.iterrows()]


class FakeClient:
    def __init__(self, today_rows):
        self.today_rows, self.submitted, self.cancelled, self.closed = today_rows, [], [], []
        self.open_orders, self.pos, self.fail_submit = [], [], False
        self.all_orders = []

    def multi_bars(self, symbols, tf, start, end, feed="iex", adjustment="raw"):
        for sym in symbols:
            for row in self.today_rows.get(sym, []):
                yield sym, row

    def account(self):
        return {"status": "ACTIVE", "equity": "100000", "last_equity": "100000", "trading_blocked": False}

    def positions(self):
        return self.pos

    def orders(self, status="open", after=None, limit=500, symbols=None, nested=True):
        return self.all_orders if status == "all" else self.open_orders

    def submit_order(self, body):
        if self.fail_submit:
            raise AlpacaError(422, "bad bracket")
        self.submitted.append(body)
        return {"id": f"id-{len(self.submitted)}", "status": "accepted"}

    def cancel_order(self, oid):
        self.cancelled.append(oid)

    def close_position(self, sym):
        self.closed.append(sym)


def build(tmp_path, cfg=CFG, today=None, history_days=12):
    days = pd.bdate_range("2024-02-26", periods=history_days)
    history = pd.concat([sess([OR_BAR, INSIDE, INSIDE], day=d.strftime("%Y-%m-%d")) for d in days])
    today = today if today is not None else sess([OR_BAR, INSIDE, BREAK], day=TODAY)
    client = FakeClient({"AAA": api_rows(today)})
    data = LiveData(client, cfg)
    data.history = {"AAA": history}
    data.daily = {}
    runner = PaperRunner(cfg, client, data, PaperDB(str(tmp_path / "paper.sqlite")), kill_path=tmp_path / "KILL")
    return runner, client


NOW = et(TODAY, "09:45") + pd.Timedelta(seconds=10)


def test_cycle_in_live_mode_submits_one_bracket_and_logs_it(tmp_path):
    runner, client = build(tmp_path)
    out = runner.cycle(NOW)
    assert out["signals"] == 1 and out["orders"] == 1 and out["blocked"] == {}
    (body,) = client.submitted
    assert body["symbol"] == "AAA" and body["side"] == "buy" and body["order_class"] == "bracket"
    assert body["stop_loss"]["stop_price"] == "99.00" and body["take_profit"]["limit_price"] == "105.25"
    (sig_row,) = runner.db.rows("SELECT decision, qty, evidence FROM signals")
    assert sig_row == ("submitted", 400, 0)  # evidence flag stays 0: this is a machinery test
    assert runner.db.has_order(body["client_order_id"])


def test_a_second_pass_over_the_same_bar_cannot_duplicate_the_order(tmp_path):
    runner, client = build(tmp_path)
    runner.cycle(NOW)
    again = runner.cycle(NOW)
    assert len(client.submitted) == 1 and again["blocked"] == {"duplicate_signal": 1}


def test_dry_run_sends_nothing_but_logs_the_would_be_order(tmp_path):
    from dataclasses import replace

    runner, client = build(tmp_path, cfg=replace(CFG, dry_run=True))
    out = runner.cycle(NOW)
    assert out["orders"] == 1 and client.submitted == []
    assert runner.db.rows("SELECT decision FROM signals") == [("dry_run",)]
    assert any("DRY RUN would submit" in m for (m,) in runner.db.rows("SELECT message FROM events"))


def test_kill_file_blocks_entries(tmp_path):
    runner, client = build(tmp_path)
    (tmp_path / "KILL").write_text("stop")
    out = runner.cycle(NOW)
    assert client.submitted == [] and out["blocked"] == {"kill_switch": 1}


def test_a_rejected_order_is_recorded_not_raised(tmp_path):
    runner, client = build(tmp_path)
    client.fail_submit = True
    out = runner.cycle(NOW)
    assert out["blocked"] == {"rejected": 1} and runner.db.rows("SELECT decision FROM signals") == [("rejected",)]


def test_no_signal_on_a_quiet_bar(tmp_path):
    runner, client = build(tmp_path, today=sess([OR_BAR, INSIDE, INSIDE], day=TODAY))
    assert runner.cycle(NOW)["signals"] == 0 and client.submitted == []


def test_cycle_sees_only_bars_that_have_closed(tmp_path):
    # the live API would not return the bar that is still forming; an earlier decision must not trade a later bar
    runner, client = build(tmp_path)
    early = et(TODAY, "09:40") + pd.Timedelta(seconds=10)  # the breakout bar (09:40) is still open
    client.today_rows = {"AAA": api_rows(sess([OR_BAR, INSIDE], day=TODAY))}
    assert runner.cycle(early)["signals"] == 0


def test_live_signals_match_the_backtest_at_every_decision_time():
    """Truncating the bars at each decision time must reproduce the full-day backtest signals exactly."""
    days = pd.bdate_range("2024-02-26", periods=12)
    frame = pd.concat([sess([OR_BAR, INSIDE, INSIDE, INSIDE, BREAK, INSIDE], day=d.strftime("%Y-%m-%d")) for d in days]
                      + [sess([OR_BAR, INSIDE, BREAK, INSIDE], day=TODAY)])
    strat = OpeningRangeBreakout()
    full = strat.generate("AAA", frame)
    live = []
    for boundary in pd.date_range(et(TODAY, "09:35"), et(TODAY, "09:55"), freq="5min"):
        seen = frame[frame.index <= boundary - pd.Timedelta(minutes=5)]  # bars whose close is <= the decision time
        live += decide.signals_at(strat.generate("AAA", seen), boundary)
    expected = [s for s in full if s.ts.tz_convert("America/New_York").date().isoformat() == TODAY]
    assert [(s.ts, s.side, s.entry_ref, s.stop, s.target) for s in live] == [(s.ts, s.side, s.entry_ref, s.stop, s.target) for s in expected]
    assert len(expected) == 1


# ---- end of day --------------------------------------------------------------------------------------------------
def test_flatten_cancels_then_closes_only_our_symbols(tmp_path):
    runner, client = build(tmp_path)
    client.open_orders = [{"id": "o1", "symbol": "AAA"}, {"id": "o2", "symbol": "AAA"}]
    client.pos = [{"symbol": "AAA"}, {"symbol": "OTHER"}]
    import tp.paper.runner as r

    r._time.sleep = lambda s: None
    runner.flatten("flat_time")
    assert client.cancelled == ["o1", "o2"] and client.closed == ["AAA"] and runner.flattened


def test_flatten_in_dry_run_touches_nothing(tmp_path):
    from dataclasses import replace

    runner, client = build(tmp_path, cfg=replace(CFG, dry_run=True))
    client.pos, client.open_orders = [{"symbol": "AAA"}], [{"id": "o1", "symbol": "AAA"}]
    runner.flatten("flat_time")
    assert client.cancelled == [] and client.closed == []


def test_reconcile_records_bracket_exits_and_flat_closes(tmp_path):
    runner, client = build(tmp_path)
    runner.cycle(NOW)
    coid = client.submitted[0]["client_order_id"]
    client.all_orders = [{
        "client_order_id": coid, "symbol": "AAA", "side": "buy", "status": "filled", "filled_qty": "400",
        "filled_avg_price": "101.52", "filled_at": "2024-03-14T13:45:01Z",
        "legs": [{"type": "limit", "status": "filled", "filled_avg_price": "105.25", "filled_at": "2024-03-14T14:20:00Z"},
                 {"type": "stop", "status": "canceled"}],
    }]
    runner.reconcile(NOW)
    row = runner.db.rows("SELECT status, filled_avg_price, exit_kind, exit_price FROM orders WHERE client_order_id = ?", (coid,))[0]
    assert row == ("filled", 101.52, "target", 105.25)

    client.all_orders = [
        {"client_order_id": coid, "symbol": "AAA", "side": "buy", "status": "filled", "filled_qty": "400", "filled_avg_price": "101.52",
         "filled_at": "2024-03-14T13:45:01Z", "legs": [{"type": "limit", "status": "canceled"}, {"type": "stop", "status": "canceled"}]},
        {"client_order_id": "x", "symbol": "AAA", "side": "sell", "status": "filled", "filled_avg_price": "100.80",
         "filled_at": "2024-03-14T19:55:02Z"},
    ]
    runner.reconcile(NOW)
    row = runner.db.rows("SELECT exit_kind, exit_price FROM orders WHERE client_order_id = ?", (coid,))[0]
    assert row == ("flat", 100.80)


def test_live_data_merges_history_and_today(tmp_path):
    runner, _ = build(tmp_path)
    runner.data.refresh_today(NOW)
    bars = runner.data.bars("AAA")
    assert bars.index.is_monotonic_increasing and bars.index.is_unique
    assert bars.index[-1] == et(TODAY, "09:40") and len(bars) == 12 * 3 + 3



def test_report_summarises_decisions_fills_and_slippage(tmp_path):
    import importlib.util

    from tp import config

    spec = importlib.util.spec_from_file_location("paper_report", config.ROOT / "scripts" / "paper_report.py")
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)

    runner, client = build(tmp_path)
    runner.cycle(NOW)
    coid = client.submitted[0]["client_order_id"]
    runner.db.order_update(coid, status="filled", filled_qty=400.0, filled_avg_price=101.53, exit_kind="target", exit_price=105.25)
    text = report.build_report(runner.db, None)
    assert "submitted" in text and "ORDERS (1)" in text
    assert "slip +0.030" in text and "target 105.25" in text and "+1.49R" in text  # (105.25-101.53)/2.5
    assert "mean entry slippage +0.030" in text and "machinery test" in text.lower()
