#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from shared.mesh_runtime.production_autonomy_clearance import verify_production_autonomy_clearance
from verify_pilot_clearance import verify_pilot_clearance
from verify_release_artifact_bundle import ARTIFACT_PATHS, verify_release_artifact_bundle
from verify_release_runtime_binding import verify_release_runtime_binding


SCHEMA_VERSION = "mesh.e2e_claim_verification.v1"
DEFAULT_LIVE_PROOF_DIR = Path(".mesh-runtime-state/live-proof-current")


def main() -> int:
    args = _parser().parse_args()
    result = verify_e2e_claim(
        expected_head=args.expected_head,
        artifact_root=Path(args.artifact_root) if args.artifact_root else None,
        release_provenance=Path(args.release_provenance) if args.release_provenance else None,
        runtime_release_provenance_path=args.runtime_release_provenance_path,
        image_ref=args.image_ref,
        health_url=args.health_url,
        timeout_seconds=args.timeout_seconds,
        pilot_base_url=args.pilot_base_url,
        live_proof_dir=Path(args.live_proof_dir),
        expected_environment=args.expected_environment,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"{result['status']}: {', '.join(result['missing']) or 'e2e claim verified'}")
    return 0 if result["status"] == "pass" else 1


def verify_e2e_claim(
    *,
    expected_head: str = "",
    artifact_root: Path | None = None,
    release_provenance: Path | None = None,
    runtime_release_provenance_path: str = "/app/.mesh-runtime-state/release-provenance.json",
    image_ref: str = "",
    health_url: str = "",
    timeout_seconds: float = 30.0,
    pilot_base_url: str = "",
    live_proof_dir: Path = DEFAULT_LIVE_PROOF_DIR,
    expected_environment: str = "pilot",
) -> dict[str, Any]:
    resolved_head = expected_head or _git_head()
    resolved_release = _release_provenance_path(artifact_root=artifact_root, explicit=release_provenance)
    release_bundle = _release_bundle_result(
        artifact_root=artifact_root,
        expected_head=resolved_head,
        runtime_release_provenance_path=runtime_release_provenance_path,
        image_ref=image_ref,
        health_url=health_url,
        timeout_seconds=timeout_seconds,
    )
    runtime_binding = _runtime_binding_result(
        release_provenance=resolved_release,
        runtime_release_provenance_path=runtime_release_provenance_path,
        image_ref=image_ref,
        health_url=health_url,
        timeout_seconds=timeout_seconds,
    )
    pilot_clearance = _pilot_clearance_result(
        pilot_base_url=pilot_base_url,
        expected_head=resolved_head,
        timeout_seconds=timeout_seconds,
    )
    autonomy_clearance = _autonomy_clearance_result(
        live_proof_dir=live_proof_dir,
        expected_head=resolved_head,
        expected_environment=expected_environment,
    )

    checks = {
        "expected_head_present": bool(resolved_head),
        "release_artifact_bundle_passed": release_bundle.get("status") == "pass",
        "runtime_binding_passed": runtime_binding.get("status") == "pass",
        "pilot_clearance_passed": pilot_clearance.get("status") == "pass",
        "production_autonomy_clearance_passed": autonomy_clearance.get("status") == "pass",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) else "fail",
        "expected_head": resolved_head,
        "expected_environment": expected_environment,
        "checks": checks,
        "missing": [name for name, passed in checks.items() if not passed],
        "inputs": {
            "artifact_root": str(artifact_root) if artifact_root else None,
            "release_provenance": str(resolved_release) if resolved_release else None,
            "runtime_release_provenance_path": runtime_release_provenance_path,
            "image_ref": image_ref or None,
            "health_url": health_url or None,
            "pilot_base_url": pilot_base_url or None,
            "live_proof_dir": str(live_proof_dir),
        },
        "artifacts": {
            "release_artifact_bundle": release_bundle,
            "runtime_binding": runtime_binding,
            "pilot_clearance": pilot_clearance,
            "production_autonomy_clearance": autonomy_clearance,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the full frontend/backend e2e release claim against explicit current-head proof artifacts."
    )
    parser.add_argument("--expected-head", default="", help="Expected commit. Defaults to git HEAD.")
    parser.add_argument("--artifact-root", default="", help="Downloaded release artifact bundle root.")
    parser.add_argument(
        "--release-provenance",
        default="",
        help="Complete mesh.release_provenance.v1 path. Defaults to the release artifact bundle path.",
    )
    parser.add_argument(
        "--runtime-release-provenance-path",
        default="/app/.mesh-runtime-state/release-provenance.json",
        help="Container-readable MESH_RELEASE_PROVENANCE_PATH.",
    )
    parser.add_argument("--image-ref", default="", help="Optional image ref for runtime binding evidence.")
    parser.add_argument("--health-url", default="", help="Optional live /api/health URL for runtime binding evidence.")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--pilot-base-url", default="", help="Live control-plane base URL for pilot clearance.")
    parser.add_argument("--live-proof-dir", default=str(DEFAULT_LIVE_PROOF_DIR))
    parser.add_argument("--expected-environment", default="pilot")
    parser.add_argument("--json", action="store_true")
    return parser


def _release_bundle_result(
    *,
    artifact_root: Path | None,
    expected_head: str,
    runtime_release_provenance_path: str,
    image_ref: str,
    health_url: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    if artifact_root is None:
        return _blocked("release_artifact_bundle", "artifact_root_missing")
    return verify_release_artifact_bundle(
        artifact_root=artifact_root,
        expected_head=expected_head,
        runtime_release_provenance_path=runtime_release_provenance_path,
        image_ref=image_ref,
        health_url=health_url,
        timeout_seconds=timeout_seconds,
    )


def _runtime_binding_result(
    *,
    release_provenance: Path | None,
    runtime_release_provenance_path: str,
    image_ref: str,
    health_url: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    if release_provenance is None:
        return _blocked("release_runtime_binding", "release_provenance_path_missing")
    if not image_ref and not health_url:
        return _blocked("release_runtime_binding", "runtime_binding_evidence_missing")
    return verify_release_runtime_binding(
        release_provenance=release_provenance,
        runtime_release_provenance_path=runtime_release_provenance_path,
        image_ref=image_ref,
        health_url=health_url,
        timeout_seconds=timeout_seconds,
    )


def _pilot_clearance_result(*, pilot_base_url: str, expected_head: str, timeout_seconds: float) -> dict[str, Any]:
    if not pilot_base_url:
        return _blocked("pilot_clearance", "pilot_base_url_missing")
    return verify_pilot_clearance(
        base_url=pilot_base_url,
        timeout_seconds=timeout_seconds,
        expected_head=expected_head,
    )


def _autonomy_clearance_result(
    *,
    live_proof_dir: Path,
    expected_head: str,
    expected_environment: str,
) -> dict[str, Any]:
    if not live_proof_dir.is_dir():
        return _blocked("production_autonomy_clearance", "live_proof_dir_missing")
    proofs = live_proof_dir / "proofs"
    if not proofs.is_dir():
        return _blocked("production_autonomy_clearance", "live_proof_proofs_dir_missing")
    return verify_production_autonomy_clearance(
        repeatability_proof=proofs / "repeatability-proof.json",
        production_target_proof=proofs / "production-target-proof.json",
        provider_action_scope_proof=proofs / "provider-action-scope-proof.json",
        watch_mode_proof=proofs / "watch-mode-proof.json",
        incident_coverage_proof=proofs / "incident-coverage-proof.json",
        on_call_drill_proof=proofs / "on-call-drill.json",
        expected_head=expected_head,
        expected_environment=expected_environment,
    )


def _release_provenance_path(*, artifact_root: Path | None, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit
    if artifact_root is not None:
        return artifact_root / ARTIFACT_PATHS["release_provenance"]
    return None


def _blocked(schema: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": f"mesh.{schema}.blocked.v1",
        "generated_at": _timestamp(),
        "status": "fail",
        "checks": {reason: False},
        "missing": [reason],
    }


def _git_head() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return completed.stdout.strip()


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
