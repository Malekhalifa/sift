import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from prometheus_client import CollectorRegistry, generate_latest

from tp.collect.metrics import Metrics
from tp.collect.scheduler import RunResult

ALERTS = Path(__file__).resolve().parents[2] / "deploy" / "sift_alerts.yml"
EXPECTED = {
    "SiftSourceStale", "SiftSourceErrors", "SiftQaFailing", "SiftQaStale", "SiftDiskLow", "SiftTargetDown",
    "SiftApifySpendHigh",
}


def rules() -> list[dict]:
    doc = yaml.safe_load(ALERTS.read_text())
    return [rule for group in doc["groups"] for rule in group["rules"]]


def exported_names() -> set[str]:
    registry = CollectorRegistry()
    m = Metrics(registry)
    m.init_source("x")
    m.record_run(RunResult("x", True, 1, 0.1, None))
    m.record_run(RunResult("x", False, 0, 0.1, "e"))
    m.set_age("x", 0)
    m.set_stale_after("x", 0)
    m.set_qa("x", "c", 0)
    m.set_qa_report_age(0)
    m.set_disk_free(0)
    m.set_apify_spend(0)
    return set(re.findall(r"^(sift_\w+?)(?:\{| )", generate_latest(registry).decode(), re.M))


def expr_metric_names(expr: str) -> set[str]:
    """sift_* identifiers in a PromQL expression, outside label matchers and string literals."""
    stripped = re.sub(r'"[^"]*"', '""', expr)
    return set(re.findall(r"\bsift_[a-z0-9_]+", stripped))


def test_alert_rules_parse_as_yaml_with_required_fields():
    found = rules()
    assert {r["alert"] for r in found} == EXPECTED
    for r in found:
        assert r["expr"].strip(), r["alert"]
        assert r["labels"]["severity"] in {"warning", "critical"}, r["alert"]
        assert r["annotations"]["summary"].strip(), r["alert"]
        assert r["annotations"]["description"].strip(), r["alert"]
        assert re.fullmatch(r"\d+[smh]", r.get("for", "0s")), f"{r['alert']}: bad for: clause"


def test_alert_severities_and_durations():
    by = {r["alert"]: r for r in rules()}
    assert by["SiftTargetDown"]["labels"]["severity"] == "critical"
    assert by["SiftTargetDown"]["for"] == "2m"
    assert by["SiftSourceStale"]["for"] == "10m"
    assert by["SiftQaFailing"]["for"] == "30m"
    assert by["SiftQaStale"]["for"] == "30m"
    assert 'up{job="sift"} == 0' in by["SiftTargetDown"]["expr"]
    assert "> on(source) sift_source_stale_after_seconds" in by["SiftSourceStale"]["expr"]
    assert "sift_source_errors_total[1h]" in by["SiftSourceErrors"]["expr"]
    assert "> 4" in by["SiftApifySpendHigh"]["expr"]
    assert "10e9" in by["SiftDiskLow"]["expr"]


def test_qa_stale_does_not_double_page_when_the_daemon_is_down():
    expr = {r["alert"]: r for r in rules()}["SiftQaStale"]["expr"]
    assert "absent(sift_qa_report_age_seconds)" in expr
    assert 'up{job="sift"} == 1' in expr


def assert_alert_metrics_exported() -> None:
    """Every sift_* metric named in an alert expr is exported by Metrics (the one shared implementation)."""
    exported = exported_names()
    used = set()
    for r in rules():
        used |= expr_metric_names(r["expr"])
    assert used, "no sift_* metrics found in the rule expressions"
    missing = used - exported
    assert not missing, f"alert expressions use metrics the recorder does not export: {sorted(missing)}"


def test_every_alert_metric_exists_in_metrics_module():
    assert_alert_metrics_exported()


def test_expr_metric_names_ignores_strings_and_requires_exact_names():
    assert expr_metric_names('sift_a{x="sift_b"} > sift_c_total') == {"sift_a", "sift_c_total"}
    assert "sift_source_errors" not in expr_metric_names("increase(sift_source_errors_total[1h])")
    assert "sift_source_errors_total" in exported_names()


needs_promtool = pytest.mark.skipif(shutil.which("promtool") is None, reason="promtool is not installed (brew install prometheus)")


def promtool(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["promtool", *args], capture_output=True, text=True, timeout=60)


@needs_promtool
def test_promtool_accepts_the_rule_file():
    result = promtool("check", "rules", str(ALERTS))
    assert result.returncode == 0, result.stdout + result.stderr


@needs_promtool
def test_promtool_unit_tests_for_the_rules_pass():
    result = promtool("test", "rules", str(ALERTS.with_name("sift_alerts_test.yml")))
    assert result.returncode == 0, result.stdout + result.stderr
