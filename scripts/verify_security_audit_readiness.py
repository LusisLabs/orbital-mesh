#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = (
    "SECURITY.md",
    ".github/CODEOWNERS",
    ".github/dependabot.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/security.yml",
    "docs/security-audit-readiness.md",
    "docs/production-hardening-records.md",
    "docs/release-provenance.md",
    "config/procurement-security.package.json",
    "latent-mesh/LatentMAS/osv-scanner.toml",
    "scripts/generate_release_provenance.py",
    "scripts/verify_procurement_security_package.py",
)

REQUIRED_MARKERS = {
    "SECURITY.md": (
        "Reporting Vulnerabilities",
        "MESH_OPERATOR_IDENTITY_REQUIRED=1",
        "MESH_FORCE_APPROVAL_GATE=1",
        "scripts/verify_security_audit_readiness.py --json",
        "complete release provenance",
    ),
    ".github/CODEOWNERS": (
        "/services/control_plane.py",
        "/control_plane_server.py",
        "/shared/mesh_runtime/schemas/",
        "/policies/",
        "@shaanp",
    ),
    ".github/dependabot.yml": (
        'package-ecosystem: "github-actions"',
        'package-ecosystem: "npm"',
        'package-ecosystem: "pip"',
        'package-ecosystem: "cargo"',
        'directory: "/latent-mesh/LatentMAS"',
    ),
    ".github/workflows/ci.yml": (
        "permissions:",
        "contents: read",
        "pnpm --dir web run lint",
        "pnpm --dir meshapp/frontend run lint",
        "docker build",
    ),
    ".github/workflows/security.yml": (
        "Security Audit",
        "cron:",
        "verify_security_audit_readiness.py --json",
        "actions: read",
        "checks: read",
        "issues: read",
        "actions/dependency-review-action@",
        "GITLEAKS_LINUX_X64_SHA256",
        "gitleaks detect --source=.",
        "ghcr.io/google/osv-scanner@sha256:",
        "osv-lockfile-scan.json",
        "pnpm --dir web audit --audit-level high --json",
        "pnpm --dir meshapp/frontend audit --audit-level high --json",
        "pnpm-audit*.json",
        "GHAS_DEPENDENCY_REVIEW_ON_PRIVATE",
        "github/codeql-action/init@",
        "ossf/scorecard-action@",
        "pull-requests: read",
        "repo_token: ${{ secrets.GITHUB_TOKEN }}",
        "statuses: read",
    ),
    "docs/security-audit-readiness.md": (
        "OpenSSF Control Map",
        "Regular Audit Cadence",
        "E2E Audit Commands",
        "Audit Evidence Package",
        "Procurement Security Package",
        "OpenSSF Best Practices Badge",
    ),
    "docs/production-hardening-records.md": (
        "OpenSSF",
        "scripts/verify_security_audit_readiness.py",
        "procurement_security_package_verified",
        "security audit workflow",
    ),
    "config/procurement-security.package.json": (
        "mesh.procurement_security_package.v1",
        "sso_identity",
        "audit_export",
        "retention_controls",
        "data_boundaries",
        "deployment_modes",
        "security_answers",
        "support_escalation",
        "known_limits",
    ),
    "docs/release-provenance.md": (
        "SBOM path",
        "vulnerability scan path",
        "builder identity",
    ),
    "latent-mesh/LatentMAS/osv-scanner.toml": (
        "RUSTSEC-2024-0436",
        "tokenizers",
        "2026-08-06",
    ),
}

WORKFLOW_ACTION_PATTERN = re.compile(r"uses:\s*([^@\s]+)@([^\s#]+)")
FULL_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify OpenSSF and security-audit readiness controls are wired into the repo.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    checks.extend(_check_required_paths())
    checks.extend(_check_required_markers())
    checks.extend(_check_pinned_workflow_actions())

    failed = [check for check in checks if check["status"] != "pass"]
    payload = {
        "schema": "mesh.security_audit_readiness.v1",
        "status": "pass" if not failed else "fail",
        "checks": checks,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for check in checks:
            print(f"{check['status']}: {check['name']} - {check['detail']}")
    return 0 if not failed else 1


def _check_required_paths() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for rel in REQUIRED_PATHS:
        exists = (REPO_ROOT / rel).exists()
        checks.append(
            {
                "name": f"path exists: {rel}",
                "status": "pass" if exists else "fail",
                "detail": "present" if exists else "missing",
            }
        )
    return checks


def _check_required_markers() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for rel, markers in REQUIRED_MARKERS.items():
        path = REPO_ROOT / rel
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        missing = [marker for marker in markers if marker not in text]
        checks.append(
            {
                "name": f"markers present: {rel}",
                "status": "pass" if not missing else "fail",
                "detail": "markers present" if not missing else f"missing markers: {missing}",
            }
        )
    return checks


def _check_pinned_workflow_actions() -> list[dict[str, Any]]:
    workflow_dir = REPO_ROOT / ".github" / "workflows"
    unpinned: list[str] = []
    for path in sorted(workflow_dir.glob("*.yml")) + sorted(workflow_dir.glob("*.yaml")):
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = WORKFLOW_ACTION_PATTERN.search(line)
            if not match:
                continue
            action, ref = match.groups()
            if action.startswith("./"):
                continue
            if not FULL_SHA_PATTERN.match(ref):
                unpinned.append(f"{path.relative_to(REPO_ROOT)}:{line_no}:{action}@{ref}")
    return [
        {
            "name": "workflow actions pinned to full commit SHA",
            "status": "pass" if not unpinned else "fail",
            "detail": "all external actions pinned" if not unpinned else f"unpinned actions: {unpinned}",
        }
    ]


if __name__ == "__main__":
    sys.exit(main())
