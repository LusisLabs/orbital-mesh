#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
AUTH_PROOF_PATH = REPO_ROOT / ".mesh-runtime-state" / "operator-auth-proof" / "latest.json"

STATUS_COMPLETE = "complete"
STATUS_BLOCKED_LOCAL = "blocked_local_evidence"
STATUS_BLOCKED_EXTERNAL = "blocked_external_provider_proof"

P0_E2E_MARKERS = [
    "first-run signup creates a team and reaches the product dashboard",
    "first-run signup can continue solo from a clean browser session",
    "logout returns a clean browser session to sign-in",
    "expired session clears cookie and recovers through login",
    "/api/operator/dashboard",
]
P0_PACKAGE_SCRIPTS = {
    "auth-provider:live-capture": "scripts/operator_auth_live_provider_capture.py",
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
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)

    audit = build_goal_audit(REPO_ROOT, auth_proof_path=Path(args.auth_proof_path))
    print(json.dumps(audit, indent=2, sort_keys=True))

    if audit["status"] == STATUS_BLOCKED_LOCAL:
        return 1
    if args.require_complete and audit["status"] != STATUS_COMPLETE:
        return 2
    return 0


def build_goal_audit(repo_root: Path, *, auth_proof_path: Path | None = None) -> dict[str, Any]:
    package = _read_package_scripts(repo_root / "package.json")
    product_app = _read(repo_root / "meshapp" / "frontend" / "src" / "product" / "ProductApp.tsx")
    product_api = _read(repo_root / "meshapp" / "frontend" / "src" / "product" / "api.ts")
    product_tests = _read(repo_root / "meshapp" / "frontend" / "src" / "product" / "ProductApp.dashboard.test.tsx")
    product_e2e = _read(repo_root / "meshapp" / "frontend" / "e2e" / "first-run-signup-dashboard.spec.ts")
    control_plane = _read(repo_root / "control_plane_server.py")
    service_control_plane = _read(repo_root / "services" / "control_plane.py")
    backend = f"{control_plane}\n{service_control_plane}"
    operator_config = _read(repo_root / "scripts" / "operator_config.py")
    docs = _read(repo_root / "docs" / "operator-product-app.md")
    auth_path = auth_proof_path or repo_root / ".mesh-runtime-state" / "operator-auth-proof" / "latest.json"
    auth_proof = _read_json(auth_path)

    requirements = [
        _p0_requirement(package, product_e2e, auth_proof, auth_path),
        _local_requirement(
            "P1",
            "Dashboard completeness",
            [
                *_marker_checks("ProductApp.tsx", product_app, P1_PRODUCT_MARKERS),
                *_marker_checks("ProductApp.dashboard.test.tsx", product_tests, P1_TEST_MARKERS),
            ],
            [
                "meshapp/frontend/src/product/ProductApp.tsx",
                "meshapp/frontend/src/product/ProductApp.dashboard.test.tsx",
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


def _p0_requirement(scripts: dict[str, str], product_e2e: str, auth_proof: dict[str, Any], auth_path: Path) -> dict[str, Any]:
    local_checks = [
        *_marker_checks("first-run-signup-dashboard.spec.ts", product_e2e, P0_E2E_MARKERS),
        *_script_checks(scripts, P0_PACKAGE_SCRIPTS),
        ("auth proof artifact exists", auth_path.exists()),
        ("auth proof schema is mesh.operator_auth_provider_readiness.v1", auth_proof.get("schema_version") == "mesh.operator_auth_provider_readiness.v1"),
        ("auth proof state slice is auth-provider-proof.v1", auth_proof.get("state_slice") == "auth-provider-proof.v1"),
        ("auth proof does not contain raw secret material", auth_proof.get("raw_secret_material_present") is False),
        ("auth env files are untracked", auth_proof.get("tracked_env_secret_material_present") is False),
        ("tracked secret hits are empty", auth_proof.get("tracked_secret_hits") == []),
        ("runtime auth evidence is reported", _runtime_auth_evidence_reported(auth_proof)),
        ("runtime auth evidence contains no raw secret material", _runtime_auth_evidence_redacted(auth_proof)),
        ("Google local callback matches", _provider_callback_ok(auth_proof, "google")),
        ("GitHub local callback matches", _provider_callback_ok(auth_proof, "github")),
        ("hCaptcha env readiness is present", auth_proof.get("captcha", {}).get("hcaptcha_env_ready") is True),
    ]
    missing = [label for label, passed in local_checks if not passed]
    evidence = [
        "meshapp/frontend/e2e/first-run-signup-dashboard.spec.ts",
        "scripts/operator_auth_provider_smoke.py",
        "tests/test_operator_auth_provider_smoke.py",
        "package.json",
        str(auth_path),
    ]
    live_status = str(auth_proof.get("status") or "auth_provider_readiness_missing")
    live_complete = live_status == "provider_browser_proof_complete"
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
