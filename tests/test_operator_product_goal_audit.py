import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.operator_product_goal_audit import (
    P0_E2E_MARKERS,
    P0_PACKAGE_SCRIPTS,
    P1_BACKEND_MARKERS,
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
        self.assertEqual(audit["requirements"][0]["live_preflight_status"], "ready")
        self.assertEqual(audit["requirements"][0]["live_stack_smoke_status"], "ready")
        self.assertEqual(audit["requirements"][0]["live_stack_smoke_stack_mode"], "managed_local_stack")
        self.assertEqual(audit["requirements"][0]["auth_checkpoint_status"], STATUS_BLOCKED_EXTERNAL)
        self.assertEqual(audit["requirements"][0]["auth_checkpoint_live_provider_status"], "blocked")
        self.assertEqual(audit["requirements"][0]["auth_checkpoint_next_required_command"], "pnpm run auth-provider:live-stack")
        self.assertEqual(audit["requirements"][0]["auth_checkpoint_final_verification_command"], "pnpm run test:auth-provider:live")
        self.assertEqual(audit["requirements"][0]["live_capture_attempt_status"], "blocked")
        self.assertEqual(audit["requirements"][0]["live_capture_attempt_stack_mode"], "managed_local_stack")
        self.assertEqual(audit["requirements"][0]["live_capture_attempt_blockers"], ["live_provider_proof_missing"])
        self.assertFalse(audit["requirements"][0]["missing"])
        self.assertTrue(all(item["status"] == STATUS_COMPLETE for item in audit["requirements"][1:]))

    def test_goal_audit_accepts_explicit_reused_local_stack_provenance(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = _minimal_goal_tree(Path(tmp_dir), auth_status="blocked_provider_console_unverified")
            stack_smoke_path = root / ".mesh-runtime-state" / "operator-auth-proof" / "live-stack-smoke.json"
            attempt_path = root / ".mesh-runtime-state" / "operator-auth-proof" / "live-capture-attempt.json"
            checkpoint_path = root / ".mesh-runtime-state" / "operator-auth-proof" / "checkpoint.json"
            stack_smoke = json.loads(stack_smoke_path.read_text(encoding="utf-8"))
            stack_smoke["stack_mode"] = "reused_local_stack"
            stack_smoke["managed_processes_owned"] = False
            stack_smoke_path.write_text(json.dumps(stack_smoke, indent=2) + "\n", encoding="utf-8")
            attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
            attempt["managed_local_stack"] = False
            attempt["stack_mode"] = "reused_local_stack"
            attempt["managed_processes_owned"] = False
            attempt_path.write_text(json.dumps(attempt, indent=2) + "\n", encoding="utf-8")
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            checkpoint["live_stack_smoke_stack_mode"] = "reused_local_stack"
            checkpoint["live_capture_attempt_stack_mode"] = "reused_local_stack"
            checkpoint["next_required_command"] = "pnpm run auth-provider:reuse-stack"
            checkpoint_path.write_text(json.dumps(checkpoint, indent=2) + "\n", encoding="utf-8")

            audit = build_goal_audit(root)

        p0 = next(item for item in audit["requirements"] if item["id"] == "P0")
        self.assertEqual(audit["status"], STATUS_BLOCKED_EXTERNAL)
        self.assertEqual(p0["status"], STATUS_BLOCKED_EXTERNAL)
        self.assertEqual(p0["live_stack_smoke_stack_mode"], "reused_local_stack")
        self.assertEqual(p0["live_capture_attempt_stack_mode"], "reused_local_stack")
        self.assertEqual(p0["auth_checkpoint_next_required_command"], "pnpm run auth-provider:reuse-stack")
        self.assertFalse(p0["missing"])

    def test_goal_audit_completes_when_live_provider_proof_is_complete(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = _minimal_goal_tree(Path(tmp_dir), auth_status="provider_browser_proof_complete")

            audit = build_goal_audit(root)

        self.assertEqual(audit["status"], STATUS_COMPLETE)
        self.assertEqual(audit["known_external_blockers"], [])
        self.assertTrue(all(item["status"] == STATUS_COMPLETE for item in audit["requirements"]))
        p0 = next(item for item in audit["requirements"] if item["id"] == "P0")
        self.assertEqual(p0["auth_checkpoint_live_provider_status"], "complete")

    def test_goal_audit_fails_local_when_complete_readiness_has_stale_blocked_checkpoint(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = _minimal_goal_tree(Path(tmp_dir), auth_status="provider_browser_proof_complete")
            checkpoint_path = root / ".mesh-runtime-state" / "operator-auth-proof" / "checkpoint.json"
            payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            payload["status"] = STATUS_BLOCKED_EXTERNAL
            payload["blockers"] = ["live_provider_proof_missing"]
            payload["live_provider_status"] = "blocked"
            payload["live_provider_blocker"] = "live_provider_proof_missing"
            checkpoint_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            audit = build_goal_audit(root)

        self.assertEqual(audit["status"], STATUS_BLOCKED_LOCAL)
        p0 = next(item for item in audit["requirements"] if item["id"] == "P0")
        self.assertEqual(p0["status"], STATUS_BLOCKED_LOCAL)
        self.assertEqual(p0["auth_checkpoint_status"], STATUS_BLOCKED_EXTERNAL)
        self.assertEqual(p0["auth_checkpoint_live_provider_status"], "blocked")
        self.assertIn("auth checkpoint completion state matches provider readiness", p0["missing"])

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

    def test_goal_audit_fails_local_when_dashboard_backend_section_contract_marker_is_missing(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = _minimal_goal_tree(Path(tmp_dir), auth_status="provider_browser_proof_complete")
            test_path = root / "tests" / "test_operator_product_contracts.py"
            test_path.write_text(test_path.read_text(encoding="utf-8").replace("required_mesh_sections", ""), encoding="utf-8")

            audit = build_goal_audit(root)

        self.assertEqual(audit["status"], STATUS_BLOCKED_LOCAL)
        dashboard_requirement = next(item for item in audit["requirements"] if item["id"] == "P1")
        self.assertEqual(dashboard_requirement["status"], STATUS_BLOCKED_LOCAL)
        self.assertIn(
            "tests/test_operator_product_contracts.py contains required_mesh_sections",
            dashboard_requirement["missing"],
        )

    def test_goal_audit_fails_local_when_auth_live_preflight_is_not_ready(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = _minimal_goal_tree(Path(tmp_dir), auth_status="provider_browser_proof_complete")
            preflight_path = root / ".mesh-runtime-state" / "operator-auth-proof" / "live-preflight.json"
            payload = json.loads(preflight_path.read_text(encoding="utf-8"))
            payload["status"] = "blocked"
            payload["blockers"] = ["github_oauth_redirect_url_mismatch"]
            payload["oauth"]["github"]["exact_match"] = False
            preflight_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            audit = build_goal_audit(root)

        self.assertEqual(audit["status"], STATUS_BLOCKED_LOCAL)
        p0 = next(item for item in audit["requirements"] if item["id"] == "P0")
        self.assertEqual(p0["status"], STATUS_BLOCKED_LOCAL)
        self.assertEqual(p0["live_preflight_status"], "blocked")
        self.assertIn("auth live preflight is ready", p0["missing"])
        self.assertIn("auth live preflight has no blockers", p0["missing"])
        self.assertIn("GitHub live preflight callback exactly matches", p0["missing"])

    def test_goal_audit_fails_local_when_auth_live_stack_smoke_is_not_ready(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = _minimal_goal_tree(Path(tmp_dir), auth_status="provider_browser_proof_complete")
            stack_smoke_path = root / ".mesh-runtime-state" / "operator-auth-proof" / "live-stack-smoke.json"
            payload = json.loads(stack_smoke_path.read_text(encoding="utf-8"))
            payload["status"] = "blocked"
            payload["blockers"] = ["local_stack_unavailable"]
            payload["readiness"]["product_shell"] = "blocked"
            stack_smoke_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            audit = build_goal_audit(root)

        self.assertEqual(audit["status"], STATUS_BLOCKED_LOCAL)
        p0 = next(item for item in audit["requirements"] if item["id"] == "P0")
        self.assertEqual(p0["status"], STATUS_BLOCKED_LOCAL)
        self.assertEqual(p0["live_stack_smoke_status"], "blocked")
        self.assertIn("auth live stack smoke is ready", p0["missing"])
        self.assertIn("auth live stack smoke has no blockers", p0["missing"])
        self.assertIn("auth live stack smoke product shell reachable", p0["missing"])

    def test_goal_audit_fails_local_when_auth_live_stack_smoke_has_ambiguous_stack_provenance(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = _minimal_goal_tree(Path(tmp_dir), auth_status="provider_browser_proof_complete")
            stack_smoke_path = root / ".mesh-runtime-state" / "operator-auth-proof" / "live-stack-smoke.json"
            payload = json.loads(stack_smoke_path.read_text(encoding="utf-8"))
            payload.pop("stack_mode")
            payload.pop("managed_processes_owned")
            stack_smoke_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            audit = build_goal_audit(root)

        self.assertEqual(audit["status"], STATUS_BLOCKED_LOCAL)
        p0 = next(item for item in audit["requirements"] if item["id"] == "P0")
        self.assertEqual(p0["status"], STATUS_BLOCKED_LOCAL)
        self.assertEqual(p0["live_stack_smoke_stack_mode"], "missing")
        self.assertIn("auth live stack smoke stack provenance is explicit", p0["missing"])

    def test_goal_audit_fails_local_when_auth_checkpoint_is_not_bound(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = _minimal_goal_tree(Path(tmp_dir), auth_status="provider_browser_proof_complete")
            checkpoint_path = root / ".mesh-runtime-state" / "operator-auth-proof" / "checkpoint.json"
            payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            payload["status"] = STATUS_BLOCKED_LOCAL
            payload["local_evidence_status"] = "blocked"
            payload["missing_local_evidence"] = ["live stack smoke artifact exists"]
            checkpoint_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            audit = build_goal_audit(root)

        self.assertEqual(audit["status"], STATUS_BLOCKED_LOCAL)
        p0 = next(item for item in audit["requirements"] if item["id"] == "P0")
        self.assertEqual(p0["status"], STATUS_BLOCKED_LOCAL)
        self.assertEqual(p0["auth_checkpoint_status"], STATUS_BLOCKED_LOCAL)
        self.assertIn("auth checkpoint local evidence is complete", p0["missing"])
        self.assertIn("auth checkpoint has no local evidence gaps", p0["missing"])

    def test_goal_audit_fails_local_when_auth_checkpoint_attempt_binding_is_stale(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = _minimal_goal_tree(Path(tmp_dir), auth_status="blocked_provider_console_unverified")
            checkpoint_path = root / ".mesh-runtime-state" / "operator-auth-proof" / "checkpoint.json"
            payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            payload["live_capture_attempt_blockers"] = ["stale_attempt_blocker"]
            checkpoint_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            audit = build_goal_audit(root)

        self.assertEqual(audit["status"], STATUS_BLOCKED_LOCAL)
        p0 = next(item for item in audit["requirements"] if item["id"] == "P0")
        self.assertEqual(p0["status"], STATUS_BLOCKED_LOCAL)
        self.assertIn("auth checkpoint live capture attempt binding matches artifact", p0["missing"])

    def test_goal_audit_fails_local_when_auth_checkpoint_next_command_is_stale(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = _minimal_goal_tree(Path(tmp_dir), auth_status="blocked_provider_console_unverified")
            checkpoint_path = root / ".mesh-runtime-state" / "operator-auth-proof" / "checkpoint.json"
            payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            payload["next_required_command"] = "pnpm run auth-provider:reuse-stack"
            checkpoint_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            audit = build_goal_audit(root)

        self.assertEqual(audit["status"], STATUS_BLOCKED_LOCAL)
        p0 = next(item for item in audit["requirements"] if item["id"] == "P0")
        self.assertEqual(p0["status"], STATUS_BLOCKED_LOCAL)
        self.assertEqual(p0["auth_checkpoint_next_required_command"], "pnpm run auth-provider:reuse-stack")
        self.assertIn("auth checkpoint next required command matches stack provenance", p0["missing"])

    def test_goal_audit_fails_local_when_auth_live_capture_attempt_is_not_bound(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = _minimal_goal_tree(Path(tmp_dir), auth_status="provider_browser_proof_complete")
            attempt_path = root / ".mesh-runtime-state" / "operator-auth-proof" / "live-capture-attempt.json"
            payload = json.loads(attempt_path.read_text(encoding="utf-8"))
            payload["status"] = "blocked"
            payload["clean_browser_session"] = False
            payload["preflight_status"] = "blocked"
            payload["managed_processes_owned"] = False
            attempt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            audit = build_goal_audit(root)

        self.assertEqual(audit["status"], STATUS_BLOCKED_LOCAL)
        p0 = next(item for item in audit["requirements"] if item["id"] == "P0")
        self.assertEqual(p0["status"], STATUS_BLOCKED_LOCAL)
        self.assertEqual(p0["live_capture_attempt_status"], "blocked")
        self.assertIn("auth live capture attempt used a clean browser", p0["missing"])
        self.assertIn("auth live capture attempt stack provenance is explicit", p0["missing"])
        self.assertIn("auth live capture attempt preflight was ready", p0["missing"])


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
    _write(root / "tests" / "test_operator_product_contracts.py", "\n".join(P1_BACKEND_MARKERS) + "\n")
    _write(root / "meshapp" / "frontend" / "e2e" / "first-run-signup-dashboard.spec.ts", "\n".join(P0_E2E_MARKERS) + "\n")
    _write(root / "control_plane_server.py", "\n".join(P2_BACKEND_MARKERS) + "\n")
    _write(root / "scripts" / "operator_config.py", "\n".join(P4_CLI_MARKERS) + "\n")
    _write(root / "docs" / "operator-product-app.md", "\n".join(P6_DOC_MARKERS) + "\n")
    _write(root / ".mesh-runtime-state" / "operator-auth-proof" / "latest.json", json.dumps(_auth_proof(auth_status), indent=2) + "\n")
    _write(
        root / ".mesh-runtime-state" / "operator-auth-proof" / "live-preflight.json",
        json.dumps(_auth_preflight(), indent=2) + "\n",
    )
    _write(
        root / ".mesh-runtime-state" / "operator-auth-proof" / "live-stack-smoke.json",
        json.dumps(_auth_stack_smoke(), indent=2) + "\n",
    )
    _write(
        root / ".mesh-runtime-state" / "operator-auth-proof" / "checkpoint.json",
        json.dumps(_auth_checkpoint(auth_status), indent=2) + "\n",
    )
    _write(
        root / ".mesh-runtime-state" / "operator-auth-proof" / "live-capture-attempt.json",
        json.dumps(_auth_attempt(auth_status), indent=2) + "\n",
    )
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


def _auth_preflight() -> dict[str, object]:
    return {
        "schema_version": "mesh.operator_auth_live_capture_preflight.v1",
        "state_slice": "auth-provider-proof.v1",
        "status": "ready",
        "blockers": [],
        "raw_secret_material_present": False,
        "identity_path_matches_default": True,
        "oauth": {
            "google": {"exact_match": True},
            "github": {"exact_match": True},
        },
        "product_redirect": {"exact_match": True},
        "captcha": {"hcaptcha_env_ready": True},
    }


def _auth_stack_smoke() -> dict[str, object]:
    return {
        "schema_version": "mesh.operator_auth_live_stack_smoke.v1",
        "state_slice": "auth-provider-proof.v1",
        "status": "ready",
        "blockers": [],
        "preflight_status": "ready",
        "stack_mode": "managed_local_stack",
        "managed_processes_owned": True,
        "raw_secret_material_present": False,
        "identity_path_matches_default": True,
        "readiness": {
            "api_auth_config": "reachable",
            "product_shell": "reachable",
        },
    }


def _auth_checkpoint(auth_status: str) -> dict[str, object]:
    complete = auth_status == "provider_browser_proof_complete"
    return {
        "schema_version": "mesh.operator_auth_checkpoint.v1",
        "state_slice": "auth-provider-proof.v1",
        "status": STATUS_COMPLETE if complete else STATUS_BLOCKED_EXTERNAL,
        "local_evidence_status": "complete",
        "blockers": [] if complete else ["live_provider_proof_missing"],
        "missing_local_evidence": [],
        "raw_secret_material_present": False,
        "live_preflight_status": "ready",
        "live_stack_smoke_status": "ready",
        "live_stack_smoke_stack_mode": "managed_local_stack",
        "live_capture_attempt_status": "complete" if complete else "blocked",
        "live_capture_attempt_stack_mode": "managed_local_stack",
        "live_capture_attempt_blockers": [] if complete else ["live_provider_proof_missing"],
        "readiness_status": auth_status,
        "live_provider_status": "complete" if complete else "blocked",
        "live_provider_blocker": "" if complete else "live_provider_proof_missing",
        "next_required_command": "pnpm run auth-provider:live-stack",
        "final_verification_command": "pnpm run test:auth-provider:live",
    }


def _auth_attempt(auth_status: str) -> dict[str, object]:
    complete = auth_status == "provider_browser_proof_complete"
    return {
        "schema_version": "mesh.operator_auth_live_capture_attempt.v1",
        "state_slice": "auth-provider-proof.v1",
        "status": "complete" if complete else "blocked",
        "blockers": [] if complete else ["live_provider_proof_missing"],
        "clean_browser_session": True,
        "managed_local_stack": True,
        "stack_mode": "managed_local_stack",
        "managed_processes_owned": True,
        "preflight_status": "ready",
        "raw_secret_material_present": False,
    }


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
