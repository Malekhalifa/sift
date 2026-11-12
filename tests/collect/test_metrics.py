import re
import socket
import urllib.request
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from tp.collect.metrics import Metrics
from tp.collect.scheduler import RunResult

from .test_alerts import assert_alert_metrics_exported

ALERTS = Path(__file__).resolve().parents[2] / "deploy" / "sift_alerts.yml"


@pytest.fixture
def registry():
    return CollectorRegistry()


@pytest.fixture
def metrics(registry):
    return Metrics(registry)


def value(registry, name, **labels):
    return registry.get_sample_value(name, labels or None)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_record_run_counts_rows_and_errors(metrics, registry):
    metrics.record_run(RunResult("bars", True, 120, 1.5, None))
    metrics.record_run(RunResult("bars", True, 30, 0.5, None))
    assert value(registry, "sift_source_rows_total", source="bars") == 150
    assert value(registry, "sift_source_errors_total", source="bars") in (None, 0)

    metrics.record_run(RunResult("bars", False, 0, 2.0, "boom"))
    assert value(registry, "sift_source_rows_total", source="bars") == 150
    assert value(registry, "sift_source_errors_total", source="bars") == 1
    assert value(registry, "sift_source_run_seconds_count", source="bars") == 3
    assert value(registry, "sift_source_run_seconds_sum", source="bars") == pytest.approx(4.0)


def test_failed_run_adds_no_rows_even_if_result_carries_some(metrics, registry):
    metrics.record_run(RunResult("bars", False, 7, 1.0, "boom"))
    assert value(registry, "sift_source_rows_total", source="bars") in (None, 0)
    assert value(registry, "sift_source_errors_total", source="bars") == 1


def test_age_and_qa_gauges_are_labelled(metrics, registry):
    metrics.set_age("bars", 12.5)
    metrics.set_age("filings", 99.0)
    metrics.set_qa("bars", "duplicates", 3)
    metrics.set_qa("bars", "future_ts", 0)
    assert value(registry, "sift_source_last_success_age_seconds", source="bars") == 12.5
    assert value(registry, "sift_source_last_success_age_seconds", source="filings") == 99.0
    assert value(registry, "sift_qa_failures", source="bars", check="duplicates") == 3
    assert value(registry, "sift_qa_failures", source="bars", check="future_ts") == 0


def test_clear_qa_removes_one_series_and_tolerates_a_missing_one(metrics, registry):
    metrics.set_qa("bars", "a", 1)
    metrics.set_qa("bars", "b", 1)
    metrics.clear_qa("bars", "b")
    metrics.clear_qa("bars", "b")
    metrics.clear_qa("never", "set")
    assert value(registry, "sift_qa_failures", source="bars", check="a") == 1
    assert value(registry, "sift_qa_failures", source="bars", check="b") is None


def test_qa_report_age_gauge_is_unset_until_given(metrics, registry):
    assert value(registry, "sift_qa_report_age_seconds") is None
    metrics.set_qa_report_age(42.5)
    assert value(registry, "sift_qa_report_age_seconds") == 42.5


def test_stale_after_gauge_is_labelled_by_source(metrics, registry):
    metrics.set_stale_after("bars", 120.0)
    metrics.set_stale_after("filings", 7200.0)
    assert value(registry, "sift_source_stale_after_seconds", source="bars") == 120.0
    assert value(registry, "sift_source_stale_after_seconds", source="filings") == 7200.0
    assert value(registry, "sift_source_stale_after_seconds", source="nope") is None


def test_scalar_gauges(metrics, registry):
    metrics.set_disk_free(123456)
    metrics.set_apify_spend(1.25)
    assert value(registry, "sift_disk_free_bytes") == 123456
    assert value(registry, "sift_apify_spend_usd_month") == 1.25


def test_exported_series_names_are_exact(metrics, registry):
    metrics.record_run(RunResult("bars", True, 1, 0.1, None))
    metrics.record_run(RunResult("bars", False, 0, 0.1, "x"))
    metrics.set_age("bars", 1)
    metrics.set_stale_after("bars", 2)
    metrics.set_qa("bars", "c", 0)
    metrics.set_qa_report_age(1)
    metrics.set_disk_free(1)
    metrics.set_apify_spend(0.0)
    text = generate_latest(registry).decode()
    series = set(re.findall(r"^(sift_\w+?)(?:\{| )", text, re.M))
    assert {
        "sift_source_last_success_age_seconds",
        "sift_source_stale_after_seconds",
        "sift_source_rows_total",
        "sift_source_errors_total",
        "sift_source_run_seconds_count",
        "sift_source_run_seconds_sum",
        "sift_qa_failures",
        "sift_qa_report_age_seconds",
        "sift_disk_free_bytes",
        "sift_apify_spend_usd_month",
    } <= series
    assert not any("_total_total" in n for n in series)


def test_instances_are_independent():
    a, b = Metrics(), Metrics()
    a.record_run(RunResult("bars", True, 5, 0.1, None))
    assert value(b.registry, "sift_source_rows_total", source="bars") in (None, 0)
    assert value(a.registry, "sift_source_rows_total", source="bars") == 5


def test_serve_exposes_metrics_on_loopback_only(metrics):
    port = free_port()
    metrics.set_disk_free(42)
    metrics.serve(port)
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        body = opener.open(f"http://127.0.0.1:{port}/metrics", timeout=5).read().decode()
        assert "sift_disk_free_bytes 42.0" in body
        assert metrics.server_address == ("127.0.0.1", port)
    finally:
        metrics.close()


def test_serve_twice_raises_a_clear_error(metrics):
    port = free_port()
    metrics.serve(port)
    try:
        with pytest.raises(RuntimeError, match="already serving"):
            metrics.serve(port)
    finally:
        metrics.close()


def test_serve_on_a_busy_port_raises_a_clear_error(metrics):
    port = free_port()
    other = Metrics()
    other.serve(port)
    try:
        with pytest.raises(RuntimeError, match=str(port)):
            metrics.serve(port)
    finally:
        other.close()


def test_metric_names_match_the_alert_rules():
    if not ALERTS.exists():
        pytest.skip(f"{ALERTS} does not exist")
    assert_alert_metrics_exported()
