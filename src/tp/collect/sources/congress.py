"""Congress stock trades from a paid Apify actor, guarded so the free monthly credit cannot be overspent.

Once a day the source starts ONE run of the actor named in `[sources.congress_trades] actor` (never hardcoded), waits for
it, reads the run's default dataset and returns the trades as rows. There is no backfill: the actor is asked only for its
recent lookback window and rows already stored are dropped by the writer. A row's `ts` is the disclosure timestamp in UTC
(a date-only value is midnight UTC, so a strategy must enter at the next open after that day has closed) and its
`source_id` is the actor's own id field when `id_field` is set, else a hash of the `id_fields` columns.

Spend guard (all of it applies before and around every run):
- `SpendLedger` (data/collect/apify_spend.json, replaced atomically) totals the cost per UTC calendar month. No run is
  started, and no HTTP call is made at all, when the month's total plus `[apify] daily_run_cap_usd` would pass
  `monthly_cap_usd`; the cap is clamped to 4.0, 80% of the $5 credit. A ledger that cannot be read refuses the run
  rather than counting from zero.
- Every run is started with `maxTotalChargeUsd = daily_run_cap_usd`, an item limit and a run timeout; the wait is bounded
  (WAIT_TOTAL_S) and a run still going after it is aborted.
- At most one run is started per UTC day, including after a failure: a failed run is not retried the same day.
- The ACTUAL cost (`usageTotalUsd` of the run object) is added to the ledger whatever the run's status. A finished run
  that reports no cost, or a run whose state could not be read after it started, is booked at the daily cap.
- Before the first ever run (empty ledger) the actor's current pricing is read from the actor details endpoint; the run
  is refused (SourceError) when the planned cost, start fees plus `max_items` times the dearest per-result price, would
  exceed the daily cap. When the pricing cannot be determined from the response, the hard caps above (maxTotalChargeUsd
  and the item limit) alone bound the spend and the run goes ahead.

The key (`config.apify_key()`, read per run) travels only in the `Authorization: Bearer` header, never in a URL. It is
registered with `redact`, which also masks any `Bearer <token>` text; the loggers used here carry a `RedactingFilter`,
and every SourceError is built from redacted text (HTTP failures give only the status code and a body excerpt cut to 200
characters, and are raised `from None` so no chained exception can carry the key). Nothing stores the key.
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
from tp.collect import datasets
from tp.collect.datasets import Dataset
from tp.collect.source import (
    RateLimited,
    RunContext,
    Source,
    SourceError,
    parse_schedule,
)

log = logging.getLogger(__name__)

API = "https://api.apify.com/v2"
HARD_MONTHLY_CAP_USD = 4.0  # 80% of the $5 free credit
EPSILON = 1e-9
RETRY_AFTER_S = 600
RUN_TIMEOUT_S = 600  # the actor's own run timeout
WAIT_TOTAL_S = 600  # the most this source waits for a run
WAIT_STEP_S = 30  # waitForFinish per poll (the API allows up to 60)
POLL_PAUSE_S = 1.0
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
            tmp.write_text(json.dumps(data, sort_keys=True))
            os.replace(tmp, self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def is_empty(self) -> bool:
        """True before any run has ever been started or booked."""
        data = self._load()
        return not data["months"] and not data["started"]

    def month_total(self, now: datetime) -> float:
        return float(self._load()["months"].get(_month(now), 0.0))

    def add(self, now: datetime, usd: float) -> None:
        if (value := _number(usd)) is None or value < 0:
            raise ValueError(f"cost must be a non-negative number, got {usd!r}")
        data = self._load()
        key = _month(now)
        data["months"][key] = round(float(data["months"].get(key, 0.0)) + value, 9)
        self._save(data)

    def allowed(self, now: datetime, planned_usd: float) -> bool:
        """False once this month's total plus the planned cost would pass the monthly cap."""
        return self.month_total(now) + planned_usd <= self.monthly_cap_usd + EPSILON

    def started_on(self, now: datetime) -> bool:
        return f"{_utc(now):%Y-%m-%d}" in self._load()["started"]

    def mark_started(self, now: datetime) -> None:
        data = self._load()
        today = _utc(now)
        horizon = f"{today - timedelta(days=KEEP_DAYS):%Y-%m-%d}"
        data["started"] = sorted({*(d for d in data["started"] if d >= horizon), f"{today:%Y-%m-%d}"})
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
        try:
            r = self.http.request(method, f"{API}{path}", headers=self.headers, params=params, json=body)
        except httpx.HTTPError as e:
            raise _fail(f"{what}: {type(e).__name__}: {e}") from None
        if r.status_code == 429:
            raise RateLimited(redact(f"Congress trades: {what}: rate limited (HTTP 429)"), RETRY_AFTER_S) from None
        if not 200 <= r.status_code < 300:
            raise _fail(f"{what}: HTTP {r.status_code}: {excerpt(r.text)}")
        try:
            return r.json()
        except ValueError:
            raise _fail(f"{what}: response is not JSON") from None

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
        try:
            key = self._key_provider()
        except ValueError:
            raise _fail("APIFY_API_KEY is not set (add it to .env)") from None
        except Exception as e:  # noqa: BLE001 - nothing may escape unredacted
            raise _fail(f"cannot read APIFY_API_KEY: {type(e).__name__}") from None
        if not key or not key.isprintable() or any(c.isspace() for c in key):
            raise _fail("APIFY_API_KEY is malformed")
        register_secret(key)
        return key

    def _check_pricing(self, api: _Api, plan: _Plan) -> None:
        details = api.send("GET", f"/acts/{plan.actor}", "actor details")
        planned = planned_cost(details, plan.max_items)
        if planned is None:
            log.warning("congress_trades: pricing of %s not determinable; maxTotalChargeUsd and the item limit bound "
                        "the spend", plan.actor)
        elif planned > plan.daily_cap + EPSILON:
            raise _fail(f"actor pricing implies up to ${planned:.4f} for {plan.max_items} results, above the daily "
                        f"cap ${plan.daily_cap:.2f}; refusing to run")

    def _await(self, api: _Api, run_id: str) -> dict | None:
        """The run object once it reaches a terminal status, or None when WAIT_TOTAL_S passes first."""
        deadline = self._monotonic() + WAIT_TOTAL_S
        while True:
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return None
            wait = int(min(WAIT_STEP_S, max(1, remaining)))
            run = api.run("GET", f"/actor-runs/{run_id}", "run status", params={"waitForFinish": wait})
            if run.get("status") in TERMINAL:
                return run
            self._sleep(POLL_PAUSE_S)

    def _abort(self, api: _Api, run_id: str) -> dict | None:
        """Best effort: abort the run and return its final object (or the abort reply) for the cost."""
        try:
            reply = api.run("POST", f"/actor-runs/{run_id}/abort", "abort run")
            try:
                return api.run("GET", f"/actor-runs/{run_id}", "run status", params={"waitForFinish": WAIT_STEP_S})
            except SourceError:
                return reply
        except SourceError as e:
            log.warning("congress_trades: could not abort run %s: %s", run_id, e)
            return None

    def _book(self, ledger: SpendLedger, now: datetime, plan: _Plan, run: dict | None, *fallbacks: dict | None) -> float:
        """Add the run's reported cost to the ledger, or the daily cap when no object reports one."""
        cost = next((c for c in (_cost_of(r) for r in (run, *fallbacks) if r) if c is not None), None)
        if cost is None:
            cost = plan.daily_cap
            log.warning("congress_trades: no cost reported for the run, booking the daily cap $%.2f", cost)
        try:
            ledger.add(now, cost)
        except (LedgerError, OSError, ValueError) as e:
            raise _fail(f"could not record the run's cost ${cost:.4f} in the ledger: {type(e).__name__}") from None
        log.info("congress_trades: run cost $%.4f", cost)
        return cost

    def _run(self, api: _Api, ledger: SpendLedger, plan: _Plan, now: datetime) -> pd.DataFrame:
        params = {"maxTotalChargeUsd": f"{plan.daily_cap:g}", "timeout": RUN_TIMEOUT_S}
        started = api.run("POST", f"/acts/{plan.actor}/runs", "start run", params=params, body=plan.body)
        run_id = started.get("id")
        if not isinstance(run_id, str) or not API_ID.fullmatch(run_id):
            raise _fail("start run: response has no usable run id")
        try:
            ledger.mark_started(now)
        except (LedgerError, OSError) as e:
            log.warning("congress_trades: could not mark the day as started: %s", type(e).__name__)
        log.info("congress_trades: started run %s, maxTotalChargeUsd %g", run_id, plan.daily_cap)
        try:
            final = self._await(api, run_id)
        except SourceError:
            self._abort(api, run_id)
            self._book(ledger, now, plan, None)
            raise
        if final is None:
            aborted = self._abort(api, run_id)
            self._book(ledger, now, plan, aborted)
            raise _fail(f"run {run_id} did not finish within {WAIT_TOTAL_S} s and was aborted")
        self._book(ledger, now, plan, final)
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
        try:
            if ledger.started_on(now):
                log.info("congress_trades: a run was already started on %s UTC, not starting another", f"{now:%Y-%m-%d}")
                return {ds: _empty(plan)}
            if not ledger.allowed(now, plan.daily_cap):
                raise _fail(f"this month's Apify spend ${ledger.month_total(now):.4f} plus the daily cap "
                            f"${plan.daily_cap:.2f} would pass the monthly cap ${plan.monthly_cap:.2f}; refusing to run")
            first = ledger.is_empty()
        except LedgerError as e:
            raise _fail(f"the Apify spend ledger is unusable ({e}); refusing to run") from None
        except OSError as e:
            raise _fail(f"the Apify spend ledger cannot be read ({type(e).__name__}); refusing to run") from None
        api = _Api(http := self._http_factory(), self._key())
        try:
            if first:
                self._check_pricing(api, plan)
            return {ds: self._run(api, ledger, plan, now)}
        except SourceError:
            raise
        except Exception as e:  # noqa: BLE001 - nothing may escape unredacted
            raise _fail(f"unexpected {type(e).__name__}: {e}") from None
        finally:
            http.close()
