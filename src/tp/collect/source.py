"""Source protocol for the recorder, and the schedule kinds a source can run on."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from tp.collect.datasets import Dataset

DEFAULT_TZ = "America/New_York"
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_UNITS = {"m": "minutes", "h": "hours", "d": "days"}


class SourceError(Exception):
    """A source failed to fetch; the daemon records it and backs off."""


class RateLimited(SourceError):
    """The upstream asked us to slow down."""

    def __init__(self, message: str, retry_after_s: float) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


def _aware(t: datetime) -> datetime:
    if t.tzinfo is None:
        raise ValueError("schedule times must be timezone-aware")
    return t.astimezone(timezone.utc)


def _zone(tz: ZoneInfo | str) -> ZoneInfo:
    return tz if isinstance(tz, ZoneInfo) else ZoneInfo(tz)


class Schedule:
    interval_seconds: int

    def next_after(self, t: datetime) -> datetime:
        """First scheduled instant strictly after t, as an aware UTC datetime."""
        raise NotImplementedError


@dataclass(frozen=True)
class Daily(Schedule):
    at: time
    tz: ZoneInfo = ZoneInfo(DEFAULT_TZ)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tz", _zone(self.tz))

    @property
    def interval_seconds(self) -> int:
        return 86400

    def next_after(self, t: datetime) -> datetime:
        t = _aware(t)
        day = t.astimezone(self.tz).date()
        for offset in range(3):
            cand = datetime.combine(day + timedelta(days=offset), self.at, tzinfo=self.tz)
            cand = cand.astimezone(timezone.utc)
            if cand > t:
                return cand
        raise AssertionError("unreachable: a daily slot always falls within two days")


@dataclass(frozen=True)
class Weekly(Schedule):
    weekday: int
    at: time
    tz: ZoneInfo = ZoneInfo(DEFAULT_TZ)

    def __post_init__(self) -> None:
        if not 0 <= self.weekday <= 6:
            raise ValueError(f"weekday must be 0 (mon) to 6 (sun), got {self.weekday}")
        object.__setattr__(self, "tz", _zone(self.tz))

    @property
    def interval_seconds(self) -> int:
        return 604800

    def next_after(self, t: datetime) -> datetime:
        t = _aware(t)
        day = t.astimezone(self.tz).date()
        for offset in range(9):
            d = day + timedelta(days=offset)
            if d.weekday() != self.weekday:
                continue
            cand = datetime.combine(d, self.at, tzinfo=self.tz).astimezone(timezone.utc)
            if cand > t:
                return cand
        raise AssertionError("unreachable: a weekly slot always falls within eight days")


@dataclass(frozen=True)
class Every(Schedule):
    """A fixed period measured from the previous run, so next_after(t) is t + period."""

    period: timedelta

    def __post_init__(self) -> None:
        if self.period <= timedelta(0):
            raise ValueError("period must be positive")

    @property
    def interval_seconds(self) -> int:
        return int(self.period.total_seconds())

    def next_after(self, t: datetime) -> datetime:
        return _aware(t) + self.period


def _parse_time(text: str) -> time:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not m:
        raise ValueError(f"bad time {text!r}, expected HH:MM")
    h, mi = int(m[1]), int(m[2])
    if h > 23 or mi > 59:
        raise ValueError(f"bad time {text!r}")
    return time(h, mi)


def _parse_tz(parts: list[str]) -> ZoneInfo:
    if len(parts) > 1:
        raise ValueError(f"unexpected trailing text {' '.join(parts)!r}")
    name = parts[0] if parts else DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"unknown timezone {name!r}") from e


def parse_schedule(text: str) -> Schedule:
    """Parse `daily HH:MM [tz]`, `weekly <mon..sun> HH:MM [tz]` or `every <N><m|h|d>`; tz defaults to America/New_York."""
    parts = text.split()
    kind, rest = (parts[0].lower(), parts[1:]) if parts else ("", [])
    if kind == "daily" and rest:
        return Daily(_parse_time(rest[0]), _parse_tz(rest[1:]))
    if kind == "weekly" and len(rest) >= 2:
        day = rest[0].lower()
        if day not in WEEKDAYS:
            raise ValueError(f"bad weekday {rest[0]!r}, expected one of {', '.join(WEEKDAYS)}")
        return Weekly(WEEKDAYS.index(day), _parse_time(rest[1]), _parse_tz(rest[2:]))
    if kind == "every" and len(rest) == 1:
        m = re.fullmatch(r"(\d+)([mhd])", rest[0].lower())
        if m and int(m[1]) > 0:
            return Every(timedelta(**{_UNITS[m[2]]: int(m[1])}))
    raise ValueError(f"unrecognised schedule {text!r}")


@dataclass
class RunContext:
    now: datetime
    settings: dict
    writer: Callable[[Dataset, pd.DataFrame], int]


class Source:
    """One upstream feed. Subclasses set the attributes and override fetch (or run)."""

    name: str
    rate_group: str = "default"
    schedule: Schedule
    lag: timedelta = timedelta(0)
    datasets: tuple[Dataset, ...] = ()

    def fetch(self, ctx: RunContext) -> dict[Dataset, pd.DataFrame]:
        raise NotImplementedError(f"{type(self).__name__} must override fetch or run")

    def run(self, ctx: RunContext) -> int:
        """Fetch and write every frame through ctx.writer; returns the total of new rows."""
        return sum(ctx.writer(ds, frame) for ds, frame in self.fetch(ctx).items())
