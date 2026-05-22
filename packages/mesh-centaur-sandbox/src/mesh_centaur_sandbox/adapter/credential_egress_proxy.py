from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

from mesh_centaur_sandbox.credential_egress import verify_credential_egress_policy


STATE_SLICE = "mesh.credential_egress_policy.v1"


class CredentialEgressProxyRuntime:
    """Mesh-owned credential egress proof boundary.

    The sandbox receives placeholders only. This runtime validates host-bound
    credential substitution requests, records audit events, and never returns
    raw credential values to callers.
    """

    def __init__(
        self,
        policy: dict[str, Any],
        *,
        env: dict[str, str] | None = None,
        proxy_instance_id: str | None = None,
    ) -> None:
        self.policy = policy
        self.env = dict(env or os.environ)
        self.proxy_instance_id = proxy_instance_id or f"credential-proxy-{uuid4().hex}"
        self.audit_events: list[dict[str, Any]] = []
        self._record_policy_loaded_events()

    def readiness(self) -> dict[str, Any]:
        verification = verify_credential_egress_policy(
            self.policy,
            proxy_runtime=self._proxy_runtime_proof(),
            egress_audit_events=self.audit_events,
            agent_attempt_outputs=self._proof_list("agent_attempt_outputs"),
            sandbox_logs=self._proof_list("sandbox_logs"),
            exported_artifacts=self._proof_list("exported_artifacts"),
            raw_secret_values=self._raw_secret_fixture_values(),
            require_proxy_runtime=True,
        )
        return {
            "status": "ok" if verification["status"] == "pass" else "blocked",
            "state_slice": STATE_SLICE,
            "proxy_instance_id": self.proxy_instance_id,
            "last_audit_event_id": self.audit_events[-1]["event_id"] if self.audit_events else None,
            "verification": verification,
        }

    def authorize(self, request: dict[str, Any]) -> dict[str, Any]:
        host = str(request.get("host") or "").strip()
        location = str(request.get("location") or "header").strip()
        placeholder = str(request.get("credential_placeholder") or "").strip()
        record = self._record_for(host=host, location=location, placeholder=placeholder)
        if record is None:
            event = self._append_audit_event(host=host, status="rejected", reason="policy_denied")
            return {
                "status": "rejected",
                "state_slice": STATE_SLICE,
                "audit_event_id": event["event_id"],
                "raw_secret_returned": False,
            }
        secret_name = str(record.get("secret_name") or "").strip()
        raw_secret_present = bool(self.env.get(secret_name))
        event = self._append_audit_event(
            host=host,
            status="approved" if raw_secret_present else "rejected",
            reason="proxy_substitution_authorized" if raw_secret_present else "secret_missing",
            secret_name=secret_name,
        )
        return {
            "status": "approved" if raw_secret_present else "rejected",
            "state_slice": STATE_SLICE,
            "audit_event_id": event["event_id"],
            "credential_substituted_by_proxy": raw_secret_present,
            "credential_visible_to_sandbox": False,
            "sandbox_visible_value": placeholder,
            "raw_secret_returned": False,
        }

    def events(self) -> list[dict[str, Any]]:
        return list(self.audit_events)

    def _record_policy_loaded_events(self) -> None:
        for record in self._records():
            event_id = str(record.get("egress_audit_event_id") or "").strip()
            if not event_id:
                continue
            self.audit_events.append(
                {
                    "event_id": event_id,
                    "recorded_at": _timestamp(),
                    "host": ",".join(_string_list(record.get("allowed_hosts"))),
                    "status": "proxy_policy_loaded",
                    "state_slice": STATE_SLICE,
                }
            )

    def _append_audit_event(
        self,
        *,
        host: str,
        status: str,
        reason: str,
        secret_name: str | None = None,
    ) -> dict[str, Any]:
        event = {
            "event_id": f"evt_credential_proxy_{len(self.audit_events) + 1}",
            "recorded_at": _timestamp(),
            "host": host,
            "status": status,
            "reason": reason,
            "state_slice": STATE_SLICE,
        }
        if secret_name:
            event["secret_name"] = secret_name
        self.audit_events.append(event)
        return event

    def _record_for(self, *, host: str, location: str, placeholder: str) -> dict[str, Any] | None:
        for record in self._records():
            secret_name = str(record.get("secret_name") or "").strip()
            if host not in _string_list(record.get("allowed_hosts")):
                continue
            allowed_locations = record.get("allowed_locations")
            if not isinstance(allowed_locations, dict) or not _string_list(allowed_locations.get(location)):
                continue
            if placeholder != f"${{secret:{secret_name}}}":
                continue
            if record.get("sandbox_placeholder_only") is not True:
                continue
            return record
        return None

    def _proxy_runtime_proof(self) -> dict[str, Any]:
        proof_hosts = sorted({host for record in self._records() for host in _string_list(record.get("allowed_hosts"))})
        sandbox_env = {str(record.get("secret_name")): f"${{secret:{record.get('secret_name')}}}" for record in self._records()}
        return {
            "runtime": "credential-egress-proxy",
            "proof_mode": "live_proxy_audit",
            "proxy_instance_id": self.proxy_instance_id,
            "last_audit_event_id": self.audit_events[-1]["event_id"] if self.audit_events else "",
            "allowed_hosts": proof_hosts,
            "sandbox_placeholder_only": True,
            "host_bound_substitution": True,
            "sandbox_env": sandbox_env,
        }

    def _records(self) -> list[dict[str, Any]]:
        records = self.policy.get("records") if isinstance(self.policy, dict) else None
        return [record for record in records if isinstance(record, dict)] if isinstance(records, list) else []

    def _proof_list(self, name: str) -> list[Any]:
        proof = self.policy.get("proof") if isinstance(self.policy, dict) and isinstance(self.policy.get("proof"), dict) else {}
        value = proof.get(name)
        return list(value) if isinstance(value, list) else []

    def _raw_secret_fixture_values(self) -> list[str]:
        return [value for value in self._proof_list("raw_secret_fixture_values") if isinstance(value, str)]


def make_handler(runtime: CredentialEgressProxyRuntime) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path in {"/health", "/health/ready"}:
                self._send_json(runtime.readiness())
                return
            if self.path == "/audit/events":
                self._send_json({"events": runtime.events(), "state_slice": STATE_SLICE})
                return
            self._send_json({"error": "not found"}, status=404)

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/egress/authorize":
                self._send_json(runtime.authorize(self._read_json()))
                return
            self._send_json({"error": "not found"}, status=404)

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0:
                return {}
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            return payload if isinstance(payload, dict) else {}

        def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def load_policy(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def main() -> None:
    policy_path = os.getenv("MESH_CREDENTIAL_EGRESS_POLICY_PATH") or os.getenv("MESH_CENTAUR_CREDENTIAL_EGRESS_POLICY_PATH")
    if not policy_path:
        raise SystemExit("MESH_CREDENTIAL_EGRESS_POLICY_PATH is required")
    host = os.getenv("MESH_CREDENTIAL_EGRESS_PROXY_HOST", "0.0.0.0")
    port = int(os.getenv("MESH_CREDENTIAL_EGRESS_PROXY_PORT", "15001"))
    instance_id = os.getenv("MESH_CREDENTIAL_EGRESS_PROXY_INSTANCE_ID")
    runtime = CredentialEgressProxyRuntime(load_policy(policy_path), proxy_instance_id=instance_id)
    server = ThreadingHTTPServer((host, port), make_handler(runtime))
    server.serve_forever()


def _string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    main()
