"""M1 data-depth probe: how much usable intraday history does the Alpaca free tier give?

Checks, per feed (iex, sip) and timeframe (1Min, 5Min, 1Day):
  * earliest bar available
  * continuity: bars per regular session at yearly anchor weeks
  * IEX vs SIP volume share over the last full month

Read-only. Writes a JSON report to data/probe/.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from tp.alpaca_data import AlpacaClient, AlpacaError
from tp.config import DATA_DIR, Settings

ET = ZoneInfo("America/New_York")
FEEDS = ("iex", "sip")
TIMEFRAMES = {"1Min": 1, "5Min": 5, "1Day": None}
EXPECTED_RTH_1MIN = 390


def utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def to_frame(bars: list[dict]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame()
    df = pd.DataFrame(bars).rename(columns={"t": "ts", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts").sort_index()


def rth_only(df: pd.DataFrame) -> pd.DataFrame:
    local = df.index.tz_convert(ET)
    mask = (local.time >= time(9, 30)) & (local.time < time(16, 0))
    return df[mask]


def session_stats(df: pd.DataFrame, bar_minutes: int) -> dict:
    if df.empty:
        return {"days": 0}
    rth = rth_only(df)
    if rth.empty:
        return {"days": 0}
    per_day = rth.groupby(rth.index.tz_convert(ET).date).size()
    expected = EXPECTED_RTH_1MIN // bar_minutes
    return {
        "days": int(len(per_day)),
        "median_bars_per_day": int(per_day.median()),
        "expected_bars_per_day": expected,
        "coverage_pct": round(100 * float(per_day.median()) / expected, 1),
        "total_volume": int(rth["volume"].sum()),
    }


def fetch(client: AlpacaClient, symbol: str, tf: str, start: datetime, end: datetime, feed: str) -> pd.DataFrame:
    return to_frame(list(client.bars(symbol, tf, start, end, feed=feed)))


def earliest(client: AlpacaClient, symbol: str, tf: str, feed: str, end: datetime) -> str | dict:
    try:
        it = client.bars(symbol, tf, utc(date(2000, 1, 1)), end, feed=feed, limit=1)
        first = next(it, None)
    except AlpacaError as e:
        return {"error": e.status, "message": e.message}
    return first["t"] if first else "no data"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="AAPL")
    args = ap.parse_args()
    sym = args.symbol

    client = AlpacaClient(Settings.from_env())
    acct = client.account()
    print(f"Auth OK. paper account status={acct.get('status')} currency={acct.get('currency')}")

    # Free tier restricts the most recent ~15 min of SIP data, so end every query 20 min ago.
    end = datetime.now(UTC) - timedelta(minutes=20)
    report: dict = {"symbol": sym, "run_at": datetime.now(UTC).isoformat(), "earliest": {}, "anchors": [], "volume_share": {}}

    print("\n== Earliest bar ==")
    for feed in FEEDS:
        for tf in TIMEFRAMES:
            val = earliest(client, sym, tf, feed, end)
            report["earliest"][f"{feed}/{tf}"] = val
            print(f"{feed:>3} {tf:>5}: {val}")

    print("\n== Continuity at yearly anchor weeks (Mar 8-14, regular hours) ==")
    print(f"{'year':>4} {'feed':>4} {'tf':>4} {'days':>4} {'bars/day':>8} {'expect':>6} {'cover%':>6}")
    for year in range(2016, end.year + 1):
        s, e = utc(date(year, 3, 8)), utc(date(year, 3, 15))
        if e > end:
            continue
        for feed in FEEDS:
            for tf in ("1Min", "5Min"):
                try:
                    st = session_stats(fetch(client, sym, tf, s, e, feed), TIMEFRAMES[tf])
                except AlpacaError as ex:
                    st = {"error": ex.status, "message": ex.message}
                report["anchors"].append({"year": year, "feed": feed, "tf": tf, **st})
                if "error" in st:
                    print(f"{year:>4} {feed:>4} {tf:>4}  ERROR {st['error']}")
                else:
                    print(f"{year:>4} {feed:>4} {tf:>4} {st['days']:>4} {st.get('median_bars_per_day', 0):>8} "
                          f"{st.get('expected_bars_per_day', 0):>6} {st.get('coverage_pct', 0):>6}")

    print("\n== IEX vs SIP volume, last full month (5Min, regular hours) ==")
    first_this_month = end.date().replace(day=1)
    last_month_start = (first_this_month - timedelta(days=1)).replace(day=1)
    vols = {}
    for feed in FEEDS:
        try:
            vols[feed] = session_stats(fetch(client, sym, "5Min", utc(last_month_start), utc(first_this_month), feed), 5)
        except AlpacaError as ex:
            vols[feed] = {"error": ex.status, "message": ex.message}
    report["volume_share"] = vols
    print(json.dumps(vols, indent=2))
    iex_v, sip_v = vols["iex"].get("total_volume"), vols["sip"].get("total_volume")
    if iex_v and sip_v:
        print(f"IEX share of consolidated volume: {100 * iex_v / sip_v:.2f}%")

    out_dir = DATA_DIR / "probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"alpaca_probe_{sym}_{date.today().isoformat()}.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nReport written: {out}")


if __name__ == "__main__":
    main()
