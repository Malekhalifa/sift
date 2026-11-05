"""Summarise what the paper loop did, and how real fills compare with the backtest's assumptions.

    uv run python scripts/paper_report.py [--all]      # default: today's session only
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from tp.paper.db import PaperDB

BACKTEST_SLIPPAGE = 0.01  # $/share the backtest charges on each market fill


def build_report(db: PaperDB, day_prefix: str | None) -> str:
    where, args = ("WHERE decision_ts LIKE ?", (day_prefix + "%",)) if day_prefix else ("", ())
    decisions = db.rows(f"SELECT decision, COALESCE(reason, ''), COUNT(*) FROM signals {where} GROUP BY 1, 2 ORDER BY 3 DESC", args)
    lines = ["SIGNALS"]
    lines += [f"  {d:<10} {r:<26} {n}" for d, r, n in decisions] or ["  none"]

    owhere, oargs = ("WHERE submitted_at LIKE ?", (day_prefix + "%",)) if day_prefix else ("", ())
    orders = db.rows(
        "SELECT symbol, side, qty, entry_ref, stop, target, filled_avg_price, exit_kind, exit_price, status, evidence "
        f"FROM orders {owhere} ORDER BY submitted_at", oargs)
    lines += ["", f"ORDERS ({len(orders)})"]
    slips, r_values, kinds = [], [], {}
    for sym, side, qty, ref, stop, target, fill, kind, exit_px, status, evidence in orders:
        tag = " (machinery test)" if not evidence else ""
        if fill is None:
            lines.append(f"  {sym:<6} {side:<5} x{qty:<5} {status:<10} not filled{tag}")
            continue
        long = side == "long" or side == "buy"
        slip = (fill - ref) if long else (ref - fill)  # positive = filled worse than the signal price
        slips.append(slip)
        if exit_px is not None:
            pnl = (exit_px - fill) if long else (fill - exit_px)
            r_values.append(pnl / abs(ref - stop))
            kinds[kind] = kinds.get(kind, 0) + 1
            lines.append(f"  {sym:<6} {side:<5} x{qty:<5} fill {fill:.2f} (slip {slip:+.3f}) -> {kind} {exit_px:.2f}  {r_values[-1]:+.2f}R{tag}")
        else:
            lines.append(f"  {sym:<6} {side:<5} x{qty:<5} fill {fill:.2f} (slip {slip:+.3f}) still open{tag}")
    if slips:
        lines += ["", "FILL QUALITY vs BACKTEST",
                  f"  mean entry slippage {sum(slips) / len(slips):+.3f} $/share over {len(slips)} fills (backtest assumes {BACKTEST_SLIPPAGE:+.3f})"]
    if r_values:
        lines.append(f"  closed trades {len(r_values)}: mean {sum(r_values) / len(r_values):+.2f}R; exits {kinds}")
        lines.append("  Machinery-test trades say nothing about any strategy's edge.")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="every day, not just today")
    args = ap.parse_args()
    print(build_report(PaperDB(), None if args.all else f"{datetime.now(UTC):%Y-%m-%d}"))


if __name__ == "__main__":
    main()
