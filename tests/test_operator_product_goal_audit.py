import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.operator_product_goal_audit import (
    P0_E2E_MARKERS,
    P0_PACKAGE_SCRIPTS,
    P1_PRODUCT_MARKERS,
    P1_TEST_MARKERS,
    P2_API_MARKERS,
    P2_BACKEND_MARKERS,
    P2_PRODUCT_MARKERS,
    P3_API_MARKERS,
    P3_PRODUCT_MARKERS,
    P4_CLI_MARKERS,
    P4_PRODUCT_MARKERS,
    P4_TEST_MARKERS,
    P5_PRODUCT_MARKERS,
    P5_TEST_MARKERS,
    P6_DOC_MARKERS,
    P6_PACKAGE_SCRIPTS,
    STATUS_BLOCKED_EXTERNAL,
    STATUS_BLOCKED_LOCAL,
    STATUS_COMPLETE,
    build_goal_audit,
)


class OperatorProductGoalAuditTests(unittest.TestCase):
    def test_goal_audit_blocks_only_on_external_provider_proof_when_local_markers_exist(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = _minimal_goal_tree(Path(tmp_dir), auth_status="blocked_provider_console_unverified")

            audit = build_goal_audit(root)

        self.assertEqual(audit["schema_version"], "mesh.operator_product_goal_audit.v1")
        self.assertEqual(audit["state_slice"], "operator-product-goal-audit")
        self.assertEqual(audit["status"], STATUS_BLOCKED_EXTERNAL)
        self.assertEqual(audit["known_external_blockers"], ["live_provider_proof_missing"])
        self.assertEqual(audit["requirements"][0]["id"], "P0")
        self.assertEqual(audit["requirements"][0]["status"], STATUS_BLOCKED_EXTERNAL)
        self.assertFalse(audit["requirements"][0]["missing"])
        self.assertTrue(all(item["status"] == STATUS_COMPLETE for item in audit["requirements"][1:]))

    def test_goal_audit_completes_when_live_provider_proof_is_complete(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = _minimal_goal_tree(Path(tmp_dir), auth_status="provider_browser_proof_complete")

            audit = build_goal_audit(root)

        self.assertEqual(audit["status"], STATUS_COMPLETE)
        self.assertEqual(audit["known_external_blockers"], [])
        self.assertTrue(all(item["status"] == STATUS_COMPLETE for item in audit["requirements"]))

    def test_goal_audit_fails_local_when_required_product_marker_is_missing(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = _minimal_goal_tree(Path(tmp_dir), auth_status="provider_browser_proof_complete")
            product_path = root / "meshapp" / "frontend" / "src" / "product" / "ProductApp.tsx"
            product_path.write_text(product_path.read_text(encoding="utf-8").replace("settingsParityRows", ""), encoding="utf-8")

            audit = build_goal_audit(root)

        self.assertEqual(audit["status"], STATUS_BLOCKED_LOCAL)
        settings_requirement = next(item for item in audit["requirements"] if item["id"] == "P4")
        self.assertEqual(settings_requirement["status"], STATUS_BLOCKED_LOCAL)
        self.assertIn("ProductApp.tsx contains settingsParityRows", settings_requirement["missing"])


def _minimal_goal_tree(root: Path, *, auth_status: str) -> Path:
    _write(root / "package.json", json.dumps({"scripts": _package_scripts(auth_status)}, indent=2) + "\n")
    _write(
        root / "meshapp" / "frontend" / "src" / "product" / "ProductApp.tsx",
        "\n".join(P1_PRODUCT_MARKERS + P2_PRODUCT_MARKERS + P3_PRODUCT_MARKERS + P4_PRODUCT_MARKERS + P5_PRODUCT_MARKERS) + "\n",
    )
    _write(root / "meshapp" / "frontend" / "src" / "product" / "api.ts", "\n".join(P2_API_MARKERS + P3_API_MARKERS) + "\n")
    _write(
        root / "meshapp" / "frontend" / "src" / "product" / "ProductApp.dashboard.test.tsx",
        "\n".join(P1_TEST_MARKERS + P4_TEST_MARKERS + P5_TEST_MARKERS) + "\n",
    )
    _write(root / "meshapp" / "frontend" / "e2e" / "first-run-signup-dashboard.spec.ts", "\n".join(P0_E2E_MARKERS) + "\n")
    _write(root / "control_plane_server.py", "\n".join(P2_BACKEND_MARKERS) + "\n")
    _write(root / "scripts" / "operator_config.py", "\n".join(P4_CLI_MARKERS) + "\n")
    _write(root / "docs" / "operator-product-app.md", "\n".join(P6_DOC_MARKERS) + "\n")
    _write(root / ".mesh-runtime-state" / "operator-auth-proof" / "latest.json", json.dumps(_auth_proof(auth_status), indent=2) + "\n")
    return root


def _package_scripts(auth_status: str) -> dict[str, str]:
    scripts = {name: marker for name, marker in {**P0_PACKAGE_SCRIPTS, **P6_PACKAGE_SCRIPTS}.items()}
    scripts["verify:operator-goal"] = "python3 scripts/operator_product_goal_audit.py"
    if auth_status == "provider_browser_proof_complete":
        scripts["test:auth-provider:live"] = "scripts/operator_auth_provider_smoke.py --require-live"
    return scripts


def _auth_proof(status: str) -> dict[str, object]:
    blockers = [] if status == "provider_browser_proof_complete" else ["live_provider_proof_missing"]
    return {
        "schema_version": "mesh.operator_auth_provider_readiness.v1",
        "state_slice": "auth-provider-proof.v1",
        "status": status,
        "raw_secret_material_present": False,
        "tracked_env_secret_material_present": False,
        "tracked_secret_hits": [],
        "blockers": blockers,
        "oauth": {
            "google": {"local_callback_match": True},
            "github": {"local_callback_match": True},
        },
        "captcha": {
            "hcaptcha_env_ready": True,
            "browser_token_verified": status == "provider_browser_proof_complete",
        },
        "runtime_auth_evidence": {
            "schema_version": "mesh.operator_auth_runtime_evidence.v1",
            "state_slice": "auth-provider-proof.v1",
            "status": "complete" if status == "provider_browser_proof_complete" else "blocked",
            "raw_secret_material_present": False,
        },
    }


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
