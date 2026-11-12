import importlib.util
from pathlib import Path

import pytest

from tp import config
from tp.collect import daemon

SCRIPTS = Path(__file__).parents[2] / "scripts"
LEGACY_WRITERS = ["fetch_political", "fetch_insider", "fetch_shares", "fetch_eightk", "fetch_earnings", "fetch_finra"]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_refuse_while_daemon_runs_is_none_when_free_and_releases_the_probe(capsys):
    assert daemon.refuse_while_daemon_runs() is None
    daemon.acquire_lock(daemon.lock_path()).close()  # the probe did not keep the lock
    assert capsys.readouterr().err == ""


def test_refuse_while_daemon_runs_returns_2_with_a_message_while_the_lock_is_held(capsys):
    held = daemon.acquire_lock(daemon.lock_path())
    try:
        assert daemon.refuse_while_daemon_runs() == 2
    finally:
        held.close()
    err = capsys.readouterr().err
    assert "recorder daemon is running" in err and ".collect.lock" in err


@pytest.mark.parametrize("name", LEGACY_WRITERS)
def test_every_legacy_writing_script_refuses_while_the_lock_is_held_and_touches_nothing(name, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", [name])
    script = load(name)
    held = daemon.acquire_lock(daemon.lock_path())
    try:
        assert script.main() == 2
    finally:
        held.close()
    assert "recorder daemon is running" in capsys.readouterr().err
    assert sorted(p.name for p in config.DATA_DIR.rglob("*")) == [".collect.lock"]
