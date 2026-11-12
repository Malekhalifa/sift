"""Per-run progress files: which items a run date already finished, so a retry after a rate limit resumes."""
from __future__ import annotations

import json
import os
from pathlib import Path


def load_progress(path: Path, field: str, day: str, flags: tuple[str, ...] = ()) -> dict:
    """What `day` already finished (`field` lists the done items; each of `flags` is a boolean). Anything missing,
    unreadable, malformed or from another day reads as a fresh start."""
    fresh = {"date": day, **dict.fromkeys(flags, False), field: []}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return fresh
    if not isinstance(data, dict) or data.get("date") != day or not isinstance(data.get(field), list):
        return fresh
    return {"date": day, **{f: bool(data.get(f)) for f in flags}, field: data[field]}


def save_progress(path: Path, progress: dict) -> None:
    """Replace the file via a pid-suffixed temp file, so a half-written file is never read."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(progress))
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
