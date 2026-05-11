#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import urlopen


SCHEMA_VERSION = "mesh.pilot_clearance_audit.v1"


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
    args = parser.parse_args()

    result = verify_pilot_clearance(
        base_url=args.base_url,
        timeout_seconds=args.timeout_seconds,
        expected_head=args.expected_head,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"{result['status']}: {', '.join(result['missing']) or 'pilot clearance verified'}")
    return 0 if result["status"] == "pass" else 1


def verify_pilot_clearance(
    *,
    base_url: str,
    timeout_seconds: float = 30.0,
    requester: Callable[[str, float], dict[str, Any]] | None = None,
    expected_head: str = "",
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

    checks = {
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
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "fail",
        "base_url": normalized_base_url,
        "checks": checks,
        "missing": [name for name, passed in checks.items() if not passed],
        "checklist": _checklist(checks),
        "artifacts": {
            "health": health_record,
            "readiness": readiness_record,
            "go_no_go": go_no_go_record,
            "release_provenance": release,
            "runtime_binding": runtime_record,
        },
    }
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
    return {
        "url": "/api/readiness",
        "profile": _string_or_none(payload.get("profile")),
        "status": _string_or_none(payload.get("status")),
        "checked_at": _string_or_none(payload.get("checked_at")),
        "blockers": [str(item) for item in blockers],
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
        "error": _string_or_none(payload.get("error")),
    }


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


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


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
