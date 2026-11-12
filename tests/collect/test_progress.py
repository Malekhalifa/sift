import json
import os

import pytest

from tp.collect.sources.progress import load_progress, save_progress


def test_missing_unreadable_or_foreign_files_read_as_a_fresh_start(tmp_path):
    path = tmp_path / "p.json"
    fresh = {"date": "2026-11-12", "tickers": False, "ciks": []}
    assert load_progress(path, "ciks", "2026-11-12", ("tickers",)) == fresh
    for text in ("{not json", "[1]", json.dumps({"date": "2026-11-11", "ciks": [1]}), json.dumps({"date": "2026-11-12", "ciks": 3})):
        path.write_text(text)
        assert load_progress(path, "ciks", "2026-11-12", ("tickers",)) == fresh


def test_save_then_load_round_trips_for_the_same_day_only(tmp_path):
    path = tmp_path / "sub" / "p.json"
    save_progress(path, {"date": "2026-11-12", "articles": ["A"]})
    assert load_progress(path, "articles", "2026-11-12") == {"date": "2026-11-12", "articles": ["A"]}
    assert load_progress(path, "articles", "2026-11-13") == {"date": "2026-11-13", "articles": []}


def test_save_goes_through_a_pid_suffixed_temp_file_that_is_removed_on_failure(tmp_path, monkeypatch):
    path = tmp_path / "p.json"
    seen: list[str] = []

    def boom(src, dst):
        seen.append(os.path.basename(src))
        raise OSError("disk")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        save_progress(path, {"date": "d", "x": []})
    assert seen == [f"p.json.{os.getpid()}.tmp"] and list(tmp_path.iterdir()) == []
