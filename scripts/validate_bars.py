"""Integrity checks on the bar store. Exit code 1 if any hard check fails.

Hard failures: bad OHLC, non-positive prices, negative volume, duplicate/unsorted timestamps.
Warnings: trading days (per the SIP daily bars) with no minute bars, thin sessions, and daily-vs-minute
close disagreement.

    uv run python scripts/validate_bars.py [--symbols AAPL,NVDA]
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from tp import bars, config, store

ET = bars.ET
THIN_SESSION_BARS = 195  # half of 390; an early-close session still has ~210 regular-hours minutes


def local_days(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return index.tz_convert(ET).tz_localize(None).normalize()


def hard_checks(df: pd.DataFrame) -> dict:
    ohlc_bad = (
        (df["high"] < df["low"])
        | (df["high"] < df[["open", "close"]].max(axis=1))
        | (df["low"] > df[["open", "close"]].min(axis=1))
    )
    return {
        "bad_ohlc": int(ohlc_bad.sum()),
        "nonpos_price": int((df[["open", "high", "low", "close"]] <= 0).any(axis=1).sum()),
        "neg_volume": int((df["volume"] < 0).sum()),
        "dup_or_unsorted": int((not df.index.is_unique) or (not df.index.is_monotonic_increasing)),
    }


def minute_checks(df: pd.DataFrame, daily: pd.DataFrame | None) -> dict:
    rth = df[bars.rth_mask(df.index)]
    if rth.empty:
        return {"sessions": 0}
    days = local_days(rth.index)
    per_day = rth.groupby(days).size()
    out = {
        "sessions": int(len(per_day)),
        "fill_pct": round(100 * float(per_day.sum()) / (len(per_day) * 390), 1),
        "thin_days": [d.date().isoformat() for d in per_day[per_day < THIN_SESSION_BARS].index],
    }
    if daily is not None and not daily.empty:
        daily_days = local_days(daily.index)
        daily = daily.set_axis(daily_days)
        trading_days = set(daily_days)
        out["missing_days"] = sorted(d.date().isoformat() for d in trading_days - set(per_day.index))
        out["extra_days"] = sorted(d.date().isoformat() for d in set(per_day.index) - trading_days)
        last_close = rth.groupby(days)["close"].last()
        both = last_close.index.intersection(daily.index)
        if len(both):
            diff = (last_close[both] / daily["close"][both] - 1).abs() * 100
            out["close_diff_med_pct"] = round(float(diff.median()), 4)
            out["close_diff_p99_pct"] = round(float(diff.quantile(0.99)), 3)
            vol_ratio = rth.groupby(days)["volume"].sum()[both] / daily["volume"][both]
            out["rth_vol_over_daily_med"] = round(float(vol_ratio.median()), 3)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", help="comma-separated; default is the whole universe")
    args = ap.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else config.all_symbols()

    hard_fail = False
    details: list[str] = []
    print(f"{'series':<16} {'rows':>9} {'first':>10} {'last':>10} {'sess':>5} {'fill%':>6} {'thin':>4} {'miss':>4} "
          f"{'extra':>5} {'clsΔmed%':>8} {'clsΔp99%':>8} {'rthVol/d':>8}  hard")
    for symbol in symbols:
        daily = store.load_raw("sip", "1Day", symbol)
        for feed, tf in (("sip", "1Day"), ("sip", "1Min"), ("iex", "1Min")):
            df = store.load_raw(feed, tf, symbol)
            label = f"{feed}/{tf}/{symbol}"
            if df.empty:
                print(f"{label:<16} {'(none)':>9}")
                continue
            hard = hard_checks(df)
            failed = {k: v for k, v in hard.items() if v}
            hard_fail |= bool(failed)
            m = minute_checks(df, daily) if tf == "1Min" else {}
            print(
                f"{label:<16} {len(df):>9} {df.index[0].date()!s:>10} {df.index[-1].date()!s:>10} "
                f"{m.get('sessions', ''):>5} {m.get('fill_pct', ''):>6} {len(m.get('thin_days', [])) if m else '':>4} "
                f"{len(m.get('missing_days', [])) if m else '':>4} {len(m.get('extra_days', [])) if m else '':>5} "
                f"{m.get('close_diff_med_pct', ''):>8} {m.get('close_diff_p99_pct', ''):>8} "
                f"{m.get('rth_vol_over_daily_med', ''):>8}  {'FAIL ' + str(failed) if failed else 'ok'}"
            )
            if m.get("thin_days"):
                details.append(f"{label} thin sessions: {m['thin_days'][:8]}{' ...' if len(m['thin_days']) > 8 else ''}")
            # IEX has no daily bars in the store, so its missing_days are measured against SIP trading days.
            if m.get("missing_days"):
                details.append(f"{label} no minute bars on trading days: {m['missing_days'][:8]}"
                               f"{' ...' if len(m['missing_days']) > 8 else ''}")

    if details:
        print("\nWarnings:")
        print("\n".join(f"  {d}" for d in details))
    print("\nRESULT:", "FAIL" if hard_fail else "no hard failures")
    return 1 if hard_fail else 0


if __name__ == "__main__":
    np.seterr(all="ignore")
    raise SystemExit(main())
