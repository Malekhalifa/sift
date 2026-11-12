"""Congress stock trades from a paid Apify actor, guarded so the free monthly credit cannot be overspent.

Once a day the source starts ONE run of the actor named in `[sources.congress_trades] actor` (never hardcoded), waits for
it, reads the run's default dataset and returns the trades as rows. There is no backfill: the actor is asked only for its
recent lookback window and rows already stored are dropped by the writer. A row's `ts` is the disclosure timestamp in UTC
(a date-only value is midnight UTC, so a strategy must enter at the next open after that day has closed) and its
`source_id` is the actor's own id field when `id_field` is set, else a hash of the `id_fields` columns.

Operator note: before switching `enabled = true`, set a $4 monthly usage limit in the Apify console (Settings, Billing,
Limits); it is the only hard backstop, everything below is this code's own guard. Also verify the actor's input field
names (`[sources.congress_trades.input]`, `item_limit_field`) against the actor's input schema, and that the field names
read from `GET /v2/users/me/limits` (`data.current.monthlyUsageUsd`, `data.limits.maxMonthlyUsageUsd`) are what the
account returns, because the guard refuses to run when it cannot read them.

Spend guard (it fails closed; every item applies before and around each run):
- Reserve, then settle. Before the start request, ONE atomic ledger write adds the full `daily_run_cap_usd` to the
  month's total and records the UTC day as started; if that write fails no run is started. When the run reaches a
  terminal state the reservation is replaced by the ACTUAL cost (`usageTotalUsd`, settled as `actual - reserved`).
  A crash or an unclear start (transport error, HTTP 5xx, no run id) leaves the reservation in place, so the ledger can
  be over-booked but not short; only a definite rejection (HTTP 4xx on the start request) releases it. An unknown cost,
  or a run still ABORTING/RUNNING after the abort, keeps the reservation (raised to any higher reported cost).
- At most one run is started per UTC day, including after a failure or an unclear start: no same-day retry.
- `SpendLedger` (data/collect/apify_spend.json, fsynced then replaced atomically) totals the cost per UTC calendar month.
  No run is started, and no HTTP call is made at all, when the month's total plus the daily cap would pass
  `monthly_cap_usd` (clamped to 4.0, 80% of the $5 credit). A ledger that cannot be read refuses the run, and so does a
  MISSING ledger when this source has run before (a `last_success` in the state file or a stored dataset).
- Before every start the account's real usage is read (`GET /users/me/limits`); the run is refused when the month's usage
  plus the daily cap would pass the cap (or the account's own limit), and when that read fails or lacks the fields.
- Every run is started with `maxTotalChargeUsd = daily_run_cap_usd`, the platform `maxItems` query parameter and an item
  limit in the input, and a run timeout; the wait is bounded (WAIT_TOTAL_S), a failed status read is retried, and a run
  still going after the wait is aborted.
- Before the first ever run (empty ledger) the actor's current pricing is read from the actor details endpoint; the run
  is refused (SourceError) when it is not a pay-per-event or per-result price (rental, free, unknown), or when the planned
  cost, start fees plus `max_items` times the dearest per-result price, would exceed the daily cap.

The key (`config.apify_key()`, read per run before any client is created) travels only in the `Authorization: Bearer`
header, never in a URL. It is registered with `redact`, which also masks any `Bearer <token>` text; the loggers used here
carry a `RedactingFilter`, and every SourceError is built from redacted text outside any `except` block (HTTP failures
give only the status code and a body excerpt cut to 200 characters), so no chained exception carries the key. Nothing
stores the key.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx
import pandas as pd

from tp import config
from tp.collect import datasets, state
from tp.collect.datasets import Dataset
from tp.collect.source import (
    RateLimited,
    RunContext,
    Source,
    SourceError,
    parse_schedule,
)
from tp.collect.state import State

log = logging.getLogger(__name__)

API = "https://api.apify.com/v2"
HARD_MONTHLY_CAP_USD = 4.0  # 80% of the $5 free credit
EPSILON = 1e-9
RETRY_AFTER_S = 600
RUN_TIMEOUT_S = 600  # the actor's own run timeout
WAIT_TOTAL_S = 600  # the most this source waits for a run
WAIT_STEP_S = 30  # waitForFinish per poll (the API allows up to 60)
POLL_PAUSE_S = 1.0
POLL_ATTEMPTS = 3  # status reads tried before the run is given up on
POLL_RETRY_PAUSE_S = 5.0
MAX_ITEMS_LIMIT = 1000
EXCERPT_CHARS = 200
TERMINAL = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}
ACTOR = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
API_ID = re.compile(r"[A-Za-z0-9_-]+")
BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
NUMERIC_FIELDS = ("amount_min", "amount_max")
KEEP_DAYS = 40


# ---- secret handling ----------------------------------------------------------------------------------------------

_SECRETS: set[str] = set()


def register_secret(secret: str) -> None:
    """Make `redact` mask `secret` (and its URL-quoted form) from now on."""
    if secret:
        _SECRETS.update({secret, quote(secret, safe="")})


def redact(text: str) -> str:
    """`text` with every registered secret and every `Bearer <token>` replaced."""
    for secret in sorted(_SECRETS, key=len, reverse=True):
        text = text.replace(secret, "[redacted]")
    return BEARER.sub("Bearer [redacted]", text)


def excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    """Redacted, whitespace-collapsed text cut to `limit` characters."""
    return " ".join(redact(text).split())[:limit]


class RedactingFilter(logging.Filter):
    """Rewrites every record passing through the logger so it carries no secret, in the message or the traceback."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - nothing may escape unredacted
            message = f"{record.msg} {record.args!r}"
        record.msg, record.args = redact(message), None
        if record.exc_info:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


for _name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"):
    logging.getLogger(_name).addFilter(RedactingFilter())
log.addFilter(RedactingFilter())


def _fail(message: str) -> SourceError:
    return SourceError(redact(f"Congress trades: {message}"))


# ---- spend ledger -------------------------------------------------------------------------------------------------


def ledger_path() -> Path:
    return config.DATA_DIR / "collect" / "apify_spend.json"


class LedgerError(Exception):
    """The ledger file exists but cannot be trusted."""


def _utc(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("ledger times must be timezone-aware")
    return now.astimezone(UTC)


def _month(now: datetime) -> str:
    return f"{_utc(now):%Y-%m}"


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _valid_cost(value: object) -> bool:
    number = _number(value)
    return number is not None and number >= 0


class SpendLedger:
    """Apify spend per UTC calendar month and the UTC days a run was started, persisted as JSON via an atomic replace."""

    def __init__(self, path: Path, monthly_cap_usd: float = HARD_MONTHLY_CAP_USD) -> None:
        self.path = Path(path)
        self.monthly_cap_usd = monthly_cap_usd

    def _load(self) -> dict:
        try:
            raw = self.path.read_text()
        except FileNotFoundError:
            return {"months": {}, "started": []}
        except OSError as e:
            raise LedgerError(f"cannot read {self.path.name}: {type(e).__name__}") from None
        try:
            data = json.loads(raw)
            months, started = data["months"], data["started"]
            ok = (
                isinstance(months, dict) and isinstance(started, list)
                and all(isinstance(k, str) and _valid_cost(v) for k, v in months.items())
                and all(isinstance(d, str) for d in started)
            )
        except (ValueError, KeyError, TypeError):
            ok = False
        if not ok:
            raise LedgerError(f"{self.path.name} is not a valid ledger")
        return {"months": months, "started": started}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        try:
            with open(tmp, "w") as f:
                f.write(json.dumps(data, sort_keys=True))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def exists(self) -> bool:
        return self.path.exists()

    def is_empty(self) -> bool:
        """True before any run has ever been started or booked."""
        data = self._load()
        return not any(data["months"].values()) and not data["started"]

    def month_total(self, now: datetime) -> float:
        return float(self._load()["months"].get(_month(now), 0.0))

    def _bump(self, data: dict, now: datetime, delta: float) -> None:
        key = _month(now)
        total = round(max(float(data["months"].get(key, 0.0)) + delta, 0.0), 9)
        if total > 0:
            data["months"][key] = total
        else:
            data["months"].pop(key, None)

    def add(self, now: datetime, usd: float) -> None:
        if (value := _number(usd)) is None or value < 0:
            raise ValueError(f"cost must be a non-negative number, got {usd!r}")
        data = self._load()
        self._bump(data, now, value)
        self._save(data)

    def allowed(self, now: datetime, planned_usd: float) -> bool:
        """False once this month's total plus the planned cost would pass the monthly cap."""
        return self.month_total(now) + planned_usd <= self.monthly_cap_usd + EPSILON

    def started_on(self, now: datetime) -> bool:
        return f"{_utc(now):%Y-%m-%d}" in self._load()["started"]

    def reserve(self, now: datetime, usd: float) -> None:
        """One atomic write: add `usd` to the month's total and record the UTC day as started. Done BEFORE a run is
        requested, so whatever happens afterwards the ledger is over-booked rather than short."""
        if (value := _number(usd)) is None or value < 0:
            raise ValueError(f"reservation must be a non-negative number, got {usd!r}")
        data = self._load()
        today = _utc(now)
        horizon = f"{today - timedelta(days=KEEP_DAYS):%Y-%m-%d}"
        data["started"] = sorted({*(d for d in data["started"] if d >= horizon), f"{today:%Y-%m-%d}"})
        self._bump(data, now, value)
        self._save(data)

    def release(self, now: datetime, usd: float) -> None:
        """Undo `reserve` after a definite rejection: take `usd` back and forget the day marker."""
        data = self._load()
        data["started"] = [d for d in data["started"] if d != f"{_utc(now):%Y-%m-%d}"]
        self._bump(data, now, -usd)
        self._save(data)

    def settle(self, now: datetime, actual_usd: float | None, reserved_usd: float) -> None:
        """Replace a reservation by the actual cost (books `actual - reserved`). An unknown actual (None) leaves the
        reservation as booked; the month's total never goes below zero."""
        if actual_usd is None:
            return
        if (value := _number(actual_usd)) is None or value < 0:
            raise ValueError(f"cost must be a non-negative number, got {actual_usd!r}")
        data = self._load()
        self._bump(data, now, value - reserved_usd)
        self._save(data)


# ---- settings -----------------------------------------------------------------------------------------------------


class _Plan:
    """The validated settings of one run."""

    def __init__(self, settings: dict) -> None:
        apify = settings.get("apify")
        cfg = (settings.get("sources") or {}).get("congress_trades")
        if not isinstance(apify, dict) or not isinstance(cfg, dict):
            raise _fail("config/collect.toml needs [apify] and [sources.congress_trades]")
        monthly, daily = _number(apify.get("monthly_cap_usd")), _number(apify.get("daily_run_cap_usd"))
        if monthly is None or daily is None or monthly <= 0 or daily <= 0:
            raise _fail("[apify] monthly_cap_usd and daily_run_cap_usd must be positive numbers")
        self.monthly_cap = min(monthly, HARD_MONTHLY_CAP_USD)
        if daily > self.monthly_cap:
            raise _fail("[apify] daily_run_cap_usd is above the monthly cap")
        self.daily_cap = daily
        actor = cfg.get("actor")
        if not isinstance(actor, str) or not ACTOR.fullmatch(actor):
            raise _fail("[sources.congress_trades] actor must be '<owner>/<name>'")
        self.actor = actor.replace("/", "~")
        items = cfg.get("max_items")
        if isinstance(items, bool) or not isinstance(items, int) or not 0 < items <= MAX_ITEMS_LIMIT:
            raise _fail(f"[sources.congress_trades] max_items must be an integer from 1 to {MAX_ITEMS_LIMIT}")
        self.max_items = items
        fields = cfg.get("fields")
        if not isinstance(fields, dict) or not fields or not all(
                isinstance(k, str) and k and isinstance(v, str) and v for k, v in fields.items()):
            raise _fail("[sources.congress_trades.fields] must map output columns to actor fields")
        self.fields: dict[str, str] = fields
        ts_field = cfg.get("ts_field")
        if not isinstance(ts_field, str) or not ts_field:
            raise _fail("[sources.congress_trades] ts_field must name the actor's disclosure timestamp field")
        self.ts_field = ts_field
        id_field = cfg.get("id_field", "")
        id_fields = cfg.get("id_fields")
        if not isinstance(id_field, str) or not isinstance(id_fields, list) or not id_fields or not all(
                isinstance(c, str) and c in fields for c in id_fields):
            raise _fail("[sources.congress_trades] id_fields must list columns of [fields]; id_field must be a string")
        self.id_field, self.id_fields = id_field, id_fields
        limit_field, extra = cfg.get("item_limit_field", "maxItems"), cfg.get("input", {})
        if not isinstance(limit_field, str) or not limit_field or not isinstance(extra, dict):
            raise _fail("[sources.congress_trades] item_limit_field must be a string and input a table")
        self.body = {**extra, limit_field: items}

    @property
    def columns(self) -> list[str]:
        return ["source_id", "ts", *self.fields]


def _empty(plan: _Plan) -> pd.DataFrame:
    frame = pd.DataFrame({c: pd.Series(dtype="str") for c in plan.columns})
    frame["ts"] = pd.Series(dtype="datetime64[us, UTC]")
    for col in NUMERIC_FIELDS:
        if col in frame:
            frame[col] = pd.Series(dtype="float64")
    return frame


# ---- HTTP ---------------------------------------------------------------------------------------------------------


def _default_http() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=False)


class _Api:
    """Apify REST calls: the key rides in the header of each request and nothing is added to the URL."""

    def __init__(self, http: httpx.Client, key: str) -> None:
        self.http = http
        self.headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}

    def send(self, method: str, path: str, what: str, params: dict | None = None, body: dict | None = None):
        failure = None
        try:
            r = self.http.request(method, f"{API}{path}", headers=self.headers, params=params, json=body)
        except httpx.HTTPError as e:
            failure = f"{what}: {type(e).__name__}: {e}"
        if failure is not None:
            raise _fail(failure)
        if r.status_code == 429:
            err = RateLimited(redact(f"Congress trades: {what}: rate limited (HTTP 429)"), RETRY_AFTER_S)
            err.status = 429
            raise err
        if not 200 <= r.status_code < 300:
            err = _fail(f"{what}: HTTP {r.status_code}: {excerpt(r.text)}")
            err.status = r.status_code
            raise err
        try:
            return r.json()
        except ValueError:
            failure = f"{what}: response is not JSON"
        raise _fail(failure)

    def run(self, method: str, path: str, what: str, params: dict | None = None, body: dict | None = None) -> dict:
        """The `data` object of a run response."""
        data = self.send(method, path, what, params, body)
        data = data.get("data") if isinstance(data, dict) else None
        if not isinstance(data, dict):
            raise _fail(f"{what}: response has no run object")
        return data


def planned_cost(details: object, max_items: int) -> float | None:
    """USD one run of `max_items` results could cost under the actor's current pricing, or None when the details do
    not state a per-result price: start events once, plus `max_items` times the dearest other event (the top tier)."""
    data = details.get("data") if isinstance(details, dict) else None
    infos = data.get("pricingInfos") if isinstance(data, dict) else None
    info = infos[-1] if isinstance(infos, list) and infos and isinstance(infos[-1], dict) else None
    if info is None:
        return None
    if info.get("pricingModel") == "PRICE_PER_DATASET_ITEM":
        price = _number(info.get("pricePerUnitUsd"))
        return None if price is None else price * max_items
    if info.get("pricingModel") != "PAY_PER_EVENT":
        return None
    per_event = info.get("pricingPerEvent")
    events = per_event.get("actorChargeEvents") if isinstance(per_event, dict) else None
    if not isinstance(events, dict) or not events:
        return None
    start, per_item = 0.0, 0.0
    for name, event in events.items():
        prices = [_number(event.get("eventPriceUsd"))] if isinstance(event, dict) else []
        tiers = event.get("eventTieredPricingUsd") if isinstance(event, dict) else None
        if isinstance(tiers, dict):
            prices += [_number(t.get("tieredEventPriceUsd")) for t in tiers.values() if isinstance(t, dict)]
        known = [p for p in prices if p is not None and p >= 0]
        if not known:
            return None
        if "start" in str(name).lower():
            start += max(known)
        else:
            per_item = max(per_item, max(known))
    return start + per_item * max_items


def _cost_of(run: dict) -> float | None:
    cost = _number(run.get("usageTotalUsd"))
    return cost if cost is not None and cost >= 0 else None


# ---- rows ---------------------------------------------------------------------------------------------------------


def _text(value: object) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True) if isinstance(value, (list, dict)) else str(value)


def _timestamp(value: object) -> pd.Timestamp | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        stamp = pd.Timestamp(value.strip())
    except (ValueError, TypeError):
        return None
    if pd.isna(stamp):
        return None
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def parse_items(items: object, plan: _Plan) -> pd.DataFrame:
    """Frame of source_id, ts and the mapped fields from the dataset items. Rows without a usable disclosure timestamp
    are dropped (counted in a warning); SourceError when the body is not a list of objects or none is usable."""
    if not isinstance(items, list) or not all(isinstance(it, dict) for it in items):
        raise _fail("the dataset is not a list of objects")
    rows: list[dict] = []
    dropped = 0
    for it in items:
        stamp = _timestamp(it.get(plan.ts_field))
        if stamp is None:
            dropped += 1
            continue
        text = {col: _text(it.get(src)) for col, src in plan.fields.items()}
        own = _text(it.get(plan.id_field)) if plan.id_field else None
        digest = hashlib.sha1(json.dumps([text[c] for c in plan.id_fields]).encode()).hexdigest()
        rows.append({"source_id": own or digest, "ts": stamp, **text})
    if dropped:
        log.warning("congress_trades: dropping %d of %d rows without a usable %s", dropped, len(items), plan.ts_field)
    if items and not rows:
        raise _fail(f"no row has a usable {plan.ts_field}")
    if not rows:
        return _empty(plan)
    frame = pd.DataFrame(rows, columns=plan.columns)
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True).astype("datetime64[us, UTC]")
    for col in plan.fields:
        frame[col] = pd.to_numeric(frame[col], errors="coerce") if col in NUMERIC_FIELDS else frame[col].astype("str")
    return frame.drop_duplicates("source_id", keep="first").reset_index(drop=True)


# ---- the source ---------------------------------------------------------------------------------------------------


def _dig(body: object, *path: str) -> object:
    for part in path:
        body = body.get(part) if isinstance(body, dict) else None
    return body


def earlier_runs_exist() -> bool:
    """True when this source has run before: a last_success in the daemon state file or a stored dataset file.
    Read-only (an unreadable state file counts as no evidence; the dataset file is checked anyway)."""
    try:
        data = json.loads(state.default_path().read_text())
        if isinstance(data, dict) and State(data=data).last_success("congress_trades") is not None:
            return True
    except (OSError, ValueError, TypeError):
        pass
    return datasets.dataset("congress_trades").path.exists()


class CongressTrades(Source):
    name = "congress_trades"
    rate_group = "apify"

    def __init__(
        self,
        schedule: str = "daily 08:30 America/New_York",
        lag_minutes: int = 0,
        http_factory: Callable[[], httpx.Client] | None = None,
        key_provider: Callable[[], str] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.schedule = parse_schedule(schedule)
        self.lag = timedelta(minutes=lag_minutes)
        self.datasets = (datasets.dataset("congress_trades"),)
        self._http_factory = http_factory or _default_http
        self._key_provider = key_provider or config.apify_key
        self._monotonic = monotonic
        self._sleep = sleep

    def _key(self) -> str:
        failure, key = None, ""
        try:
            key = self._key_provider()
        except ValueError:
            failure = "APIFY_API_KEY is not set (add it to .env)"
        except Exception as e:  # noqa: BLE001 - nothing may escape unredacted
            failure = f"cannot read APIFY_API_KEY: {type(e).__name__}"
        if failure is None and (not key or not key.isprintable() or any(c.isspace() for c in key)):
            failure = "APIFY_API_KEY is malformed"
        if failure is not None:
            raise _fail(failure)
        register_secret(key)
        return key

    def _check_account(self, api: _Api, plan: _Plan) -> None:
        """Fail closed on the account's real month-to-date usage, whatever else spends from the same credit."""
        body = api.send("GET", "/users/me/limits", "account limits")
        usage = _number(_dig(body, "data", "current", "monthlyUsageUsd"))
        limit = _number(_dig(body, "data", "limits", "maxMonthlyUsageUsd"))
        if usage is None or limit is None or usage < 0 or limit <= 0:
            raise _fail("account usage and limit could not be read from the limits response; refusing to run")
        cap = min(plan.monthly_cap, limit)
        if usage + plan.daily_cap > cap + EPSILON:
            raise _fail(f"the account's usage ${usage:.4f} plus the daily cap ${plan.daily_cap:.2f} would pass "
                        f"${cap:.2f} for the month; refusing to run")

    def _check_pricing(self, api: _Api, plan: _Plan) -> None:
        details = api.send("GET", f"/acts/{plan.actor}", "actor details")
        planned = planned_cost(details, plan.max_items)
        if planned is None:
            raise _fail(f"the pricing of {plan.actor} is not a per-result or pay-per-event price (rental, free or "
                        "unknown); refusing to run")
        if planned > plan.daily_cap + EPSILON:
            raise _fail(f"actor pricing implies up to ${planned:.4f} for {plan.max_items} results, above the daily "
                        f"cap ${plan.daily_cap:.2f}; refusing to run")

    def _poll(self, api: _Api, run_id: str, wait: int) -> dict:
        """One status read, retried a couple of times so a network blip does not abort a healthy run."""
        for attempt in range(1, POLL_ATTEMPTS + 1):
            try:
                return api.run("GET", f"/actor-runs/{run_id}", "run status", params={"waitForFinish": wait})
            except SourceError:
                if attempt == POLL_ATTEMPTS:
                    raise
                log.warning("congress_trades: status read %d of %d failed, retrying", attempt, POLL_ATTEMPTS)
                self._sleep(POLL_RETRY_PAUSE_S)
        raise AssertionError("unreachable")

    def _await(self, api: _Api, run_id: str) -> dict | None:
        """The run object once it reaches a terminal status, or None when WAIT_TOTAL_S passes first."""
        deadline = self._monotonic() + WAIT_TOTAL_S
        while True:
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return None
            run = self._poll(api, run_id, int(min(WAIT_STEP_S, max(1, remaining))))
            if run.get("status") in TERMINAL:
                return run
            self._sleep(POLL_PAUSE_S)

    def _abort(self, api: _Api, run_id: str) -> dict | None:
        """Best effort: abort the run and return its latest object (or the abort reply) for the cost."""
        try:
            reply = api.run("POST", f"/actor-runs/{run_id}/abort", "abort run")
        except SourceError as e:
            log.warning("congress_trades: could not abort run %s: %s", run_id, e)
            return None
        try:
            return api.run("GET", f"/actor-runs/{run_id}", "run status", params={"waitForFinish": WAIT_STEP_S})
        except SourceError:
            return reply

    def _settle(self, ledger: SpendLedger, now: datetime, plan: _Plan, *runs: dict | None) -> None:
        """Replace the reservation by the cost a TERMINAL run object reports. When none does (unknown cost, or the run
        is still ABORTING/RUNNING) the reservation stays, raised to the highest cost reported."""
        known = [r for r in runs if r]
        actual = next((c for r in known if r.get("status") in TERMINAL and (c := _cost_of(r)) is not None), None)
        if actual is None:
            reported = max((c for r in known if (c := _cost_of(r)) is not None), default=0.0)
            actual = max(reported, plan.daily_cap)
            log.warning("congress_trades: no final cost known for the run, keeping $%.4f booked", actual)
        failure = None
        try:
            ledger.settle(now, actual, plan.daily_cap)
        except (LedgerError, OSError, ValueError) as e:
            failure = (f"could not settle the run's cost ${actual:.4f} in the ledger ({type(e).__name__}); the "
                       f"reservation of ${plan.daily_cap:.2f} stays booked")
        if failure is not None:
            raise _fail(failure)
        log.info("congress_trades: run booked at $%.4f", actual)

    def _reserve(self, ledger: SpendLedger, now: datetime, plan: _Plan) -> None:
        failure = None
        try:
            ledger.reserve(now, plan.daily_cap)
        except (LedgerError, OSError, ValueError) as e:
            failure = f"could not reserve the run's cost in the ledger ({type(e).__name__}); not starting a run"
        if failure is not None:
            raise _fail(failure)

    def _release(self, ledger: SpendLedger, now: datetime, plan: _Plan) -> None:
        try:
            ledger.release(now, plan.daily_cap)
        except (LedgerError, OSError, ValueError) as e:
            log.warning("congress_trades: could not release the reservation (%s); it stays booked", type(e).__name__)

    def _start(self, api: _Api, ledger: SpendLedger, plan: _Plan, now: datetime) -> str:
        """Reserve the daily cap, then ask for the run. Only a definite rejection (HTTP 4xx) releases the reservation:
        after a transport error or a 5xx the run may exist, so the reservation and the day marker stay."""
        self._reserve(ledger, now, plan)
        params = {"maxTotalChargeUsd": f"{plan.daily_cap:g}", "timeout": RUN_TIMEOUT_S, "maxItems": plan.max_items}
        try:
            started = api.run("POST", f"/acts/{plan.actor}/runs", "start run", params=params, body=plan.body)
        except SourceError as e:
            if 400 <= (getattr(e, "status", None) or 0) < 500:
                self._release(ledger, now, plan)
            raise
        run_id = started.get("id")
        if not isinstance(run_id, str) or not API_ID.fullmatch(run_id):
            raise _fail("start run: response has no usable run id; the reservation stays booked")
        log.info("congress_trades: started run %s, maxTotalChargeUsd %g", run_id, plan.daily_cap)
        return run_id

    def _run(self, api: _Api, ledger: SpendLedger, plan: _Plan, now: datetime) -> pd.DataFrame:
        run_id = self._start(api, ledger, plan, now)
        try:
            final = self._await(api, run_id)
        except SourceError:
            self._settle(ledger, now, plan, self._abort(api, run_id))
            raise
        if final is None:
            self._settle(ledger, now, plan, self._abort(api, run_id))
            raise _fail(f"run {run_id} did not finish within {WAIT_TOTAL_S} s and was aborted")
        self._settle(ledger, now, plan, final)
        status = final.get("status")
        if status != "SUCCEEDED":
            detail = excerpt(str(final.get("statusMessage") or ""))
            raise _fail(f"run {run_id} ended {status}" + (f": {detail}" if detail else ""))
        dataset_id = final.get("defaultDatasetId")
        if not isinstance(dataset_id, str) or not API_ID.fullmatch(dataset_id):
            raise _fail(f"run {run_id} has no usable default dataset")
        items = api.send("GET", f"/datasets/{dataset_id}/items", "dataset items",
                         params={"format": "json", "clean": "true", "limit": plan.max_items})
        return parse_items(items, plan)

    def fetch(self, ctx: RunContext) -> dict[Dataset, pd.DataFrame]:
        plan = _Plan(ctx.settings)
        ds = self.datasets[0]
        now = _utc(ctx.now)
        ledger = SpendLedger(ledger_path(), plan.monthly_cap)
        failure = None
        try:
            if not ledger.exists() and earlier_runs_exist():
                failure = ("apify ledger missing but earlier runs exist; restore data/collect/apify_spend.json or "
                           "confirm spend (recreate it with the month's real spend)")
            elif ledger.started_on(now):
                log.warning("congress_trades: a run was already started on %s UTC, not starting another",
                            f"{now:%Y-%m-%d}")
                return {ds: _empty(plan)}
            elif not ledger.allowed(now, plan.daily_cap):
                failure = (f"this month's Apify spend ${ledger.month_total(now):.4f} plus the daily cap "
                           f"${plan.daily_cap:.2f} would pass the monthly cap ${plan.monthly_cap:.2f}; refusing to run")
            first = failure is None and ledger.is_empty()
        except LedgerError as e:
            failure = f"the Apify spend ledger is unusable ({e}); refusing to run"
        except OSError as e:
            failure = f"the Apify spend ledger cannot be read ({type(e).__name__}); refusing to run"
        if failure is not None:
            raise _fail(failure)
        key = self._key()
        http = self._http_factory()
        api = _Api(http, key)
        failure = None
        try:
            self._check_account(api, plan)
            if first:
                self._check_pricing(api, plan)
            return {ds: self._run(api, ledger, plan, now)}
        except SourceError:
            raise
        except Exception as e:  # noqa: BLE001 - nothing may escape unredacted
            failure = f"unexpected {type(e).__name__}: {e}"
        finally:
            http.close()
        raise _fail(failure)
