"""Supervised check that Alpaca accepts our bracket-order format. PAPER account only.

Places a 1-share bracket whose limit entry sits at half the market price, so it cannot fill; confirms Alpaca
accepted it (parent and both legs), cancels it, and confirms no order or position is left behind.

    uv run python scripts/paper_smoke_order.py [SYMBOL]
"""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime, timedelta

from tp import config
from tp.alpaca_data import AlpacaError, TradingClient


def main() -> int:
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL"
    client = TradingClient(config.Settings.from_env())
    now = datetime.now(UTC)
    bars = list(client.bars(symbol, "1Min", now - timedelta(hours=2), now - timedelta(minutes=1), feed="iex"))
    if not bars:
        print("no recent bars; is the market open?")
        return 1
    last = bars[-1]["c"]
    entry = round(last * 0.5, 2)
    coid = f"smoketest-{now:%H%M%S}"
    payload = {
        "symbol": symbol, "qty": "1", "side": "buy", "type": "limit", "limit_price": f"{entry:.2f}", "time_in_force": "day",
        "order_class": "bracket", "take_profit": {"limit_price": f"{entry * 1.03:.2f}"}, "stop_loss": {"stop_price": f"{entry * 0.97:.2f}"},
        "client_order_id": coid,
    }
    before = len(client.positions())
    print(f"{symbol} last {last}; placing limit-entry bracket at {entry:.2f} (cannot fill)")
    try:
        order = client.submit_order(payload)
    except AlpacaError as e:
        print("REJECTED:", e)
        return 1
    print(f"accepted: id={order['id']} status={order['status']} class={order.get('order_class')} legs={len(order.get('legs') or [])}")
    ok = order.get("order_class") == "bracket" and len(order.get("legs") or []) == 2
    time.sleep(1)
    client.cancel_order(order["id"])
    time.sleep(2)
    open_after = [o for o in client.orders("open", nested=False, symbols=[symbol]) if o.get("client_order_id") == coid or o.get("parent_order_id") == order["id"]]
    positions_after = len(client.positions())
    print(f"after cancel: {len(open_after)} of our orders still open, positions {before} -> {positions_after}")
    clean = not open_after and positions_after == before
    print("RESULT:", "OK, format accepted and cleanly cancelled" if ok and clean else "CHECK MANUALLY")
    return 0 if ok and clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
