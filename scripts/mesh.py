#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.hsai_bridge import (
    build_combined_proof_packet,
    load_hsai_formal_backend_run_metadata,
    validate_hsai_decision,
    verify_combined_proof_packet_payload,
)

HSAI_BRIDGE_FIXTURE_NAMES = (
    "golden_allow_request.json",
    "golden_allow_decision.json",
    "golden_deny_request.json",
    "golden_deny_decision.json",
)
HSAI_FORMAL_BACKEND_BUNDLE_FIXTURE = "formal_backend_notrun_bundle"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mesh operator utility commands.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify-proof-packet", help="Verify a mesh.combined_proof_packet.v1 artifact.")
    verify.add_argument("--packet", required=True, help="Path to mesh.combined_proof_packet.v1 JSON.")
    verify.add_argument("--request", required=True, help="Path to the bound mesh.hsai_admission_request.v1 JSON.")
    verify.add_argument("--decision", required=True, help="Path to the bound mesh.hsai_admission_decision.v1 JSON.")
    verify.add_argument("--json", action="store_true", help="Emit JSON.")
    fixture_verify = subparsers.add_parser(
        "verify-hsai-bridge-fixtures",
        help="Verify bundled HSAI admission bridge golden fixtures.",
    )
    fixture_verify.add_argument(
        "--fixtures",
        default=str(REPO_ROOT / "fixtures" / "hsai_bridge"),
        help="Directory containing golden HSAI bridge fixture JSON files.",
    )
    fixture_verify.add_argument("--json", action="store_true", help="Emit JSON.")

    args = parser.parse_args(argv)
    if args.command == "verify-proof-packet":
        result = verify_combined_proof_packet_payload(
            packet=_read_json_object(Path(args.packet)),
            request=_read_json_object(Path(args.request)),
            decision=_read_json_object(Path(args.decision)),
        )
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"{result['status']}: {', '.join(result['issues']) or 'combined proof packet verified'}")
        return 0 if result["status"] == "pass" else 1
    if args.command == "verify-hsai-bridge-fixtures":
        result = verify_hsai_bridge_fixtures(Path(args.fixtures))
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"{result['status']}: {', '.join(result['issues']) or 'HSAI bridge fixtures verified'}")
        return 0 if result["status"] == "pass" else 1
    return 2


def verify_hsai_bridge_fixtures(fixtures_dir: Path) -> dict[str, Any]:
    issues: list[str] = []
    checks: dict[str, Any] = {}
    try:
        fixtures = {name: _read_json_object(fixtures_dir / name) for name in HSAI_BRIDGE_FIXTURE_NAMES}
        allow_request = fixtures["golden_allow_request.json"]
        allow_decision = fixtures["golden_allow_decision.json"]
        deny_request = fixtures["golden_deny_request.json"]
        deny_decision = fixtures["golden_deny_decision.json"]

        validate_hsai_decision(allow_request, allow_decision)
        validate_hsai_decision(deny_request, deny_decision)
        checks["allow_contract"] = _decision_check(allow_decision, "allow", [])
        checks["deny_contract"] = _decision_check(deny_decision, "deny", ["missing_explicit_nonclaims"])
        checks["allow_packet"] = _verify_fixture_packet(allow_request, allow_decision, status="executed")
        checks["deny_packet"] = _verify_fixture_packet(deny_request, deny_decision, status="blocked")
        checks["formal_backend_bundle"] = _verify_formal_backend_bundle_fixture(
            fixtures_dir / HSAI_FORMAL_BACKEND_BUNDLE_FIXTURE
        )
    except Exception as exc:
        issues.append(str(exc))
    for key, check in checks.items():
        if check.get("status") != "pass":
            issues.append(f"{key}: {check.get('summary', 'failed')}")
    return {
        "schema_version": "mesh.hsai_bridge_fixture_verification.v1",
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "fixtures_dir": str(fixtures_dir),
        "fixture_names": list(HSAI_BRIDGE_FIXTURE_NAMES),
        "formal_backend_bundle_fixture": HSAI_FORMAL_BACKEND_BUNDLE_FIXTURE,
        "checks": checks,
    }


def _decision_check(decision: dict[str, Any], expected_decision: str, expected_reason_codes: list[str]) -> dict[str, Any]:
    if decision.get("decision") != expected_decision:
        return {"status": "fail", "summary": f"expected decision {expected_decision}"}
    if list(decision.get("reason_codes") or []) != expected_reason_codes:
        return {"status": "fail", "summary": f"expected reason codes {expected_reason_codes}"}
    return {"status": "pass", "summary": expected_decision}


def _verify_fixture_packet(request: dict[str, Any], decision: dict[str, Any], *, status: str) -> dict[str, Any]:
    gate = {
        "allowed": decision["decision"] == "allow",
        "request": request,
        "decision": decision,
        "request_digest": decision["request_digest"],
        "decision_digest": decision["decision_digest"],
        "candidate_digest": decision["candidate_digest"],
        "reason_codes": list(decision.get("reason_codes") or []),
    }
    packet = build_combined_proof_packet(
        gate,
        mesh_policy_approved=True,
        action_execution_result=_fixture_action_result(decision, status=status),
        executor_receipt_digest="sha256:" + ("6" * 64) if status != "blocked" else None,
        created_at="2026-07-02T00:00:00Z",
    )
    result = verify_combined_proof_packet_payload(packet=packet, request=request, decision=decision)
    return {"status": result["status"], "summary": result["issues"] or status}


def _verify_formal_backend_bundle_fixture(bundle_root: Path) -> dict[str, Any]:
    metadata = load_hsai_formal_backend_run_metadata(bundle_root)
    expected = {
        "backend": "hsai-formal-backend-run-bundle",
        "backend_run_id": "hsai-formal-run-1",
        "state_slice": "phase-276-hsai-gateway-formal-backend-run-inert-artifact-metadata",
        "execution_mode": "NotRun",
        "exit_status": "NotRun",
        "checker_status": "NotRun",
    }
    mismatches = [
        f"{field}={metadata.get(field)!r}"
        for field, value in expected.items()
        if metadata.get(field) != value
    ]
    if "not accepted evidence" not in metadata.get("nonclaims", []):
        mismatches.append("missing not accepted evidence nonclaim")
    if "not formal proof evidence" not in metadata.get("nonclaims", []):
        mismatches.append("missing not formal proof evidence nonclaim")
    return {
        "status": "pass" if not mismatches else "fail",
        "summary": mismatches or "formal backend bundle verified",
        "metadata_digest": metadata.get("metadata_digest"),
    }


def _fixture_action_result(decision: dict[str, Any], *, status: str) -> dict[str, Any]:
    if status == "blocked":
        return {
            "status": "blocked",
            "executor": "native_hermes",
            "reason": "hsai_admission_blocked",
            "hsai_reason_codes": list(decision.get("reason_codes") or []),
            "mesh_blocking_reasons": [],
        }
    return {
        "status": status,
        "executor": "native_hermes",
        "result_digest": "sha256:" + ("5" * 64),
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected JSON object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
