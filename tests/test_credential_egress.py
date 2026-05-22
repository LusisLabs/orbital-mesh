from __future__ import annotations

import json
import unittest
from pathlib import Path

from shared.mesh_runtime.credential_egress import verify_credential_egress_policy


class CredentialEgressPolicyTests(unittest.TestCase):
    def test_policy_passes_when_sandbox_has_placeholder_only_and_outputs_have_no_raw_secret(self) -> None:
        policy = {
            "schema_version": "mesh.credential_egress_policy.v1",
            "records": [
                {
                    "secret_name": "GITHUB_TOKEN",
                    "allowed_hosts": ["api.github.com"],
                    "allowed_locations": {"header": ["Authorization"], "query": [], "path": []},
                    "sandbox_placeholder_only": True,
                    "egress_audit_event_id": "evt_egress_1",
                }
            ],
        }

        result = verify_credential_egress_policy(
            policy,
            agent_attempt_outputs=[
                {
                    "credential_policy": {
                        "secret_name": "GITHUB_TOKEN",
                        "sandbox_visible_value": "${secret:GITHUB_TOKEN}",
                    }
                }
            ],
            raw_secret_values=["ghp_real_secret"],
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["checks"]["no_raw_secret_in_attempt_output"], True)

    def test_policy_fails_when_attempt_output_contains_raw_secret(self) -> None:
        policy = {
            "schema_version": "mesh.credential_egress_policy.v1",
            "records": [
                {
                    "secret_name": "GITHUB_TOKEN",
                    "allowed_hosts": ["api.github.com"],
                    "allowed_locations": {"header": ["Authorization"]},
                    "sandbox_placeholder_only": True,
                    "egress_audit_event_id": "evt_egress_1",
                }
            ],
        }

        result = verify_credential_egress_policy(
            policy,
            agent_attempt_outputs=[{"token": "ghp_real_secret"}],
            raw_secret_values=["ghp_real_secret"],
        )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["checks"]["no_raw_secret_in_attempt_output"], False)

    def test_policy_passes_with_proxy_runtime_and_audit_event_proof(self) -> None:
        policy = {
            "schema_version": "mesh.credential_egress_policy.v1",
            "records": [
                {
                    "secret_name": "GITHUB_TOKEN",
                    "allowed_hosts": ["api.github.com"],
                    "allowed_locations": {"header": ["Authorization"]},
                    "sandbox_placeholder_only": True,
                    "egress_audit_event_id": "evt_egress_1",
                }
            ],
        }

        result = verify_credential_egress_policy(
            policy,
            agent_attempt_outputs=[{"credential_policy": {"sandbox_visible_value": "${secret:GITHUB_TOKEN}"}}],
            raw_secret_values=["ghp_real_secret"],
            proxy_runtime={
                "runtime": "iron-proxy",
                "proof_mode": "live_proxy_audit",
                "proxy_instance_id": "proxy_1",
                "last_audit_event_id": "evt_egress_1",
                "allowed_hosts": ["api.github.com"],
                "sandbox_placeholder_only": True,
                "host_bound_substitution": True,
                "sandbox_env": {"GITHUB_TOKEN": "${secret:GITHUB_TOKEN}"},
            },
            egress_audit_events=[{"event_id": "evt_egress_1", "host": "api.github.com"}],
            require_proxy_runtime=True,
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["checks"]["proxy_runtime_present"], True)
        self.assertEqual(result["checks"]["proxy_runtime_live_audit_proven"], True)
        self.assertEqual(result["checks"]["egress_audit_events_present"], True)

    def test_policy_fails_proxy_runtime_when_raw_secret_reaches_sandbox_env(self) -> None:
        policy = {
            "schema_version": "mesh.credential_egress_policy.v1",
            "records": [
                {
                    "secret_name": "GITHUB_TOKEN",
                    "allowed_hosts": ["api.github.com"],
                    "allowed_locations": {"header": ["Authorization"]},
                    "sandbox_placeholder_only": True,
                    "egress_audit_event_id": "evt_egress_1",
                }
            ],
        }

        result = verify_credential_egress_policy(
            policy,
            raw_secret_values=["ghp_real_secret"],
            proxy_runtime={
                "runtime": "iron-proxy",
                "proof_mode": "live_proxy_audit",
                "proxy_instance_id": "proxy_1",
                "last_audit_event_id": "evt_egress_1",
                "allowed_hosts": ["api.github.com"],
                "sandbox_placeholder_only": True,
                "host_bound_substitution": True,
                "sandbox_env": {"GITHUB_TOKEN": "ghp_real_secret"},
            },
            egress_audit_events=[{"event_id": "evt_egress_1", "host": "api.github.com"}],
            require_proxy_runtime=True,
        )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["checks"]["proxy_runtime_forbids_raw_secret_env"], False)

    def test_policy_fails_when_raw_secret_reaches_logs_or_exports(self) -> None:
        policy = {
            "schema_version": "mesh.credential_egress_policy.v1",
            "records": [
                {
                    "secret_name": "GITHUB_TOKEN",
                    "allowed_hosts": ["api.github.com"],
                    "allowed_locations": {"header": ["Authorization"]},
                    "sandbox_placeholder_only": True,
                    "egress_audit_event_id": "evt_egress_1",
                }
            ],
        }

        result = verify_credential_egress_policy(
            policy,
            sandbox_logs=["request used ghp_real_secret"],
            exported_artifacts=[{"env": {"GITHUB_TOKEN": "ghp_real_secret"}}],
            raw_secret_values=["ghp_real_secret"],
        )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["checks"]["no_raw_secret_in_sandbox_logs"], False)
        self.assertEqual(result["checks"]["no_raw_secret_in_exports"], False)

    def test_policy_can_carry_env_specific_proxy_proof(self) -> None:
        policy = {
            "schema_version": "mesh.credential_egress_policy.v1",
            "environment": "local",
            "records": [
                {
                    "secret_name": "GITHUB_TOKEN",
                    "allowed_hosts": ["api.github.com"],
                    "allowed_locations": {"header": ["Authorization"]},
                    "sandbox_placeholder_only": True,
                    "egress_audit_event_id": "evt_egress_1",
                }
            ],
            "proof": {
                "proxy_runtime": {
                    "runtime": "credential-egress-proxy",
                    "proof_mode": "live_proxy_audit",
                    "proxy_instance_id": "proxy_1",
                    "last_audit_event_id": "evt_egress_1",
                    "allowed_hosts": ["api.github.com"],
                    "sandbox_placeholder_only": True,
                    "host_bound_substitution": True,
                    "sandbox_env": {"GITHUB_TOKEN": "${secret:GITHUB_TOKEN}"},
                },
                "egress_audit_events": [{"event_id": "evt_egress_1", "host": "api.github.com"}],
                "agent_attempt_outputs": [{"token": "${secret:GITHUB_TOKEN}"}],
                "sandbox_logs": ["placeholder credential only"],
                "exported_artifacts": [{"token": "${secret:GITHUB_TOKEN}"}],
                "raw_secret_fixture_values": ["ghp_real_secret"],
            },
        }

        result = verify_credential_egress_policy(policy, require_proxy_runtime=True)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["checks"]["no_raw_secret_in_attempt_output"], True)
        self.assertEqual(result["checks"]["no_raw_secret_in_sandbox_logs"], True)
        self.assertEqual(result["checks"]["no_raw_secret_in_exports"], True)

    def test_local_centaur_policy_fixture_requires_proxy_audit_and_has_no_secret_leaks(self) -> None:
        policy = json.loads(Path("config/centaur-credential-egress.local.json").read_text(encoding="utf-8"))

        result = verify_credential_egress_policy(policy, require_proxy_runtime=True)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["checks"]["proxy_runtime_live_audit_proven"], True)
        self.assertEqual(result["checks"]["proxy_runtime_forbids_raw_secret_env"], True)
        self.assertEqual(result["checks"]["no_raw_secret_in_attempt_output"], True)
        self.assertEqual(result["checks"]["no_raw_secret_in_sandbox_logs"], True)
        self.assertEqual(result["checks"]["no_raw_secret_in_exports"], True)


if __name__ == "__main__":
    unittest.main()
