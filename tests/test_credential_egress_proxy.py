from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from services.orchestrator.credential_egress_proxy import CredentialEgressProxyRuntime, make_handler


class CredentialEgressProxyTests(unittest.TestCase):
    def test_runtime_authorizes_placeholder_only_egress_without_returning_raw_secret(self) -> None:
        policy = _local_policy()
        runtime = CredentialEgressProxyRuntime(
            policy,
            env={"CENTAUR_API_KEY": "centaur_real_secret"},
            proxy_instance_id="test-proxy",
        )

        readiness = runtime.readiness()
        authorization = runtime.authorize(
            {
                "host": "mesh-centaur-adapter",
                "location": "header",
                "credential_placeholder": "${secret:CENTAUR_API_KEY}",
            }
        )
        serialized = json.dumps(
            {"readiness": readiness, "authorization": authorization, "events": runtime.events()},
            sort_keys=True,
        )

        self.assertEqual(readiness["status"], "ok")
        self.assertEqual(authorization["status"], "approved")
        self.assertEqual(authorization["credential_substituted_by_proxy"], True)
        self.assertEqual(authorization["credential_visible_to_sandbox"], False)
        self.assertEqual(authorization["raw_secret_returned"], False)
        self.assertIn("audit_event_id", authorization)
        self.assertNotIn("centaur_real_secret", serialized)

    def test_http_proxy_serves_readiness_audit_and_authorization_endpoints(self) -> None:
        runtime = CredentialEgressProxyRuntime(
            _local_policy(),
            env={"CENTAUR_API_KEY": "centaur_real_secret"},
            proxy_instance_id="test-proxy-http",
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(runtime))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_port}"
            readiness = _request_json(f"{base_url}/health/ready")
            authorization = _request_json(
                f"{base_url}/egress/authorize",
                method="POST",
                payload={
                    "host": "mesh-centaur-adapter",
                    "location": "header",
                    "credential_placeholder": "${secret:CENTAUR_API_KEY}",
                },
            )
            events = _request_json(f"{base_url}/audit/events")
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        serialized = json.dumps({"readiness": readiness, "authorization": authorization, "events": events})
        self.assertEqual(readiness["status"], "ok")
        self.assertEqual(authorization["status"], "approved")
        self.assertEqual(authorization["raw_secret_returned"], False)
        self.assertGreaterEqual(len(events["events"]), 2)
        self.assertNotIn("centaur_real_secret", serialized)


def _local_policy() -> dict[str, object]:
    payload = json.loads(Path("config/centaur-credential-egress.local.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(request, timeout=2) as response:
        result = json.loads(response.read().decode("utf-8"))
    assert isinstance(result, dict)
    return result


if __name__ == "__main__":
    unittest.main()
