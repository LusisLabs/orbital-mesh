#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
AUTH_PROOF_PATH = REPO_ROOT / ".mesh-runtime-state" / "operator-auth-proof" / "latest.json"
AUTH_PREFLIGHT_PATH = REPO_ROOT / ".mesh-runtime-state" / "operator-auth-proof" / "live-preflight.json"
AUTH_STACK_SMOKE_PATH = REPO_ROOT / ".mesh-runtime-state" / "operator-auth-proof" / "live-stack-smoke.json"
AUTH_CHECKPOINT_PATH = REPO_ROOT / ".mesh-runtime-state" / "operator-auth-proof" / "checkpoint.json"
AUTH_ATTEMPT_PATH = REPO_ROOT / ".mesh-runtime-state" / "operator-auth-proof" / "live-capture-attempt.json"

STATUS_COMPLETE = "complete"
STATUS_BLOCKED_LOCAL = "blocked_local_evidence"
STATUS_BLOCKED_EXTERNAL = "blocked_external_provider_proof"
STACK_MODE_MANAGED = "managed_local_stack"
STACK_MODE_REUSED = "reused_local_stack"

P0_E2E_MARKERS = [
    "first-run signup creates a team and reaches the product dashboard",
    "first-run signup can continue solo from a clean browser session",
    "logout returns a clean browser session to sign-in",
    "expired session clears cookie and recovers through login",
    "/api/operator/dashboard",
]
P0_PACKAGE_SCRIPTS = {
    "auth-provider:live-capture": "scripts/operator_auth_live_provider_capture.py",
    "auth-provider:live-stack": "scripts/operator_auth_live_provider_capture.py --manage-local-stack",
    "auth-provider:live-stack-smoke": "scripts/operator_auth_live_provider_capture.py --stack-smoke-only",
    "auth-provider:reuse-stack-smoke": "scripts/operator_auth_live_provider_capture.py --stack-smoke-only --reuse-local-stack",
    "auth-provider:live-preflight": "scripts/operator_auth_live_provider_capture.py --preflight-only",
    "auth-provider:checkpoint": "scripts/operator_auth_live_provider_capture.py --checkpoint-only",
    "auth-provider:live-attempt": "scripts/operator_auth_live_provider_capture.py --manage-local-stack --timeout-seconds 300 --allow-blocked-attempt",
    "auth-provider:reuse-attempt": "scripts/operator_auth_live_provider_capture.py --reuse-local-stack --timeout-seconds 300 --allow-blocked-attempt",
    "auth-provider:reuse-stack": "scripts/operator_auth_live_provider_capture.py --reuse-local-stack",
    "test:auth-provider:smoke": "scripts/operator_auth_provider_smoke.py",
    "test:auth-provider:live": "scripts/operator_auth_provider_smoke.py --require-live",
    "auth-provider:live-template": "scripts/operator_auth_provider_smoke.py --print-live-proof-template",
    "test:product:e2e": "scripts/operator_product_e2e.py",
}
P1_PRODUCT_MARKERS = [
    'DashboardSurfaceState = "ready" | "empty" | "degraded" | "blocked" | "unauthorized" | "backend-unavailable"',
    "buildDashboardTiles",
    "dashboardSectionState",
    "dashboardLoadSurfaceState",
    "apiSection",
]
P1_TEST_MARKERS = [
    "binds every home dashboard tile to an explicit /api/operator/dashboard section",
    "maps dashboard section payloads into explicit product states",
]
P1_BACKEND_MARKERS = [
    "test_operator_dashboard_exposes_every_product_home_section",
    "required_mesh_sections",
]
P2_PRODUCT_MARKERS = [
    "LaunchRunPanel",
    "productApi.createRun",
    "Audit reason",
    "POST /api/runs",
    "mesh.run_admission.v1",
]
P2_API_MARKERS = [
    "createRun(payload: RunLaunchPayload)",
    '"/api/runs"',
    "RunAdmissionPacket",
]
P2_BACKEND_MARKERS = [
    'parsed.path == "/api/runs"',
    'self._authorize({"launcher", "admin"})',
    "audit_reason",
    "run_admission",
    "meshapp.run-admission-launch.v1",
    "audit",
]
P3_PRODUCT_MARKERS = [
    "ApprovalQueuePanel",
    "ProofDrilldownPanel",
    "Evidence graph / proof packet / RCA trace / export",
    "Mesh owns evidence, RCA, export, and decision records.",
]
P3_API_MARKERS = [
    "steerRun",
    "runEvents",
    "evidenceGraph",
    "scenarioAnalysis",
    "merkle",
    "timelineProof",
    "exportRun",
]
P4_PRODUCT_MARKERS = [
    "settingsParityRows",
    "/api/operator/settings",
    "scripts/operator_config.py",
    "readOnlyReason",
]
P4_TEST_MARKERS = [
    "gives every dashboard setting a UI mutation path, CLI path, or read-only reason",
]
P4_CLI_MARKERS = [
    "set",
    "--scope",
    "--operator-id",
    "--reason",
]
P5_PRODUCT_MARKERS = [
    "runtimeProductPage",
    "PraxisView",
    "Connector Status",
    "Topology",
    "Memory Projection",
    "Kill Switch",
    "Readiness",
    "Policy State",
    "legacy tab shortcut",
]
P5_TEST_MARKERS = [
    "maps runtime navigation to product-native read-model pages",
]
P6_PACKAGE_SCRIPTS = {
    "lint:fast": "pnpm run verify:contracts",
    "test:auth-provider:smoke": "scripts/operator_auth_provider_smoke.py",
    "test:focused": "tests.test_operator_product_contracts",
    "test:product:e2e": "scripts/operator_product_e2e.py",
    "verify:contracts": "scripts/verify_operator_product_buildout.py",
    "verify:full": "pnpm run test:product:e2e",
    "lint": "pnpm run verify:full",
}
P6_DOC_MARKERS = [
    "pnpm run lint:fast",
    "pnpm run test:focused",
    "pnpm run test:product:e2e",
    "pnpm run verify:contracts",
    "pnpm run lint",
    "git diff --check",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit P0-P6 operator product goal evidence.")
    parser.add_argument("--auth-proof-path", default=str(AUTH_PROOF_PATH))
    parser.add_argument("--auth-preflight-path", default=str(AUTH_PREFLIGHT_PATH))
    parser.add_argument("--auth-stack-smoke-path", default=str(AUTH_STACK_SMOKE_PATH))
    parser.add_argument("--auth-checkpoint-path", default=str(AUTH_CHECKPOINT_PATH))
    parser.add_argument("--auth-attempt-path", default=str(AUTH_ATTEMPT_PATH))
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)

    audit = build_goal_audit(
        REPO_ROOT,
        auth_proof_path=Path(args.auth_proof_path),
        auth_preflight_path=Path(args.auth_preflight_path),
        auth_stack_smoke_path=Path(args.auth_stack_smoke_path),
        auth_checkpoint_path=Path(args.auth_checkpoint_path),
        auth_attempt_path=Path(args.auth_attempt_path),
    )
    print(json.dumps(audit, indent=2, sort_keys=True))

    if audit["status"] == STATUS_BLOCKED_LOCAL:
        return 1
    if args.require_complete and audit["status"] != STATUS_COMPLETE:
        return 2
    return 0


def build_goal_audit(
    repo_root: Path,
    *,
    auth_proof_path: Path | None = None,
    auth_preflight_path: Path | None = None,
    auth_stack_smoke_path: Path | None = None,
    auth_checkpoint_path: Path | None = None,
    auth_attempt_path: Path | None = None,
) -> dict[str, Any]:
    package = _read_package_scripts(repo_root / "package.json")
    product_app = _read(repo_root / "meshapp" / "frontend" / "src" / "product" / "ProductApp.tsx")
    product_api = _read(repo_root / "meshapp" / "frontend" / "src" / "product" / "api.ts")
    product_tests = _read(repo_root / "meshapp" / "frontend" / "src" / "product" / "ProductApp.dashboard.test.tsx")
    product_contract_tests = _read(repo_root / "tests" / "test_operator_product_contracts.py")
    product_e2e = _read(repo_root / "meshapp" / "frontend" / "e2e" / "first-run-signup-dashboard.spec.ts")
    control_plane = _read(repo_root / "control_plane_server.py")
    service_control_plane = _read(repo_root / "services" / "control_plane.py")
    backend = f"{control_plane}\n{service_control_plane}"
    operator_config = _read(repo_root / "scripts" / "operator_config.py")
    docs = _read(repo_root / "docs" / "operator-product-app.md")
    auth_path = auth_proof_path or repo_root / ".mesh-runtime-state" / "operator-auth-proof" / "latest.json"
    auth_preflight_path = auth_preflight_path or repo_root / ".mesh-runtime-state" / "operator-auth-proof" / "live-preflight.json"
    auth_stack_smoke_path = auth_stack_smoke_path or repo_root / ".mesh-runtime-state" / "operator-auth-proof" / "live-stack-smoke.json"
    auth_checkpoint_path = auth_checkpoint_path or repo_root / ".mesh-runtime-state" / "operator-auth-proof" / "checkpoint.json"
    auth_attempt_path = auth_attempt_path or repo_root / ".mesh-runtime-state" / "operator-auth-proof" / "live-capture-attempt.json"
    auth_proof = _read_json(auth_path)
    auth_preflight = _read_json(auth_preflight_path)
    auth_stack_smoke = _read_json(auth_stack_smoke_path)
    auth_checkpoint = _read_json(auth_checkpoint_path)
    auth_attempt = _read_json(auth_attempt_path)

    requirements = [
        _p0_requirement(
            package,
            product_e2e,
            auth_proof,
            auth_path,
            auth_preflight,
            auth_preflight_path,
            auth_stack_smoke,
            auth_stack_smoke_path,
            auth_checkpoint,
            auth_checkpoint_path,
            auth_attempt,
            auth_attempt_path,
        ),
        _local_requirement(
            "P1",
            "Dashboard completeness",
            [
                *_marker_checks("ProductApp.tsx", product_app, P1_PRODUCT_MARKERS),
                *_marker_checks("ProductApp.dashboard.test.tsx", product_tests, P1_TEST_MARKERS),
                *_marker_checks("tests/test_operator_product_contracts.py", product_contract_tests, P1_BACKEND_MARKERS),
            ],
            [
                "meshapp/frontend/src/product/ProductApp.tsx",
                "meshapp/frontend/src/product/ProductApp.dashboard.test.tsx",
                "tests/test_operator_product_contracts.py",
            ],
        ),
        _local_requirement(
            "P2",
            "Product-native run admission",
            [
                *_marker_checks("ProductApp.tsx", product_app, P2_PRODUCT_MARKERS),
                *_marker_checks("api.ts", product_api, P2_API_MARKERS),
                *_marker_checks("run admission backend", backend, P2_BACKEND_MARKERS),
            ],
            [
                "meshapp/frontend/src/product/ProductApp.tsx",
                "meshapp/frontend/src/product/api.ts",
                "control_plane_server.py",
                "services/control_plane.py",
            ],
        ),
        _local_requirement(
            "P3",
            "Approvals and evidence",
            [
                *_marker_checks("ProductApp.tsx", product_app, P3_PRODUCT_MARKERS),
                *_marker_checks("api.ts", product_api, P3_API_MARKERS),
            ],
            [
                "meshapp/frontend/src/product/ProductApp.tsx",
                "meshapp/frontend/src/product/api.ts",
            ],
        ),
        _local_requirement(
            "P4",
            "Settings parity",
            [
                *_marker_checks("ProductApp.tsx", product_app, P4_PRODUCT_MARKERS),
                *_marker_checks("ProductApp.dashboard.test.tsx", product_tests, P4_TEST_MARKERS),
                *_marker_checks("scripts/operator_config.py", operator_config, P4_CLI_MARKERS),
            ],
            [
                "meshapp/frontend/src/product/ProductApp.tsx",
                "scripts/operator_config.py",
                "meshapp/frontend/src/product/ProductApp.dashboard.test.tsx",
            ],
        ),
        _local_requirement(
            "P5",
            "Connector and runtime pages",
            [
                *_marker_checks("ProductApp.tsx", product_app, P5_PRODUCT_MARKERS),
                *_marker_checks("ProductApp.dashboard.test.tsx", product_tests, P5_TEST_MARKERS),
            ],
            [
                "meshapp/frontend/src/product/ProductApp.tsx",
                "meshapp/frontend/src/product/ProductApp.dashboard.test.tsx",
            ],
        ),
        _local_requirement(
            "P6",
            "Deployment proof ladder",
            [
                *_script_checks(package, P6_PACKAGE_SCRIPTS),
                *_marker_checks("docs/operator-product-app.md", docs, P6_DOC_MARKERS),
            ],
            ["package.json", "docs/operator-product-app.md"],
        ),
    ]
    local_blocked = [item for item in requirements if item["status"] == STATUS_BLOCKED_LOCAL]
    external_blocked = [item for item in requirements if item["status"] == STATUS_BLOCKED_EXTERNAL]
    if local_blocked:
        status = STATUS_BLOCKED_LOCAL
    elif external_blocked:
        status = STATUS_BLOCKED_EXTERNAL
    else:
        status = STATUS_COMPLETE
    known_external_blockers = sorted(
        {
            blocker
            for item in requirements
            if item["status"] == STATUS_BLOCKED_EXTERNAL
            for blocker in item["blockers"]
        }
    )
    return {
        "schema_version": "mesh.operator_product_goal_audit.v1",
        "generated_at": _timestamp(),
        "state_slice": "operator-product-goal-audit",
        "status": status,
        "requirements": requirements,
        "known_external_blockers": known_external_blockers,
        "authority_boundary": (
            "This audit binds local evidence markers and redacted provider proof status. "
            "Mesh remains the authority for auth/session state, run admission, approvals, evidence, settings, runtime pages, and deployment gates."
        ),
    }


def _p0_requirement(
    scripts: dict[str, str],
    product_e2e: str,
    auth_proof: dict[str, Any],
    auth_path: Path,
    auth_preflight: dict[str, Any],
    auth_preflight_path: Path,
    auth_stack_smoke: dict[str, Any],
    auth_stack_smoke_path: Path,
    auth_checkpoint: dict[str, Any],
    auth_checkpoint_path: Path,
    auth_attempt: dict[str, Any],
    auth_attempt_path: Path,
) -> dict[str, Any]:
    local_checks = [
        *_marker_checks("first-run-signup-dashboard.spec.ts", product_e2e, P0_E2E_MARKERS),
        *_script_checks(scripts, P0_PACKAGE_SCRIPTS),
        ("auth proof artifact exists", auth_path.exists()),
        ("auth proof schema is mesh.operator_auth_provider_readiness.v1", auth_proof.get("schema_version") == "mesh.operator_auth_provider_readiness.v1"),
        ("auth proof state slice is auth-provider-proof.v1", auth_proof.get("state_slice") == "auth-provider-proof.v1"),
        ("auth proof generated_at is present", _generated_at_present(auth_proof)),
        ("auth proof does not contain raw secret material", auth_proof.get("raw_secret_material_present") is False),
        ("auth env files are untracked", auth_proof.get("tracked_env_secret_material_present") is False),
        ("tracked secret hits are empty", auth_proof.get("tracked_secret_hits") == []),
        ("runtime auth evidence is reported", _runtime_auth_evidence_reported(auth_proof)),
        ("runtime auth evidence contains no raw secret material", _runtime_auth_evidence_redacted(auth_proof)),
        ("Google local callback matches", _provider_callback_ok(auth_proof, "google")),
        ("GitHub local callback matches", _provider_callback_ok(auth_proof, "github")),
        ("hCaptcha env readiness is present", auth_proof.get("captcha", {}).get("hcaptcha_env_ready") is True),
        ("auth live preflight artifact exists", auth_preflight_path.exists()),
        ("auth live preflight schema is mesh.operator_auth_live_capture_preflight.v1", auth_preflight.get("schema_version") == "mesh.operator_auth_live_capture_preflight.v1"),
        ("auth live preflight state slice is auth-provider-proof.v1", auth_preflight.get("state_slice") == "auth-provider-proof.v1"),
        ("auth live preflight generated_at is present", _generated_at_present(auth_preflight)),
        ("auth live preflight is ready", auth_preflight.get("status") == "ready"),
        ("auth live preflight has no blockers", auth_preflight.get("blockers") == []),
        ("auth live preflight does not contain raw secret material", auth_preflight.get("raw_secret_material_present") is False),
        ("Google live preflight callback exactly matches", _preflight_provider_ok(auth_preflight, "google")),
        ("GitHub live preflight callback exactly matches", _preflight_provider_ok(auth_preflight, "github")),
        ("auth product redirect preflight matches", _preflight_product_redirect_ok(auth_preflight)),
        ("hCaptcha live preflight readiness is present", auth_preflight.get("captcha", {}).get("hcaptcha_env_ready") is True),
        ("auth live preflight identity path matches default", auth_preflight.get("identity_path_matches_default") is True),
        ("auth live stack smoke artifact exists", auth_stack_smoke_path.exists()),
        ("auth live stack smoke schema is mesh.operator_auth_live_stack_smoke.v1", auth_stack_smoke.get("schema_version") == "mesh.operator_auth_live_stack_smoke.v1"),
        ("auth live stack smoke state slice is auth-provider-proof.v1", auth_stack_smoke.get("state_slice") == "auth-provider-proof.v1"),
        ("auth live stack smoke generated_at is present", _generated_at_present(auth_stack_smoke)),
        ("auth live stack smoke is ready", auth_stack_smoke.get("status") == "ready"),
        ("auth live stack smoke has no blockers", auth_stack_smoke.get("blockers") == []),
        ("auth live stack smoke preflight was ready", auth_stack_smoke.get("preflight_status") == "ready"),
        ("auth live stack smoke API auth config reachable", _stack_smoke_ready(auth_stack_smoke, "api_auth_config")),
        ("auth live stack smoke product shell reachable", _stack_smoke_ready(auth_stack_smoke, "product_shell")),
        ("auth live stack smoke does not contain raw secret material", auth_stack_smoke.get("raw_secret_material_present") is False),
        ("auth live stack smoke identity path matches default", auth_stack_smoke.get("identity_path_matches_default") is True),
        ("auth live stack smoke stack provenance is explicit", _stack_provenance_ok(auth_stack_smoke)),
        ("auth checkpoint artifact exists", auth_checkpoint_path.exists()),
        ("auth checkpoint schema is mesh.operator_auth_checkpoint.v1", auth_checkpoint.get("schema_version") == "mesh.operator_auth_checkpoint.v1"),
        ("auth checkpoint state slice is auth-provider-proof.v1", auth_checkpoint.get("state_slice") == "auth-provider-proof.v1"),
        ("auth checkpoint local evidence is complete", auth_checkpoint.get("local_evidence_status") == "complete"),
        ("auth checkpoint has no local evidence gaps", auth_checkpoint.get("missing_local_evidence") == []),
        ("auth checkpoint does not contain raw secret material", auth_checkpoint.get("raw_secret_material_present") is False),
        ("auth checkpoint binds live preflight readiness", auth_checkpoint.get("live_preflight_status") == "ready"),
        ("auth checkpoint binds live stack smoke readiness", auth_checkpoint.get("live_stack_smoke_status") == "ready"),
        ("auth checkpoint binds live capture attempt status", auth_checkpoint.get("live_capture_attempt_status") in {"complete", "blocked"}),
        ("auth checkpoint binds live capture attempt blockers", isinstance(auth_checkpoint.get("live_capture_attempt_blockers"), list)),
        ("auth checkpoint live capture attempt binding matches artifact", _checkpoint_attempt_matches_attempt(auth_checkpoint, auth_attempt)),
        (
            "auth checkpoint evidence timestamps match source artifacts",
            _checkpoint_evidence_timestamps_match(auth_checkpoint, auth_proof, auth_preflight, auth_stack_smoke, auth_attempt),
        ),
        ("auth checkpoint next required command matches stack provenance", _checkpoint_next_required_command_ok(auth_checkpoint, auth_stack_smoke)),
        ("auth checkpoint final verification command is auth-provider live test", auth_checkpoint.get("final_verification_command") == "pnpm run test:auth-provider:live"),
        ("auth checkpoint readiness status matches provider readiness", auth_checkpoint.get("readiness_status") == auth_proof.get("status")),
        ("auth checkpoint completion state matches provider readiness", _checkpoint_completion_state_matches_readiness(auth_proof, auth_checkpoint, auth_attempt)),
        ("auth checkpoint status is complete or externally blocked", auth_checkpoint.get("status") in {STATUS_COMPLETE, STATUS_BLOCKED_EXTERNAL}),
        ("auth live capture attempt artifact exists", auth_attempt_path.exists()),
        ("auth live capture attempt schema is mesh.operator_auth_live_capture_attempt.v1", auth_attempt.get("schema_version") == "mesh.operator_auth_live_capture_attempt.v1"),
        ("auth live capture attempt state slice is auth-provider-proof.v1", auth_attempt.get("state_slice") == "auth-provider-proof.v1"),
        ("auth live capture attempt generated_at is present", _generated_at_present(auth_attempt)),
        ("auth live capture attempt used a clean browser", auth_attempt.get("clean_browser_session") is True),
        ("auth live capture attempt stack provenance is explicit", _stack_provenance_ok(auth_attempt)),
        ("auth live capture attempt preflight was ready", auth_attempt.get("preflight_status") == "ready"),
        ("auth live capture attempt does not contain raw secret material", auth_attempt.get("raw_secret_material_present") is False),
    ]
    missing = [label for label, passed in local_checks if not passed]
    evidence = [
        "meshapp/frontend/e2e/first-run-signup-dashboard.spec.ts",
        "scripts/operator_auth_provider_smoke.py",
        "tests/test_operator_auth_provider_smoke.py",
        "package.json",
        str(auth_path),
        str(auth_preflight_path),
        str(auth_stack_smoke_path),
        str(auth_checkpoint_path),
        str(auth_attempt_path),
    ]
    live_status = str(auth_proof.get("status") or "auth_provider_readiness_missing")
    live_complete = (
        live_status == "provider_browser_proof_complete"
        and _checkpoint_completion_state_matches_readiness(auth_proof, auth_checkpoint, auth_attempt)
    )
    if missing:
        status = STATUS_BLOCKED_LOCAL
        blockers = missing
    elif live_complete:
        status = STATUS_COMPLETE
        blockers = []
    else:
        status = STATUS_BLOCKED_EXTERNAL
        blockers = _auth_blockers(auth_proof)
    return {
        "id": "P0",
        "title": "Checkpoint and auth proof",
        "status": status,
        "state_slice": "auth-provider-proof.v1",
        "evidence": evidence,
        "missing": missing,
        "blockers": blockers,
        "live_provider_status": live_status,
        "live_preflight_status": str(auth_preflight.get("status") or "auth_live_preflight_missing"),
        "live_stack_smoke_status": str(auth_stack_smoke.get("status") or "auth_live_stack_smoke_missing"),
        "live_stack_smoke_stack_mode": str(auth_stack_smoke.get("stack_mode") or "missing"),
        "auth_checkpoint_status": str(auth_checkpoint.get("status") or "auth_checkpoint_missing"),
        "auth_checkpoint_live_provider_status": str(auth_checkpoint.get("live_provider_status") or "missing"),
        "auth_checkpoint_next_required_command": str(auth_checkpoint.get("next_required_command") or "missing"),
        "auth_checkpoint_final_verification_command": str(auth_checkpoint.get("final_verification_command") or "missing"),
        "auth_checkpoint_evidence_generated_at": auth_checkpoint.get("evidence_generated_at") if isinstance(auth_checkpoint.get("evidence_generated_at"), dict) else {},
        "live_capture_attempt_status": str(auth_attempt.get("status") or "auth_live_capture_attempt_missing"),
        "live_capture_attempt_stack_mode": str(auth_attempt.get("stack_mode") or "missing"),
        "live_capture_attempt_blockers": _string_list(auth_attempt.get("blockers")),
    }


def _local_requirement(id_: str, title: str, checks: list[tuple[str, bool]], evidence: list[str]) -> dict[str, Any]:
    missing = [label for label, passed in checks if not passed]
    return {
        "id": id_,
        "title": title,
        "status": STATUS_BLOCKED_LOCAL if missing else STATUS_COMPLETE,
        "state_slice": _state_slice_for_requirement(id_),
        "evidence": evidence,
        "missing": missing,
        "blockers": missing,
    }


def _state_slice_for_requirement(id_: str) -> str:
    return {
        "P1": "mesh-dashboard-read-model",
        "P2": "mesh-run-admission",
        "P3": "mesh-approval-evidence-proof",
        "P4": "mesh-settings-control",
        "P5": "mesh-runtime-read-model-pages",
        "P6": "tests-and-validation",
    }.get(id_, "operator-product-goal-audit")


def _marker_checks(label: str, text: str, markers: list[str]) -> list[tuple[str, bool]]:
    return [(f"{label} contains {marker}", marker in text) for marker in markers]


def _script_checks(scripts: dict[str, str], expected: dict[str, str]) -> list[tuple[str, bool]]:
    return [
        (f"package script {name} contains {marker}", marker in scripts.get(name, ""))
        for name, marker in expected.items()
    ]


def _provider_callback_ok(auth_proof: dict[str, Any], provider: str) -> bool:
    oauth = auth_proof.get("oauth")
    if not isinstance(oauth, dict):
        return False
    provider_status = oauth.get(provider)
    return isinstance(provider_status, dict) and provider_status.get("local_callback_match") is True


def _preflight_provider_ok(auth_preflight: dict[str, Any], provider: str) -> bool:
    oauth = auth_preflight.get("oauth")
    if not isinstance(oauth, dict):
        return False
    provider_status = oauth.get(provider)
    return isinstance(provider_status, dict) and provider_status.get("exact_match") is True


def _preflight_product_redirect_ok(auth_preflight: dict[str, Any]) -> bool:
    product_redirect = auth_preflight.get("product_redirect")
    return isinstance(product_redirect, dict) and product_redirect.get("exact_match") is True


def _stack_smoke_ready(auth_stack_smoke: dict[str, Any], name: str) -> bool:
    readiness = auth_stack_smoke.get("readiness")
    return isinstance(readiness, dict) and readiness.get(name) == "reachable"


def _stack_provenance_ok(payload: dict[str, Any]) -> bool:
    stack_mode = payload.get("stack_mode")
    managed_processes_owned = payload.get("managed_processes_owned")
    if stack_mode == STACK_MODE_MANAGED:
        return managed_processes_owned is True
    if stack_mode == STACK_MODE_REUSED:
        return managed_processes_owned is False
    return False


def _checkpoint_attempt_matches_attempt(auth_checkpoint: dict[str, Any], auth_attempt: dict[str, Any]) -> bool:
    return (
        auth_checkpoint.get("live_capture_attempt_status") == auth_attempt.get("status")
        and auth_checkpoint.get("live_capture_attempt_stack_mode") == auth_attempt.get("stack_mode")
        and _string_list(auth_checkpoint.get("live_capture_attempt_blockers")) == _string_list(auth_attempt.get("blockers"))
    )


def _checkpoint_next_required_command_ok(auth_checkpoint: dict[str, Any], auth_stack_smoke: dict[str, Any]) -> bool:
    expected = "pnpm run auth-provider:reuse-stack" if auth_stack_smoke.get("stack_mode") == STACK_MODE_REUSED else "pnpm run auth-provider:live-stack"
    return auth_checkpoint.get("next_required_command") == expected


def _checkpoint_evidence_timestamps_match(
    auth_checkpoint: dict[str, Any],
    auth_proof: dict[str, Any],
    auth_preflight: dict[str, Any],
    auth_stack_smoke: dict[str, Any],
    auth_attempt: dict[str, Any],
) -> bool:
    evidence_generated_at = auth_checkpoint.get("evidence_generated_at")
    if not isinstance(evidence_generated_at, dict):
        return False
    source_artifacts = {
        "provider_readiness": auth_proof,
        "live_preflight": auth_preflight,
        "live_stack_smoke": auth_stack_smoke,
        "live_capture_attempt": auth_attempt,
    }
    for key, payload in source_artifacts.items():
        generated_at = payload.get("generated_at")
        if not isinstance(generated_at, str) or not generated_at:
            return False
        if evidence_generated_at.get(key) != generated_at:
            return False
    return True


def _generated_at_present(payload: dict[str, Any]) -> bool:
    generated_at = payload.get("generated_at")
    return isinstance(generated_at, str) and bool(generated_at)


def _checkpoint_completion_state_matches_readiness(
    auth_proof: dict[str, Any],
    auth_checkpoint: dict[str, Any],
    auth_attempt: dict[str, Any],
) -> bool:
    readiness_complete = auth_proof.get("status") == "provider_browser_proof_complete"
    checkpoint_complete = (
        auth_checkpoint.get("status") == STATUS_COMPLETE
        and auth_checkpoint.get("live_provider_status") == "complete"
        and auth_checkpoint.get("live_capture_attempt_status") == "complete"
        and auth_attempt.get("status") == "complete"
    )
    if readiness_complete:
        return checkpoint_complete
    return not checkpoint_complete


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _runtime_auth_evidence_reported(auth_proof: dict[str, Any]) -> bool:
    evidence = auth_proof.get("runtime_auth_evidence")
    return (
        isinstance(evidence, dict)
        and evidence.get("schema_version") == "mesh.operator_auth_runtime_evidence.v1"
        and evidence.get("state_slice") == "auth-provider-proof.v1"
    )


def _runtime_auth_evidence_redacted(auth_proof: dict[str, Any]) -> bool:
    evidence = auth_proof.get("runtime_auth_evidence")
    return isinstance(evidence, dict) and evidence.get("raw_secret_material_present") is False


def _auth_blockers(auth_proof: dict[str, Any]) -> list[str]:
    blockers = auth_proof.get("blockers")
    if isinstance(blockers, list) and blockers:
        return [str(item) for item in blockers]
    live_proof = auth_proof.get("live_provider_proof")
    if isinstance(live_proof, dict):
        missing = live_proof.get("missing_or_blocked")
        if isinstance(missing, list) and missing:
            return [str(item) for item in missing]
        blocker = live_proof.get("blocker")
        if blocker:
            return [str(blocker)]
    return ["provider_console_and_browser_completion_unverified"]


def _read_package_scripts(path: Path) -> dict[str, str]:
    package = _read_json(path)
    scripts = package.get("scripts")
    if not isinstance(scripts, dict):
        return {}
    return {str(key): str(value) for key, value in scripts.items()}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
