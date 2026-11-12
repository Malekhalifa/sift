"""Run the Sift recorder on this Mac as two launchd user agents (no Docker).

    uv run python -m tp.collect.tools.local_stack install --dry-run   # checks and prints, changes nothing
    uv run python -m tp.collect.tools.local_stack install
    uv run python -m tp.collect.tools.local_stack status
    uv run python -m tp.collect.tools.local_stack uninstall            # keeps all data and logs

Run `uv sync --frozen --no-dev` first: the agents run the venv's interpreter (`.venv/bin/python`) directly, with no
`uv` in between, so launchd's tracked pid is the daemon and KeepAlive, SIGTERM on stop and signals reach it.

com.sift.recorder keeps `python -m tp.collect run` alive (KeepAlive, Interactive). com.sift.qa runs
`python -m tp.collect qa` every day at 06:15 local time (Background). The plists hold no secrets: the tools read
`.env` themselves, so the only environment variable set is PATH. `install` is idempotent: agents that are already
loaded are stopped and loaded again. See docs/recorder-runbook.md.
"""
from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import socket
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from tp import config

PREFIX = "com.sift"
AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
DEFAULT_PORT = 9120
QA_AT = (6, 15)
STOP_GRACE_S = 30  # launchd sends SIGTERM, then SIGKILL after this
THROTTLE_S = 30  # minimum seconds between respawns of the recorder (launchd's default is 10)
ALERT_DISK_GB = 10  # SiftDiskLow fires below this
WARN_DISK_GB = 20
ENV_REQUIRED = ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY", "SEC_USER_AGENT")
ENV_APIFY = "APIFY_API_KEY"
SYSTEM_PATH = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]
PortProbe = Callable[[int], bool]


@dataclass(frozen=True)
class Layout:
    repo: Path
    data_dir: Path
    port: int = DEFAULT_PORT

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def python(self) -> str:
        """The project venv's interpreter, run directly so launchd's tracked pid is the daemon itself."""
        return str(self.repo / ".venv" / "bin" / "python")

    @property
    def env_file(self) -> Path:
        return self.repo / ".env"


@dataclass(frozen=True)
class Job:
    name: str
    args: list[str]
    cwd: Path
    log_name: str
    env: dict[str, str] = field(default_factory=dict)
    daily_at: tuple[int, int] | None = None  # (hour, minute) local time; None = keep running
    process_type: str | None = None
    throttle_s: int | None = None

    @property
    def label(self) -> str:
        return f"{PREFIX}.{self.name}"


def metrics_port(repo: Path) -> int:
    """The port in config/collect.toml [metrics]; DEFAULT_PORT when the file or key is absent."""
    try:
        with open(repo / "config" / "collect.toml", "rb") as f:
            return int(tomllib.load(f)["metrics"]["port"])
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError, ValueError):
        return DEFAULT_PORT


def default_layout() -> Layout:
    repo = config.ROOT
    return Layout(repo=repo, data_dir=repo / "data", port=metrics_port(repo))


def build_jobs(layout: Layout) -> list[Job]:
    """The recorder first, then the QA job."""
    env = {"PATH": ":".join(SYSTEM_PATH)}
    base = [layout.python, "-m", "tp.collect"]
    return [
        Job("recorder", [*base, "run"], layout.repo, "collect-recorder.log", env, process_type="Interactive", throttle_s=THROTTLE_S),
        Job("qa", [*base, "qa"], layout.repo, "collect-qa.log", env, daily_at=QA_AT, process_type="Background"),
    ]


def plist_for(job: Job, log_dir: Path) -> dict[str, Any]:
    plist: dict[str, Any] = {
        "Label": job.label,
        "ProgramArguments": list(job.args),
        "WorkingDirectory": str(job.cwd),
        "StandardOutPath": str(log_dir / job.log_name),
        "StandardErrorPath": str(log_dir / job.log_name),
        "ExitTimeOut": STOP_GRACE_S,
        "EnvironmentVariables": dict(job.env),
    }
    if job.process_type is not None:
        plist["ProcessType"] = job.process_type
    if job.throttle_s is not None:
        plist["ThrottleInterval"] = job.throttle_s
    if job.daily_at is None:
        plist["RunAtLoad"] = True
        plist["KeepAlive"] = True
    else:
        plist["StartCalendarInterval"] = {"Hour": job.daily_at[0], "Minute": job.daily_at[1]}
    return plist


def write_plists(jobs: Sequence[Job], log_dir: Path, agents_dir: Path) -> list[Path]:
    agents_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for job in jobs:
        path = agents_dir / f"{job.label}.plist"
        with open(path, "wb") as f:
            plistlib.dump(plist_for(job, log_dir), f)
        os.chmod(path, 0o644)
        paths.append(path)
    return paths


def _launchctl(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def port_is_free(port: int) -> bool:
    """True when nothing is listening on 127.0.0.1:port."""
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) != 0


def _free_gb(path: Path) -> float:
    probe = next((p for p in (path, *path.parents) if p.exists()), Path("/"))
    return shutil.disk_usage(probe).free / 1e9


def _apify_enabled(repo: Path) -> bool:
    try:
        with open(repo / "config" / "collect.toml", "rb") as f:
            sources = tomllib.load(f).get("sources", {})
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return bool(sources.get("congress_trades", {}).get("enabled", True))


def installed_labels(agents_dir: Path = AGENTS_DIR) -> list[str]:
    """Installed Sift agents, the recorder first."""
    found = sorted(p.stem for p in agents_dir.glob(f"{PREFIX}.*.plist"))
    return sorted(found, key=lambda label: (label != f"{PREFIX}.recorder", label))


def preflight(
    layout: Layout,
    agents_dir: Path = AGENTS_DIR,
    port_free: PortProbe = port_is_free,
    apify_enabled: bool | None = None,
) -> tuple[list[str], list[str]]:
    """(errors, warnings). Errors stop `install`. `.env` is checked by key name only; values are never shown."""
    errors: list[str] = []
    warnings: list[str] = []
    python = Path(layout.python)
    if not python.is_file() or not os.access(python, os.X_OK):
        errors.append(f"{python} is missing or not executable: run `uv sync --frozen --no-dev` first")
    if not (layout.repo / "pyproject.toml").is_file():
        errors.append(f"{layout.repo} is not the repo root (no pyproject.toml)")

    if not layout.env_file.is_file():
        errors.append(f"{layout.env_file} missing: cp .env.example .env and fill in the keys")
    else:
        present = {k for k, v in dotenv_values(layout.env_file).items() if v and v.strip()}
        for key in ENV_REQUIRED:
            if key not in present:
                errors.append(f".env is missing {key} (or it is empty)")
        if ENV_APIFY not in present:
            needed = _apify_enabled(layout.repo) if apify_enabled is None else apify_enabled
            (errors if needed else warnings).append(
                f".env has no {ENV_APIFY}: congress_trades "
                + ("is enabled and needs it" if needed else "stays disabled until it is added")
            )

    probe = next((p for p in (layout.data_dir, *layout.data_dir.parents) if p.exists()), Path("/"))
    if not os.access(probe, os.W_OK | os.X_OK):
        errors.append(f"data dir {layout.data_dir} is not writable ({probe} is not)")
    free = _free_gb(layout.data_dir)
    if free < ALERT_DISK_GB:
        errors.append(f"only {free:.1f} GB free for {layout.data_dir}: SiftDiskLow would fire at once (< {ALERT_DISK_GB} GB)")
    elif free < WARN_DISK_GB:
        warnings.append(f"only {free:.1f} GB free for {layout.data_dir}: SiftDiskLow fires below {ALERT_DISK_GB} GB")

    if not port_free(layout.port):
        message = f"port {layout.port} is in use"
        if (agents_dir / f"{PREFIX}.recorder.plist").exists():
            warnings.append(f"{message}: expected, the installed recorder holds it and install restarts it")
        else:
            errors.append(f"{message}: another process serves it, so the recorder could not export metrics")
    return errors, warnings


def stop_agent(domain: str, label: str, run: Runner = _launchctl, sleep: Callable[[float], None] = time.sleep) -> None:
    """`launchctl bootout` returns while the process is still shutting down; wait until launchd forgets the agent."""
    run(["bootout", f"{domain}/{label}"])  # not loaded is fine
    for _ in range(STOP_GRACE_S + 10):
        if run(["print", f"{domain}/{label}"]).returncode != 0:
            return
        sleep(1)
    raise RuntimeError(f"{label} is still running {STOP_GRACE_S + 10} s after bootout")


def install(
    layout: Layout,
    agents_dir: Path = AGENTS_DIR,
    run: Runner = _launchctl,
    sleep: Callable[[float], None] = time.sleep,
    port_free: PortProbe = port_is_free,
) -> None:
    """Preflight, stop what is installed, write the plists and load them."""
    errors, _ = preflight(layout, agents_dir, port_free)
    if errors:
        raise RuntimeError("preflight failed: " + "; ".join(errors))
    domain = f"gui/{os.getuid()}"
    for label in installed_labels(agents_dir):
        stop_agent(domain, label, run, sleep)
    layout.log_dir.mkdir(parents=True, exist_ok=True)
    jobs = build_jobs(layout)
    for job, path in zip(jobs, write_plists(jobs, layout.log_dir, agents_dir), strict=True):
        result = run(["bootstrap", domain, str(path)])
        if result.returncode != 0:
            raise RuntimeError(f"launchctl bootstrap {job.label}: {result.stderr.strip()}")


def uninstall(
    agents_dir: Path = AGENTS_DIR, run: Runner = _launchctl, sleep: Callable[[float], None] = time.sleep
) -> list[str]:
    """Stop and remove the Sift agents. Data and logs are left alone."""
    domain = f"gui/{os.getuid()}"
    labels = installed_labels(agents_dir)
    for label in labels:
        stop_agent(domain, label, run, sleep)
        (agents_dir / f"{label}.plist").unlink()
    return labels


def status(agents_dir: Path = AGENTS_DIR, run: Runner = _launchctl) -> list[tuple[str, str]]:
    domain = f"gui/{os.getuid()}"
    rows = []
    for label in installed_labels(agents_dir):
        result = run(["print", f"{domain}/{label}"])
        fields = {}
        for line in result.stdout.splitlines():
            key, sep, value = line.strip().partition(" = ")
            if sep and key in ("state", "pid", "last exit code", "runs"):
                fields[key] = value
        rows.append((label, ", ".join(f"{k} {v}" for k, v in fields.items()) or "not loaded"))
    return rows


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local_stack", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    ins = sub.add_parser("install", help="write the launchd agents and load them")
    ins.add_argument("--dry-run", action="store_true", help="check and print, write and load nothing")
    sub.add_parser("status", help="state of each installed agent")
    sub.add_parser("uninstall", help="stop and remove the agents (data is kept)")
    return parser


def _dry_run(layout: Layout, agents_dir: Path, port_free: PortProbe) -> int:
    errors, warnings = preflight(layout, agents_dir, port_free)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    domain = f"gui/{os.getuid()}"
    print(f"dry run: nothing is written or loaded. Logs would go to {layout.log_dir}")
    for label in installed_labels(agents_dir):
        print(f"would run: launchctl bootout {domain}/{label}")
    for job in build_jobs(layout):
        path = agents_dir / f"{job.label}.plist"
        print(f"\nwould write {path}:\n{plistlib.dumps(plist_for(job, layout.log_dir)).decode()}")
        print(f"would run: launchctl bootstrap {domain} {path}")
    return 1 if errors else 0


def main(
    argv: Sequence[str] | None = None,
    *,
    agents_dir: Path = AGENTS_DIR,
    run: Runner = _launchctl,
    layout: Layout | None = None,
    port_free: PortProbe = port_is_free,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    args = _parser().parse_args(argv)
    if args.command == "status":
        rows = status(agents_dir, run)
        for label, state in rows:
            print(f"{label:24} {state}")
        if not rows:
            print("nothing installed")
        return 0
    if args.command == "uninstall":
        try:
            labels = uninstall(agents_dir, run, sleep)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print("removed:", ", ".join(labels) if labels else "nothing installed")
        return 0
    layout = layout or default_layout()
    if args.dry_run:
        return _dry_run(layout, agents_dir, port_free)
    errors, warnings = preflight(layout, agents_dir, port_free)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    try:
        install(layout, agents_dir, run, sleep, port_free)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"loaded {', '.join(label for label in installed_labels(agents_dir))}; logs under {layout.log_dir}")
    print("check with: uv run python -m tp.collect.tools.local_stack status")
    return 0


if __name__ == "__main__":
    sys.exit(main())
