from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from services.control_plane import RunCoordinator
from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.deferred_runs import DeferredRunStore


REPO_ROOT = Path(__file__).resolve().parents[1]


def _config(tmp: str, **overrides) -> RuntimeConfig:
    values = {
        "state_directory": tmp,
        "vault_path": str(Path(tmp) / "vault"),
        "integrations_config_path": str(Path(tmp) / "integrations.json"),
        "promptfoo_command": "/missing/promptfoo",
        "hermes_command": "/missing/hermes",
        "goose_command": "/missing/goose",
        "evo_command": "/missing/evo",
        "vault_mirror_mode": "sync",
    }
    values.update(overrides)
    return RuntimeConfig(**values)


class ReleasePackagingTests(unittest.TestCase):
    def test_release_cut_guard_passes_current_tree(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/verify_release_cut_list.py", "--json"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "pass")

    def test_postgres_restart_proof_can_skip_without_database_url(self) -> None:
        env = dict(os.environ)
        env.pop("MESH_DATABASE_URL", None)
        result = subprocess.run(
            [
                sys.executable,
                "scripts/verify_postgres_restart_proof.py",
                "--skip-if-missing",
                "--json",
            ],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "skipped")

    def test_packaging_docs_reference_active_paths(self) -> None:
        docs = {
            "docs/evaluation-kits.md": [
                "docker-compose.stack.yml",
                "docker-compose.prod.yml",
                "scripts/compose_stack_smoke.sh",
                "scripts/prod_smoke.sh",
            ],
            "docs/community-governance.md": [
                "services/control_plane.py",
                "control_plane_server.py",
                "shared/mesh_runtime/schemas/",
            ],
            "docs/design-partner-packet.md": [
                "docs/production-hardening-records.md",
                "docs/production-live-runbook.md",
                "scripts/prod_smoke.sh",
            ],
            "docs/postgres-restart-proof.md": [
                "scripts/verify_postgres_restart_proof.py",
                "shared/mesh_runtime/postgres_state.py",
            ],
            "docs/authenticated-ingress.md": [
                "control_plane_server.py",
                "scripts/verify_authenticated_ingress.py",
            ],
        }
        for doc, refs in docs.items():
            text = (REPO_ROOT / doc).read_text(encoding="utf-8")
            for ref in refs:
                self.assertIn(ref, text)
                self.assertTrue((REPO_ROOT / ref).exists(), ref)

    def test_compose_stack_defaults_to_pilot_safe_identity_and_postgres(self) -> None:
        compose = (REPO_ROOT / "docker-compose.stack.yml").read_text(encoding="utf-8")

        for marker in [
            'MESH_STATE_BACKEND: "${MESH_STATE_BACKEND:-postgres}"',
            'MESH_DEFAULT_STEERING_MODE: "${MESH_DEFAULT_STEERING_MODE:-approval_gate}"',
            'MESH_OPERATOR_IDENTITY_REQUIRED: "${MESH_OPERATOR_IDENTITY_REQUIRED:-1}"',
            'MESH_FEATURE_FLAG_CREDENTIALS_AVAILABLE: "${MESH_FEATURE_FLAG_CREDENTIALS_AVAILABLE:-false}"',
            'MESH_INCIDENT_CREDENTIALS_AVAILABLE: "${MESH_INCIDENT_CREDENTIALS_AVAILABLE:-false}"',
            'E2E_AUTO_APPROVE: "${E2E_AUTO_APPROVE:-1}"',
            'MESH_E2E_OPERATOR_ROLES: "${MESH_E2E_OPERATOR_ROLES:-launcher,approver}"',
            'MESH_AGENT_OPERATOR_ROLES: "${MESH_AGENT_OPERATOR_ROLES:-approver}"',
        ]:
            self.assertIn(marker, compose)

    def test_smoke_and_agent_operator_send_identity_headers(self) -> None:
        smoke = (REPO_ROOT / "scripts/e2e_run_mesh.sh").read_text(encoding="utf-8")
        agent_operator = (REPO_ROOT / "scripts/mesh_agent_operator.py").read_text(encoding="utf-8")

        for marker in ["MESH_E2E_OPERATOR_ID", "MESH_E2E_OPERATOR_ROLES", "/api/runs/{run_id}/steer"]:
            self.assertIn(marker, smoke)
        for marker in ["MESH_AGENT_OPERATOR_ID", "MESH_AGENT_OPERATOR_ROLES", "X-Mesh-Operator", "X-Mesh-Roles"]:
            self.assertIn(marker, agent_operator)


class DistributedFaultTests(unittest.TestCase):
    def test_backpressured_run_queue_marks_run_failed_and_cleans_control(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp, run_queue_size=1))
            try:
                with patch.object(coordinator._run_queue, "put_nowait", side_effect=queue.Full):
                    run = coordinator.create_run(
                        {
                            "scenario_key": "search_latency_regression",
                            "evaluation_mode": "native",
                            "orchestration_mode": "native",
                            "steering_mode": "interruptible_auto",
                        }
                    )

                self.assertEqual(run["stage"], "failed")
                self.assertEqual(run["status"], "failed")
                self.assertNotIn(run["run_id"], coordinator.controls)
                events = coordinator.state_store.list_run_events(run["run_id"])
                self.assertEqual(events[-1].event_type, "run_failed")
                self.assertEqual(events[-1].payload["error"], "run queue is full")
            finally:
                coordinator.stop_background_workers()

    def test_duplicate_correlated_signal_attaches_to_active_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coordinator = RunCoordinator(_config(tmp))
            try:
                parent = coordinator.state_store.create_run_session(
                    goal_id=None,
                    scenario_key="live_kubernetes:search/semantic-search",
                    steering_mode="approval_gate",
                    auto_mode=False,
                    pause_points=["evaluation_ready"],
                    evaluation_mode="native",
                    orchestration_mode="native",
                    artifacts={
                        "correlation_key": "corr-search",
                        "input_signal": {"related_context": {"correlation_key": "corr-search"}},
                    },
                )

                attached = coordinator._maybe_attach_to_correlated_run(
                    {"live_signal": {"source": "kubernetes", "correlation_key": "corr-search"}},
                    {"signal_type": "kubernetes_deployment_issue", "related_context": {}},
                )

                self.assertIsNotNone(attached)
                assert attached is not None
                self.assertEqual(attached["run_id"], parent.run_id)
                self.assertEqual(len(attached["artifacts"]["correlated_signals"]), 1)
                events = coordinator.state_store.list_run_events(parent.run_id)
                self.assertEqual(events[-1].event_type, "correlated_signal_recorded")
            finally:
                coordinator.stop_background_workers()

    def test_delayed_deferred_records_are_not_claimed_until_due(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = DeferredRunStore(tmp)
            future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
            past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")

            future_record = store.create(
                source_run_id="run_future",
                due_at=future,
                signal_payload={"signal_type": "test"},
                parameters={"condition": "later"},
            )
            past_record = store.create(
                source_run_id="run_past",
                due_at=past,
                signal_payload={"signal_type": "test"},
                parameters={"condition": "now"},
            )

            claimed = store.claim_due(limit=10)
            claimed_ids = [record["defer_id"] for record in claimed]

            self.assertEqual(claimed_ids, [past_record["defer_id"]])
            self.assertNotIn(future_record["defer_id"], claimed_ids)
            self.assertEqual(store.claim_due(limit=10), [])


if __name__ == "__main__":
    unittest.main()
