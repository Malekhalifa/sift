import os
import plistlib
import socket
import subprocess
from pathlib import Path

import pytest

from tp.collect.tools import local_stack as ls

SECRET_VALUE = "s3cr3t-value-do-not-print"


class FakeLaunchctl:
    """Records every launchctl call; an agent counts as loaded between bootstrap and bootout."""

    def __init__(self, loaded: set[str] | None = None, fail_bootstrap: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.loaded = set(loaded or ())
        self.fail_bootstrap = fail_bootstrap

    def __call__(self, args):
        args = list(args)
        self.calls.append(args)
        verb = args[0]
        label = args[1].rsplit("/", 1)[-1] if verb in ("bootout", "print") else Path(args[-1]).stem
        if verb == "bootout":
            self.loaded.discard(label)
            return subprocess.CompletedProcess(args, 0, "", "")
        if verb == "print":
            if label in self.loaded:
                return subprocess.CompletedProcess(args, 0, "\tstate = running\n\tpid = 42\n\truns = 3\n", "")
            return subprocess.CompletedProcess(args, 113, "", "not found")
        if verb == "bootstrap":
            if self.fail_bootstrap:
                return subprocess.CompletedProcess(args, 5, "", "Bootstrap failed: 5")
            self.loaded.add(label)
        return subprocess.CompletedProcess(args, 0, "", "")


@pytest.fixture
def layout(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("")
    uv = tmp_path / "bin" / "uv"
    uv.parent.mkdir()
    uv.write_text("")
    (repo / ".env").write_text(
        f"ALPACA_API_KEY_ID={SECRET_VALUE}\nALPACA_API_SECRET_KEY={SECRET_VALUE}\n"
        f"APIFY_API_KEY={SECRET_VALUE}\nSEC_USER_AGENT={SECRET_VALUE}\n"
    )
    return ls.Layout(repo=repo, data_dir=repo / "data", uv=str(uv))


@pytest.fixture
def agents(tmp_path):
    return tmp_path / "LaunchAgents"


def by_name(layout):
    return {j.name: j for j in ls.build_jobs(layout)}


def flatten(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from flatten(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from flatten(v)
    else:
        yield str(value)


def test_plists_have_keepalive_label_and_working_directory_and_no_secrets(layout):
    jobs = by_name(layout)
    rec = ls.plist_for(jobs["recorder"], layout.log_dir)
    qa = ls.plist_for(jobs["qa"], layout.log_dir)

    assert rec["Label"] == "com.sift.recorder"
    assert rec["KeepAlive"] is True and rec["RunAtLoad"] is True
    assert rec["ProcessType"] == "Interactive"
    assert rec["ProgramArguments"] == [layout.uv, "run", "python", "-m", "tp.collect", "run"]
    assert rec["WorkingDirectory"] == str(layout.repo)
    assert rec["StandardOutPath"] == str(layout.data_dir / "logs" / "collect-recorder.log")
    assert rec["StandardErrorPath"] == rec["StandardOutPath"]

    assert qa["Label"] == "com.sift.qa"
    assert "KeepAlive" not in qa and "RunAtLoad" not in qa
    assert qa["ProcessType"] == "Background"
    assert qa["StartCalendarInterval"] == {"Hour": 6, "Minute": 15}
    assert qa["ProgramArguments"] == [layout.uv, "run", "python", "-m", "tp.collect", "qa"]
    assert qa["WorkingDirectory"] == str(layout.repo)
    assert qa["StandardOutPath"] == str(layout.data_dir / "logs" / "collect-qa.log")

    for plist in (rec, qa):
        assert set(plist["EnvironmentVariables"]) == {"PATH"}
        assert str(Path(layout.uv).parent) in plist["EnvironmentVariables"]["PATH"].split(":")
        text = "\n".join(flatten(plist))
        for banned in ("APIFY", "ALPACA", "SEC_USER_AGENT", SECRET_VALUE):
            assert banned not in text


def test_dry_run_writes_nothing_and_loads_nothing(layout, agents, capsys):
    run = FakeLaunchctl()
    code = ls.main(
        ["install", "--dry-run"], agents_dir=agents, run=run, layout=layout, port_free=lambda p: True, sleep=lambda s: None
    )
    out = capsys.readouterr().out
    assert code == 0
    assert run.calls == []
    assert not agents.exists()
    assert not layout.data_dir.exists()
    assert "com.sift.recorder" in out and "com.sift.qa" in out
    assert "bootstrap" in out
    assert SECRET_VALUE not in out


def test_install_writes_both_plists_and_loads_them_in_order(layout, agents):
    run = FakeLaunchctl()
    ls.install(layout, agents_dir=agents, run=run, sleep=lambda s: None, port_free=lambda p: True)

    domain = f"gui/{os.getuid()}"
    assert run.calls == [
        ["bootstrap", domain, str(agents / "com.sift.recorder.plist")],
        ["bootstrap", domain, str(agents / "com.sift.qa.plist")],
    ]
    rec = plistlib.loads((agents / "com.sift.recorder.plist").read_bytes())
    assert rec["Label"] == "com.sift.recorder"
    assert plistlib.loads((agents / "com.sift.qa.plist").read_bytes())["Label"] == "com.sift.qa"
    assert (layout.data_dir / "logs").is_dir()


def test_install_is_idempotent_second_install_unloads_then_loads(layout, agents):
    run = FakeLaunchctl()
    kw = dict(agents_dir=agents, run=run, sleep=lambda s: None, port_free=lambda p: True)
    ls.install(layout, **kw)
    run.calls.clear()
    ls.install(layout, **kw)

    verbs = [c[0] for c in run.calls]
    assert verbs.index("bootout") < verbs.index("bootstrap")
    boots = [c for c in run.calls if c[0] == "bootstrap"]
    assert len(boots) == 2
    last_bootout = max(i for i, c in enumerate(run.calls) if c[0] == "bootout")
    first_boot = min(i for i, c in enumerate(run.calls) if c[0] == "bootstrap")
    assert last_bootout < first_boot
    assert run.loaded == {"com.sift.recorder", "com.sift.qa"}


def test_install_stops_with_a_clear_error_when_bootstrap_fails(layout, agents):
    run = FakeLaunchctl(fail_bootstrap=True)
    with pytest.raises(RuntimeError, match="com.sift.recorder"):
        ls.install(layout, agents_dir=agents, run=run, sleep=lambda s: None, port_free=lambda p: True)


def test_install_refuses_when_preflight_has_errors(layout, agents):
    (layout.repo / ".env").unlink()
    run = FakeLaunchctl()
    with pytest.raises(RuntimeError, match="preflight"):
        ls.install(layout, agents_dir=agents, run=run, sleep=lambda s: None, port_free=lambda p: True)
    assert run.calls == [] and not agents.exists()


def test_uninstall_removes_plists_but_leaves_data(layout, agents):
    run = FakeLaunchctl()
    ls.install(layout, agents_dir=agents, run=run, sleep=lambda s: None, port_free=lambda p: True)
    (layout.data_dir / "logs" / "collect-recorder.log").write_text("log")
    (layout.data_dir / "bars.parquet").write_text("data")
    (agents / "com.other.thing.plist").write_text("not ours")

    removed = ls.uninstall(agents_dir=agents, run=run, sleep=lambda s: None)

    assert removed == ["com.sift.recorder", "com.sift.qa"]
    assert not (agents / "com.sift.recorder.plist").exists()
    assert not (agents / "com.sift.qa.plist").exists()
    assert (agents / "com.other.thing.plist").exists()
    assert (layout.data_dir / "bars.parquet").read_text() == "data"
    assert (layout.data_dir / "logs" / "collect-recorder.log").exists()
    assert run.loaded == set()


def test_uninstall_with_nothing_installed_is_a_noop(agents):
    run = FakeLaunchctl()
    assert ls.uninstall(agents_dir=agents, run=run, sleep=lambda s: None) == []
    assert run.calls == []


def test_status_reports_each_installed_agent(layout, agents):
    run = FakeLaunchctl()
    ls.install(layout, agents_dir=agents, run=run, sleep=lambda s: None, port_free=lambda p: True)
    run.loaded.discard("com.sift.qa")
    rows = dict(ls.status(agents_dir=agents, run=run))
    assert "state running" in rows["com.sift.recorder"] and "pid 42" in rows["com.sift.recorder"]
    assert rows["com.sift.qa"] == "not loaded"


def test_preflight_clean_layout_has_no_errors(layout, agents):
    errors, warnings = ls.preflight(layout, agents_dir=agents, port_free=lambda p: True)
    assert errors == []


def test_preflight_reports_missing_env_keys_by_name_never_values(layout, agents):
    (layout.repo / ".env").write_text(f"ALPACA_API_KEY_ID={SECRET_VALUE}\nSEC_USER_AGENT=\n")
    errors, warnings = ls.preflight(layout, agents_dir=agents, port_free=lambda p: True)
    text = "\n".join(errors + warnings)
    assert "ALPACA_API_SECRET_KEY" in text
    assert "SEC_USER_AGENT" in text  # present but empty counts as missing
    assert "ALPACA_API_KEY_ID" not in text
    assert SECRET_VALUE not in text


def test_preflight_missing_env_file(layout, agents):
    (layout.repo / ".env").unlink()
    errors, _ = ls.preflight(layout, agents_dir=agents, port_free=lambda p: True)
    assert any(".env" in e for e in errors)


def test_preflight_apify_key_is_only_required_when_congress_trades_is_enabled(layout, agents):
    (layout.repo / ".env").write_text(
        f"ALPACA_API_KEY_ID={SECRET_VALUE}\nALPACA_API_SECRET_KEY={SECRET_VALUE}\nSEC_USER_AGENT={SECRET_VALUE}\n"
    )
    errors, warnings = ls.preflight(layout, agents_dir=agents, port_free=lambda p: True, apify_enabled=False)
    assert errors == []
    assert any("APIFY_API_KEY" in w for w in warnings)
    errors, _ = ls.preflight(layout, agents_dir=agents, port_free=lambda p: True, apify_enabled=True)
    assert any("APIFY_API_KEY" in e for e in errors)


def test_preflight_port_in_use_is_an_error_unless_our_agent_is_installed(layout, agents):
    errors, _ = ls.preflight(layout, agents_dir=agents, port_free=lambda p: False)
    assert any("9120" in e for e in errors)

    agents.mkdir()
    (agents / "com.sift.recorder.plist").write_bytes(b"x")
    errors, warnings = ls.preflight(layout, agents_dir=agents, port_free=lambda p: False)
    assert not any("9120" in e for e in errors)
    assert any("9120" in w for w in warnings)


def test_preflight_low_disk_and_missing_uv(layout, agents, monkeypatch):
    monkeypatch.setattr(ls, "_free_gb", lambda p: 3.0)
    errors, _ = ls.preflight(layout, agents_dir=agents, port_free=lambda p: True)
    assert any("free" in e for e in errors)
    monkeypatch.setattr(ls, "_free_gb", lambda p: 15.0)
    errors, warnings = ls.preflight(layout, agents_dir=agents, port_free=lambda p: True)
    assert errors == [] and any("free" in w for w in warnings)

    bad = ls.Layout(repo=layout.repo, data_dir=layout.data_dir, uv="")
    errors, _ = ls.preflight(bad, agents_dir=agents, port_free=lambda p: True)
    assert any("uv" in e for e in errors)


def test_preflight_data_dir_not_writable(layout, agents):
    layout.data_dir.mkdir()
    layout.data_dir.chmod(0o500)
    try:
        if os.access(layout.data_dir, os.W_OK):
            pytest.skip("running as a user that ignores directory permissions")
        errors, _ = ls.preflight(layout, agents_dir=agents, port_free=lambda p: True)
        assert any("writable" in e for e in errors)
    finally:
        layout.data_dir.chmod(0o700)


def test_port_is_free_detects_a_listener():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        assert ls.port_is_free(s.getsockname()[1]) is False
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    assert ls.port_is_free(free) is True
