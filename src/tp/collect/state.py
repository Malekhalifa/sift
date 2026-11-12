"""Per-source run state (last success, failures, backoff), persisted atomically as JSON."""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tp import config

log = logging.getLogger(__name__)

BACKOFF_BASE_S = 60.0
BACKOFF_CAP_S = 6 * 3600.0


def default_path() -> Path:
    return config.DATA_DIR / "collect" / "state.json"


def _iso(t: datetime) -> str:
    if t.tzinfo is None:
        raise ValueError("state times must be timezone-aware")
    return t.astimezone(timezone.utc).isoformat()


def _parse(s: str | None) -> datetime | None:
    return None if s is None else datetime.fromisoformat(s)


class State:
    def __init__(self, path: Path | None = None, data: dict[str, dict] | None = None) -> None:
        self.path = path or default_path()
        self._data: dict[str, dict] = data or {}
        self._lock = threading.Lock()

    @classmethod
    def load(cls, path: Path | None = None) -> State:
        """Read the state file; a missing file is empty and an unreadable one is set aside."""
        path = path or default_path()
        if not path.exists():
            return cls(path)
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                raise ValueError("state root is not an object")
            return cls(path, data)
        except (ValueError, OSError) as e:
            aside = path.with_suffix(path.suffix + ".corrupt")
            log.warning("unreadable state file %s (%s); moving it to %s and starting empty", path, e, aside)
            os.replace(path, aside)
            return cls(path)

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return json.loads(json.dumps(self._data))

    def _entry(self, name: str) -> dict:
        return self._data.get(name, {})

    def last_success(self, name: str) -> datetime | None:
        return _parse(self._entry(name).get("last_success"))

    def rows(self, name: str) -> int:
        return int(self._entry(name).get("rows", 0))

    def failures(self, name: str) -> int:
        return int(self._entry(name).get("failures", 0))

    def last_error(self, name: str) -> str | None:
        return self._entry(name).get("last_error")

    def backoff_until(self, name: str) -> datetime | None:
        return _parse(self._entry(name).get("backoff_until"))

    def record_success(self, name: str, now: datetime, rows: int) -> None:
        self._update(name, {
            "last_success": _iso(now), "rows": rows, "failures": 0, "last_error": None, "backoff_until": None,
        })

    def record_failure(self, name: str, now: datetime, error: str, retry_after_s: float | None = None) -> None:
        """Count a failure and set backoff: exponential from 60s; retry_after_s applies only when larger; capped at 6h."""
        with self._lock:
            failures = int(self._data.get(name, {}).get("failures", 0)) + 1
        wait = min(BACKOFF_BASE_S * 2 ** min(failures - 1, 20), BACKOFF_CAP_S)
        if retry_after_s is not None:
            wait = min(max(wait, retry_after_s), BACKOFF_CAP_S)
        self._update(name, {
            "failures": failures, "last_error": error, "backoff_until": _iso(now + timedelta(seconds=wait)),
        })

    def _update(self, name: str, fields: dict) -> None:
        """Merge into memory first so backoff holds even when the save fails; the save error propagates."""
        with self._lock:
            merged = {**self._data.get(name, {}), **fields}
            self._data[name] = merged
            self._save(self._data)

    def _save(self, data: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
            os.replace(tmp, self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
