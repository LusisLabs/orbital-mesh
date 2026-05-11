#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import urlopen


SCHEMA_VERSION = "mesh.pilot_clearance_audit.v1"
DEFAULT_EXPECTED_READINESS_BLOCKERS = (
    "authenticated_ingress_deployment_verified",
    "mesh_brain_artifact_uri_prefix_configured",
    "mesh_brain_artifact_upload_proof_verified",
    "design_partner_packet_verified",
)
DEFAULT_EXPECTED_GO_NO_GO_MISSING = (
    "readiness_green",
    "operator_approval_observed",
    "live_action_proof_observed",
    "mesh_brain_model_kernel_gate_observed",
    "mesh_brain_live_canary_smoke_observed",
    "mesh_brain_single_crops_canary_lane_observed",
    "mesh_brain_rollback_drill_observed",
    "mesh_brain_artifact_upload_proof_verified",
    "release_provenance_complete",
    "on_call_drill_verified",
)
DEFAULT_EXPECTED_GO_NO_GO_TRUE_CHECKS = (
    "denied_action_proof_observed",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit the live pilot readiness, go/no-go, and release runtime binding gates."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8787", help="Control-plane base URL.")
    parser.add_argument("--timeout-seconds", type=float, default=30.0, help="HTTP request timeout.")
    parser.add_argument(
        "--expected-head",
        default="",
        help="Require /api/health commit to match this git commit for current-head pilot proof.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable result JSON.")
    parser.add_argument(
        "--expect-blocked",
        action="store_true",
        help="Pass when the live endpoints are healthy and explicitly blocked on expected pilot evidence gaps.",
    )
    parser.add_argument(
        "--expected-readiness-blocker",
        action="append",
        default=None,
        help="Readiness blocker expected in --expect-blocked mode. Repeatable; defaults to current pilot evidence gates.",
    )
    parser.add_argument(
        "--expected-go-no-go-missing",
        action="append",
        default=None,
        help="Go/no-go missing_evidence item expected in --expect-blocked mode. Repeatable; defaults to current pilot evidence gates.",
    )
    parser.add_argument(
        "--expected-go-no-go-true-check",
        action="append",
        default=None,
        help="Go/no-go check expected to be true in --expect-blocked mode. Repeatable; defaults to current observed pilot proofs.",
    )
    args = parser.parse_args()

    result = verify_pilot_clearance(
        base_url=args.base_url,
        timeout_seconds=args.timeout_seconds,
        expected_head=args.expected_head,
        expect_blocked=args.expect_blocked,
        expected_readiness_blockers=tuple(args.expected_readiness_blocker or DEFAULT_EXPECTED_READINESS_BLOCKERS),
        expected_go_no_go_missing=tuple(args.expected_go_no_go_missing or DEFAULT_EXPECTED_GO_NO_GO_MISSING),
        expected_go_no_go_true_checks=tuple(args.expected_go_no_go_true_check or DEFAULT_EXPECTED_GO_NO_GO_TRUE_CHECKS),
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        success = "pilot blocked state verified" if args.expect_blocked else "pilot clearance verified"
        print(f"{result['status']}: {', '.join(result['missing']) or success}")
    return 0 if result["status"] == "pass" else 1


def verify_pilot_clearance(
    *,
    base_url: str,
    timeout_seconds: float = 30.0,
    requester: Callable[[str, float], dict[str, Any]] | None = None,
    expected_head: str = "",
    expect_blocked: bool = False,
    expected_readiness_blockers: tuple[str, ...] = DEFAULT_EXPECTED_READINESS_BLOCKERS,
    expected_go_no_go_missing: tuple[str, ...] = DEFAULT_EXPECTED_GO_NO_GO_MISSING,
    expected_go_no_go_true_checks: tuple[str, ...] = DEFAULT_EXPECTED_GO_NO_GO_TRUE_CHECKS,
) -> dict[str, Any]:
    normalized_base_url = base_url.rstrip("/")
    fetch = requester or _request_json
    health = _safe_request(f"{normalized_base_url}/api/health", timeout_seconds, fetch)
    readiness = _safe_request(f"{normalized_base_url}/api/readiness", timeout_seconds, fetch)
    go_no_go = _safe_request(f"{normalized_base_url}/api/pilot/go-no-go", timeout_seconds, fetch)
    release = _release_record(go_no_go)

    health_record = _health_record(health)
    readiness_record = _readiness_record(readiness)
    go_no_go_record = _go_no_go_record(go_no_go)
    runtime_record = _runtime_binding_record(health=health, release=release, expected_head=expected_head)

    clearance_checks = {
        "health_status_ok": health_record["status_ok"],
        "readiness_profile_pilot": readiness_record["profile_pilot"],
        "readiness_ready": readiness_record["ready"],
        "readiness_blockers_empty": readiness_record["blockers_empty"],
        "go_no_go_packet_version": go_no_go_record["packet_version_valid"],
        "go_no_go_status_go": go_no_go_record["status_go"],
        "go_no_go_missing_empty": go_no_go_record["missing_empty"],
        "go_no_go_checks_passed": go_no_go_record["checks_passed"],
        "release_provenance_complete": release["complete"],
        "release_git_commit": bool(release["git_commit"]),
        "release_image_digest": bool(release["image_digest"]),
        "runtime_build_commit": bool(runtime_record["build_commit"]),
        "runtime_image_digest": bool(runtime_record["image_digest"]),
        "runtime_build_commit_match": runtime_record["build_commit_match"],
        "runtime_image_digest_match": runtime_record["image_digest_match"],
        "runtime_expected_head_valid": runtime_record["expected_head_valid"],
        "runtime_build_commit_matches_expected_head": runtime_record["build_commit_matches_expected_head"],
    }
    expected_blocked = _expected_blocked_record(
        health=health_record,
        readiness=readiness_record,
        go_no_go=go_no_go_record,
        release=release,
        expected_readiness_blockers=expected_readiness_blockers,
        expected_go_no_go_missing=expected_go_no_go_missing,
        expected_go_no_go_true_checks=expected_go_no_go_true_checks,
    )
    checks = expected_blocked["checks"] if expect_blocked else clearance_checks
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "fail",
        "mode": "expect_blocked" if expect_blocked else "clearance",
        "base_url": normalized_base_url,
        "checks": checks,
        "missing": [name for name, passed in checks.items() if not passed],
        "checklist": _blocked_checklist(checks) if expect_blocked else _checklist(checks),
        "artifacts": {
            "health": health_record,
            "readiness": readiness_record,
            "go_no_go": go_no_go_record,
            "release_provenance": release,
            "runtime_binding": runtime_record,
        },
    }
    if expect_blocked:
        result["expected_blocked"] = expected_blocked
    result["prompt_to_artifact_checklist"] = _prompt_to_artifact_checklist(
        health=health_record,
        readiness=readiness_record,
        go_no_go=go_no_go_record,
        release=release,
        runtime=runtime_record,
        expected_blocked=expected_blocked,
        expect_blocked=expect_blocked,
    )
    result["status"] = "pass" if not result["missing"] else "fail"
    return result


def _safe_request(
    url: str,
    timeout_seconds: float,
    requester: Callable[[str, float], dict[str, Any]],
) -> dict[str, Any]:
    try:
        payload = requester(url, timeout_seconds)
    except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}
    return payload if isinstance(payload, dict) else {"error": "endpoint returned non-object JSON"}


def _request_json(url: str, timeout_seconds: float) -> dict[str, Any]:
    with urlopen(url, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("endpoint returned non-object JSON")
    return payload


def _health_record(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": "/api/health",
        "status": _string_or_none(payload.get("status")),
        "status_ok": payload.get("status") == "ok",
        "timestamp": _string_or_none(payload.get("timestamp")),
        "commit": _string_or_none(payload.get("commit")),
        "image_digest": _string_or_none(payload.get("image_digest")),
        "error": _string_or_none(payload.get("error")),
    }


def _readiness_record(payload: dict[str, Any]) -> dict[str, Any]:
    blockers = payload.get("blockers")
    blockers = blockers if isinstance(blockers, list) else []
    details = payload.get("blocker_details") if isinstance(payload.get("blocker_details"), dict) else {}
    return {
        "url": "/api/readiness",
        "profile": _string_or_none(payload.get("profile")),
        "status": _string_or_none(payload.get("status")),
        "checked_at": _string_or_none(payload.get("checked_at")),
        "blockers": [str(item) for item in blockers],
        "blocker_details": {
            str(name): _json_ready(detail)
            for name, detail in details.items()
            if isinstance(detail, dict)
        },
        "profile_pilot": payload.get("profile") == "pilot",
        "ready": payload.get("status") == "ready",
        "blockers_empty": blockers == [],
        "error": _string_or_none(payload.get("error")),
    }


def _go_no_go_record(payload: dict[str, Any]) -> dict[str, Any]:
    missing = payload.get("missing_evidence")
    missing = missing if isinstance(missing, list) else []
    checks = payload.get("checks")
    checks = checks if isinstance(checks, dict) else {}
    return {
        "url": "/api/pilot/go-no-go",
        "packet_version": _string_or_none(payload.get("packet_version")),
        "status": _string_or_none(payload.get("status")),
        "generated_at": _string_or_none(payload.get("generated_at")),
        "missing_evidence": [str(item) for item in missing],
        "packet_version_valid": payload.get("packet_version") == "pilot.go_no_go.v1",
        "status_go": payload.get("status") == "go",
        "missing_empty": missing == [],
        "checks_passed": bool(checks) and all(value is True for value in checks.values()),
        "check_results": {str(name): value for name, value in checks.items() if isinstance(value, bool)},
        "observed": _compact_observed(payload.get("observed")),
        "mesh_brain_artifact_upload_proof": _json_ready(payload.get("mesh_brain_artifact_upload_proof")),
        "on_call_drill": _json_ready(payload.get("on_call_drill")),
        "error": _string_or_none(payload.get("error")),
    }


def _expected_blocked_record(
    *,
    health: dict[str, Any],
    readiness: dict[str, Any],
    go_no_go: dict[str, Any],
    release: dict[str, Any],
    expected_readiness_blockers: tuple[str, ...],
    expected_go_no_go_missing: tuple[str, ...],
    expected_go_no_go_true_checks: tuple[str, ...],
) -> dict[str, Any]:
    readiness_blockers = set(readiness["blockers"])
    go_no_go_missing = set(go_no_go["missing_evidence"])
    readiness_details = readiness.get("blocker_details")
    readiness_details = readiness_details if isinstance(readiness_details, dict) else {}
    expected_readiness = tuple(dict.fromkeys(expected_readiness_blockers))
    expected_go_no_go = tuple(dict.fromkeys(expected_go_no_go_missing))
    expected_true_checks = tuple(dict.fromkeys(expected_go_no_go_true_checks))
    missing_readiness = [name for name in expected_readiness if name not in readiness_blockers]
    missing_go_no_go = [name for name in expected_go_no_go if name not in go_no_go_missing]
    unexpected_readiness = sorted(readiness_blockers - set(expected_readiness))
    unexpected_go_no_go = sorted(go_no_go_missing - set(expected_go_no_go))
    check_results = go_no_go.get("check_results") if isinstance(go_no_go.get("check_results"), dict) else {}
    missing_true_checks = [name for name in expected_true_checks if check_results.get(name) is not True]
    missing_readiness_details = [name for name in expected_readiness if name not in readiness_details]
    go_no_go_details = _go_no_go_missing_detail_map(
        readiness=readiness,
        go_no_go=go_no_go,
        release=release,
        names=expected_go_no_go,
    )
    observed_proof_details = _go_no_go_true_check_detail_map(go_no_go=go_no_go, names=expected_true_checks)
    missing_go_no_go_details = [name for name in expected_go_no_go if name not in go_no_go_details]
    missing_observed_proof_details = [name for name in expected_true_checks if name not in observed_proof_details]
    checks = {
        "health_status_ok": health["status_ok"],
        "readiness_endpoint_ok": readiness["error"] is None,
        "readiness_profile_pilot": readiness["profile_pilot"],
        "readiness_status_blocked": readiness["status"] == "blocked",
        "readiness_blockers_present": bool(readiness["blockers"]),
        "expected_readiness_blockers_present": missing_readiness == [],
        "unexpected_readiness_blockers_absent": unexpected_readiness == [],
        "expected_readiness_blocker_details_present": missing_readiness_details == [],
        "go_no_go_endpoint_ok": go_no_go["error"] is None,
        "go_no_go_packet_version": go_no_go["packet_version_valid"],
        "go_no_go_status_blocked": go_no_go["status"] == "blocked",
        "go_no_go_missing_present": bool(go_no_go["missing_evidence"]),
        "expected_go_no_go_missing_present": missing_go_no_go == [],
        "unexpected_go_no_go_missing_absent": unexpected_go_no_go == [],
        "expected_go_no_go_missing_details_present": missing_go_no_go_details == [],
        "expected_go_no_go_true_checks_present": missing_true_checks == [],
        "expected_go_no_go_observed_proof_details_present": missing_observed_proof_details == [],
    }
    return {
        "expected_readiness_blockers": list(expected_readiness),
        "expected_go_no_go_missing": list(expected_go_no_go),
        "expected_go_no_go_true_checks": list(expected_true_checks),
        "missing_expected_readiness_blockers": missing_readiness,
        "missing_expected_go_no_go": missing_go_no_go,
        "missing_expected_go_no_go_true_checks": missing_true_checks,
        "unexpected_readiness_blockers": unexpected_readiness,
        "unexpected_go_no_go_missing": unexpected_go_no_go,
        "missing_expected_readiness_blocker_details": missing_readiness_details,
        "missing_expected_go_no_go_missing_details": missing_go_no_go_details,
        "missing_expected_go_no_go_observed_proof_details": missing_observed_proof_details,
        "readiness_blocker_details": {
            name: readiness_details[name]
            for name in expected_readiness
            if name in readiness_details
        },
        "go_no_go_missing_details": go_no_go_details,
        "go_no_go_observed_proof_details": observed_proof_details,
        "checks": checks,
    }


def _go_no_go_missing_detail_map(
    *,
    readiness: dict[str, Any],
    go_no_go: dict[str, Any],
    release: dict[str, Any],
    names: tuple[str, ...],
) -> dict[str, Any]:
    details: dict[str, Any] = {}
    readiness_details = readiness.get("blocker_details")
    readiness_details = readiness_details if isinstance(readiness_details, dict) else {}
    check_results = go_no_go.get("check_results") if isinstance(go_no_go.get("check_results"), dict) else {}
    observed = go_no_go.get("observed") if isinstance(go_no_go.get("observed"), dict) else {}
    evidence_keys = {
        "operator_approval_observed": ("approved_run_ids",),
        "live_action_proof_observed": ("live_action_run_ids",),
        "mesh_brain_model_kernel_gate_observed": ("mesh_brain_model_kernel_run_ids",),
        "mesh_brain_live_canary_smoke_observed": (
            "mesh_brain_live_canary_smoke_run_ids",
            "mesh_brain_canary_lanes",
        ),
        "mesh_brain_single_crops_canary_lane_observed": ("mesh_brain_canary_lanes",),
        "mesh_brain_rollback_drill_observed": ("mesh_brain_rollback_drill_run_ids",),
    }
    for name in names:
        if name == "readiness_green":
            details[name] = {
                "source": "/api/readiness",
                "status": readiness.get("status"),
                "blockers": readiness.get("blockers", []),
                "blocker_details": readiness_details,
            }
        elif name == "mesh_brain_artifact_upload_proof_verified":
            proof = go_no_go.get("mesh_brain_artifact_upload_proof")
            if isinstance(proof, dict):
                details[name] = {
                    "source": "/api/pilot/go-no-go.mesh_brain_artifact_upload_proof",
                    "proof": proof,
                }
            elif name in readiness_details:
                details[name] = {
                    "source": "/api/readiness.blocker_details",
                    "blocker_detail": readiness_details[name],
                }
        elif name == "release_provenance_complete":
            details[name] = {
                "source": "/api/pilot/go-no-go.release_provenance",
                "release_provenance": release,
            }
        elif name == "on_call_drill_verified" and isinstance(go_no_go.get("on_call_drill"), dict):
            details[name] = {
                "source": "/api/pilot/go-no-go.on_call_drill",
                "on_call_drill": go_no_go["on_call_drill"],
            }
        elif name in check_results:
            details[name] = {
                "source": "/api/pilot/go-no-go.checks",
                "check": name,
                "passed": check_results.get(name),
                "observed": {
                    key: observed.get(key)
                    for key in evidence_keys.get(name, ())
                    if key in observed
                },
            }
    return details


def _go_no_go_true_check_detail_map(*, go_no_go: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    details: dict[str, Any] = {}
    check_results = go_no_go.get("check_results") if isinstance(go_no_go.get("check_results"), dict) else {}
    observed = go_no_go.get("observed") if isinstance(go_no_go.get("observed"), dict) else {}
    evidence_keys = {
        "denied_action_proof_observed": ("denied_action_run_ids",),
        "mesh_brain_model_kernel_gate_observed": ("mesh_brain_model_kernel_run_ids",),
        "mesh_brain_live_canary_smoke_observed": ("mesh_brain_live_canary_smoke_run_ids", "mesh_brain_canary_lanes"),
        "mesh_brain_single_crops_canary_lane_observed": ("mesh_brain_canary_lanes",),
        "mesh_brain_rollback_drill_observed": ("mesh_brain_rollback_drill_run_ids",),
    }
    for name in names:
        if check_results.get(name) is not True:
            continue
        details[name] = {
            "source": "/api/pilot/go-no-go.checks",
            "check": name,
            "observed": {
                key: observed.get(key)
                for key in evidence_keys.get(name, ())
                if key in observed
            },
        }
    return details


def _release_record(go_no_go: dict[str, Any]) -> dict[str, Any]:
    payload = go_no_go.get("release_provenance")
    payload = payload if isinstance(payload, dict) else {}
    missing = payload.get("missing")
    missing = missing if isinstance(missing, list) else []
    checks = payload.get("checks")
    checks = checks if isinstance(checks, dict) else {}
    git_commit = _normalized_git_commit(_nested(payload, "git", "commit"))
    image_digest = _normalized_digest(_nested(payload, "image", "digest"))
    return {
        "path": _string_or_none(payload.get("path")),
        "schema_version": _string_or_none(payload.get("schema_version")),
        "status": _string_or_none(payload.get("status")),
        "packet_sha256": _string_or_none(payload.get("packet_sha256")),
        "missing": [str(item) for item in missing],
        "git_commit": git_commit,
        "image_digest": image_digest,
        "complete": (
            payload.get("schema_version") == "mesh.release_provenance.v1"
            and payload.get("status") == "complete"
            and missing == []
            and bool(checks)
            and all(value is True for value in checks.values())
        ),
    }


def _runtime_binding_record(*, health: dict[str, Any], release: dict[str, Any], expected_head: str = "") -> dict[str, Any]:
    release_commit = _normalized_git_commit(release.get("git_commit"))
    release_digest = _normalized_digest(release.get("image_digest"))
    runtime_commit = _normalized_git_commit(health.get("commit"))
    runtime_digest = _normalized_digest(health.get("image_digest"))
    expected_head_required = bool(expected_head.strip())
    expected_head_commit = _normalized_git_commit(expected_head)
    return {
        "build_commit": runtime_commit,
        "image_digest": runtime_digest,
        "expected_build_commit": release_commit,
        "expected_image_digest": release_digest,
        "build_commit_match": bool(runtime_commit and release_commit and runtime_commit == release_commit),
        "image_digest_match": bool(runtime_digest and release_digest and runtime_digest == release_digest),
        "expected_head_required": expected_head_required,
        "expected_head": expected_head_commit,
        "expected_head_valid": not expected_head_required or bool(expected_head_commit),
        "build_commit_matches_expected_head": (
            not expected_head_required
            or bool(runtime_commit and expected_head_commit and runtime_commit == expected_head_commit)
        ),
    }


def _prompt_to_artifact_checklist(
    *,
    health: dict[str, Any],
    readiness: dict[str, Any],
    go_no_go: dict[str, Any],
    release: dict[str, Any],
    runtime: dict[str, Any],
    expected_blocked: dict[str, Any],
    expect_blocked: bool,
) -> list[dict[str, Any]]:
    readiness_details = readiness.get("blocker_details")
    readiness_details = readiness_details if isinstance(readiness_details, dict) else {}
    checklist: list[dict[str, Any]] = [
        {
            "id": "runtime_booted",
            "requirement": "Readiness and pilot go/no-go endpoints are reachable and not failed to boot.",
            "status": "pass" if health["status_ok"] and readiness["error"] is None and go_no_go["error"] is None else "fail",
            "artifacts": ["/api/health", "/api/readiness", "/api/pilot/go-no-go"],
            "evidence": {
                "health_status": health.get("status"),
                "readiness_error": readiness.get("error"),
                "go_no_go_error": go_no_go.get("error"),
            },
        },
        {
            "id": "exact_blocked_shape",
            "requirement": "Blocked state matches the expected pilot evidence/config gaps.",
            "status": (
                "pass"
                if expect_blocked and all(value is True for value in expected_blocked.get("checks", {}).values())
                else "not_checked"
            ),
            "artifacts": ["/api/readiness", "/api/pilot/go-no-go"],
            "evidence": {
                "unexpected_readiness_blockers": expected_blocked.get("unexpected_readiness_blockers", []),
                "unexpected_go_no_go_missing": expected_blocked.get("unexpected_go_no_go_missing", []),
            },
        },
    ]
    readiness_requirements = {
        "authenticated_ingress_deployment_verified": "authenticated ingress proof",
        "policy_lifecycle_signed": "signed policy lifecycle",
        "backup_restore_rehearsal_verified": "backup/restore rehearsal",
        "mesh_brain_artifact_uri_prefix_configured": "Mesh Brain artifact URI",
        "mesh_brain_artifact_upload_proof_verified": "Mesh Brain artifact upload proof",
        "mesh_brain_serving_backend_configured": "Mesh Brain serving backend",
        "run_export_retention_reviewed": "retention review",
        "design_partner_packet_verified": "design partner packet",
    }
    for blocker in expected_blocked.get("expected_readiness_blockers", DEFAULT_EXPECTED_READINESS_BLOCKERS):
        blocker_name = str(blocker)
        detail = readiness_details.get(blocker_name, {})
        checklist.append(
            {
                "id": f"readiness.{blocker_name}",
                "source_id": blocker_name,
                "requirement": readiness_requirements.get(blocker_name, blocker_name),
                "status": "blocked_expected" if blocker_name in readiness.get("blockers", []) else "pass",
                "artifacts": ["/api/readiness"],
                "evidence": {
                    "state_slice": detail.get("state_slice"),
                    "env": detail.get("env"),
                    "evidence_path": detail.get("evidence_path"),
                    "observed": detail.get("observed"),
                    "remediation": detail.get("remediation"),
                },
            }
        )
    missing_details = expected_blocked.get("go_no_go_missing_details")
    missing_details = missing_details if isinstance(missing_details, dict) else {}
    for item in expected_blocked.get("expected_go_no_go_missing", DEFAULT_EXPECTED_GO_NO_GO_MISSING):
        item_name = str(item)
        checklist.append(
            {
                "id": f"go_no_go.missing.{item_name}",
                "source_id": item_name,
                "requirement": _go_no_go_requirement_name(item_name),
                "status": "blocked_expected" if item_name in go_no_go.get("missing_evidence", []) else "pass",
                "artifacts": ["/api/pilot/go-no-go"],
                "evidence": missing_details.get(item_name, {}),
            }
        )
    observed_details = expected_blocked.get("go_no_go_observed_proof_details")
    observed_details = observed_details if isinstance(observed_details, dict) else {}
    for check_name in expected_blocked.get("expected_go_no_go_true_checks", DEFAULT_EXPECTED_GO_NO_GO_TRUE_CHECKS):
        name = str(check_name)
        checklist.append(
            {
                "id": f"go_no_go.observed.{name}",
                "source_id": name,
                "requirement": _go_no_go_requirement_name(name),
                "status": "pass" if name in observed_details else "fail",
                "artifacts": ["/api/pilot/go-no-go"],
                "evidence": observed_details.get(name, {}),
            }
        )
    checklist.append(
        {
            "id": "runtime_release_binding",
            "requirement": "release provenance and runtime commit/image binding",
            "status": "pass" if release["complete"] and runtime["build_commit_match"] and runtime["image_digest_match"] else "blocked_expected",
            "artifacts": ["/api/pilot/go-no-go.release_provenance", "/api/health"],
            "evidence": {
                "release_provenance": release,
                "runtime_binding": runtime,
            },
        }
    )
    return checklist


def _go_no_go_requirement_name(name: str) -> str:
    labels = {
        "readiness_green": "readiness green",
        "operator_approval_observed": "operator approval proof",
        "live_action_proof_observed": "live-action proof",
        "mesh_brain_artifact_upload_proof_verified": "Mesh Brain artifact upload proof",
        "release_provenance_complete": "release provenance",
        "on_call_drill_verified": "on-call drill proof",
        "denied_action_proof_observed": "denied-action proof",
        "mesh_brain_model_kernel_gate_observed": "Mesh Brain model kernel evidence",
        "mesh_brain_live_canary_smoke_observed": "Mesh Brain live canary evidence",
        "mesh_brain_single_crops_canary_lane_observed": "Mesh Brain single CROPS canary lane evidence",
        "mesh_brain_rollback_drill_observed": "Mesh Brain rollback drill evidence",
    }
    return labels.get(name, name)


def _checklist(checks: dict[str, bool]) -> list[dict[str, Any]]:
    rows = [
        ("live control plane health", "/api/health", ("health_status_ok",)),
        (
            "pilot readiness profile",
            "/api/readiness",
            ("readiness_profile_pilot", "readiness_ready", "readiness_blockers_empty"),
        ),
        (
            "pilot go/no-go packet",
            "/api/pilot/go-no-go",
            ("go_no_go_packet_version", "go_no_go_status_go", "go_no_go_missing_empty", "go_no_go_checks_passed"),
        ),
        (
            "release provenance packet",
            "/api/pilot/go-no-go.release_provenance",
            ("release_provenance_complete", "release_git_commit", "release_image_digest"),
        ),
        (
            "deployed runtime binding",
            "/api/health + release_provenance",
            (
                "runtime_build_commit",
                "runtime_image_digest",
                "runtime_build_commit_match",
                "runtime_image_digest_match",
                "runtime_expected_head_valid",
                "runtime_build_commit_matches_expected_head",
            ),
        ),
    ]
    return [
        {
            "requirement": requirement,
            "artifact": artifact,
            "checks": list(names),
            "status": "pass" if all(checks.get(name) is True for name in names) else "fail",
        }
        for requirement, artifact, names in rows
    ]


def _blocked_checklist(checks: dict[str, bool]) -> list[dict[str, Any]]:
    rows = [
        ("live control plane health", "/api/health", ("health_status_ok",)),
        (
            "pilot readiness blocked state",
            "/api/readiness",
            (
                "readiness_endpoint_ok",
                "readiness_profile_pilot",
                "readiness_status_blocked",
                "readiness_blockers_present",
                "expected_readiness_blockers_present",
                "unexpected_readiness_blockers_absent",
                "expected_readiness_blocker_details_present",
            ),
        ),
        (
            "pilot go/no-go blocked state",
            "/api/pilot/go-no-go",
            (
                "go_no_go_endpoint_ok",
                "go_no_go_packet_version",
                "go_no_go_status_blocked",
                "go_no_go_missing_present",
                "expected_go_no_go_missing_present",
                "unexpected_go_no_go_missing_absent",
                "expected_go_no_go_missing_details_present",
                "expected_go_no_go_true_checks_present",
                "expected_go_no_go_observed_proof_details_present",
            ),
        ),
    ]
    return [
        {
            "requirement": requirement,
            "artifact": artifact,
            "checks": list(names),
            "status": "pass" if all(checks.get(name) is True for name in names) else "fail",
        }
        for requirement, artifact, names in rows
    ]


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _compact_observed(value: Any) -> Any:
    if not isinstance(value, dict):
        return _json_ready(value)
    compact: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, list) and len(item) > 8:
            compact[str(key)] = {
                "count": len(item),
                "sample": _json_ready(item[:8]),
            }
        else:
            compact[str(key)] = _json_ready(item)
    return compact


def _string_or_none(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _normalized_git_commit(value: Any) -> str | None:
    candidate = value.strip() if isinstance(value, str) else ""
    if candidate in {"", "unknown"}:
        return None
    if len(candidate) not in {40, 64}:
        return None
    if any(char not in "0123456789abcdefABCDEF" for char in candidate):
        return None
    return candidate.lower()


def _normalized_digest(value: Any) -> str | None:
    candidate = value.strip() if isinstance(value, str) else ""
    if not candidate.startswith("sha256:"):
        return None
    tail = candidate[len("sha256:") :]
    if len(tail) != 64 or any(char not in "0123456789abcdefABCDEF" for char in tail):
        return None
    return "sha256:" + tail.lower()


if __name__ == "__main__":
    raise SystemExit(main())
