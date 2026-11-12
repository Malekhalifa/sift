"""Prometheus metrics for the recorder daemon, served on loopback only."""
from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server

from tp.collect.scheduler import RunResult

BIND_ADDR = "127.0.0.1"
RUN_SECONDS_BUCKETS = (0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600)


class Metrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry if registry is not None else CollectorRegistry()
        r = self.registry
        # Counter appends "_total" itself, so names are given without it.
        self._rows = Counter("sift_source_rows", "Rows written per source", ["source"], registry=r)
        self._errors = Counter("sift_source_errors", "Failed runs per source", ["source"], registry=r)
        self._run_seconds = Histogram(
            "sift_source_run_seconds", "Run duration per source", ["source"],
            buckets=RUN_SECONDS_BUCKETS, registry=r,
        )
        self._age = Gauge(
            "sift_source_last_success_age_seconds", "Seconds since the last successful run", ["source"], registry=r
        )
        self._stale_after = Gauge(
            "sift_source_stale_after_seconds", "Age beyond which a source counts as stale", ["source"], registry=r
        )
        self._qa = Gauge("sift_qa_failures", "Rows failing a QA check", ["source", "check"], registry=r)
        self._disk = Gauge("sift_disk_free_bytes", "Free bytes on the data volume", registry=r)
        self._apify = Gauge("sift_apify_spend_usd_month", "Apify spend this month in USD", registry=r)
        self._httpd = None
        self.server_address: tuple[str, int] | None = None

    def record_run(self, result: RunResult) -> None:
        """Count a finished run: rows for a success, one error for a failure."""
        self._run_seconds.labels(result.source).observe(result.seconds)
        if result.ok:
            self._rows.labels(result.source).inc(result.rows)
        else:
            self._errors.labels(result.source).inc()

    def set_age(self, source: str, seconds: float) -> None:
        self._age.labels(source).set(seconds)

    def set_stale_after(self, source: str, seconds: float) -> None:
        self._stale_after.labels(source).set(seconds)

    def set_qa(self, source: str, check: str, failures: int) -> None:
        self._qa.labels(source, check).set(failures)

    def set_disk_free(self, bytes: int) -> None:
        self._disk.set(bytes)

    def set_apify_spend(self, usd: float) -> None:
        self._apify.set(usd)

    def serve(self, port: int) -> None:
        """Start the exporter on 127.0.0.1:port; raise RuntimeError if already serving or the port is taken."""
        if self._httpd is not None:
            raise RuntimeError(f"metrics already serving on {BIND_ADDR}:{self.server_address[1]}")
        try:
            httpd, _ = start_http_server(port, addr=BIND_ADDR, registry=self.registry)
        except OSError as e:
            raise RuntimeError(f"cannot serve metrics on {BIND_ADDR}:{port}: {e}") from e
        self._httpd = httpd
        self.server_address = (BIND_ADDR, httpd.server_port)

    def close(self) -> None:
        """Stop the exporter if it is running."""
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            self.server_address = None
