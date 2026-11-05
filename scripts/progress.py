"""Progress bars for the data download and the M4 sweep, read from their log files. Touches nothing else.

    uv run python scripts/progress.py            # one snapshot
    uv run python scripts/progress.py --watch    # refresh every 2 seconds, Ctrl-C to quit
"""

from __future__ import annotations

import argparse
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from tp import config

LOGS = config.DATA_DIR / "logs"
SWEEP_LOG = LOGS / "sweep-m4-v1.log"
SWEEP_TOTALS = {"orb": 54, "fade": 24}
BAR = 32


def bar(done: int, total: int) -> str:
    frac = 0 if total <= 0 else min(done / total, 1.0)
    filled = int(round(BAR * frac))
    return f"[{'█' * filled}{'░' * (BAR - filled)}] {100 * frac:5.1f}%  {done}/{total}"


def human(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else (f"{m}m{s:02d}s" if m else f"{s}s")


def running(pattern: str) -> bool:
    return subprocess.run(["pgrep", "-f", pattern], capture_output=True).returncode == 0


def read(path: Path | None) -> str:
    return path.read_text(errors="replace") if path and path.exists() else ""


def latest(pattern: str) -> Path | None:
    files = sorted(LOGS.glob(pattern), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def first_timestamp(text: str) -> datetime | None:
    m = re.search(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", text, re.M)
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") if m else None


def eta_text(done: int, total: int, per_item: float | None) -> str:
    if done >= total:
        return "finished"
    if not per_item:
        return "estimating..."
    left = per_item * (total - done)
    return f"about {human(left)} left (done around {(datetime.now() + timedelta(seconds=left)):%H:%M})"


def download_section() -> list[str]:
    path = latest("backfill-resume-*.log")
    text = read(path)
    lines = ["DATA DOWNLOAD  (1-minute prices, 12 tickers x 2 sources)"]
    if not text:
        return lines + ["  no download log found"]
    done = re.findall(r"\[(\d+)/(\d+)\] (\w+) 1Min (\w+) \+\d+ bars \(([\d.]+)s\)", text)
    failed = re.findall(r"\[\d+/\d+\] (\w+) 1Min (\w+) FAILED", text)
    total = int(re.search(r"\[\d+/(\d+)\]", text).group(1)) if re.search(r"\[\d+/(\d+)\]", text) else 24
    n_done = len(done) + len(failed)
    alive = running("m tp.recorder")
    started = first_timestamp(text)
    secs = [float(d[4]) for d in done if float(d[4]) > 5]  # skip the near-instant "already up to date" rows
    per = sum(secs[-4:]) / len(secs[-4:]) if secs else None
    lines.append("  " + bar(n_done, total))
    state = "running" if alive else ("finished" if n_done >= total else "NOT running")
    elapsed = f", running for {human((datetime.now() - started).total_seconds())}" if started and alive else ""
    lines.append(f"  status: {state}{elapsed}; {eta_text(n_done, total, per) if alive else ''}".rstrip("; "))
    ok = {(d[2], d[3]) for d in done}
    bad = {(f[0], f[1]) for f in failed}
    symbols = config.all_symbols()
    pending = [(f, s) for f in ("sip", "iex") for s in symbols if (f, s) not in ok | bad]
    current = pending[0] if alive and pending else None
    for feed, label in (("sip", "SIP full market"), ("iex", "IEX live feed")):
        cells = []
        for s in symbols:
            mark = "✗" if (feed, s) in bad else "✓" if (feed, s) in ok else "▶" if (feed, s) == current else "·"
            cells.append(f"{mark}{s}")
        lines.append(f"  {label:<16} " + " ".join(cells))
    lines.append("  ✓ done  ▶ downloading now  · waiting")
    return lines


def sweep_section(download_alive: bool) -> list[str]:
    text = read(SWEEP_LOG)
    lines = ["", "BIG TEST  (78 strategy variants, tested year by year)"]
    if not text:
        waiting = "waiting for SPY data to finish downloading, then it starts by itself" if download_alive else "not started"
        return lines + [f"  {waiting}"]
    exit_m = re.search(r"^exit=(\d+)", text, re.M)
    counts = {fam: len(re.findall(rf"\[\d+/{n}\] {fam}-\d+", text)) for fam, n in SWEEP_TOTALS.items()}
    secs = [float(s) for s in re.findall(r"\] (?:orb|fade)-\d+ ([\d.]+)s", text)]
    per = sum(secs[-6:]) / len(secs[-6:]) if secs else None
    total = sum(SWEEP_TOTALS.values())
    done = sum(counts.values())
    if exit_m:
        code = int(exit_m.group(1))
        verdict = "finished" if code == 0 else f"STOPPED with exit code {code}, see {SWEEP_LOG}"
        lines.append("  " + bar(done, total))
        lines.append(f"  status: {verdict}")
        if code == 0:
            lines.append(f"  results: {config.DATA_DIR / 'sweeps' / 'm4-v1' / 'report.txt'}")
        else:
            lines += ["  " + ln for ln in text.strip().splitlines()[-4:]]
        return lines
    if "Incomplete data" in text:
        return lines + ["  stopped: data incomplete", *["  " + ln for ln in text.strip().splitlines()[-4:]]]
    if "Loading" in text and done == 0:
        phase = "loading price history into memory"
    elif done < total:
        phase = "trying strategy variants" + (f" ({'breakout' if counts['fade'] == 0 else 'fade'} family)")
    else:
        phase = "scoring results (walk-forward, significance checks)"
    lines.append("  " + bar(done, total))
    lines.append(f"  breakout {counts['orb']}/{SWEEP_TOTALS['orb']}    fade {counts['fade']}/{SWEEP_TOTALS['fade']}")
    lines.append(f"  status: {phase}; {eta_text(done, total, per) if done < total else ''}".rstrip("; "))
    return lines


def render() -> str:
    dl = download_section()
    alive = running("m tp.recorder")
    return "\n".join([f"Trading pipeline progress  {datetime.now():%H:%M:%S}", "", *dl, *sweep_section(alive)])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watch", action="store_true")
    args = ap.parse_args()
    if not args.watch:
        print(render())
        return
    try:
        while True:
            print("\033[2J\033[H" + render() + "\n\n(Ctrl-C to quit)", flush=True)
            time.sleep(2)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
