"""The paper-trading loop. One decision cycle per closed 5-minute bar, flat before the close.

Safety: orders only go to the Alpaca PAPER api; `dry_run` (the default) logs what would be sent and sends nothing;
a KILL file in the data directory stops entries and flattens; daily loss cap, position caps and a per-day trade
cap block entries; a restart cannot duplicate a signal because client order ids are deterministic.
"""

from __future__ import annotations

import time as _time
from datetime import UTC, datetime, timedelta

import pandas as pd

from tp import config
from tp.alpaca_data import AlpacaError, TradingClient
from tp.paper import decide
from tp.paper.db import PaperDB
from tp.paper.decide import PaperConfig, Snapshot
from tp.paper.livedata import LiveData
from tp.strategies import REGISTRY


class PaperRunner:
    def __init__(self, cfg: PaperConfig, client: TradingClient, data: LiveData, db: PaperDB, kill_path=None):
        self.cfg, self.client, self.data, self.db = cfg, client, data, db
        self.strategy = REGISTRY[cfg.strategy](**cfg.params)
        self.kill_path = kill_path or (config.DATA_DIR / "KILL")
        self.last_decided: pd.Timestamp | None = None
        self.flattened = False
        self.errors = 0

    # ---- state ---------------------------------------------------------------------------------------------
    def snapshot(self, now: pd.Timestamp) -> Snapshot:
        acct = self.client.account()
        positions = self.client.positions()
        working = [o for o in self.client.orders("open", nested=False) if o.get("order_class") != "bracket" or o.get("parent_order_id") is None]
        symbols = {p["symbol"] for p in positions} | {o["symbol"] for o in working}
        notional = sum(abs(float(p["market_value"])) for p in positions)
        return Snapshot(
            equity=float(acct["equity"]), last_equity=float(acct.get("last_equity") or acct["equity"]),
            open_symbols=frozenset(symbols), open_notional=notional,
            trades_today=self.db.trades_submitted_on(f"{now:%Y-%m-%d}"),
            kill_switch=self.kill_path.exists(), recent_split=self.data.recent_split,
        )

    # ---- one decision cycle ----------------------------------------------------------------------------------
    def cycle(self, now: pd.Timestamp) -> dict:
        """Decide on the bar that just closed. Returns a summary (also useful in tests)."""
        cfg, dts = self.cfg, decide.decision_time(now)
        summary = {"decision_ts": dts, "signals": 0, "orders": 0, "blocked": {}}
        self.data.refresh_today(now)
        snap = self.snapshot(now)
        for sym in self.data.history:
            bars = self.data.bars(sym)
            found = decide.signals_at(self.strategy.generate(sym, bars, self.data.daily.get(sym), self.data.spy_daily), dts)
            for sig in found:
                summary["signals"] += 1
                reason = decide.block_reason(sig, snap, cfg)
                qty = 0
                if reason is None:
                    qty, reason = decide.position_size(sig, snap, cfg)
                coid = decide.client_order_id(cfg, sig)
                if reason is None and self.db.has_order(coid):
                    reason = "duplicate_signal"
                params = self.strategy.params_dict()
                if reason is not None:
                    self.db.signal(sig, cfg.strategy, params, "blocked", reason, qty or None, coid, cfg.evidence)
                    summary["blocked"][reason] = summary["blocked"].get(reason, 0) + 1
                    continue
                if cfg.dry_run:
                    self.db.signal(sig, cfg.strategy, params, "dry_run", None, qty, coid, cfg.evidence)
                    self.db.event("INFO", f"DRY RUN would submit {sig.side} {qty} {sig.symbol}", payload=decide.order_payload(sig, qty, coid))
                else:
                    try:
                        order = self.client.submit_order(decide.order_payload(sig, qty, coid))
                    except AlpacaError as e:
                        self.db.signal(sig, cfg.strategy, params, "rejected", str(e)[:200], qty, coid, cfg.evidence)
                        summary["blocked"]["rejected"] = summary["blocked"].get("rejected", 0) + 1
                        continue
                    self.db.order_submitted(coid, order, sig, qty, cfg.evidence)
                    self.db.signal(sig, cfg.strategy, params, "submitted", None, qty, coid, cfg.evidence)
                summary["orders"] += 1
                snap = Snapshot(**{**snap.__dict__, "open_symbols": snap.open_symbols | {sig.symbol},
                                   "open_notional": snap.open_notional + qty * sig.entry_ref, "trades_today": snap.trades_today + 1})
        self.db.event("INFO", "cycle", **{k: (str(v) if k == "decision_ts" else v) for k, v in summary.items()})
        return summary

    # ---- end of day ------------------------------------------------------------------------------------------
    def flatten(self, reason: str) -> None:
        """Cancel working orders and close positions in our symbols."""
        self.flattened = True
        if self.cfg.dry_run:
            self.db.event("INFO", f"DRY RUN would flatten ({reason})")
            return
        for o in self.client.orders("open", symbols=self.cfg.symbols, nested=False):
            try:
                self.client.cancel_order(o["id"])
            except AlpacaError as e:
                self.db.event("WARN", f"cancel failed {o['symbol']}: {e}")
        _time.sleep(2)  # let the cancels release held shares before closing
        for p in self.client.positions():
            if p["symbol"] in self.cfg.symbols:
                try:
                    self.client.close_position(p["symbol"])
                except AlpacaError as e:
                    self.db.event("ERROR", f"close failed {p['symbol']}: {e}")
        self.db.event("INFO", f"flattened ({reason})")

    def reconcile(self, now: pd.Timestamp) -> None:
        """Copy fills from Alpaca into the database."""
        after = now.tz_convert("America/New_York").normalize().tz_convert(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        orders = self.client.orders("all", after=after, nested=True)
        for o in orders:
            coid = o.get("client_order_id", "")
            if not coid.startswith(self.cfg.tag) or not self.db.has_order(coid):
                continue
            fields = {"status": o.get("status"), "filled_qty": float(o.get("filled_qty") or 0),
                      "filled_avg_price": float(o["filled_avg_price"]) if o.get("filled_avg_price") else None}
            for leg in o.get("legs") or []:
                if leg.get("status") == "filled":
                    fields.update(exit_kind="target" if leg.get("type") == "limit" else "stop",
                                  exit_price=float(leg["filled_avg_price"]), exit_at=leg.get("filled_at"))
            if fields["filled_qty"] and "exit_kind" not in fields:  # closed by our flatten, not by a bracket leg
                closer = [x for x in orders if x["symbol"] == o["symbol"] and x["side"] != o["side"] and not x.get("parent_order_id")
                          and x.get("status") == "filled" and (x.get("filled_at") or "") > (o.get("filled_at") or "")]
                if closer:
                    fields.update(exit_kind="flat", exit_price=float(closer[0]["filled_avg_price"]), exit_at=closer[0].get("filled_at"))
            self.db.order_update(coid, **fields)

    # ---- main loop -------------------------------------------------------------------------------------------
    def run(self, sleep=_time.sleep) -> int:
        cfg = self.cfg
        banner = "dry run" if cfg.dry_run else "PAPER ORDERS ENABLED"
        self.db.event("INFO", f"start ({banner}); evidence={cfg.evidence}; strategy={cfg.strategy}; {len(cfg.symbols)} symbols")
        acct = self.client.account()
        if acct.get("status") != "ACTIVE" or acct.get("trading_blocked"):
            self.db.event("ERROR", "account not tradable", status=acct.get("status"))
            return 1
        now = pd.Timestamp(datetime.now(UTC))
        for w in self.data.load_static(now):
            self.db.event("WARN", w)
        if not self.data.history:
            self.db.event("ERROR", "no usable symbols")
            return 1
        seen_open = False
        while True:
            now = pd.Timestamp(datetime.now(UTC))
            clock = self.client.clock()
            if not clock["is_open"]:
                if seen_open:
                    self.reconcile(now)
                    self.db.event("INFO", "market closed, session finished")
                    return 0
                wait = (pd.Timestamp(clock["next_open"]) - now).total_seconds()
                if wait > 6 * 3600:
                    self.db.event("INFO", "market closed and next open is far away; exiting", next_open=clock["next_open"])
                    return 0
                sleep(min(30, max(wait, 1)))
                continue
            seen_open = True
            if self.kill_path.exists() and not self.flattened:
                self.db.event("WARN", "KILL file present: flattening and stopping")
                self.flatten("kill_switch")
                return 0
            if not self.flattened and decide.minute_of_day(now) >= decide.flat_minute(cfg):
                self.flatten("flat_time")
            dts = decide.decision_time(now)
            if (not self.flattened and dts != self.last_decided and (now - dts).total_seconds() >= cfg.poll_delay_s
                    and decide.minute_of_day(dts) >= 9 * 60 + 35):
                self.last_decided = dts
                try:
                    self.cycle(now)
                    self.errors = 0
                except Exception as e:  # noqa: BLE001 - keep the loop alive, but stop trading if it keeps failing
                    self.errors += 1
                    self.db.event("ERROR", f"cycle failed ({self.errors}): {e!r}")
                    if self.errors >= cfg.max_consecutive_errors:
                        self.db.event("ERROR", "too many consecutive errors: flattening and stopping")
                        self.flatten("errors")
                        return 1
            sleep(3)
