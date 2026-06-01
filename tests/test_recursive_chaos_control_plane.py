from __future__ import annotations

import json
import tempfile
import time
import unittest
from http import HTTPStatus
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from control_plane_server import start_server_in_thread
from shared.mesh_runtime import RuntimeConfig


class RecursiveChaosControlPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = RuntimeConfig(
            state_directory=self.temp_dir.name,
            vault_path=str(Path(self.temp_dir.name) / "vault"),
            integrations_config_path=str(Path(self.temp_dir.name) / "integrations.json"),
            server_host="127.0.0.1",
            server_port=0,
            operator_identity_required=True,
            promptfoo_command="/missing/promptfoo",
            hermes_command="/missing/hermes",
            goose_command="/missing/goose",
        )
        self.server, self.thread = start_server_in_thread(self.config, start_sidecar=False)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.server.coordinator._lock:
                active_workers = list(self.server.coordinator._threads.values())
            if not any(worker.is_alive() for worker in active_workers):
                break
            time.sleep(0.05)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def test_profiles_are_read_only_api_surface_with_verification(self) -> None:
        payload = self._request("GET", "/api/recursive-chaos/profiles")

        self.assertEqual(payload["schema_version"], "mesh.recursive_chaos.arena_profiles.v1")
        self.assertEqual(payload["verification"]["status"], "pass")
        self.assertEqual(payload["verification"]["profile_count"], 16)
        self.assertIn("kubernetes_service_platform", {profile["profile_id"] for profile in payload["profiles"]})

    def test_session_creation_requires_operator_and_records_mesh_run(self) -> None:
        with self.assertRaises(HTTPError) as unauth:
            self._request(
                "POST",
                "/api/recursive-chaos/sessions",
                {"profile_ids": ["kubernetes_service_platform"], "max_cycles": 1},
            )
        self.assertEqual(unauth.exception.code, HTTPStatus.UNAUTHORIZED)

        run = self._request(
            "POST",
            "/api/recursive-chaos/sessions",
            {"profile_ids": ["kubernetes_service_platform"], "max_cycles": 1, "seed": 3},
            operator="operator@example.com",
            roles="launcher",
            status=HTTPStatus.CREATED,
        )

        self.assertEqual(run["scenario_key"], "recursive_chaos_arena")
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["artifacts"]["decision"]["decision_type"], "no_action")
        self.assertTrue(run["artifacts"]["decision"]["reasoning"]["evidence_pack"]["advisory_only"])
        self.assertEqual(run["artifacts"]["recursive_chaos_session_summary"]["cycles_total"], 1)
        advisory = run["artifacts"]["mesh_brain_recursive_chaos_advisory"]
        self.assertTrue(advisory["sealed_source_required"])
        self.assertTrue(advisory["advisory_only"])
        self.assertFalse(advisory["training_allowed"])
        self.assertEqual(advisory["mesh_model_mode"], "recommend_only")
        self.assertFalse(advisory["mesh_model_training_allowed"])
        self.assertFalse(advisory["production_authority"])
        feedback_gate = run["artifacts"]["mesh_brain_recursive_chaos_feedback_gate"]
        self.assertEqual(feedback_gate["schema_version"], "mesh.recursive_chaos.feedback_gate.v1")
        self.assertEqual(feedback_gate["mesh_brain_mode"], "recommend_only")
        self.assertEqual(feedback_gate["mesh_model_mode"], "recommend_only")
        self.assertFalse(feedback_gate["mesh_model_training_allowed"])
        self.assertFalse(feedback_gate["production_authority"])
        graph = self._request("GET", f"/api/runs/{run['run_id']}/evidence-graph", operator="operator@example.com")
        self.assertEqual(graph["schema_version"], "mesh.recursive_chaos.run_evidence_graph.v1")
        self.assertEqual(graph["run_id"], run["run_id"])
        self.assertTrue(graph["advisory_only"])
        self.assertFalse(graph["mesh_model_training_allowed"])
        self.assertFalse(graph["production_authority"])
        self.assertIn("feedback_gate", {node["type"] for node in graph["nodes"]})

        output_dir = Path(run["artifacts"]["recursive_chaos_session_summary"]["output_dir"])
        self.assertTrue((output_dir / run["artifacts"]["recursive_chaos_session_summary"]["cycle_packet_refs"][0]).exists())
        artifact_records = json.loads((Path(self.temp_dir.name) / "artifacts.json").read_text(encoding="utf-8"))[
            "artifacts"
        ]
        self.assertTrue(any(record["artifact_key"].endswith("learning_packet") for record in artifact_records))

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        operator: str | None = None,
        roles: str | None = None,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(f"{self.base_url}{path}", data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if operator:
            request.add_header("X-Mesh-Operator", operator)
        if roles:
            request.add_header("X-Mesh-Role", roles)
        with urlopen(request, timeout=10) as response:
            self.assertEqual(response.status, status)
            return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
