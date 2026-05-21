from __future__ import annotations

import base64
import json
import tempfile
import time
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from control_plane_server import start_server_in_thread
from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.schema_validation import validate_payload


def _decode_jwt_payload(token: str) -> dict:
    payload = token.split(".")[1]
    padded = payload + "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))


class OperatorAuthHttpTests(unittest.TestCase):
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

    def test_signup_team_dashboard_and_protected_run_creation(self) -> None:
        with self.assertRaises(HTTPError) as unauth:
            self._request("GET", "/api/operator/dashboard")
        self.assertEqual(unauth.exception.code, HTTPStatus.UNAUTHORIZED)

        payload, cookie = self._request(
            "POST",
            "/api/auth/signup",
            {
                "email": "operator@example.com",
                "password": "correct-horse-42",
                "captcha_token": "dev-captcha-ok",
                "accepted_terms": True,
            },
            include_cookie=True,
        )
        self.assertEqual(payload["user"]["email"], "operator@example.com")
        self.assertIn("mesh_session=", cookie)

        team_payload, _ = self._request(
            "POST",
            "/api/auth/team",
            {"name": "Mesh Operators", "members": [{"email": "viewer@example.com", "role": "viewer"}]},
            cookie=cookie,
            include_cookie=True,
        )
        self.assertEqual(team_payload["active_team"]["name"], "Mesh Operators")
        team_id = team_payload["active_team"]["id"]

        updated_team, _ = self._request(
            "POST",
            "/api/auth/team/update",
            {"team_id": team_id, "name": "Mesh Operators Pilot", "display_name": "Pilot Operators"},
            cookie=cookie,
            include_cookie=True,
        )
        self.assertEqual(updated_team["active_team"]["name"], "Mesh Operators Pilot")
        self.assertEqual(updated_team["active_team"]["display_name"], "Pilot Operators")

        cleared_team_display, _ = self._request(
            "POST",
            "/api/auth/team/update",
            {"team_id": team_id, "name": "Mesh Operators Pilot", "display_name": ""},
            cookie=cookie,
            include_cookie=True,
        )
        self.assertEqual(cleared_team_display["active_team"]["display_name"], "Mesh Operators Pilot")

        updated_members, _ = self._request(
            "POST",
            "/api/auth/team/members",
            {"team_id": team_id, "members": [{"email": "approver@example.com", "role": "approver"}]},
            cookie=cookie,
            include_cookie=True,
        )
        approver = next(member for member in updated_members["active_team"]["members"] if member["email"] == "approver@example.com")
        self.assertEqual(approver["role"], "approver")

        dashboard, _ = self._request("GET", "/api/operator/dashboard", cookie=cookie, include_cookie=True)
        self.assertEqual(dashboard["scope"]["kind"], "team")
        self.assertIn("Mesh remains the authority", dashboard["authority_boundary"])
        self.assertIn("readiness", dashboard["mesh"])
        self.assertEqual(dashboard["mesh"]["praxis"]["state_slice"], "praxis.managed-dry-run-runtime.v1")
        self.assertEqual(dashboard["mesh"]["praxis"]["status"], "no_runs")
        self.assertEqual(dashboard["mesh"]["praxis"]["pilot_runtime"]["status"], "not_started")
        self.assertTrue(dashboard["mesh"]["praxis"]["pilot_runtime"]["dry_run_only"])
        self.assertFalse(dashboard["mesh"]["praxis"]["pilot_runtime"]["managed_runtime_deployed"])
        self.assertEqual(dashboard["operator_preferences_state"]["state_slice"], "mesh.operator-preferences.v1")
        self.assertEqual(dashboard["operator_preferences_state"]["scope"], f"team:{team_id}")

        preferences, _ = self._request(
            "POST",
            "/api/operator/preferences",
            {
                "team_id": team_id,
                "operator_preferences": {"agent_fabric_mode": "deepagents", "preferred_agents": ["codex", "hermes"]},
                "reason": "configure operator lanes",
            },
            cookie=cookie,
            include_cookie=True,
        )
        self.assertEqual(preferences["state_slice"], "mesh.operator-preferences.v1")
        self.assertEqual(preferences["audit"]["state_slice"], "mesh.operator-preferences.v1")
        self.assertEqual(preferences["operator_preferences"]["agent_fabric_mode"], "deepagents")

        run, _ = self._request(
            "POST",
            "/api/runs",
            {"scenario_key": "reth_peer_starvation", "audit_reason": "prove product-native run admission"},
            cookie=cookie,
            include_cookie=True,
        )
        self.assertIn("run_id", run)
        self.assertIn(run["status"], {"queued", "pending", "running", "completed", "failed"})
        self.assertEqual(run["artifacts"]["run_admission"]["schema_version"], "mesh.run_admission.v1")
        self.assertEqual(run["artifacts"]["operator_audit"]["state_slice"], "meshapp.run-admission-launch.v1")
        self.assertEqual(run["artifacts"]["operator_audit"]["reason"], "prove product-native run admission")

    def test_praxis_generation_runtime_api_persists_team_scoped_dry_run(self) -> None:
        _, cookie = self._request(
            "POST",
            "/api/auth/signup",
            {
                "email": "praxis@example.com",
                "password": "correct-horse-42",
                "captcha_token": "dev-captcha-ok",
                "accepted_terms": True,
            },
            include_cookie=True,
        )
        team_payload, _ = self._request(
            "POST",
            "/api/auth/team",
            {"name": "Praxis Operators"},
            cookie=cookie,
            include_cookie=True,
        )
        team_id = team_payload["active_team"]["id"]

        generation, _ = self._request(
            "POST",
            "/api/operator/praxis/generation-requests",
            {
                "team_id": team_id,
                "request_id": "praxis-request-http-001",
                "sources": [
                    {"source_type": "openapi", "source_ref": "fixtures/praxis/demo-openapi.redacted.json"},
                    {"source_type": "postman_json", "source_ref": "fixtures/praxis/demo-postman.redacted.json"},
                    {"source_type": "sop_markdown", "source_ref": "fixtures/praxis/demo-sop.redacted.md"},
                    {"source_type": "redacted_traffic_ref", "source_ref": "fixtures/praxis/demo-traffic-ref.redacted.json"},
                ],
            },
            cookie=cookie,
            include_cookie=True,
        )
        self.assertEqual(generation["status"], "candidate_generated")
        self.assertEqual(generation["owner_scope"]["scope_id"], f"team:{team_id}")

        evidence, _ = self._request(
            "POST",
            "/api/operator/praxis/generation-requests/praxis-request-http-001/akto-evidence",
            {
                "team_id": team_id,
                "evidence_id": "praxis-akto-http-001",
                "akto_result_path": "fixtures/praxis/demo-akto-results.json",
            },
            cookie=cookie,
            include_cookie=True,
        )
        self.assertEqual(evidence["status"], "security_evidence_imported")

        binding, _ = self._request(
            "POST",
            "/api/operator/praxis/generation-requests/praxis-request-http-001/certification-binding",
            {
                "team_id": team_id,
                "binding_id": "praxis-binding-http-001",
                "connector_id": "praxis-http-generated-mcp",
                "acp_session_id": "praxis-acp-http-001",
            },
            cookie=cookie,
            include_cookie=True,
        )
        self.assertEqual(binding["dry_run_runtime"]["status"], "dry_run_ready")
        self.assertFalse(binding["dry_run_runtime"]["managed_runtime_deployed"])

        running, _ = self._request(
            "POST",
            "/api/operator/praxis/generation-requests/praxis-request-http-001/dry-run/start",
            {"team_id": team_id},
            cookie=cookie,
            include_cookie=True,
        )
        self.assertEqual(running["dry_run_runtime"]["status"], "running")

        call, _ = self._request(
            "POST",
            "/api/operator/praxis/generation-requests/praxis-request-http-001/dry-run/call",
            {"team_id": team_id, "tool_id": "tool.listorders", "arguments": {}},
            cookie=cookie,
            include_cookie=True,
        )
        self.assertTrue(call["allowed"])
        self.assertFalse(call["side_effects_executed"])

        with self.assertRaises(HTTPError) as denied:
            self._request(
                "POST",
                "/api/operator/praxis/generation-requests/praxis-request-http-001/dry-run/call",
                {"team_id": team_id, "tool_id": "tool.cancelorder", "arguments": {"order_id": "ord_demo"}},
                cookie=cookie,
            )
        self.assertEqual(denied.exception.code, HTTPStatus.FORBIDDEN)

        revoked, _ = self._request(
            "POST",
            "/api/operator/praxis/generation-requests/praxis-request-http-001/revoke",
            {"team_id": team_id, "reason": "operator test complete"},
            cookie=cookie,
            include_cookie=True,
        )
        self.assertEqual(revoked["dry_run_runtime"]["status"], "revoked")
        self.assertEqual(revoked["p10_proof_packet"]["status"], "complete")

        runs, _ = self._request("GET", f"/api/operator/praxis/runs?team_id={team_id}", cookie=cookie, include_cookie=True)
        self.assertEqual(runs["state_slice"], "praxis.managed-dry-run-runtime.v1")
        self.assertEqual(runs["runs"][0]["request_id"], "praxis-request-http-001")
        self.assertEqual(runs["runs"][0]["dry_run_status"], "revoked")

        dashboard, _ = self._request("GET", f"/api/operator/dashboard?team_id={team_id}", cookie=cookie, include_cookie=True)
        self.assertEqual(dashboard["mesh"]["praxis"]["summary"]["runs"], 1)
        self.assertEqual(dashboard["mesh"]["praxis"]["pilot_runtime"]["status"], "revoked")
        self.assertEqual(dashboard["mesh"]["praxis"]["p10_proof_packet"]["status"], "complete")

    def test_dashboard_read_model_degrades_failed_sections_explicitly(self) -> None:
        def broken_readiness():
            raise RuntimeError("readiness unavailable")

        self.server.coordinator.build_readiness = broken_readiness
        _, cookie = self._request(
            "POST",
            "/api/auth/signup",
            {
                "email": "dashboard@example.com",
                "password": "correct-horse-42",
                "captcha_token": "dev-captcha-ok",
                "accepted_terms": True,
            },
            include_cookie=True,
        )

        dashboard, _ = self._request("GET", "/api/operator/dashboard", cookie=cookie, include_cookie=True)
        self.assertEqual(dashboard["mesh"]["read_model"]["authority"], "read_only")
        self.assertEqual(dashboard["mesh"]["readiness"]["status"], "unavailable")
        self.assertEqual(dashboard["mesh"]["readiness"]["error"], "readiness unavailable")

    def test_agent_flow_chat_livekit_and_confirmation_are_session_scoped(self) -> None:
        with self.assertRaises(HTTPError) as unauth:
            self._request("POST", "/api/operator/agent-flow/chat", {"message": "inspect readiness"})
        self.assertEqual(unauth.exception.code, HTTPStatus.UNAUTHORIZED)

        _, cookie = self._request(
            "POST",
            "/api/auth/signup",
            {
                "email": "agent-flow@example.com",
                "password": "correct-horse-42",
                "captcha_token": "dev-captcha-ok",
                "accepted_terms": True,
            },
            include_cookie=True,
        )
        team_payload = self._request(
            "POST",
            "/api/auth/team",
            {"name": "Agent Flow Operators"},
            cookie=cookie,
        )
        team_id = team_payload["active_team"]["id"]

        unconfigured_livekit = self._request(
            "POST",
            "/api/operator/agent-flow/livekit-session",
            {"team_id": team_id},
            cookie=cookie,
        )
        self.assertEqual(unconfigured_livekit["state_slice"], "mesh.agent_flow.livekit_session.v1")
        self.assertEqual(unconfigured_livekit["status"], "unconfigured")
        self.assertEqual(unconfigured_livekit["token"], "")
        self.assertFalse(unconfigured_livekit["side_effects_executed"])

        self.server.config.livekit_url = "wss://livekit.example.test"
        self.server.config.livekit_api_key = "lk-public-key"
        self.server.config.livekit_api_secret = "lk-secret-redacted"
        configured_livekit = self._request(
            "POST",
            "/api/operator/agent-flow/livekit-session",
            {"team_id": team_id, "room": "agent-flow-test"},
            cookie=cookie,
        )
        validate_payload("operator-product.schema.json", {"agent_flow_livekit_session_response": configured_livekit})
        second_livekit = self._request(
            "POST",
            "/api/operator/agent-flow/livekit-session",
            {"team_id": team_id, "room": "agent-flow-test"},
            cookie=cookie,
        )
        self.assertEqual(configured_livekit["status"], "ready")
        self.assertEqual(configured_livekit["livekit_url"], "wss://livekit.example.test")
        self.assertTrue(configured_livekit["room"].startswith("harper-696-team-"))
        self.assertTrue(configured_livekit["room"].endswith("-agent-flow-test"))
        self.assertNotEqual(configured_livekit["participant_identity"], second_livekit["participant_identity"])
        self.assertTrue(configured_livekit["token"])
        self.assertNotIn("lk-secret-redacted", configured_livekit["token"])
        livekit_claims = _decode_jwt_payload(configured_livekit["token"])
        self.assertEqual(livekit_claims["video"]["canPublishSources"], ["microphone"])
        self.assertFalse(livekit_claims["video"]["canPublishData"])

        chat = self._request(
            "POST",
            "/api/operator/agent-flow/chat",
            {"team_id": team_id, "message": "Inspect blockers and draft a launch"},
            cookie=cookie,
        )
        validate_payload("operator-product.schema.json", {"agent_flow_chat_response": chat})
        self.assertEqual(chat["state_slice"], "mesh.agent_flow.chat_response.v1")
        self.assertIn("mesh.agent_flow.mutation_preview.v1", chat["state_slices"])
        self.assertEqual(chat["mutation_preview"]["state_slice"], "mesh.agent_flow.mutation_preview.v1")
        self.assertEqual(chat["mutation_preview"]["endpoint"], "/api/runs")
        self.assertEqual(chat["mutation_preview"]["issued_scope"], f"team:{team_id}")
        self.assertEqual(chat["mutation_preview"]["proof"]["algorithm"], "HMAC-SHA256")
        self.assertTrue(chat["mutation_preview"]["proof"]["signature"])
        self.assertTrue(chat["mutation_preview"]["confirmation_required"])
        self.assertFalse(chat["mutation_preview"]["side_effects_executed"])
        self.assertGreaterEqual(len(chat["lifecycle"]["tasks"]), 3)

        with self.assertRaises(HTTPError) as missing_reason:
            self._request(
                "POST",
                "/api/operator/agent-flow/confirm-preview",
                {
                    "team_id": team_id,
                    "preview_id": chat["mutation_preview"]["preview_id"],
                    "preview": chat["mutation_preview"],
                    "reason": "",
                },
                cookie=cookie,
            )
        self.assertEqual(missing_reason.exception.code, HTTPStatus.BAD_REQUEST)

        tampered_preview = dict(chat["mutation_preview"])
        tampered_preview["endpoint"] = "/api/auth/logout"
        with self.assertRaises(HTTPError) as tampered:
            self._request(
                "POST",
                "/api/operator/agent-flow/confirm-preview",
                {
                    "team_id": team_id,
                    "preview_id": chat["mutation_preview"]["preview_id"],
                    "preview": tampered_preview,
                    "reason": "tampered route should not be accepted",
                },
                cookie=cookie,
            )
        self.assertEqual(tampered.exception.code, HTTPStatus.BAD_REQUEST)

        metadata_tampered_preview = dict(chat["mutation_preview"])
        metadata_tampered_preview["proof"] = dict(chat["mutation_preview"]["proof"])
        metadata_tampered_preview["status"] = "confirmed"
        metadata_tampered_preview["proof"]["bound_state_slice"] = "mesh.other"
        with self.assertRaises(HTTPError) as metadata_tampered:
            self._request(
                "POST",
                "/api/operator/agent-flow/confirm-preview",
                {
                    "team_id": team_id,
                    "preview_id": chat["mutation_preview"]["preview_id"],
                    "preview": metadata_tampered_preview,
                    "reason": "metadata tampering should not be accepted",
                },
                cookie=cookie,
            )
        self.assertEqual(metadata_tampered.exception.code, HTTPStatus.BAD_REQUEST)

        _, other_cookie = self._request(
            "POST",
            "/api/auth/signup",
            {
                "email": "agent-flow-other@example.com",
                "password": "correct-horse-42",
                "captcha_token": "dev-captcha-ok",
                "accepted_terms": True,
            },
            include_cookie=True,
        )
        with self.assertRaises(HTTPError) as wrong_session:
            self._request(
                "POST",
                "/api/operator/agent-flow/confirm-preview",
                {
                    "preview_id": chat["mutation_preview"]["preview_id"],
                    "preview": chat["mutation_preview"],
                    "reason": "different session should not confirm this preview",
                },
                cookie=other_cookie,
            )
        self.assertEqual(wrong_session.exception.code, HTTPStatus.BAD_REQUEST)

        confirmation = self._request(
            "POST",
            "/api/operator/agent-flow/confirm-preview",
            {
                "team_id": team_id,
                "preview_id": chat["mutation_preview"]["preview_id"],
                "preview": chat["mutation_preview"],
                "reason": "operator reviewed state slice and endpoint",
            },
            cookie=cookie,
        )
        validate_payload("operator-product.schema.json", {"agent_flow_confirmation_response": confirmation})
        self.assertEqual(confirmation["state_slice"], "mesh.agent_flow.mutation_preview.v1")
        self.assertEqual(confirmation["status"], "confirmation_recorded")
        self.assertEqual(confirmation["routed_to"], "/api/runs")
        self.assertFalse(confirmation["side_effects_executed"])

    def test_logout_login_and_dashboard_recovery(self) -> None:
        _, cookie = self._request(
            "POST",
            "/api/auth/signup",
            {
                "email": "recover@example.com",
                "password": "correct-horse-42",
                "captcha_token": "dev-captcha-ok",
                "accepted_terms": True,
            },
            include_cookie=True,
        )
        self._request("POST", "/api/auth/team", {"name": "Recovery Operators"}, cookie=cookie)
        logout, clear_cookie = self._request("POST", "/api/auth/logout", {}, cookie=cookie, include_cookie=True)
        self.assertEqual(logout["status"], "logged_out")
        self.assertIn("Max-Age=0", clear_cookie)

        with self.assertRaises(HTTPError) as expired:
            self._request("GET", "/api/operator/dashboard", cookie=cookie)
        self.assertEqual(expired.exception.code, HTTPStatus.UNAUTHORIZED)

        logged_in, login_cookie = self._request(
            "POST",
            "/api/auth/login",
            {"email": "recover@example.com", "password": "correct-horse-42"},
            include_cookie=True,
        )
        self.assertEqual(logged_in["user"]["email"], "recover@example.com")
        dashboard, _ = self._request("GET", "/api/operator/dashboard", cookie=login_cookie, include_cookie=True)
        self.assertEqual(dashboard["scope"]["kind"], "team")

    def test_expired_session_recovery_clears_cookie_across_product_routes(self) -> None:
        routes = [
            ("GET", "/api/auth/me", None),
            ("GET", "/api/operator/dashboard", None),
            ("POST", "/api/auth/team", {"name": "Expired Operators"}),
        ]
        for index, (method, path, payload) in enumerate(routes):
            with self.subTest(path=path):
                _, cookie = self._request(
                    "POST",
                    "/api/auth/signup",
                    {
                        "email": f"expired-{index}@example.com",
                        "password": "correct-horse-42",
                        "captcha_token": "dev-captcha-ok",
                        "accepted_terms": True,
                    },
                    include_cookie=True,
                )
                self._expire_all_sessions()

                with self.assertRaises(HTTPError) as expired:
                    self._request(method, path, payload, cookie=cookie)
                self.assertEqual(expired.exception.code, HTTPStatus.UNAUTHORIZED)
                self.assertIn("Max-Age=0", expired.exception.headers.get("Set-Cookie", ""))

    def test_team_isolation_and_scoped_settings_are_forbidden_for_non_member(self) -> None:
        _, owner_cookie = self._request(
            "POST",
            "/api/auth/signup",
            {
                "email": "owner@example.com",
                "password": "correct-horse-42",
                "captcha_token": "dev-captcha-ok",
                "accepted_terms": True,
            },
            include_cookie=True,
        )
        team_payload, _ = self._request("POST", "/api/auth/team", {"name": "Private Operators"}, cookie=owner_cookie, include_cookie=True)
        team_id = team_payload["active_team"]["id"]

        _, outsider_cookie = self._request(
            "POST",
            "/api/auth/signup",
            {
                "email": "outsider@example.com",
                "password": "correct-horse-42",
                "captcha_token": "dev-captcha-ok",
                "accepted_terms": True,
            },
            include_cookie=True,
        )
        with self.assertRaises(HTTPError) as dashboard_error:
            self._request("GET", f"/api/operator/dashboard?team_id={team_id}", cookie=outsider_cookie)
        self.assertEqual(dashboard_error.exception.code, HTTPStatus.FORBIDDEN)

        with self.assertRaises(HTTPError) as switch_error:
            self._request("POST", "/api/auth/switch-team", {"team_id": team_id}, cookie=outsider_cookie)
        self.assertEqual(switch_error.exception.code, HTTPStatus.FORBIDDEN)

        with self.assertRaises(HTTPError) as team_update_error:
            self._request("POST", "/api/auth/team/update", {"team_id": team_id, "name": "Blocked"}, cookie=outsider_cookie)
        self.assertEqual(team_update_error.exception.code, HTTPStatus.FORBIDDEN)

        with self.assertRaises(HTTPError) as member_update_error:
            self._request(
                "POST",
                "/api/auth/team/members",
                {"team_id": team_id, "members": [{"email": "blocked@example.com", "role": "viewer"}]},
                cookie=outsider_cookie,
            )
        self.assertEqual(member_update_error.exception.code, HTTPStatus.FORBIDDEN)

        with self.assertRaises(HTTPError) as settings_error:
            self._request(
                "POST",
                "/api/operator/settings",
                {"team_id": team_id, "settings": {"default_evaluation_mode": "promptfoo"}, "reason": "verify team isolation"},
                cookie=outsider_cookie,
            )
        self.assertEqual(settings_error.exception.code, HTTPStatus.FORBIDDEN)

        with self.assertRaises(HTTPError) as preferences_error:
            self._request(
                "POST",
                "/api/operator/preferences",
                {"team_id": team_id, "operator_preferences": {"agent_fabric_mode": "deepagents"}, "reason": "verify team isolation"},
                cookie=outsider_cookie,
            )
        self.assertEqual(preferences_error.exception.code, HTTPStatus.FORBIDDEN)

    def test_operator_settings_requires_reason_and_writes_shared_audit(self) -> None:
        payload, cookie = self._request(
            "POST",
            "/api/auth/signup",
            {
                "email": "settings@example.com",
                "password": "correct-horse-42",
                "captcha_token": "dev-captcha-ok",
                "accepted_terms": True,
            },
            include_cookie=True,
        )

        with self.assertRaises(HTTPError) as missing_reason:
            self._request(
                "POST",
                "/api/operator/settings",
                {"settings": {"default_evaluation_mode": "promptfoo"}},
                cookie=cookie,
            )
        self.assertEqual(missing_reason.exception.code, HTTPStatus.BAD_REQUEST)

        updated, _ = self._request(
            "POST",
            "/api/operator/settings",
            {
                "settings": {"default_evaluation_mode": "promptfoo"},
                "reason": "P6 parity test",
            },
            cookie=cookie,
            include_cookie=True,
        )
        scope = f"user:{payload['user']['id']}"
        self.assertEqual(updated["settings"]["default_evaluation_mode"], "promptfoo")
        self.assertEqual(updated["audit"]["scope"], scope)
        self.assertEqual(updated["audit"]["state_slice"], "mesh-settings-control")

        with self.assertRaises(HTTPError) as missing_preference_reason:
            self._request(
                "POST",
                "/api/operator/preferences",
                {"operator_preferences": {"agent_fabric_mode": "deepagents"}},
                cookie=cookie,
            )
        self.assertEqual(missing_preference_reason.exception.code, HTTPStatus.BAD_REQUEST)

        preference_update, _ = self._request(
            "POST",
            "/api/operator/preferences",
            {
                "operator_preferences": {"agent_fabric_mode": "deepagents", "preferred_agents": ["codex"]},
                "reason": "preference parity test",
            },
            cookie=cookie,
            include_cookie=True,
        )
        self.assertEqual(preference_update["operator_preferences"]["agent_fabric_mode"], "deepagents")
        self.assertEqual(preference_update["audit"]["scope"], scope)
        self.assertEqual(preference_update["audit"]["state_slice"], "mesh.operator-preferences.v1")

        identity_path = Path(self.config.operator_identity_path)
        data = json.loads(identity_path.read_text(encoding="utf-8"))
        self.assertEqual(data["settings"][scope]["default_evaluation_mode"], "promptfoo")
        self.assertEqual(data["operator_preferences"][scope]["agent_fabric_mode"], "deepagents")
        audit_path = identity_path.parent / "operator-config-audit.jsonl"
        audit_record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(audit_record["operator_id"], "settings@example.com")
        self.assertEqual(audit_record["reason"], "P6 parity test")
        self.assertEqual(audit_record["fields"], ["default_evaluation_mode"])

    def test_oauth_start_urls_and_callback_failures_are_clear(self) -> None:
        self.server.config.google_oauth_client_id = "google-client"
        self.server.config.google_oauth_client_secret = "google-secret"
        self.server.config.google_oauth_redirect_url = "http://127.0.0.1:8787/api/auth/oauth/google/callback"
        self.server.config.github_oauth_client_id = "github-client"
        self.server.config.github_oauth_client_secret = "github-secret"
        self.server.config.github_oauth_redirect_url = "http://127.0.0.1:8787/api/auth/oauth/github/callback"

        google, _ = self._request("GET", "/api/auth/oauth/google/start", include_cookie=True)
        google_url = urlparse(google["authorize_url"])
        google_query = parse_qs(google_url.query)
        self.assertEqual(google_url.netloc, "accounts.google.com")
        self.assertEqual(google_query["client_id"], ["google-client"])
        self.assertEqual(google_query["redirect_uri"], ["http://127.0.0.1:8787/api/auth/oauth/google/callback"])
        self.assertTrue(google_query["state"][0])

        github, _ = self._request("GET", "/api/auth/oauth/github/start", include_cookie=True)
        github_url = urlparse(github["authorize_url"])
        github_query = parse_qs(github_url.query)
        self.assertEqual(github_url.netloc, "github.com")
        self.assertEqual(github_query["client_id"], ["github-client"])
        self.assertEqual(github_query["redirect_uri"], ["http://127.0.0.1:8787/api/auth/oauth/github/callback"])
        self.assertTrue(github_query["state"][0])

        with self.assertRaises(HTTPError) as missing_code:
            self._request_no_redirect("GET", "/api/auth/oauth/google/callback")
        self.assertEqual(missing_code.exception.code, HTTPStatus.FOUND)
        self.assertEqual(missing_code.exception.headers["Location"], "/?auth_error=missing_oauth_code")

    def test_oauth_callback_redirects_to_configured_local_product_url(self) -> None:
        self.server.config.google_oauth_client_id = "google-client"
        self.server.config.google_oauth_client_secret = "google-secret"
        self.server.config.google_oauth_redirect_url = f"{self.base_url}/api/auth/oauth/google/callback"
        self.server.config.auth_product_redirect_url = "http://127.0.0.1:3000"

        self._complete_oauth_callback(
            "google",
            {
                "provider_user_id": "google-redirect-user",
                "email": "google-redirect@example.com",
                "display_name": "Google Redirect",
            },
            expected_location="http://127.0.0.1:3000?auth=ok",
        )

        with self.assertRaises(HTTPError) as missing_code:
            self._request_no_redirect("GET", "/api/auth/oauth/google/callback")
        self.assertEqual(missing_code.exception.code, HTTPStatus.FOUND)
        self.assertEqual(missing_code.exception.headers["Location"], "http://127.0.0.1:3000?auth_error=missing_oauth_code")

    def test_oauth_callback_rejects_unallowed_product_redirect_url(self) -> None:
        self.server.config.github_oauth_client_id = "github-client"
        self.server.config.github_oauth_client_secret = "github-secret"
        self.server.config.github_oauth_redirect_url = f"{self.base_url}/api/auth/oauth/github/callback"
        self.server.config.auth_product_redirect_url = "https://evil.example.test/"

        self._complete_oauth_callback(
            "github",
            {
                "provider_user_id": "github-redirect-user",
                "email": "github-redirect@example.com",
                "display_name": "GitHub Redirect",
            },
            expected_location="/?auth=ok",
        )

    def test_oauth_callback_allows_configured_auth_origin(self) -> None:
        self.server.config.github_oauth_client_id = "github-client"
        self.server.config.github_oauth_client_secret = "github-secret"
        self.server.config.github_oauth_redirect_url = f"{self.base_url}/api/auth/oauth/github/callback"
        self.server.config.auth_product_redirect_url = "https://operators.example.com/product"
        self.server.config.auth_allowed_origins = ("https://operators.example.com",)

        self._complete_oauth_callback(
            "github",
            {
                "provider_user_id": "github-origin-user",
                "email": "github-origin@example.com",
                "display_name": "GitHub Origin",
            },
            expected_location="https://operators.example.com/product?auth=ok",
        )

    def test_auth_provider_runtime_evidence_records_redacted_provider_sessions(self) -> None:
        self.server.config.captcha_dev_bypass_enabled = False
        self.server.config.captcha_provider = "hcaptcha"
        self.server.config.captcha_site_key = "site-key"
        self.server.config.captcha_secret_key = "secret-key"
        self.server.config.google_oauth_client_id = "google-client"
        self.server.config.google_oauth_client_secret = "google-secret"
        self.server.config.google_oauth_redirect_url = f"{self.base_url}/api/auth/oauth/google/callback"
        self.server.config.github_oauth_client_id = "github-client"
        self.server.config.github_oauth_client_secret = "github-secret"
        self.server.config.github_oauth_redirect_url = f"{self.base_url}/api/auth/oauth/github/callback"

        with patch("shared.mesh_runtime.operator_identity.verify_captcha_token", return_value=None):
            _, signup_cookie = self._request(
                "POST",
                "/api/auth/signup",
                {
                    "email": "provider-proof@example.com",
                    "password": "correct-horse-42",
                    "captcha_token": "provider-browser-token-redacted",
                    "accepted_terms": True,
                },
                include_cookie=True,
            )
        self.assertIn("mesh_session=", signup_cookie)

        self._complete_oauth_callback(
            "google",
            {
                "provider_user_id": "google-user-1",
                "email": "google-proof@example.com",
                "display_name": "Google Proof",
            },
        )
        self._complete_oauth_callback(
            "github",
            {
                "provider_user_id": "github-user-1",
                "email": "github-proof@example.com",
                "display_name": "GitHub Proof",
            },
        )

        evidence = self.server.operator_identity.auth_provider_evidence()
        self.assertEqual(evidence["schema_version"], "mesh.operator_auth_runtime_evidence.v1")
        self.assertEqual(evidence["state_slice"], "auth-provider-proof.v1")
        self.assertEqual(evidence["status"], "complete")
        self.assertEqual(evidence["email_signup"]["status"], "complete")
        self.assertEqual(evidence["providers"]["google_oauth"]["status"], "complete")
        self.assertEqual(evidence["providers"]["github_oauth"]["status"], "complete")
        self.assertEqual(evidence["captcha"]["status"], "complete")
        self.assertTrue(evidence["captcha"]["browser_token_verified"])

        data = json.loads(Path(self.config.operator_identity_path).read_text(encoding="utf-8"))
        events_json = json.dumps(data["auth_events"], sort_keys=True)
        self.assertIn("session_token_hash", events_json)
        self.assertNotIn("provider-browser-token-redacted", events_json)
        self.assertNotIn("google-secret", events_json)
        self.assertNotIn("github-secret", events_json)
        self.assertNotIn("access_token", events_json)

    def test_oauth_start_routes_fail_closed_without_provider_config(self) -> None:
        for provider in ("google", "github"):
            with self.subTest(provider=provider):
                with self.assertRaises(HTTPError) as oauth_error:
                    self._request("GET", f"/api/auth/oauth/{provider}/start")

                self.assertEqual(oauth_error.exception.code, HTTPStatus.SERVICE_UNAVAILABLE)
                body = json.loads(oauth_error.exception.read().decode("utf-8"))
                self.assertEqual(body["error"], f"{provider} oauth is not configured")

    def test_captcha_missing_provider_secret_fails_closed(self) -> None:
        self.server.config.captcha_dev_bypass_enabled = False
        self.server.config.captcha_provider = "hcaptcha"
        self.server.config.captcha_site_key = "site-key"
        self.server.config.captcha_secret_key = ""

        with self.assertRaises(HTTPError) as signup_error:
            self._request(
                "POST",
                "/api/auth/signup",
                {
                    "email": "blocked@example.com",
                    "password": "correct-horse-42",
                    "captcha_token": "",
                },
            )
        self.assertEqual(signup_error.exception.code, HTTPStatus.BAD_REQUEST)

    def _expire_all_sessions(self) -> None:
        identity_path = Path(self.config.operator_identity_path)
        data = json.loads(identity_path.read_text(encoding="utf-8"))
        for record in data["sessions"].values():
            record["expires_at"] = "2000-01-01T00:00:00Z"
        identity_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

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
                return parsed, response.headers.get("Set-Cookie", "")
            return parsed

    def _request_no_redirect(self, method: str, path: str, payload: dict | None = None):
        body = json.dumps(payload or {}).encode("utf-8") if method != "GET" else None
        req = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        opener = build_opener(_NoRedirectHandler)
        with opener.open(req, timeout=10) as response:
            return response

    def _complete_oauth_callback(self, provider: str, profile: dict[str, str], *, expected_location: str = "/?auth=ok") -> str:
        start, _ = self._request("GET", f"/api/auth/oauth/{provider}/start", include_cookie=True)
        query = parse_qs(urlparse(start["authorize_url"]).query)
        state = query["state"][0]
        with patch("control_plane_server.exchange_oauth_profile", return_value=profile):
            with self.assertRaises(HTTPError) as redirect:
                self._request_no_redirect("GET", f"/api/auth/oauth/{provider}/callback?code=provider-code-redacted&state={state}")
        self.assertEqual(redirect.exception.code, HTTPStatus.FOUND)
        self.assertEqual(redirect.exception.headers["Location"], expected_location)
        cookie = redirect.exception.headers.get("Set-Cookie", "")
        self.assertIn("mesh_session=", cookie)
        return cookie


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


if __name__ == "__main__":
    unittest.main()
