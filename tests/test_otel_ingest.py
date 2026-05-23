"""Tests for the OpenTelemetry consumer path.

Coverage:
- OTLP/HTTP JSON parsing (gauge, sum, histogram)
- OtlpPushIngester produces a signal that IngestService can normalize
- Schema validation accepts the produced signal
- Prometheus client handles success, empty result, and failure
- PrometheusPullIngester returns None when queries fail
- PrometheusFeedbackObserver merges stub + live observations correctly
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from control_plane_server import start_server_in_thread
from services.feedback.otel_observer import PrometheusFeedbackObserver, augment_observations
from services.ingest.otel_signal import AlertContext, OtlpPushIngester, PrometheusPullIngester
from services.ingest.service import IngestService
from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.otel import (
    PrometheusClient,
    PrometheusQueryError,
    parse_otlp_metrics,
)


def _otlp_payload_with(metrics: list[dict]) -> dict:
    """Build a minimal OTLP/HTTP JSON metrics envelope carrying ``metrics``."""
    return {
        "resourceMetrics": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "api-gateway"}},
                        {"key": "deployment.environment", "value": {"stringValue": "production"}},
                        {"key": "cloud.region", "value": {"stringValue": "us-east-1"}},
                    ]
                },
                "scopeMetrics": [
                    {
                        "scope": {"name": "test-scope"},
                        "metrics": metrics,
                    }
                ],
            }
        ]
    }


class OtlpParsingTests(unittest.TestCase):
    def test_parse_gauge_metric(self) -> None:
        payload = _otlp_payload_with(
            [
                {
                    "name": "http.server.error_rate",
                    "unit": "1",
                    "gauge": {
                        "dataPoints": [
                            {
                                "asDouble": 0.042,
                                "timeUnixNano": "1704000000000000000",
                                "attributes": [
                                    {"key": "http.route", "value": {"stringValue": "/search"}},
                                ],
                            }
                        ]
                    },
                }
            ]
        )
        resources = parse_otlp_metrics(payload)
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0].resource_attributes["service.name"], "api-gateway")
        self.assertEqual(len(resources[0].metrics), 1)
        metric = resources[0].metrics[0]
        self.assertEqual(metric.kind, "gauge")
        self.assertEqual(metric.data_points[0].value, 0.042)
        self.assertEqual(metric.data_points[0].attributes["http.route"], "/search")

    def test_parse_histogram_uses_mean(self) -> None:
        payload = _otlp_payload_with(
            [
                {
                    "name": "http.server.duration",
                    "unit": "ms",
                    "histogram": {
                        "dataPoints": [
                            {
                                "count": "100",
                                "sum": 65000.0,  # mean = 650ms
                                "timeUnixNano": "1704000000000000000",
                                "attributes": [],
                            }
                        ]
                    },
                }
            ]
        )
        resources = parse_otlp_metrics(payload)
        metric = resources[0].metrics[0]
        self.assertEqual(metric.kind, "histogram")
        self.assertAlmostEqual(metric.data_points[0].value, 650.0)

    def test_parse_unknown_metric_kind_is_tolerated(self) -> None:
        payload = _otlp_payload_with([{"name": "mystery", "exponentialHistogram": {"dataPoints": []}}])
        resources = parse_otlp_metrics(payload)
        # Unknown kinds still produce a metric entry (kind="unknown") so the caller can log + skip.
        self.assertEqual(resources[0].metrics[0].kind, "unknown")


class OtlpPushIngesterTests(unittest.TestCase):
    def test_ingester_produces_schema_valid_signal(self) -> None:
        payload = _otlp_payload_with(
            [
                {
                    "name": "http.server.duration",
                    "unit": "ms",
                    "histogram": {
                        "dataPoints": [
                            {"count": "100", "sum": 42000.0, "timeUnixNano": "1", "attributes": []},
                            {"count": "100", "sum": 72000.0, "timeUnixNano": "2", "attributes": []},
                        ]
                    },
                }
            ]
        )
        signal = OtlpPushIngester().build_signal(payload)
        self.assertEqual(signal["signal_type"], "otel_metric_regression")
        self.assertEqual(signal["source"], "otlp_push")
        self.assertEqual(signal["service"], "api-gateway")
        self.assertEqual(signal["environment"], "production")
        # Normalizing the signal through IngestService should succeed.
        envelope = IngestService().normalize_signal(signal)
        self.assertEqual(envelope.payload["signal_type"], "otel_metric_regression")
        # Latency-like metric name should be projected into request_telemetry.
        self.assertIn("request_telemetry", envelope.payload)
        self.assertGreater(envelope.payload["request_telemetry"]["observed"]["p95_latency_ms"], 0)

    def test_alert_context_overrides_heuristics(self) -> None:
        payload = _otlp_payload_with(
            [
                {
                    "name": "business.custom.rating",
                    "gauge": {
                        "dataPoints": [
                            {"asDouble": 2.3, "timeUnixNano": "1", "attributes": []},
                        ]
                    },
                }
            ]
        )
        context = AlertContext(
            metric_name="business.custom.rating",
            service="ratings-service",
            environment="staging",
            baseline_value=4.5,
            threshold_pct=20.0,
        )
        signal = OtlpPushIngester().build_signal(payload, alert_context=context)
        self.assertEqual(signal["service"], "ratings-service")
        self.assertEqual(signal["environment"], "staging")
        self.assertEqual(signal["metric_regression"]["baseline_value"], 4.5)
        self.assertEqual(signal["metric_regression"]["observed_value"], 2.3)
        self.assertIsNotNone(signal["metric_regression"]["delta_pct"])

    def test_empty_payload_raises(self) -> None:
        with self.assertRaises(ValueError):
            OtlpPushIngester().build_signal({"resourceMetrics": []})


class PrometheusClientTests(unittest.TestCase):
    def test_instant_query_success(self) -> None:
        client = PrometheusClient("http://prom:9090")
        fake_payload = {
            "status": "success",
            "data": {"result": [{"metric": {}, "value": [1704000000, "0.07"]}]},
        }
        with patch.object(client, "_fetch", return_value=fake_payload):
            self.assertAlmostEqual(client.instant_query("up"), 0.07)

    def test_instant_query_empty_returns_none(self) -> None:
        client = PrometheusClient("http://prom:9090")
        with patch.object(client, "_fetch", return_value={"status": "success", "data": {"result": []}}):
            self.assertIsNone(client.instant_query("up"))

    def test_query_failure_raises(self) -> None:
        client = PrometheusClient("http://prom:9090")
        with patch.object(client, "_fetch", side_effect=PrometheusQueryError("boom")):
            with self.assertRaises(PrometheusQueryError):
                client.instant_query("up")


class PrometheusPullIngesterTests(unittest.TestCase):
    def test_returns_none_when_prometheus_fails(self) -> None:
        client = PrometheusClient("http://prom:9090")
        with patch.object(client, "instant_query", side_effect=PrometheusQueryError("boom")):
            signal = PrometheusPullIngester(client).build_signal(
                service="api",
                endpoint="/search",
                environment="production",
                metric_name="http_requests_error_rate",
                observed_query="rate(errors[5m])",
                baseline_query="rate(errors[1h] offset 1h)",
            )
        # Missing data should not raise — it's a monitoring gap, not a remediation failure.
        self.assertIsNone(signal)

    def test_returns_signal_when_both_queries_succeed(self) -> None:
        client = PrometheusClient("http://prom:9090")
        with patch.object(client, "instant_query", side_effect=[0.09, 0.015]):
            signal = PrometheusPullIngester(client).build_signal(
                service="api",
                endpoint="/search",
                environment="production",
                metric_name="http_requests_error_rate",
                observed_query="obs",
                baseline_query="base",
            )
        self.assertIsNotNone(signal)
        self.assertEqual(signal["source"], "prometheus_pull")
        self.assertEqual(signal["metric_regression"]["observed_value"], 0.09)
        self.assertEqual(signal["metric_regression"]["baseline_value"], 0.015)
        # Schema validation: normalize_signal should accept this.
        IngestService().normalize_signal(signal)


class OtlpHttpRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = RuntimeConfig(
            state_directory=self.temp.name,
            vault_path=str(Path(self.temp.name) / "vault"),
            integrations_config_path=str(Path(self.temp.name) / "integrations.json"),
            server_host="127.0.0.1",
            server_port=0,
            promptfoo_command="/missing/promptfoo",
            goose_command="/missing/goose",
            gitnexus_sidecar_url="http://127.0.0.1:65535",
            otel_receiver_enabled=True,
            otel_receiver_token="test-token",
        )
        self.server, self.thread = start_server_in_thread(self.config, start_sidecar=False)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_otlp_receiver_rejects_missing_bearer_token(self) -> None:
        with self.assertRaises(HTTPError) as ctx:
            self._post_metrics(headers={})

        self.assertEqual(ctx.exception.code, 401)

    def test_otlp_receiver_accepts_authorized_payload(self) -> None:
        response = self._post_metrics(headers={"Authorization": "Bearer test-token"})

        self.assertEqual(response["status"], "accepted")
        self.assertTrue(str(response["run_id"]).startswith("run_"))

    def _post_metrics(self, *, headers: dict[str, str]) -> dict:
        payload = _otlp_payload_with(
            [
                {
                    "name": "http.server.duration",
                    "unit": "ms",
                    "histogram": {
                        "dataPoints": [
                            {"count": "100", "sum": 42000.0, "timeUnixNano": "1", "attributes": []},
                            {"count": "100", "sum": 72000.0, "timeUnixNano": "2", "attributes": []},
                        ]
                    },
                }
            ]
        )
        request = Request(
            f"{self.base_url}/v1/metrics",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", **headers},
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read())


class FeedbackObserverTests(unittest.TestCase):
    def test_augment_observations_live_wins_stub_fills(self) -> None:
        client = PrometheusClient("http://prom:9090")
        with patch.object(client, "instant_query", side_effect=[430.0, 0.013, 420.0, 0.011]):
            observer = PrometheusFeedbackObserver(
                client=client,
                latency_query_template='latency{service="{service}"}[{window}]',
                error_rate_query_template='error_rate{service="{service}"}[{window}]',
            )
            merged = augment_observations(
                signal_observations={"10m": {"side_effects": ["stub"]}, "30m": {}},
                observer=observer,
                service="api",
            )
        # Live wins on latency, stub carries side_effects through.
        self.assertAlmostEqual(merged["10m"]["p95_latency_ms"], 430.0)
        self.assertEqual(merged["10m"]["side_effects"], ["stub"])
        self.assertAlmostEqual(merged["30m"]["error_rate"], 0.011)

    def test_promql_template_keeps_label_braces_literal(self) -> None:
        client = PrometheusClient("http://prom:9090")
        with patch.object(client, "instant_query", return_value=430.0) as instant_query:
            observer = PrometheusFeedbackObserver(
                client=client,
                latency_query_template='histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{service="{service}"}[{window}])) by (le)) * 1000',
                error_rate_query_template='sum(rate(http_requests_total{service="{service}",status=~"5.."}[{window}]))',
            )
            observer.observe('api"gateway', "10m")
        self.assertEqual(
            instant_query.call_args_list[0].args[0],
            'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{service="api\\"gateway"}[10m])) by (le)) * 1000',
        )

    def test_augment_without_observer_returns_stub_intact(self) -> None:
        merged = augment_observations(
            signal_observations={"10m": {"p95_latency_ms": 400.0}, "30m": {}},
            observer=None,
            service="api",
        )
        self.assertEqual(merged["10m"]["p95_latency_ms"], 400.0)


if __name__ == "__main__":
    unittest.main()
