from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from control_plane_server import start_server_in_thread
from services.ingest.webhook_service import (
    SignatureMismatchError,
    UnknownWebhookSourceError,
    WebhookIngestError,
    WebhookIngestService,
)
from shared.mesh_runtime import (
    ACTION_FIRE,
    ACTION_RESOLVE,
    ACTION_WARN,
    AlertStore,
    RuntimeConfig,
    WebhookTemplate,
    apply_template,
    extract_path,
    verify_signature,
)
from shared.mesh_runtime.webhook_templates import WebhookTemplateError


FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "webhook_templates"


class PathExtractionTests(unittest.TestCase):
    def test_dotted_path(self) -> None:
        payload = {"tags": {"service": "checkout", "env": "prod"}}
        self.assertEqual(extract_path(payload, "$.tags.service"), "checkout")
        self.assertEqual(extract_path(payload, "tags.env"), "prod")

    def test_array_index(self) -> None:
        payload = {"alerts": [{"fingerprint": "abc"}, {"fingerprint": "def"}]}
        self.assertEqual(extract_path(payload, "$.alerts[0].fingerprint"), "abc")
        self.assertEqual(extract_path(payload, "$.alerts[1].fingerprint"), "def")

    def test_missing_segments_return_none(self) -> None:
        self.assertIsNone(extract_path({"a": {}}, "$.a.b.c"))
        self.assertIsNone(extract_path({"alerts": []}, "$.alerts[0].x"))

    def test_root_path(self) -> None:
        payload = {"x": 1}
        self.assertEqual(extract_path(payload, "$"), payload)


class TemplateApplicationTests(unittest.TestCase):
    def test_datadog_fixture_normalizes(self) -> None:
        template = WebhookTemplate.from_dict(json.loads((FIXTURES_ROOT / "datadog.json").read_text()))
        payload = {
            "alert_id": "314159",
            "date": 1_744_000_000_000,
            "alert_transition": "Triggered",
            "priority": "normal",
            "event_title": "p95 latency high",
            "event_msg": "checkout degraded",
            "tags": {"service": "checkout", "env": "prod", "team": "payments"},
        }
        event = apply_template(template, payload)
        self.assertEqual(event.action, ACTION_FIRE)
        self.assertEqual(event.service, "checkout")
        self.assertEqual(event.environment, "prod")
        self.assertEqual(event.alert_id, "314159")
        self.assertTrue(event.timestamp.endswith("Z"))
        self.assertEqual(event.labels["team"], "payments")
        self.assertEqual(event.template_source_type, "datadog_monitor")

    def test_prometheus_resolve_action(self) -> None:
        template = WebhookTemplate.from_dict(json.loads((FIXTURES_ROOT / "prometheus.json").read_text()))
        payload = {
            "status": "resolved",
            "alerts": [
                {
                    "fingerprint": "fp-xyz",
                    "startsAt": "2026-04-18T10:00:00Z",
                    "status": "resolved",
                }
            ],
            "commonLabels": {"severity": "critical", "service": "api", "env": "prod"},
            "commonAnnotations": {"description": "API down"},
        }
        event = apply_template(template, payload)
        self.assertEqual(event.action, ACTION_RESOLVE)
        self.assertEqual(event.severity, "critical")
        self.assertEqual(event.service, "api")

    def test_synonym_normalization(self) -> None:
        template = WebhookTemplate.from_dict(
            {
                "source_id": "custom",
                "source_type": "custom",
                "fields": {
                    "alert_id": "$.id",
                    "timestamp": "$.time",
                    "action": "$.state",
                },
            }
        )
        event = apply_template(template, {"id": "1", "time": 1_700_000_000, "state": "Firing"})
        self.assertEqual(event.action, ACTION_FIRE)
        # Unix seconds (not ms) heuristic kicks in.
        self.assertTrue(event.timestamp.startswith("2023-"))

    def test_unknown_action_raises(self) -> None:
        template = WebhookTemplate.from_dict(
            {
                "source_id": "custom",
                "source_type": "custom",
                "fields": {
                    "alert_id": "$.id",
                    "timestamp": "$.time",
                    "action": "$.state",
                },
            }
        )
        with self.assertRaises(WebhookTemplateError):
            apply_template(template, {"id": "1", "time": "2026-01-01T00:00:00Z", "state": "lolwut"})

    def test_missing_required_field(self) -> None:
        template = WebhookTemplate.from_dict(
            {
                "source_id": "custom",
                "source_type": "custom",
                "fields": {
                    "alert_id": "$.id",
                    "timestamp": "$.time",
                    "action": "$.state",
                },
            }
        )
        with self.assertRaises(WebhookTemplateError):
            apply_template(template, {"time": "2026-01-01T00:00:00Z", "state": "fire"})


class SignatureTests(unittest.TestCase):
    def test_valid_signature_passes(self) -> None:
        secret = "shhh"
        body = b'{"ok":true}'
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_signature(body, sig, secret))
        self.assertTrue(verify_signature(body, f"sha256={sig}", secret))

    def test_invalid_signature_fails(self) -> None:
        self.assertFalse(verify_signature(b"{}", "bad", "shhh"))
        self.assertFalse(verify_signature(b"{}", None, "shhh"))

    def test_missing_secret_allows_all(self) -> None:
        self.assertTrue(verify_signature(b"{}", None, None))


class WebhookIngestServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = AlertStore(self.temp.name)
        self.service = WebhookIngestService(self.store)

    def _register_datadog(self, **overrides) -> dict:
        template = json.loads((FIXTURES_ROOT / "datadog.json").read_text())
        template.update(overrides)
        return self.service.register_source(template)

    def test_round_trip_register_ingest_list(self) -> None:
        self._register_datadog()
        payload = {
            "alert_id": "abc",
            "date": 1_744_000_000_000,
            "alert_transition": "Triggered",
            "priority": "P1",
            "event_title": "latency spike",
            "event_msg": "...",
            "tags": {"service": "checkout", "env": "prod"},
        }
        outcome = self.service.ingest("datadog", payload)
        self.assertEqual(outcome["alert"]["action"], ACTION_FIRE)
        self.assertIsNone(outcome["spawned_run"])
        events = self.service.list_events("datadog")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["alert_id"], "abc")

    def test_secret_is_redacted_on_read(self) -> None:
        self._register_datadog(secret="superSecret", require_signature=True)
        record = self.service.get_source("datadog")
        self.assertEqual(record["secret"], "***")

    def test_signature_required_when_configured(self) -> None:
        secret = "topsecret"
        self._register_datadog(secret=secret, require_signature=True)
        body = json.dumps({
            "alert_id": "abc",
            "date": 1_744_000_000_000,
            "alert_transition": "Triggered",
            "tags": {},
        }).encode()
        payload = json.loads(body)
        with self.assertRaises(SignatureMismatchError):
            self.service.ingest("datadog", payload, raw_body=body, signature="bogus")
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        outcome = self.service.ingest("datadog", payload, raw_body=body, signature=sig)
        self.assertEqual(outcome["alert"]["alert_id"], "abc")

    def test_unknown_source(self) -> None:
        with self.assertRaises(UnknownWebhookSourceError):
            self.service.ingest("nope", {}, raw_body=b"")

    def test_invalid_payload_raises_ingest_error(self) -> None:
        self._register_datadog()
        with self.assertRaises(WebhookIngestError):
            self.service.ingest("datadog", {"not": "datadog"})

    def test_auto_run_invokes_factory_only_on_fire(self) -> None:
        calls = []

        def factory(event, record):
            calls.append((event.action, event.source_id))
            return {"run_id": "run_test"}

        service = WebhookIngestService(self.store, run_factory=factory)
        template = json.loads((FIXTURES_ROOT / "datadog.json").read_text())
        template["auto_run"] = True
        service.register_source(template)

        fire = service.ingest("datadog", {
            "alert_id": "1",
            "date": 1_744_000_000_000,
            "alert_transition": "Triggered",
            "tags": {"service": "x", "env": "prod"},
        })
        self.assertEqual(fire["spawned_run"], {"run_id": "run_test"})

        resolve = service.ingest("datadog", {
            "alert_id": "1",
            "date": 1_744_000_000_000,
            "alert_transition": "Recovered",
            "tags": {"service": "x", "env": "prod"},
        })
        self.assertIsNone(resolve["spawned_run"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], ACTION_FIRE)


class WebhookHttpRouteTests(unittest.TestCase):
    """End-to-end over the real HTTP control plane."""

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
        )
        self.server, self.thread = start_server_in_thread(self.config, start_sidecar=False)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_register_then_post_webhook(self) -> None:
        template = json.loads((FIXTURES_ROOT / "prometheus.json").read_text())
        created = self._request("POST", "/api/webhook-sources", template)
        self.assertEqual(created["source_id"], "prometheus")

        listed = self._request("GET", "/api/webhook-sources")
        self.assertEqual(len(listed["sources"]), 1)

        payload = {
            "status": "firing",
            "alerts": [
                {
                    "fingerprint": "xxx",
                    "startsAt": "2026-04-18T10:00:00Z",
                    "status": "firing",
                }
            ],
            "commonLabels": {"severity": "critical", "service": "api", "env": "prod"},
            "commonAnnotations": {"description": "API down"},
        }
        outcome = self._request("POST", "/api/webhooks/prometheus", payload)
        self.assertEqual(outcome["alert"]["action"], ACTION_FIRE)

        alerts = self._request("GET", "/api/alerts?source_id=prometheus")
        self.assertEqual(len(alerts["alerts"]), 1)

    def test_unknown_source_returns_404(self) -> None:
        with self.assertRaises(HTTPError) as ctx:
            self._request("POST", "/api/webhooks/ghost", {"x": 1})
        self.assertEqual(ctx.exception.code, 404)

    def test_invalid_signature_returns_401(self) -> None:
        template = json.loads((FIXTURES_ROOT / "prometheus.json").read_text())
        template["secret"] = "topsecret"
        template["require_signature"] = True
        self._request("POST", "/api/webhook-sources", template)
        with self.assertRaises(HTTPError) as ctx:
            self._request(
                "POST",
                "/api/webhooks/prometheus",
                {"status": "firing", "alerts": [{"fingerprint": "x", "startsAt": "2026-04-18T10:00:00Z", "status": "firing"}], "commonLabels": {}, "commonAnnotations": {}},
                headers={"X-Mesh-Signature": "bad"},
            )
        self.assertEqual(ctx.exception.code, 401)

    def test_delete_source(self) -> None:
        template = json.loads((FIXTURES_ROOT / "prometheus.json").read_text())
        self._request("POST", "/api/webhook-sources", template)
        response = self._request("DELETE", "/api/webhook-sources/prometheus")
        self.assertEqual(response["deleted"], "prometheus")
        listed = self._request("GET", "/api/webhook-sources")
        self.assertEqual(listed["sources"], [])

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        headers: dict | None = None,
    ) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        merged_headers = {"Content-Type": "application/json"}
        if headers:
            merged_headers.update(headers)
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers=merged_headers,
        )
        with urlopen(request, timeout=5) as response:
            raw = response.read()
            if not raw:
                return {}
            return json.loads(raw)


class ReadinessCacheTests(unittest.TestCase):
    def test_readiness_is_cached_within_ttl(self) -> None:
        from services.control_plane import RunCoordinator

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        config = RuntimeConfig(
            state_directory=temp.name,
            vault_path=str(Path(temp.name) / "vault"),
            integrations_config_path=str(Path(temp.name) / "integrations.json"),
            promptfoo_command="/missing/promptfoo",
            goose_command="/missing/goose",
            gitnexus_sidecar_url="http://127.0.0.1:65535",
        )
        coordinator = RunCoordinator(config)
        first = coordinator.build_readiness()
        # Mutate cache sentinel; should still hit cache because TTL has not expired.
        cached_marker = "test-marker"
        with coordinator._readiness_lock:
            coordinator._readiness_cache = (
                time.monotonic(),
                {**first, "marker": cached_marker},
            )
        second = coordinator.build_readiness()
        self.assertEqual(second["marker"], cached_marker)
        coordinator.invalidate_readiness()
        third = coordinator.build_readiness()
        self.assertNotIn("marker", third)


if __name__ == "__main__":
    unittest.main()
