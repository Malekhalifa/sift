import json
import logging
import os
import traceback
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import pytest

from tp import config
from tp.collect import datasets, store
from tp.collect.source import RateLimited, RunContext, SourceError
from tp.collect.sources import build_sources, source_settings
from tp.collect.sources import congress as cg
from tp.collect.sources.congress import CongressTrades, SpendLedger

KEY = "apify_api_FAKEKEY0123456789abcdefXYZ"
ACTOR = "someone/congress-feed"
NOW = datetime(2026, 11, 12, 13, 30, tzinfo=UTC)
FIELDS = {
    "politician": "politician", "chamber": "chamber", "ticker": "ticker", "transaction_type": "transactionType",
    "amount_range": "amountRange", "amount_min": "amountMin", "amount_max": "amountMax",
    "traded_date": "transactionDate", "disclosure_date": "disclosureDate", "owner": "owner",
    "asset_name": "assetName", "filing_url": "filingUrl",
}
CONGRESS = {
    "schedule": "daily 08:30 America/New_York", "lag_minutes": 0, "actor": ACTOR, "max_items": 10,
    "item_limit_field": "maxItems", "ts_field": "disclosureDate", "id_field": "",
    "id_fields": ["filing_url", "politician", "ticker", "transaction_type", "traded_date", "amount_range", "owner",
                  "asset_name"],
    "input": {"lookbackDays": 7}, "fields": FIELDS,
}
SETTINGS = {
    "apify": {"monthly_cap_usd": 4.0, "daily_run_cap_usd": 0.05},
    "sources": {
        "alpaca_bars": {"schedule": "daily 21:00 America/New_York", "lag_minutes": 20},
        "sec_filings": {"schedule": "daily 07:30 America/New_York", "lag_minutes": 0},
        "sec_form4": {"schedule": "daily 08:00 America/New_York", "lag_minutes": 0},
        "sec_xbrl_shares": {"schedule": "weekly sun 09:00 America/New_York", "lag_minutes": 0},
        "finra_shortvol": {"schedule": "daily 18:30 America/New_York", "lag_minutes": 0},
        "finra_short_interest": {"schedule": "daily 09:00 America/New_York", "lag_minutes": 0},
        "dod_awards": {"schedule": "weekly mon 06:00 America/New_York", "lag_minutes": 0},
        "trump_posts": {"schedule": "daily 07:00 America/New_York", "lag_minutes": 0},
        "sp500_changes": {"schedule": "weekly sun 10:00 America/New_York", "lag_minutes": 0},
        "wikipedia_pageviews": {"schedule": "daily 06:30 UTC", "lag_minutes": 0},
        "congress_trades": CONGRESS,
    },
}


def trade(i: int = 0, **over) -> dict:
    row = {
        "chamber": "Senate", "politician": f"Sen Number{i}", "ticker": "MSFT", "transactionType": "Sale (Partial)",
        "transactionDate": "2026-10-15", "disclosureDate": "2026-11-02", "amountRange": "$1,001 - $15,000",
        "amountMin": 1001, "amountMax": 15000, "owner": "Spouse", "assetName": "Microsoft Corporation",
        "filingUrl": f"https://efdsearch.senate.gov/search/view/ptr/doc{i}/", "committees": ["x"],
    }
    return row | over


def run_object(status="SUCCEEDED", cost: object = 0.0312, rid="run1", **over) -> dict:
    data = {"id": rid, "status": status, "defaultDatasetId": "ds1", "usageTotalUsd": cost}
    if cost is None:
        del data["usageTotalUsd"]
    return {"data": data | over}


def pricing(*infos: dict) -> dict:
    return {"data": {"name": "congress-feed", "pricingInfos": list(infos)}}


PER_EVENT = {"pricingModel": "PAY_PER_EVENT", "pricingPerEvent": {"actorChargeEvents": {
    "trade": {"eventTitle": "A trade", "eventPriceUsd": 0.005}}}}


class FakeApify:
    """Plays the parts of the Apify REST API that the source uses and records every request it receives."""

    def __init__(self, items=None, run=None, polls=None, details=None, start_status=201):
        self.items = [trade(0), trade(1)] if items is None else items
        self.run = run or run_object()
        self.polls = polls or []  # statuses answered before the final run object
        self.details = details if details is not None else pricing(PER_EVENT)
        self.start_status = start_status
        self.requests: list[httpx.Request] = []
        self.abort_cost = 0.01

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path.startswith("/v2/acts/") and not path.endswith("/runs"):
            return self._reply(self.details)
        if request.method == "POST" and path.endswith("/runs"):
            if self.start_status != 201:
                return self._reply({"error": {"message": f"nope {KEY}"}}, self.start_status)
            return self._reply(run_object("RUNNING", None, rid=self.run["data"]["id"]), 201)
        if request.method == "POST" and path.endswith("/abort"):
            self.polls.clear()
            self.run = run_object("ABORTED", self.abort_cost, rid=self.run["data"]["id"])
            return self._reply(self.run)
        if request.method == "GET" and path.startswith("/v2/actor-runs/"):
            if self.polls:
                return self._reply(run_object(self.polls.pop(0), None, rid=self.run["data"]["id"]))
            return self._reply(self.run)
        if request.method == "GET" and path.startswith("/v2/datasets/"):
            return self._reply(self.items)
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    @staticmethod
    def _reply(body, status=200) -> httpx.Response:
        return httpx.Response(status, json=body)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def calls(self, method: str, suffix: str = "") -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path.endswith(suffix)]

    def starts(self) -> list[httpx.Request]:
        return self.calls("POST", "/runs")


class Clock:
    """Monotonic clock that advances only through sleep, so the bounded wait is deterministic."""

    def __init__(self, step: float = 0.0):
        self.t = 0.0
        self.step = step

    def now(self) -> float:
        self.t += self.step
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def make(api: FakeApify | None = None, key=KEY, clock: Clock | None = None):
    api = api or FakeApify()
    clock = clock or Clock()

    def provider() -> str:
        if key is None:
            raise ValueError("APIFY_API_KEY is not set")
        return key

    src = CongressTrades(http_factory=api.client, key_provider=provider, monotonic=clock.now, sleep=clock.sleep)
    return src, api


def ctx(now=NOW, settings=SETTINGS, writer=None) -> RunContext:
    return RunContext(now=now, settings=settings, writer=writer or (lambda ds, df: store.write(ds, df, now=now)))


def with_congress(**over) -> dict:
    return {**SETTINGS, "sources": {**SETTINGS["sources"], "congress_trades": CONGRESS | over}}


def ledger() -> SpendLedger:
    return SpendLedger(cg.ledger_path())


def frame(src: CongressTrades, c: RunContext | None = None) -> pd.DataFrame:
    return src.fetch(c or ctx())[datasets.dataset("congress_trades")]


@pytest.fixture(autouse=True)
def quiet_logs(caplog):
    caplog.set_level(logging.DEBUG)


def test_source_attributes_and_dataset():
    src, _ = make()
    assert src.name == "congress_trades" and src.rate_group == "apify"
    assert src.schedule.at.hour == 8 and src.schedule.at.minute == 30 and str(src.schedule.tz) == "America/New_York"
    ds = datasets.dataset("congress_trades")
    assert src.datasets == (ds,) and ds.key == ("source_id",) and ds.ts_col == "ts"


# ---- the spend ledger ---------------------------------------------------------------------------------------------


def test_ledger_refuses_when_the_month_would_pass_80_percent_of_the_credit(tmp_path):
    led = SpendLedger(tmp_path / "l.json")
    led.add(NOW, 3.95)
    assert led.allowed(NOW, 0.05) is True  # exactly at the cap is still allowed
    led.add(NOW, 0.01)
    assert led.allowed(NOW, 0.05) is False
    assert led.allowed(NOW, 0.0) is True


def test_run_is_refused_when_the_month_would_pass_80_percent_of_the_credit():
    src, api = make()
    ledger().add(NOW, 3.99)
    with pytest.raises(SourceError, match="monthly"):
        frame(src)
    assert api.requests == []


def test_ledger_persists_across_restarts_and_rolls_over_at_the_utc_month_boundary(tmp_path):
    path = tmp_path / "sub" / "l.json"
    SpendLedger(path).add(datetime(2026, 11, 30, 23, 59, tzinfo=UTC), 1.25)
    again = SpendLedger(path)
    assert again.month_total(datetime(2026, 11, 3, tzinfo=UTC)) == pytest.approx(1.25)
    again.add(datetime(2026, 11, 3, tzinfo=UTC), 0.5)
    assert SpendLedger(path).month_total(datetime(2026, 11, 30, tzinfo=UTC)) == pytest.approx(1.75)
    assert SpendLedger(path).month_total(datetime(2026, 12, 1, 0, 0, tzinfo=UTC)) == 0.0
    # 20:00 New York on 30 November is already 1 December in UTC.
    late = datetime(2026, 11, 30, 20, 0, tzinfo=ZoneInfo("America/New_York"))
    assert SpendLedger(path).month_total(late) == 0.0
    assert [p.name for p in path.parent.iterdir()] == ["l.json"]  # no temp file left behind
    assert set(json.loads(path.read_text())) <= {"months", "started"}


def test_ledger_rejects_naive_datetimes_and_negative_costs(tmp_path):
    led = SpendLedger(tmp_path / "l.json")
    with pytest.raises(ValueError):
        led.month_total(datetime(2026, 11, 1))  # noqa: DTZ001
    with pytest.raises(ValueError):
        led.add(NOW, -0.01)


def test_a_corrupt_ledger_refuses_the_run_instead_of_starting_from_zero():
    src, api = make()
    path = cg.ledger_path()
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    with pytest.raises(SourceError, match="ledger"):
        frame(src)
    assert api.requests == []
    assert path.read_text() == "{not json"


def test_ledger_lives_under_the_data_directory(tmp_data_dir):
    assert cg.ledger_path() == tmp_data_dir / "collect" / "apify_spend.json"


# ---- the run itself -----------------------------------------------------------------------------------------------


def test_every_run_sets_a_max_charge_equal_to_the_daily_cap():
    src, api = make()
    frame(src)
    (start,) = api.starts()
    query = parse_qs(start.url.query.decode())
    assert float(query["maxTotalChargeUsd"][0]) == 0.05
    assert json.loads(start.content) == {"lookbackDays": 7, "maxItems": 10}
    assert start.url.path == "/v2/acts/someone~congress-feed/runs"

    other, api2 = make()
    frame(other, ctx(now=NOW + timedelta(days=1), settings=with_congress() | {
        "apify": {"monthly_cap_usd": 4.0, "daily_run_cap_usd": 0.03}}))
    assert float(parse_qs(api2.starts()[0].url.query.decode())["maxTotalChargeUsd"][0]) == 0.03


def test_the_run_has_a_bounded_timeout_and_the_item_limit_cannot_be_overridden_by_input():
    src, api = make()
    frame(src, ctx(settings=with_congress(input={"maxItems": 100000, "lookbackDays": 3})))
    (start,) = api.starts()
    assert json.loads(start.content)["maxItems"] == 10
    assert 0 < int(parse_qs(start.url.query.decode())["timeout"][0]) <= 900


def test_actual_cost_is_added_to_the_ledger():
    src, _ = make(FakeApify(run=run_object(cost=0.0312)))
    frame(src)
    assert ledger().month_total(NOW) == pytest.approx(0.0312)
    src2, _ = make(FakeApify(run=run_object(cost=0.04)))
    frame(src2, ctx(now=NOW + timedelta(days=1)))
    assert ledger().month_total(NOW) == pytest.approx(0.0712)


def test_a_finished_run_without_a_cost_is_booked_at_the_daily_cap():
    src, _ = make(FakeApify(run=run_object(cost=None)))
    frame(src)
    assert ledger().month_total(NOW) == pytest.approx(0.05)
    src2, _ = make(FakeApify(run=run_object(cost="free")))
    frame(src2, ctx(now=NOW + timedelta(days=1)))
    assert ledger().month_total(NOW) == pytest.approx(0.10)


@pytest.mark.parametrize("status", ["FAILED", "ABORTED", "TIMED-OUT"])
def test_a_run_that_does_not_succeed_raises_and_still_records_its_cost(status):
    api = FakeApify(run=run_object(status, cost=0.021, statusMessage="actor crashed"))
    src, _ = make(api)
    with pytest.raises(SourceError, match=status):
        frame(src)
    assert ledger().month_total(NOW) == pytest.approx(0.021)
    assert api.calls("GET", "/items") == []


def test_polling_waits_for_the_run_with_wait_for_finish():
    api = FakeApify(polls=["RUNNING", "RUNNING"])
    src, _ = make(api)
    assert len(frame(src)) == 2
    polls = api.calls("GET", "/run1")
    assert len(polls) == 3 and all("waitForFinish" in p.url.params for p in polls)
    assert all(0 < int(p.url.params["waitForFinish"]) <= 60 for p in polls)


def test_a_run_that_outlives_the_bounded_wait_is_aborted_and_its_cost_recorded():
    api = FakeApify(polls=["RUNNING"] * 1000)
    clock = Clock(step=30.0)
    src, _ = make(api, clock=clock)
    with pytest.raises(SourceError, match="did not finish"):
        frame(src)
    assert len(api.calls("POST", "/abort")) == 1
    assert ledger().month_total(NOW) == pytest.approx(0.01)
    assert len(api.calls("GET", "/run1")) < 100  # bounded


def test_only_one_run_is_started_per_day_even_after_a_failure():
    api = FakeApify(run=run_object("FAILED", cost=0.01))
    src, _ = make(api)
    with pytest.raises(SourceError):
        frame(src)
    assert len(api.starts()) == 1
    n = len(api.requests)
    assert frame(src, ctx(now=NOW + timedelta(hours=2))).empty
    assert len(api.requests) == n and len(api.starts()) == 1
    ok_api = FakeApify()
    src2, _ = make(ok_api)
    assert len(frame(src2, ctx(now=NOW + timedelta(days=1)))) == 2
    assert len(ok_api.starts()) == 1


def test_a_second_fetch_the_same_utc_day_makes_no_http_call_and_returns_no_rows():
    src, api = make()
    assert len(frame(src)) == 2
    n = len(api.requests)
    again = frame(src, ctx(now=NOW + timedelta(hours=3)))
    assert again.empty and len(api.requests) == n


def test_a_run_that_never_started_does_not_use_up_the_day():
    api = FakeApify(start_status=500)
    src, _ = make(api)
    with pytest.raises(SourceError):
        frame(src)
    assert ledger().month_total(NOW) == 0.0
    api.start_status = 201
    assert len(frame(src)) == 2


def test_rate_limit_on_start_maps_to_rate_limited():
    src, _ = make(FakeApify(start_status=429))
    with pytest.raises(RateLimited) as e:
        frame(src)
    assert e.value.retry_after_s == 600 and KEY not in str(e.value)


# ---- pricing check ------------------------------------------------------------------------------------------------


def test_first_run_is_refused_when_pricing_could_exceed_the_daily_cap():
    expensive = {"pricingModel": "PAY_PER_EVENT", "pricingPerEvent": {"actorChargeEvents": {
        "trade": {"eventTitle": "A trade", "eventPriceUsd": 0.01}}}}
    api = FakeApify(details=pricing(expensive))
    src, _ = make(api)
    with pytest.raises(SourceError, match="pricing"):
        frame(src)
    assert api.starts() == []
    assert len(api.calls("GET", "congress-feed")) == 1
    assert ledger().month_total(NOW) == 0.0


def test_first_run_is_checked_against_per_item_pricing_and_start_fees():
    per_item = {"pricingModel": "PRICE_PER_DATASET_ITEM", "pricePerUnitUsd": 0.0051}
    src, api = make(FakeApify(details=pricing(per_item)))
    with pytest.raises(SourceError, match="pricing"):
        frame(src)
    assert api.starts() == []
    with_start = {"pricingModel": "PAY_PER_EVENT", "pricingPerEvent": {"actorChargeEvents": {
        "apify-actor-start": {"eventPriceUsd": 0.01}, "trade": {"eventPriceUsd": 0.0045}}}}
    src2, api2 = make(FakeApify(details=pricing(with_start)))
    with pytest.raises(SourceError, match="pricing"):
        frame(src2)
    assert api2.starts() == []
    tiered = {"pricingModel": "PAY_PER_EVENT", "pricingPerEvent": {"actorChargeEvents": {
        "trade": {"eventTieredPricingUsd": {"FREE": {"tieredEventPriceUsd": 0.009}, "GOLD": {
            "tieredEventPriceUsd": 0.004}}}}}}
    src3, api3 = make(FakeApify(details=pricing(tiered)))
    with pytest.raises(SourceError, match="pricing"):
        frame(src3)
    assert api3.starts() == []


def test_first_run_proceeds_when_pricing_fits_and_the_pricing_is_not_asked_again():
    src, api = make()
    frame(src)
    assert len(api.starts()) == 1 and len(api.calls("GET", "congress-feed")) == 1
    api2 = FakeApify()
    src2, _ = make(api2)
    frame(src2, ctx(now=NOW + timedelta(days=1)))
    assert api2.calls("GET", "congress-feed") == [] and len(api2.starts()) == 1


@pytest.mark.parametrize("details", [{"data": {}}, {"data": {"pricingInfos": []}}, {"unexpected": 1},
                                     pricing({"pricingModel": "FREE"}), pricing({"pricingModel": "PAY_PER_EVENT"})])
def test_undeterminable_pricing_still_runs_under_the_hard_caps(details):
    api = FakeApify(details=details)
    src, _ = make(api)
    assert len(frame(src)) == 2
    (start,) = api.starts()
    assert float(parse_qs(start.url.query.decode())["maxTotalChargeUsd"][0]) == 0.05
    assert json.loads(start.content)["maxItems"] == 10


# ---- the secret ---------------------------------------------------------------------------------------------------


def test_every_request_carries_the_key_only_in_the_authorization_header():
    src, api = make(FakeApify(polls=["RUNNING"]))
    frame(src)
    assert len(api.requests) >= 5
    for r in api.requests:
        assert r.headers["authorization"] == f"Bearer {KEY}"
        assert r.url.scheme == "https" and r.url.host == "api.apify.com"
        assert KEY not in str(r.url) and "token" not in str(r.url).lower()
        assert KEY.encode() not in r.content
        assert all(KEY not in v for k, v in r.headers.items() if k.lower() != "authorization")


BODY_WITH_KEY = f'{{"error": "bad token {KEY} sent as Bearer {KEY}"}}' + " pad" * 200


@pytest.mark.parametrize("where", ["start", "details", "poll", "items"])
@pytest.mark.parametrize("failure", ["status", "transport", "bad-json"])
def test_api_key_never_appears_in_logs_or_exception_text(where, failure, caplog):
    api = FakeApify()
    base = api.handler

    def hostile(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        target = {
            "start": request.method == "POST" and path.endswith("/runs"),
            "details": request.method == "GET" and path.startswith("/v2/acts/"),
            "poll": request.method == "GET" and path.startswith("/v2/actor-runs/"),
            "items": request.method == "GET" and path.startswith("/v2/datasets/"),
        }[where]
        if not target:
            return base(request)
        if failure == "transport":
            raise httpx.ConnectError(f"cannot reach {request.url} with Authorization: Bearer {KEY} / {KEY}")
        if failure == "bad-json":
            return httpx.Response(200, text=f"<html>{KEY}</html>")
        return httpx.Response(401, text=BODY_WITH_KEY)

    api.client = lambda: httpx.Client(transport=httpx.MockTransport(hostile))
    src, _ = make(api)
    with pytest.raises(SourceError) as e:
        frame(src)
    err = e.value
    rendered = "".join(traceback.format_exception(err))
    for text in (str(err), repr(err), rendered, caplog.text, *(r.getMessage() for r in caplog.records),
                 *(str(r.__dict__) for r in caplog.records)):
        assert KEY not in text
    assert err.__cause__ is None
    if failure == "status":
        assert "401" in str(err) and len(str(err)) < 400


def test_secret_is_absent_from_every_stored_file_and_the_frame():
    src, _ = make()
    out = frame(src)
    store.write(datasets.dataset("congress_trades"), out, now=NOW)
    for path in (p for p in (config.DATA_DIR).rglob("*") if p.is_file()):
        assert KEY.encode() not in path.read_bytes()
    assert KEY not in out.to_csv()


def test_error_bodies_are_redacted_and_cut_to_200_characters():
    api = FakeApify(start_status=500)
    src, _ = make(api)
    with pytest.raises(SourceError) as e:
        frame(src)
    assert "500" in str(e.value) and "[redacted]" in str(e.value) and KEY not in str(e.value)
    body = "x" * 190 + KEY + "y" * 500
    assert KEY not in cg.redact(body) and len(cg.excerpt(body)) <= 200
    assert KEY not in cg.excerpt(body)
    assert cg.redact("Authorization: Bearer abc.DEF-123_xyz== tail") == "Authorization: Bearer [redacted] tail"


def test_log_filter_redacts_the_key_in_messages_arguments_and_tracebacks(caplog):
    cg.register_secret(KEY)
    cg.log.info("plain %s and %s", KEY, {"k": f"Bearer {KEY}"})
    cg.log.info(f"f-string {KEY}")
    try:
        raise RuntimeError(f"boom {KEY}")
    except RuntimeError:
        cg.log.warning("with traceback", exc_info=True)
    assert caplog.records and KEY not in caplog.text
    assert all(KEY not in r.getMessage() and KEY not in (r.exc_text or "") for r in caplog.records)
    assert any(isinstance(f, cg.RedactingFilter) for f in cg.log.filters)


def test_a_missing_key_is_a_clear_source_error_and_makes_no_http_call():
    src, api = make(key=None)
    with pytest.raises(SourceError, match="APIFY_API_KEY"):
        frame(src)
    assert api.requests == []
    assert ledger().month_total(NOW) == 0.0


def test_unexpected_exceptions_are_wrapped_without_the_key():
    api = FakeApify()
    base = api.handler

    def boom(request):
        if request.url.path.startswith("/v2/datasets/"):
            raise KeyError(f"surprise {KEY}")
        return base(request)

    api.client = lambda: httpx.Client(transport=httpx.MockTransport(boom))
    src, _ = make(api)
    with pytest.raises(SourceError) as e:
        frame(src)
    assert KEY not in str(e.value) and KEY not in repr(e.value) and ledger().month_total(NOW) > 0


def test_apify_key_helper_reads_env_lazily_and_never_puts_it_in_the_error(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.delenv("APIFY_API_KEY", raising=False)
    with pytest.raises(ValueError, match="APIFY_API_KEY"):
        config.apify_key()
    monkeypatch.setenv("APIFY_API_KEY", f"  {KEY} \n")
    assert config.apify_key() == KEY
    monkeypatch.delenv("APIFY_API_KEY")
    (tmp_path / ".env").write_text(f"APIFY_API_KEY={KEY}\n")
    try:
        assert config.apify_key() == KEY
    finally:
        os.environ.pop("APIFY_API_KEY", None)


def test_settings_from_env_does_not_need_the_apify_key(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.delenv("APIFY_API_KEY", raising=False)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "a")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "b")
    assert config.Settings.from_env().alpaca_key_id == "a"


# ---- rows ---------------------------------------------------------------------------------------------------------


def test_rows_get_ts_in_utc_and_a_stable_source_id_and_the_mapped_fields():
    src, _ = make()
    first = frame(src)
    assert str(first["ts"].dtype) == "datetime64[us, UTC]"
    assert (first["ts"] == pd.Timestamp("2026-11-02", tz="UTC")).all()
    assert first["source_id"].is_unique and first["source_id"].str.fullmatch("[0-9a-f]{40}").all()
    row = first.iloc[0]
    assert row["politician"] == "Sen Number0" and row["chamber"] == "Senate" and row["ticker"] == "MSFT"
    assert row["transaction_type"] == "Sale (Partial)" and row["amount_range"] == "$1,001 - $15,000"
    assert row["traded_date"] == "2026-10-15" and row["amount_min"] == 1001 and row["amount_max"] == 15000
    assert "committees" not in first.columns and "ingested_at" not in first.columns

    reordered, _ = make(FakeApify(items=[trade(1), trade(0)]))
    second = frame(reordered, ctx(now=NOW + timedelta(days=1)))
    assert set(first["source_id"]) == set(second["source_id"])
    changed, _ = make(FakeApify(items=[trade(0, amountRange="$15,001 - $50,000")]))
    third = frame(changed, ctx(now=NOW + timedelta(days=2)))
    assert third["source_id"].iloc[0] not in set(first["source_id"])


def test_source_id_comes_from_the_actors_id_field_when_configured():
    items = [trade(0, documentId="d-1"), trade(1, documentId="d-2")]
    src, _ = make(FakeApify(items=items))
    out = frame(src, ctx(settings=with_congress(id_field="documentId", fields=FIELDS)))
    assert list(out["source_id"]) == ["d-1", "d-2"]


def test_ts_accepts_iso_timestamps_with_offsets_and_converts_to_utc():
    items = [trade(0, disclosureDate="2026-11-02T20:15:00-05:00"), trade(1, disclosureDate="2026-11-02T12:00:00Z")]
    src, _ = make(FakeApify(items=items))
    out = frame(src)
    assert list(out["ts"]) == [pd.Timestamp("2026-11-03 01:15", tz="UTC"), pd.Timestamp("2026-11-02 12:00", tz="UTC")]


@pytest.mark.parametrize("items", [{"a": 1}, [1, 2], [trade(0, disclosureDate="soon")], [trade(0, disclosureDate=None)]])
def test_unusable_items_raise_and_the_cost_is_still_booked(items):
    src, _ = make(FakeApify(items=items))
    with pytest.raises(SourceError):
        frame(src)
    assert ledger().month_total(NOW) == pytest.approx(0.0312)


def test_rows_without_a_usable_timestamp_are_dropped_with_a_warning_when_others_are_fine(caplog):
    items = [trade(0), trade(1, disclosureDate="soon"), trade(2, disclosureDate=None)]
    src, _ = make(FakeApify(items=items))
    out = frame(src)
    assert list(out["politician"]) == ["Sen Number0"]
    assert "dropping 2" in caplog.text


def test_an_empty_dataset_is_not_an_error():
    src, _ = make(FakeApify(items=[]))
    out = frame(src)
    assert out.empty and list(out.columns[:2]) == ["source_id", "ts"]
    assert ledger().month_total(NOW) == pytest.approx(0.0312)


def test_rows_are_stored_with_ingested_at_and_a_rerun_adds_nothing_new():
    ds = datasets.dataset("congress_trades")
    src, _ = make()
    assert src.run(ctx()) == 2
    stored = pd.read_parquet(ds.path)
    assert len(stored) == 2 and (stored["ingested_at"] == pd.Timestamp(NOW)).all()
    src2, _ = make()
    assert src2.run(ctx(now=NOW + timedelta(days=1))) == 0
    assert len(pd.read_parquet(ds.path)) == 2


def test_no_backfill_a_run_makes_exactly_one_actor_start_and_reads_only_that_dataset():
    src, api = make()
    frame(src)
    assert len(api.starts()) == 1
    assert [r.url.path for r in api.calls("GET", "/items")] == ["/v2/datasets/ds1/items"]
    assert int(api.calls("GET", "/items")[0].url.params["limit"]) == 10


# ---- configuration ------------------------------------------------------------------------------------------------


def test_the_actor_comes_from_settings_and_is_not_hardcoded():
    src, api = make()
    frame(src, ctx(settings=with_congress(actor="other-owner/other-actor")))
    assert api.starts()[0].url.path == "/v2/acts/other-owner~other-actor/runs"
    text = (config.ROOT / "src" / "tp" / "collect" / "sources" / "congress.py").read_text()
    assert "smartmoney" not in text and "capitol" not in text.lower()


@pytest.mark.parametrize("bad", ["", "no-slash", "a/b/c", "../x/y", "a b/c", "a/b?x=1"])
def test_a_malformed_actor_id_is_rejected_before_any_http_call(bad):
    src, api = make()
    with pytest.raises(SourceError, match="actor"):
        frame(src, ctx(settings=with_congress(actor=bad)))
    assert api.requests == []


@pytest.mark.parametrize("apify", [
    {}, {"monthly_cap_usd": 4.0}, {"monthly_cap_usd": 4.0, "daily_run_cap_usd": 0},
    {"monthly_cap_usd": 4.0, "daily_run_cap_usd": "x"}, {"monthly_cap_usd": 4.0, "daily_run_cap_usd": 5.0},
])
def test_missing_or_nonsensical_caps_refuse_the_run(apify):
    src, api = make()
    with pytest.raises(SourceError, match="apify"):
        frame(src, ctx(settings={**SETTINGS, "apify": apify}))
    assert api.requests == []


def test_a_monthly_cap_above_80_percent_of_the_credit_is_clamped():
    src, api = make()
    ledger().add(NOW, 3.99)
    with pytest.raises(SourceError, match="monthly"):
        frame(src, ctx(settings={**SETTINGS, "apify": {"monthly_cap_usd": 50.0, "daily_run_cap_usd": 0.05}}))
    assert api.requests == []


@pytest.mark.parametrize("override", [{"max_items": 0}, {"max_items": "ten"}, {"max_items": 10_000},
                                      {"fields": {}}, {"ts_field": ""}, {"id_fields": []}])
def test_bad_source_settings_refuse_the_run(override):
    src, api = make()
    with pytest.raises(SourceError):
        frame(src, ctx(settings=with_congress(**override)))
    assert api.requests == []


def test_shipped_config_ships_the_source_disabled_with_an_actor_and_a_field_map():
    settings = config_toml()
    table = source_settings(settings, "congress_trades")
    assert table["enabled"] is False and table["lag_minutes"] == 0
    assert table["schedule"] == "daily 08:30 America/New_York"
    assert "/" in table["actor"] and table["fields"] and table["ts_field"] and table["max_items"] > 0
    assert settings["apify"] == {"monthly_cap_usd": 4.0, "daily_run_cap_usd": 0.05}
    assert table["max_items"] * 0.005 <= settings["apify"]["daily_run_cap_usd"] + 1e-9
    assert "congress_trades" not in [s.name for s in build_sources(settings)]


def config_toml() -> dict:
    import tomllib

    with open(config.ROOT / "config" / "collect.toml", "rb") as f:
        return tomllib.load(f)


def test_build_sources_registers_it_when_enabled_and_skips_it_when_disabled():
    names = [s.name for s in build_sources(SETTINGS)]
    assert "congress_trades" in names
    found = {s.name: s for s in build_sources(SETTINGS)}["congress_trades"]
    assert isinstance(found, CongressTrades) and found.schedule.at.hour == 8
    off = with_congress(enabled=False)
    assert "congress_trades" not in [s.name for s in build_sources(off)]
