from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from control_plane_server import start_server_in_thread
from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.schema_validation import SchemaValidationError, validate_payload


class AgentFlowContractBoundaryTests(unittest.TestCase):
    def test_confirmation_contract_rejects_executed_side_effects(self) -> None:
        confirmation = {
            "schema_version": "mesh.agent_flow.confirmation.v1",
            "state_slice": "mesh.agent_flow.mutation_preview.v1",
            "preview_id": "agent-flow-test",
            "status": "confirmation_recorded",
            "confirmed_by": "operator@example.com",
            "reason": "operator reviewed state slice and endpoint",
            "proposed_resource": "RunSession",
            "would_touch_state_slice": "mesh.run_admission.v1",
            "routed_to": "/api/runs",
            "side_effects_executed": True,
            "next_step": "Use the named Mesh-owned endpoint to execute after final operator review.",
            "created_at": "2026-05-25T00:00:00Z",
        }

        with self.assertRaises(SchemaValidationError):
            validate_payload("operator-product.schema.json", {"agent_flow_confirmation_response": confirmation})


class OperatorProductContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = RuntimeConfig(
            state_directory=self.temp_dir.name,
            vault_path=str(Path(self.temp_dir.name) / "vault"),
            integrations_config_path=str(Path(self.temp_dir.name) / "integrations.json"),
            operator_identity_path=str(Path(self.temp_dir.name) / "operator-identity.json"),
            server_host="127.0.0.1",
            server_port=0,
            auth_mode="app_session",
            captcha_dev_bypass_enabled=True,
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

    def test_product_auth_dashboard_and_settings_responses_match_schema(self) -> None:
        auth_config = self._request("GET", "/api/auth/config")
        validate_payload("operator-product.schema.json", {"auth_config": auth_config})

        session, cookie = self._request(
            "POST",
            "/api/auth/signup",
            {
                "email": "contract-operator@example.com",
                "password": "correct-horse-42",
                "display_name": "Contract Operator",
                "captcha_token": "dev-captcha-ok",
                "accepted_terms": True,
            },
            include_cookie=True,
        )
        validate_payload("operator-product.schema.json", {"session_payload": session})

        team_session, cookie = self._request(
            "POST",
            "/api/auth/team",
            {"name": "Contract Operators", "members": [{"email": "viewer@example.com", "role": "viewer"}]},
            cookie=cookie,
            include_cookie=True,
        )
        validate_payload("operator-product.schema.json", {"session_payload": team_session})
        team_id = team_session["active_team"]["id"]

        team_session = self._request(
            "POST",
            "/api/auth/team/update",
            {"team_id": team_id, "name": "Contract Operators Pilot", "display_name": "Contract Pilot"},
            cookie=cookie,
        )
        validate_payload("operator-product.schema.json", {"session_payload": team_session})

        team_session = self._request(
            "POST",
            "/api/auth/team/members",
            {"team_id": team_id, "members": [{"email": "approver@example.com", "role": "approver"}]},
            cookie=cookie,
        )
        validate_payload("operator-product.schema.json", {"session_payload": team_session})

        dashboard = self._request("GET", f"/api/operator/dashboard?team_id={team_id}", cookie=cookie)
        validate_payload("operator-product.schema.json", {"dashboard_payload": dashboard})
        self.assertIn("Mesh remains the authority", dashboard["authority_boundary"])
        self.assertEqual(dashboard["mesh"]["praxis"]["product_entrypoint"], "meshapp.home.praxis")
        self.assertEqual(dashboard["mesh"]["praxis"]["state_slice"], "praxis.managed-dry-run-runtime.v1")
        self.assertEqual(dashboard["mesh"]["praxis"]["status"], "no_runs")
        self.assertTrue(dashboard["mesh"]["praxis"]["pilot_runtime"]["dry_run_only"])
        self.assertFalse(dashboard["mesh"]["praxis"]["pilot_runtime"]["managed_runtime_deployed"])
        self.assertEqual(dashboard["operator_preferences_state"]["schema_version"], "mesh.operator-preferences.v1")
        self.assertEqual(dashboard["operator_preferences_state"]["state_slice"], "mesh.operator-preferences.v1")
        self.assertEqual(dashboard["operator_preferences_state"]["scope"], f"team:{team_id}")
        for scenario_key in dashboard["settings_schema"]["default_run_scenario"]["values"]:
            fixture_path = Path("fixtures/signals") / f"{scenario_key}.json"
            self.assertTrue(fixture_path.exists(), f"{scenario_key} must map to a runnable signal fixture")

        settings = self._request(
            "POST",
            "/api/operator/settings",
            {
                "team_id": team_id,
                "settings": {"default_orchestration_mode": "hermes"},
                "reason": "contract response validation",
            },
            cookie=cookie,
        )
        validate_payload("operator-product.schema.json", {"settings_update_response": settings})
        self.assertEqual(settings["audit"]["state_slice"], "mesh-settings-control")

        preferences = self._request(
            "POST",
            "/api/operator/preferences",
            {
                "team_id": team_id,
                "operator_preferences": {"agent_fabric_mode": "deepagents", "preferred_agents": ["codex", "hermes"]},
                "reason": "operator preference contract validation",
            },
            cookie=cookie,
        )
        validate_payload("operator-product.schema.json", {"operator_preferences_update_response": preferences})
        self.assertEqual(preferences["audit"]["state_slice"], "mesh.operator-preferences.v1")

    def test_operator_dashboard_exposes_every_product_home_section(self) -> None:
        _, cookie = self._request(
            "POST",
            "/api/auth/signup",
            {
                "email": "section-contract-operator@example.com",
                "password": "correct-horse-42",
                "display_name": "Section Contract Operator",
                "captcha_token": "dev-captcha-ok",
                "accepted_terms": True,
            },
            include_cookie=True,
        )
        team_session, cookie = self._request(
            "POST",
            "/api/auth/team",
            {"name": "Section Contracts", "members": [{"email": "viewer@example.com", "role": "viewer"}]},
            cookie=cookie,
            include_cookie=True,
        )
        team_id = team_session["active_team"]["id"]

        dashboard = self._request("GET", f"/api/operator/dashboard?team_id={team_id}", cookie=cookie)

        validate_payload("operator-product.schema.json", {"dashboard_payload": dashboard})
        required_mesh_sections = {
            "health",
            "read_model",
            "agent_flow",
            "readiness",
            "connectors",
            "approvals",
            "kill_switch",
            "pilot_go_no_go",
            "praxis",
            "trust_ladder",
            "watchers",
            "graph",
            "runs",
            "memory",
        }
        self.assertEqual(required_mesh_sections - set(dashboard["mesh"]), set())
        self.assertEqual(dashboard["mesh"]["read_model"]["source"], "/api/operator/dashboard")
        self.assertEqual(dashboard["mesh"]["read_model"]["authority"], "read_only")
        self.assertIn("degraded_reason", dashboard["mesh"]["read_model"])
        self.assertEqual(dashboard["mesh"]["agent_flow"]["state_slice"], "mesh.agent_flow.dashboard.v1")
        self.assertEqual(dashboard["mesh"]["agent_flow"]["chat_endpoint"], "/api/operator/agent-flow/chat")
        self.assertFalse(dashboard["mesh"]["agent_flow"]["livekit_configured"])
        self.assertIsInstance(dashboard["mesh"]["runs"]["runs"], list)
        self.assertIsInstance(dashboard["mesh"]["trust_ladder"]["entries"], list)
        self.assertIn("active", dashboard["mesh"]["memory"])
        self.assertIn("graph", dashboard["mesh"]["memory"])
        self.assertEqual(dashboard["operator_preferences_state"]["state_slice"], "mesh.operator-preferences.v1")
        self.assertIn("agent_fabric_mode", dashboard["operator_preferences_state"]["operator_preferences"])

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        cookie: str = "",
        include_cookie: bool = False,
    ):
        body = json.dumps(payload or {}).encode("utf-8") if method != "GET" else None
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        req = Request(f"{self.base_url}{path}", data=body, method=method, headers=headers)
        with urlopen(req, timeout=10) as response:
            parsed = json.loads(response.read().decode("utf-8"))
            if include_cookie:
                next_cookie = response.headers.get("Set-Cookie", cookie)
                return parsed, next_cookie
            return parsed
