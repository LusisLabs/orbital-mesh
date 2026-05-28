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


class HardenedArenaApiTests(unittest.TestCase):
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

    def test_profiles_and_catalog_are_read_only_api_surfaces(self) -> None:
        profiles = self._request("GET", "/api/hardened-arena/profiles")
        catalog = self._request("GET", "/api/hardened-arena/catalog")

        self.assertEqual(profiles["schema_version"], "mesh.hardened_arena.profiles.v1")
        self.assertEqual({profile["profile_id"] for profile in profiles["profiles"]}, {
            "solo_project_default",
            "startup_saas_staging",
            "enterprise_onprem_rehearsal",
        })
        self.assertEqual(catalog["schema_version"], "mesh.hardened_arena.catalog.v1")
        self.assertEqual(catalog["claim_status"], "catalog_data_only")
        self.assertFalse(catalog["deployment_claim"])
        self.assertFalse(catalog["production_readiness_claim"])
        self.assertGreater(len(catalog["entries"]), 0)

    def test_packet_creation_requires_operator_identity_and_stores_artifact(self) -> None:
        with self.assertRaises(HTTPError) as unauth:
            self._request("POST", "/api/hardened-arena/packets", {"profile_id": "solo_project_default"})
        self.assertEqual(unauth.exception.code, HTTPStatus.UNAUTHORIZED)

        created = self._request(
            "POST",
            "/api/hardened-arena/packets",
            {"profile_id": "solo_project_default"},
            operator="operator@example.com",
            roles="launcher",
            status=HTTPStatus.CREATED,
        )

        self.assertEqual(created["schema_version"], "mesh.hardened_arena.packet_create_response.v1")
        self.assertEqual(created["operator_id"], "operator@example.com")
        self.assertTrue(created["stored_artifact"])
        self.assertFalse(created["live_deployment_allowed"])
        self.assertFalse(created["secret_ingestion_allowed"])
        self.assertEqual(created["packet"]["selected_profile"]["profile_id"], "solo_project_default")
        self.assertFalse(created["packet"]["readiness_posture"]["target_validated"])
        stored_path = Path(self.temp_dir.name) / created["packet_path"]
        self.assertTrue(stored_path.exists())

        fetched = self._request("GET", f"/api/hardened-arena/packets/{created['packet_id']}")
        self.assertEqual(fetched["packet_id"], created["packet_id"])
        self.assertEqual(fetched["readiness_posture"]["status"], "profile_verified")

    def test_packet_api_rejects_unknown_profile(self) -> None:
        with self.assertRaises(HTTPError) as bad_request:
            self._request(
                "POST",
                "/api/hardened-arena/packets",
                {"profile_id": "missing_profile"},
                operator="operator@example.com",
                roles="launcher",
            )
        self.assertEqual(bad_request.exception.code, HTTPStatus.BAD_REQUEST)

    def test_intent_creation_requires_operator_identity_and_stores_review_bundle(self) -> None:
        with self.assertRaises(HTTPError) as unauth:
            self._request("POST", "/api/hardened-arena/intents", {"profile_id": "solo_project_default"})
        self.assertEqual(unauth.exception.code, HTTPStatus.UNAUTHORIZED)

        created = self._request(
            "POST",
            "/api/hardened-arena/intents",
            {"profile_id": "solo_project_default"},
            operator="operator@example.com",
            roles="launcher",
            status=HTTPStatus.CREATED,
        )

        self.assertEqual(created["schema_version"], "mesh.hardened_arena.intent_create_response.v1")
        self.assertEqual(created["operator_id"], "operator@example.com")
        self.assertTrue(created["stored_artifact"])
        self.assertFalse(created["live_deployment_allowed"])
        self.assertFalse(created["secret_ingestion_allowed"])
        self.assertFalse(created["kubeconfig_material_present"])
        self.assertTrue(created["intent"]["review_only"])
        self.assertFalse(created["intent"]["live_deployment_allowed"])
        self.assertEqual(created["intent"]["profile_id"], "solo_project_default")
        self.assertIn("target_validation_missing", created["intent"]["blockers"])
        stored_path = Path(self.temp_dir.name) / created["intent_path"]
        self.assertTrue(stored_path.exists())
        self.assertEqual(json.loads(stored_path.read_text(encoding="utf-8"))["intent_id"], created["intent_id"])

    def test_intent_api_rejects_unknown_profile(self) -> None:
        with self.assertRaises(HTTPError) as bad_request:
            self._request(
                "POST",
                "/api/hardened-arena/intents",
                {"profile_id": "missing_profile"},
                operator="operator@example.com",
                roles="launcher",
            )
        self.assertEqual(bad_request.exception.code, HTTPStatus.BAD_REQUEST)

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
