#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

IMAGE_DEFAULTS = {
    "docker-compose.prod.yml": ("${MESH_IMAGE:-orbital-mesh:",),
    "docker-compose.stack.yml": (
        "${HERMES_RUNTIME_IMAGE:-orbital-mesh-hermes:",
        "${MESH_STACK_IMAGE:-orbital-mesh-stack:",
        "${MESH_LATENTMAS_IMAGE:-orbital-mesh-latentmas:",
    ),
}

REQUIRED_DOCS = (
    "docs/production-hardening-records.md",
    "docs/evaluation-kits.md",
    "docs/community-governance.md",
    "docs/design-partner-packet.md",
    "docs/postgres-restart-proof.md",
    "docs/release-provenance.md",
    "docs/authenticated-ingress.md",
    "docs/reference-architectures.md",
    "docs/pilot-slo-error-budget.md",
)

REQUIRED_SCRIPTS = (
    "scripts/compose_stack_smoke.sh",
    "scripts/prod_smoke.sh",
    "scripts/e2e_ui_operator.sh",
    "scripts/verify_postgres_restart_proof.py",
    "scripts/generate_release_provenance.py",
    "scripts/verify_authenticated_ingress.py",
)

REQUIRED_API_MARKERS = (
    "/api/readiness",
    "/api/kill-switch",
    "/api/pilot/go-no-go",
    "/api/policy/simulate",
)

REQUIRED_MARKERS = {
    "docker-compose.stack.yml": (
        'MESH_STATE_BACKEND: "${MESH_STATE_BACKEND:-postgres}"',
        'MESH_DEFAULT_STEERING_MODE: "${MESH_DEFAULT_STEERING_MODE:-approval_gate}"',
        'MESH_OPERATOR_IDENTITY_REQUIRED: "${MESH_OPERATOR_IDENTITY_REQUIRED:-1}"',
        'MESH_FEATURE_FLAG_CREDENTIALS_AVAILABLE: "${MESH_FEATURE_FLAG_CREDENTIALS_AVAILABLE:-false}"',
        'MESH_INCIDENT_CREDENTIALS_AVAILABLE: "${MESH_INCIDENT_CREDENTIALS_AVAILABLE:-false}"',
        'E2E_AUTO_APPROVE: "${E2E_AUTO_APPROVE:-1}"',
        'MESH_E2E_OPERATOR_ROLES: "${MESH_E2E_OPERATOR_ROLES:-launcher,approver}"',
        'MESH_AGENT_OPERATOR_ROLES: "${MESH_AGENT_OPERATOR_ROLES:-approver}"',
    ),
    "scripts/e2e_run_mesh.sh": (
        "E2E_AUTO_APPROVE",
        "MESH_E2E_OPERATOR_ID",
        "/api/runs/{run_id}/steer",
    ),
    "scripts/mesh_agent_operator.py": (
        "MESH_AGENT_OPERATOR_ID",
        "MESH_AGENT_OPERATOR_ROLES",
    ),
    "scripts/generate_release_provenance.py": (
        "mesh.release_provenance.v1",
        "--require-complete",
        "base_image_digests",
        "policy_hashes",
        "migration_version",
        "sbom_path",
        "vulnerability_scan_path",
    ),
    "docs/release-provenance.md": (
        "MESH_IMAGE_DIGEST",
        "MESH_SBOM_PATH",
        "MESH_VULNERABILITY_SCAN_PATH",
    ),
    "scripts/verify_authenticated_ingress.py": (
        "mesh.authenticated_ingress_rehearsal.v1",
        "operator_identity_required=True",
        "X-Mesh-Operator",
        "X-Mesh-Roles",
        "anonymous_run_creation_denied",
        "viewer_policy_simulation_accepted",
        "launcher_run_creation_accepted",
        "approver_approval_accepted",
        "admin_kill_switch_accepted",
    ),
    "docs/authenticated-ingress.md": (
        "MESH_OPERATOR_IDENTITY_REQUIRED=1",
        "X-Mesh-Operator",
        "X-Mesh-Roles",
        "viewer",
        "launcher",
        "approver",
        "admin",
        "scripts/verify_authenticated_ingress.py",
    ),
    "docs/reference-architectures.md": (
        "docker-compose.stack.yml",
        "docker-compose.prod.yml",
        "docs/authenticated-ingress.md",
        "scripts/prod_smoke.sh",
        "scripts/verify_postgres_restart_proof.py",
        "scripts/generate_release_provenance.py",
        "Kubernetes Platform Team",
        "GPU And AI Infrastructure",
        "Regulated Enterprise",
        "Air-Gapped Or Offline-Adjacent",
    ),
    "docs/pilot-slo-error-budget.md": (
        "/api/health",
        "/api/readiness",
        "/api/agent/slo",
        "/metrics",
        "/api/pilot/go-no-go",
        "scripts/prod_smoke.sh",
        "scripts/verify_authenticated_ingress.py",
        "scripts/verify_postgres_restart_proof.py",
        "scripts/generate_release_provenance.py",
        "Hard Stop Conditions",
        "Error Budget",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the production cut-list release packet references active orbital-mesh paths.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    checks.extend(_check_image_defaults())
    checks.extend(_check_required_paths("doc", REQUIRED_DOCS))
    checks.extend(_check_required_paths("script", REQUIRED_SCRIPTS))
    checks.extend(_check_api_markers())
    checks.extend(_check_required_markers())
    checks.extend(_check_docs_reference_active_paths())

    failed = [check for check in checks if check["status"] != "pass"]
    payload = {
        "status": "pass" if not failed else "fail",
        "checks": checks,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for check in checks:
            print(f"{check['status']}: {check['name']} - {check['detail']}")
    return 0 if not failed else 1


def _check_image_defaults() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for rel, markers in IMAGE_DEFAULTS.items():
        text = _read(rel)
        missing = [marker for marker in markers if marker not in text]
        legacy = "mesh-intelligence" in text
        status = "pass" if not missing and not legacy else "fail"
        detail = "orbital-mesh image defaults present"
        if missing:
            detail = f"missing defaults: {missing}"
        if legacy:
            detail = "legacy mesh-intelligence image/default reference present"
        checks.append({"name": f"image defaults: {rel}", "status": status, "detail": detail})
    return checks


def _check_required_paths(kind: str, paths: tuple[str, ...]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for rel in paths:
        path = REPO_ROOT / rel
        checks.append(
            {
                "name": f"{kind} exists: {rel}",
                "status": "pass" if path.exists() else "fail",
                "detail": "present" if path.exists() else "missing",
            }
        )
    return checks


def _check_api_markers() -> list[dict[str, Any]]:
    text = _read("control_plane_server.py")
    return [
        {
            "name": f"API marker: {marker}",
            "status": "pass" if marker in text else "fail",
            "detail": "present" if marker in text else "missing",
        }
        for marker in REQUIRED_API_MARKERS
    ]


def _check_required_markers() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for rel, markers in REQUIRED_MARKERS.items():
        text = _read(rel)
        missing = [marker for marker in markers if marker not in text]
        checks.append(
            {
                "name": f"release marker: {rel}",
                "status": "pass" if not missing else "fail",
                "detail": "markers present" if not missing else f"missing markers: {missing}",
            }
        )
    return checks


def _check_docs_reference_active_paths() -> list[dict[str, Any]]:
    references = {
        "docs/evaluation-kits.md": (
            "docker-compose.stack.yml",
            "docker-compose.prod.yml",
            "scripts/compose_stack_smoke.sh",
            "scripts/prod_smoke.sh",
        ),
        "docs/design-partner-packet.md": (
            "docs/production-hardening-records.md",
            "docs/production-live-runbook.md",
            "docs/production-readiness-validation.md",
        ),
        "docs/postgres-restart-proof.md": (
            "scripts/verify_postgres_restart_proof.py",
            "shared/mesh_runtime/postgres_state.py",
        ),
        "docs/release-provenance.md": (
            "scripts/generate_release_provenance.py",
        ),
        "docs/authenticated-ingress.md": (
            "control_plane_server.py",
            "scripts/verify_authenticated_ingress.py",
        ),
        "docs/reference-architectures.md": (
            "docker-compose.stack.yml",
            "docker-compose.prod.yml",
            "docs/authenticated-ingress.md",
            "scripts/prod_smoke.sh",
            "scripts/verify_postgres_restart_proof.py",
            "scripts/generate_release_provenance.py",
            "services/ingest/kubernetes_live_signal.py",
            "services/watchers/kubernetes.py",
            "services/actuators/service.py",
            "docker-compose.latentmas.yml",
            "mesh_brain/",
            "fixtures/signals/",
            "policies/",
        ),
        "docs/pilot-slo-error-budget.md": (
            "docs/design-partner-packet.md",
            "scripts/prod_smoke.sh",
            "scripts/verify_authenticated_ingress.py",
            "scripts/verify_postgres_restart_proof.py",
            "scripts/generate_release_provenance.py",
        ),
    }
    checks: list[dict[str, Any]] = []
    for doc, expected in references.items():
        text = _read(doc)
        missing = [rel for rel in expected if rel not in text or not (REPO_ROOT / rel).exists()]
        checks.append(
            {
                "name": f"active path references: {doc}",
                "status": "pass" if not missing else "fail",
                "detail": "all references present" if not missing else f"missing references: {missing}",
            }
        )
    return checks


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
