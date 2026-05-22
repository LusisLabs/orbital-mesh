from __future__ import annotations

import json
import tempfile
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from mesh_centaur_sandbox.centaur_deployment import (
    verify_centaur_kubernetes_live_proof,
    verify_centaur_kubernetes_profile,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PACKAGE_ROOT / "manifests" / "centaur-sandbox-runtime.k8s.yaml"


def _write_fake_centaur_kubectl(path: Path, *, fail: bool) -> str:
    script = path / "fake-centaur-kubectl.py"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            from __future__ import annotations

            import json
            import sys

            FAIL = {str(fail)}

            def emit(payload):
                print(json.dumps(payload))
                raise SystemExit(0)

            def deployment(name, container, env):
                return {{
                    "kind": "Deployment",
                    "metadata": {{"name": name}},
                    "spec": {{
                        "template": {{
                            "spec": {{
                                "automountServiceAccountToken": False,
                                "containers": [{{
                                    "name": container,
                                    "env": [{{"name": key, "value": value}} for key, value in env.items()]
                                }}]
                            }}
                        }}
                    }}
                }}

            args = sys.argv[1:]
            text = " ".join(args)
            if "apply --dry-run=client" in text:
                print("manifest configured (client dry run)")
                raise SystemExit(0)
            if FAIL:
                print("simulated cluster unavailable", file=sys.stderr)
                raise SystemExit(1)
            if "get namespace mesh-centaur-sandboxes" in text:
                emit({{"kind": "Namespace", "metadata": {{"name": "mesh-centaur-sandboxes"}}}})
            if "get deployment mesh-centaur-sandbox-adapter" in text:
                emit(deployment("mesh-centaur-sandbox-adapter", "adapter", {{
                    "MESH_CREDENTIAL_EGRESS_PROXY_URL": "http://mesh-centaur-credential-egress-proxy:15001"
                }}))
            if "get deployment mesh-centaur-credential-egress-proxy" in text:
                emit(deployment("mesh-centaur-credential-egress-proxy", "credential-egress-proxy", {{
                    "MESH_CREDENTIAL_PLACEHOLDER_MODE": "true",
                    "MESH_CREDENTIAL_POLICY_REF": "mesh.credential_egress_policy.v1"
                }}))
            if "get service mesh-centaur-credential-egress-proxy" in text:
                emit({{
                    "kind": "Service",
                    "metadata": {{"name": "mesh-centaur-credential-egress-proxy"}},
                    "spec": {{"ports": [{{"port": 15001}}]}}
                }})
            if "get networkpolicy default-deny" in text:
                emit({{
                    "kind": "NetworkPolicy",
                    "metadata": {{"name": "default-deny"}},
                    "spec": {{"podSelector": {{}}, "policyTypes": ["Ingress", "Egress"]}}
                }})
            if "get networkpolicy allow-adapter-to-credential-proxy" in text:
                emit({{
                    "kind": "NetworkPolicy",
                    "metadata": {{"name": "allow-adapter-to-credential-proxy"}},
                    "spec": {{
                        "podSelector": {{"matchLabels": {{"app.kubernetes.io/name": "mesh-centaur-sandbox-adapter"}}}},
                        "egress": [{{
                            "to": [{{
                                "podSelector": {{"matchLabels": {{"app.kubernetes.io/name": "mesh-centaur-credential-egress-proxy"}}}}
                            }}],
                            "ports": [{{"protocol": "TCP", "port": 15001}}]
                        }}]
                    }}
                }})
            print(f"unsupported fake kubectl args: {{args}}", file=sys.stderr)
            raise SystemExit(2)
            """
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return str(script)


def _start_fake_credential_proxy(*, raw_secret_event: bool = False) -> tuple[HTTPServer, threading.Thread]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health/ready":
                self._send_json(
                    {
                        "status": "ok",
                        "state_slice": "mesh.credential_egress_policy.v1",
                        "last_audit_event_id": "evt_proxy_1",
                    }
                )
                return
            if self.path == "/audit/events":
                event = {
                    "event_id": "evt_proxy_1",
                    "state_slice": "mesh.credential_egress_policy.v1",
                    "status": "proxy_policy_loaded",
                    "host": "api.github.com",
                }
                if raw_secret_event:
                    event["token"] = "ghp_rawsecret"
                self._send_json({"events": [event], "state_slice": "mesh.credential_egress_policy.v1"})
                return
            self.send_error(404)

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _send_json(self, payload: dict[str, object]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def verify_package_e2e() -> dict[str, Any]:
    blockers: list[str] = []
    profile = verify_centaur_kubernetes_profile(str(MANIFEST_PATH))
    if profile.get("status") != "pass":
        blockers.append("static_profile_failed")

    with tempfile.TemporaryDirectory() as tmp:
        kubectl = _write_fake_centaur_kubectl(Path(tmp), fail=False)
        proxy_server, proxy_thread = _start_fake_credential_proxy()
        try:
            live = verify_centaur_kubernetes_live_proof(
                manifest_path=str(MANIFEST_PATH),
                kubectl_command=kubectl,
                credential_proxy_url=f"http://127.0.0.1:{proxy_server.server_port}",
                timeout_seconds=2,
            )
        finally:
            proxy_server.shutdown()
            proxy_thread.join(timeout=2)
            proxy_server.server_close()

    if live.get("status") != "pass":
        blockers.append("live_proof_failed")

    return {
        "status": "pass" if not blockers else "fail",
        "static_profile": profile,
        "live_proof": live,
        "blockers": blockers,
    }
