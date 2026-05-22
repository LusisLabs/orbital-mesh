from __future__ import annotations

from pathlib import Path
import tempfile
import textwrap
import unittest

from shared.mesh_runtime.centaur_deployment import (
    verify_centaur_kubernetes_live_proof,
    verify_centaur_kubernetes_profile,
)


class CentaurDeploymentProfileTests(unittest.TestCase):
    def test_kubernetes_profile_renders_as_disabled_mesh_owned_sandbox_profile(self) -> None:
        result = verify_centaur_kubernetes_profile("config/centaur-sandbox-runtime.k8s.yaml")

        self.assertEqual(result["status"], "pass")
        self.assertIn("Namespace", result["kinds"])
        self.assertIn("NetworkPolicy", result["kinds"])
        self.assertEqual(result["checks"]["deployment_disabled_by_default"], True)
        self.assertEqual(result["checks"]["proxy_deployment_disabled_by_default"], True)
        self.assertEqual(result["checks"]["default_deny_network_policy_present"], True)
        self.assertEqual(result["checks"]["live_execution_blocked_annotation_present"], True)
        self.assertEqual(result["checks"]["adapter_egress_proxy_url_present"], True)
        self.assertEqual(result["checks"]["credential_proxy_separate_deployment_present"], True)
        self.assertEqual(result["checks"]["credential_proxy_service_present"], True)
        self.assertEqual(result["checks"]["adapter_proxy_only_network_policy_present"], True)
        self.assertEqual(result["checks"]["dns_egress_policy_present"], True)
        self.assertEqual(result["checks"]["credential_proxy_not_sidecar"], True)
        self.assertEqual(result["checks"]["credential_proxy_placeholder_mode"], True)
        self.assertEqual(result["checks"]["credential_proxy_health_probe_present"], True)
        self.assertEqual(result["checks"]["real_adapter_image_configured"], True)
        self.assertEqual(result["checks"]["per_sandbox_labels_present"], True)
        self.assertEqual(result["checks"]["cleanup_policy_present"], True)

    def test_kubernetes_overlays_keep_preview_and_prod_gated(self) -> None:
        local = Path("config/centaur-sandbox-runtime.local.k8s.yaml").read_text(encoding="utf-8")
        preview = Path("config/centaur-sandbox-runtime.preview.k8s.yaml").read_text(encoding="utf-8")
        prod = Path("config/centaur-sandbox-runtime.prod.k8s.yaml").read_text(encoding="utf-8")

        self.assertIn("mesh.lusis.io/environment: local", local)
        self.assertIn("replicas: 1", local)
        self.assertIn("mesh-centaur-credential-egress-proxy", local)
        self.assertIn("MESH_CREDENTIAL_EGRESS_PROXY_URL", local)
        self.assertIn("local-only-after-credential-egress-proof", local)
        self.assertIn("replicas: 0", preview)
        self.assertIn("mesh-centaur-credential-egress-proxy", preview)
        self.assertIn("blocked-until-preview-credential-egress-proof", preview)
        self.assertIn("replicas: 0", prod)
        self.assertIn("mesh-centaur-credential-egress-proxy", prod)
        self.assertIn("blocked-until-prod-credential-egress-proof", prod)
        self.assertIn("release-thread-and-delete-sandbox", prod)

    def test_live_kubernetes_proof_passes_with_observed_proxy_gated_resources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kubectl = _write_fake_centaur_kubectl(Path(tmp), fail=False)
            result = verify_centaur_kubernetes_live_proof(kubectl_command=kubectl, timeout_seconds=2)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["checks"]["client_dry_run_apply"], True)
        self.assertEqual(result["checks"]["adapter_points_to_credential_proxy"], True)
        self.assertEqual(result["checks"]["proxy_placeholder_mode"], True)
        self.assertEqual(result["checks"]["live_policy_allows_adapter_to_proxy_only"], True)
        self.assertEqual(result["blockers"], [])

    def test_live_kubernetes_proof_blocks_when_cluster_resources_are_unreachable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kubectl = _write_fake_centaur_kubectl(Path(tmp), fail=True)
            result = verify_centaur_kubernetes_live_proof(kubectl_command=kubectl, timeout_seconds=2)

        self.assertEqual(result["status"], "blocked")
        self.assertIn("namespace_reachable_failed", result["blockers"])
        self.assertIn("adapter_points_to_credential_proxy_failed", result["blockers"])


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


if __name__ == "__main__":
    unittest.main()
