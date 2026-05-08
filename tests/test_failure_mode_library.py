from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime import RuntimeConfig, load_schema, validate_payload
from shared.mesh_runtime.failure_modes import build_failure_mode_library_packet
from shared.mesh_runtime.integrations import build_readiness


class FailureModeLibraryTests(unittest.TestCase):
    def test_failure_mode_library_schemas_are_loadable(self) -> None:
        library_schema = load_schema("failure-mode-library.schema.json")
        packet_schema = load_schema("failure-mode-library-packet.schema.json")

        self.assertEqual(library_schema["title"], "FailureModeLibrary")
        self.assertEqual(packet_schema["title"], "FailureModeLibraryPacket")

    def test_default_failure_mode_library_covers_required_modes(self) -> None:
        packet = build_failure_mode_library_packet()

        self.assertEqual(packet["schema_version"], "mesh.failure_mode_library.v1")
        self.assertEqual(packet["status"], "complete")
        self.assertEqual(packet["entry_count"], len(packet["entries"]))
        self.assertEqual(packet["missing_modes"], [])
        self.assertTrue(all(packet["checks"].values()))
        validate_payload("failure-mode-library-packet.schema.json", packet)

    def test_failure_mode_library_blocks_missing_required_mode_and_ui_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "failure-mode.library.json"
            payload = _minimal_library()
            payload["entries"] = [entry for entry in payload["entries"] if entry["id"] != "audit_sink_unavailable"]
            payload["entries"][0]["replay_refs"] = ["docs://missing-ui-replay"]
            path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            packet = build_failure_mode_library_packet(str(path))

        self.assertEqual(packet["status"], "incomplete")
        self.assertIn("audit_sink_unavailable", packet["missing_modes"])
        self.assertIn("denied_namespace", packet["entries_without_ui_replay"])
        self.assertFalse(packet["checks"]["required_modes_present"])
        self.assertFalse(packet["checks"]["ui_replay_refs_present"])

    def test_staging_readiness_requires_failure_mode_library(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blocked = build_readiness(
                _config(tmp, failure_mode_library_path=str(Path(tmp) / "missing.json")),
                force=True,
            ).to_dict()
            ready = build_readiness(_config(tmp), force=True).to_dict()

        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("failure_mode_library_configured", blocked["blockers"])
        self.assertEqual(ready["status"], "ready")
        self.assertTrue(ready["required_checks"]["failure_mode_library_configured"])

    def test_verify_failure_mode_library_cli(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/verify_failure_mode_library.py",
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["schema_version"], "mesh.failure_mode_library.v1")


def _config(tmp: str, **overrides) -> RuntimeConfig:
    backup_restore_rehearsal_path = Path(tmp) / "backup-restore-rehearsal.json"
    authenticated_ingress_proof_path = Path(tmp) / "authenticated-ingress-deployment-proof.json"
    if not authenticated_ingress_proof_path.exists():
        authenticated_ingress_proof_path.write_text(
            json.dumps(_authenticated_ingress_deployment_proof(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    values = {
        "state_directory": tmp,
        "vault_path": str(Path(tmp) / "vault"),
        "integrations_config_path": str(Path(tmp) / "integrations.json"),
        "readiness_profile": "staging",
        "operator_identity_required": True,
        "policy_signing_key": "test-policy-signing-key",
        "promptfoo_command": "/missing/promptfoo",
        "hermes_command": "/missing/hermes",
        "goose_command": "/missing/goose",
        "evo_command": "/missing/evo",
        "backup_restore_rehearsal_path": str(backup_restore_rehearsal_path),
        "authenticated_ingress_proof_path": str(authenticated_ingress_proof_path),
    }
    values.update(overrides)
    if not backup_restore_rehearsal_path.exists():
        backup_restore_rehearsal_path.write_text(
            json.dumps(
                _backup_restore_rehearsal(
                    environment=str(values.get("readiness_profile") or "local"),
                    state_backend=str(values.get("state_backend") or "file"),
                ),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return RuntimeConfig(**values)


def _backup_restore_rehearsal(*, environment: str = "staging", state_backend: str = "postgres") -> dict:
    digest = "a" * 64
    return {
        "schema_version": "mesh.backup_restore_rehearsal.v1",
        "rehearsal_id": "restore_rehearsal_test",
        "generated_at": "2026-05-05T23:00:00Z",
        "environment": environment,
        "operator_id": "platform@example.com",
        "state_backend": state_backend,
        "backup_ref": "backup://orbital-mesh/staging/test",
        "restore_ref": "restore://orbital-mesh/staging/test",
        "rpo_seconds": 300,
        "rto_seconds": 900,
        "measured_restore_seconds": 300,
        "components": [
            {
                "component": component,
                "backup_uri": f"s3://mesh-backups/staging/{component}.json",
                "restored": True,
                "sha256_before": digest,
                "sha256_after": digest,
                "record_count": 1,
            }
            for component in (
                "state_store",
                "vault",
                "merkle_proofs",
                "integrations_config",
                "research_artifacts",
            )
        ],
    }


def _authenticated_ingress_deployment_proof() -> dict:
    return {
        "schema_version": "mesh.authenticated_ingress_deployment_proof.v1",
        "proof_id": "authenticated_ingress_deployment_test",
        "generated_at": "2026-05-06T04:10:00Z",
        "environment": "staging",
        "operator_id": "platform@example.com",
        "ingress_url": "https://mesh.staging.example.com",
        "tls": {
            "terminated": True,
            "public_listener": True,
            "minimum_version": "TLSv1.3",
            "certificate_ref": "acm://mesh-staging-cert",
            "evidence_ref": "ingress-proof://tls/test",
        },
        "identity_provider": {
            "type": "oidc",
            "sso_enforced": True,
            "identity_claim": "email",
            "roles_claim": "groups",
            "evidence_ref": "ingress-proof://oidc/test",
        },
        "header_sanitization": {
            "client_mesh_operator_header_stripped": True,
            "client_mesh_roles_header_stripped": True,
            "proxy_operator_header_stamped": True,
            "proxy_roles_header_stamped": True,
            "evidence_ref": "ingress-proof://headers/test",
        },
        "role_mapping": {
            "viewer": "group://mesh/viewers",
            "launcher": "group://mesh/launchers",
            "approver": "group://mesh/approvers",
            "admin": "group://mesh/admins",
            "evidence_ref": "ingress-proof://role-mapping/test",
        },
        "network_boundary": {
            "raw_service_publicly_reachable": False,
            "upstream_private": True,
            "allowed_proxy_ref": "security-group://mesh-ingress-to-control-plane",
            "evidence_ref": "ingress-proof://network/test",
        },
        "app_rehearsal": {
            "schema_version": "mesh.authenticated_ingress_rehearsal.v1",
            "status": "passed",
            "run_id": "run_ingress_rehearsal",
            "evidence_ref": "run-artifact://authenticated-ingress-rehearsal.json",
        },
        "audit": {
            "source_ip_or_proxy_identity_recorded": True,
            "operator_identity_recorded": True,
            "evidence_ref": "ingress-proof://audit/test",
        },
        "raw_secret_material_present": False,
    }


def _minimal_library() -> dict:
    entries = []
    for mode in (
        "denied_namespace",
        "stale_kubeconfig",
        "llm_unavailable",
        "audit_sink_unavailable",
        "kubernetes_crashloop",
        "kubernetes_image_pull_backoff",
        "kubernetes_oom_killed",
        "kubernetes_readiness_probe_failure",
        "duplicate_signal",
        "delayed_feedback",
        "dependency_timeout",
        "queue_backpressure",
        "transient_network_failure",
    ):
        entries.append(
            {
                "id": mode,
                "title": mode.replace("_", " ").title(),
                "category": "kubernetes" if mode.startswith("kubernetes_") else "policy",
                "risk_tier": "medium",
                "authority_boundary": "test authority boundary",
                "detection_refs": ["services/control_plane.py"],
                "expected_blockers": [],
                "operator_actions": ["review"],
                "replay_refs": [f"ui://failure-mode/{mode}"],
                "test_refs": ["tests/test_failure_mode_library.py"],
            }
        )
    return {
        "schema_version": "mesh.failure_mode_library.registry.v1",
        "generated_from": ["tests/test_failure_mode_library.py"],
        "entries": entries,
    }
