"""Alpaca bars and splits, synced through the same code path as `python -m tp.recorder`."""
from __future__ import annotations

import fcntl
from collections.abc import Callable
from datetime import timedelta

from tp import config, corp_actions, recorder
from tp.alpaca_data import AlpacaClient
from tp.collect.source import RunContext, Source, SourceError, parse_schedule

WORKERS = 4
MAX_LISTED_FAILURES = 20


class AlpacaBars(Source):
    name = "alpaca_bars"
    rate_group = "alpaca"

    def __init__(
        self,
        schedule: str = "daily 21:00 America/New_York",
        lag_minutes: int = 20,
        client_factory: Callable[[], AlpacaClient] | None = None,
    ) -> None:
        self.schedule = parse_schedule(schedule)
        self.lag = timedelta(minutes=lag_minutes)
        self._client_factory = client_factory or (lambda: AlpacaClient(config.Settings.from_env()))

    def run(self, ctx: RunContext) -> int:
        """Sync the whole universe; returns the bars added. sync_splits overwrites the splits store with only the
        symbols it is given, so the plan is always universe="all" rather than a subset."""
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.DATA_DIR / ".recorder.lock", "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SourceError("another recorder run holds the lock") from None
            try:
                return self._sync(ctx)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _sync(self, ctx: RunContext) -> int:
        plan = recorder.build_plan(None, "all", list(recorder.SPECS))
        names = sorted({sym for _, _, sym in plan})
        client = self._client_factory()
        corp_actions.sync_splits(client, names, recorder.FEED_START["sip"], ctx.now.astimezone(recorder.ET).date())
        added, failures = recorder.sync_plan(client, plan, ctx.now, WORKERS)
        if failures:
            failures = sorted(failures)
            shown = failures[:MAX_LISTED_FAILURES]
            more = len(failures) - len(shown)
            tail = f"\n  ... and {more} more" if more else ""
            raise SourceError(f"{len(failures)} series failed:\n  " + "\n  ".join(shown) + tail)
        return added
