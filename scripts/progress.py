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
    path = latest("backfill-*.log")
    text = read(path)
    lines = ["DATA DOWNLOAD"]
    if not text:
        return lines + ["  no download log found"]
    row = r"\[(\d+)/(\d+)\] (\w+) (\w+) (\w+)"
    done = re.findall(row + r" \+\d+ bars \(([\d.]+)s\)", text)  # n, total, feed, tf, symbol, secs
    failed = re.findall(row + r" FAILED", text)
    totals = re.findall(r"\[\d+/(\d+)\]", text)
    m_syms = re.search(r"splits synced: \d+ records for (\d+) symbols", text)
    n_syms = int(m_syms.group(1)) if m_syms else 0
    total = int(totals[-1]) if totals else 0
    n_done = len(done) + len(failed)
    alive = running("m tp.recorder")
    started = first_timestamp(text)
    secs = [float(d[5]) for d in done if float(d[5]) > 2]  # skip near-instant "already up to date" rows
    per = sum(secs[-6:]) / len(secs[-6:]) if secs else None

    universe = "wide universe" if n_syms > 14 else "core universe"
    lines[0] = f"DATA DOWNLOAD  ({universe}: {n_syms} tickers, {total} series; {path.name})"
    lines.append("  " + bar(n_done, total))
    state = "running" if alive else ("finished" if total and n_done >= total else "NOT running")
    elapsed = f", running for {human((datetime.now() - started).total_seconds())}" if started and alive else ""
    lines.append(f"  status: {state}{elapsed}@@ETA@@")

    ok = {(d[2], d[3], d[4]) for d in done}
    bad = {(f[2], f[3], f[4]) for f in failed}
    seen_specs = list(dict.fromkeys((d[2], d[3]) for d in [*done, *failed]))
    n_specs = round(total / n_syms) if n_syms else len(seen_specs)
    from tp.recorder import CORE_SPECS, SPECS, WIDE_SPECS  # spec order, to name the ones not started yet

    kinds = WIDE_SPECS if n_syms > 14 else CORE_SPECS
    upcoming = [sp for sp in SPECS if sp in kinds and sp not in seen_specs][: max(n_specs - len(seen_specs), 0)]
    all_specs = seen_specs + upcoming
    current_spec = None
    if alive and n_done < total and all_specs:
        current_spec = all_specs[min(n_done // max(n_syms, 1), len(all_specs) - 1)]
    if alive and current_spec and n_syms:
        in_spec = [float(d[5]) for d in done if (d[2], d[3]) == current_spec and float(d[5]) > 2]
        left_here = n_syms - sum(1 for k in ok | bad if k[:2] == current_spec)
        untimed = [sp for sp in all_specs[all_specs.index(current_spec) + 1 :] if sp not in seen_specs]
        if in_spec:
            here = sum(in_spec[-6:]) / len(in_spec[-6:]) * left_here
            note = f" for this step; the {', '.join(tf for _, tf in untimed)} step is timed once it starts" if untimed else ""
            eta = f"; about {human(here)} left{note} (this step done around {(datetime.now() + timedelta(seconds=here)):%H:%M})"
        else:
            eta = "; estimating..."
        lines[-1] = lines[-1].replace("@@ETA@@", eta)
    else:
        lines[-1] = lines[-1].replace("@@ETA@@", "")
    names = {"sip": "SIP full market", "iex": "IEX live feed"}
    if n_syms <= 14:
        symbols = config.all_symbols()
        for feed, tf in all_specs:
            pending = [s for s in symbols if (feed, tf, s) not in ok | bad]
            cur = pending[0] if (feed, tf) == current_spec and pending else None
            cells = [("✗" if (feed, tf, s) in bad else "✓" if (feed, tf, s) in ok else "▶" if s == cur else "·") + s for s in symbols]
            lines.append(f"  {names.get(feed, feed)} {tf:<5} " + " ".join(cells))
        lines.append("  ✓ done  ▶ downloading now  · waiting")
    else:
        for feed, tf in all_specs:
            n_ok = sum(1 for k in ok if k[:2] == (feed, tf))
            n_bad = sum(1 for k in bad if k[:2] == (feed, tf))
            mark = "▶" if (feed, tf) == current_spec else ("✓" if n_ok + n_bad >= n_syms else "·")
            fail = f"  ({n_bad} failed)" if n_bad else ""
            lines.append(f"  {mark} {names.get(feed, feed)} {tf:<5} {bar(n_ok + n_bad, n_syms)}{fail}")
        last = done[-1][4] if done else "-"
        lines.append(f"  last finished: {last}")
    return lines


def sweep_names() -> list[str]:
    import tomllib

    names = []
    for path in sorted((config.ROOT / "config" / "sweeps").glob("*.toml"), key=lambda p: p.stat().st_mtime):
        with open(path, "rb") as f:
            names.append(tomllib.load(f)["name"])
    return names


def sweep_section(download_alive: bool) -> list[str]:
    lines = []
    for name in sweep_names():
        lines += ["", f"BIG TEST  ({name})"] + sweep_block(name, download_alive)
    return lines


def sweep_block(name: str, download_alive: bool) -> list[str]:
    path = LOGS / f"sweep-{name}.log"
    text = read(path)
    lines: list[str] = []
    if not text:
        return [f"  {'waiting for its data to finish downloading' if download_alive else 'not started'}"]
    exit_m = re.search(r"^exit=(\d+)", text, re.M)
    totals = {fam: int(n) for fam, n in re.findall(r"\[\d+/(\d+)\] (\w+)-\d+ ", text)[::-1]} if False else {}
    for n, fam in re.findall(r"\[\d+/(\d+)\] ([a-z]+)-\d+ ", text):
        totals[fam] = int(n)
    counts = {fam: len(re.findall(rf"\[\d+/{n}\] {fam}-\d+", text)) for fam, n in totals.items()}
    secs = [float(x) for x in re.findall(r"\] [a-z]+-\d+ ([\d.]+)s", text)]
    per = sum(secs[-6:]) / len(secs[-6:]) if secs else None
    total = sum(totals.values())
    done = sum(counts.values())
    if exit_m:
        code = int(exit_m.group(1))
        lines.append("  " + bar(done, total))
        if code == 0:
            lines += ["  status: finished", f"  results: {config.DATA_DIR / 'sweeps' / name / 'report.txt'}"]
        else:
            lines += [f"  status: STOPPED with exit code {code}", *["  " + ln for ln in text.strip().splitlines()[-4:]]]
        return lines
    if "Incomplete data" in text:
        return lines + ["  stopped: data incomplete", *["  " + ln for ln in text.strip().splitlines()[-4:]]]
    if not totals:
        return lines + ["  loading price history into memory"]
    phase = "trying strategy variants" if done < total else "scoring results (walk-forward, significance checks)"
    lines.append("  " + bar(done, total))
    lines.append("  " + "    ".join(f"{fam} {counts[fam]}/{n}" for fam, n in totals.items()))
    lines.append(f"  status: {phase}" + (f"; {eta_text(done, total, per)}" if done < total else ""))
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
