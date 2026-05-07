#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify and materialize runtime metadata that binds a release packet to a deployed control plane."
    )
    parser.add_argument(
        "--release-provenance",
        default="",
        help="Path to a complete mesh.release_provenance.v1 packet. Defaults to MESH_RELEASE_PROVENANCE_PATH.",
    )
    parser.add_argument(
        "--runtime-release-provenance-path",
        default="",
        help="Container-readable MESH_RELEASE_PROVENANCE_PATH to write into --env-output. Defaults to --release-provenance.",
    )
    parser.add_argument("--image-ref", default="", help="Optional local Docker image ref to compare with the packet digest.")
    parser.add_argument("--health-url", default="", help="Optional /api/health URL to compare with the packet commit and digest.")
    parser.add_argument("--timeout-seconds", type=float, default=10.0, help="Timeout for --health-url.")
    parser.add_argument("--env-output", default="", help="Write a dotenv file for runtime release binding.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable result JSON.")
    args = parser.parse_args()

    release_path = args.release_provenance or _env("MESH_RELEASE_PROVENANCE_PATH")
    if not release_path:
        result = _failure(["release_provenance_path"], release_path="")
    else:
        result = verify_release_runtime_binding(
            release_provenance=Path(release_path),
            runtime_release_provenance_path=args.runtime_release_provenance_path or release_path,
            image_ref=args.image_ref,
            health_url=args.health_url,
            timeout_seconds=args.timeout_seconds,
        )

    if args.env_output and result["status"] == "pass":
        _write_env_output(Path(args.env_output), result["runtime_env"])

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"{result['status']}: {', '.join(result['missing']) or 'release runtime binding verified'}")
    return 0 if result["status"] == "pass" else 1


def verify_release_runtime_binding(
    *,
    release_provenance: Path,
    runtime_release_provenance_path: str,
    image_ref: str = "",
    health_url: str = "",
    timeout_seconds: float = 10.0,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    result = _base_result(release_provenance, runtime_release_provenance_path)
    payload = _load_json(release_provenance)
    if payload is None:
        result["missing"].append("release_provenance_json")
        return _finalize(result)

    release = _release_record(payload)
    result["release"] = release
    result["checks"].update(release["checks"])
    result["missing"].extend(release["missing"])
    if release["checks"]["release_git_commit"]:
        result["runtime_env"]["MESH_BUILD_COMMIT"] = release["git_commit"]
    if release["checks"]["release_image_digest"]:
        result["runtime_env"]["MESH_BUILD_IMAGE_DIGEST"] = release["image_digest"]

    if image_ref:
        image = _image_ref_record(image_ref, release.get("image_digest"), runner=runner or _run)
        result["image_ref"] = image
        result["checks"]["image_ref_digest_match"] = image["digest_match"]
        if not image["digest_match"]:
            result["missing"].append("image_ref_digest_match")

    if health_url:
        health = _health_record(
            health_url=health_url,
            expected_commit=release.get("git_commit"),
            expected_digest=release.get("image_digest"),
            timeout_seconds=timeout_seconds,
        )
        result["health"] = health
        result["checks"]["runtime_build_commit_match"] = health["commit_match"]
        result["checks"]["runtime_image_digest_match"] = health["image_digest_match"]
        if not health["commit_match"]:
            result["missing"].append("runtime_build_commit_match")
        if not health["image_digest_match"]:
            result["missing"].append("runtime_image_digest_match")

    return _finalize(result)


def _base_result(release_provenance: Path, runtime_release_provenance_path: str) -> dict[str, Any]:
    return {
        "schema_version": "mesh.release_runtime_binding.v1",
        "generated_at": _timestamp(),
        "status": "fail",
        "release_provenance_path": str(release_provenance),
        "runtime_env": {
            "MESH_RELEASE_PROVENANCE_PATH": runtime_release_provenance_path,
        },
        "checks": {},
        "missing": [],
    }


def _release_record(payload: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "schema_version": payload.get("schema_version") == "mesh.release_provenance.v1",
        "release_provenance_complete": payload.get("status") == "complete",
        "release_provenance_missing_empty": payload.get("missing") == [],
        "release_provenance_checks": _embedded_checks_pass(payload),
        "ci_attestation_sha_matches_git_commit": _ci_sha_matches_git_commit(payload),
        "release_git_commit": bool(_normalized_git_commit(_nested(payload, "git", "commit"))),
        "release_image_digest": bool(_normalized_digest(_nested(payload, "image", "digest"))),
    }
    missing = [name for name, passed in checks.items() if not passed]
    return {
        "packet_sha256": _string_or_none(payload.get("packet_sha256")),
        "git_commit": _normalized_git_commit(_nested(payload, "git", "commit")),
        "image_digest": _normalized_digest(_nested(payload, "image", "digest")),
        "checks": checks,
        "missing": missing,
    }


def _embedded_checks_pass(payload: dict[str, Any]) -> bool:
    raw_checks = payload.get("checks")
    if not isinstance(raw_checks, dict) or not raw_checks:
        return False
    return all(value is True for value in raw_checks.values())


def _ci_sha_matches_git_commit(payload: dict[str, Any]) -> bool:
    attestation = _nested(payload, "ci", "attestation")
    if not isinstance(attestation, dict):
        return False
    return attestation.get("sha_matches_git_commit") is True


def _image_ref_record(
    image_ref: str,
    expected_digest: Any,
    *,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    expected = _normalized_digest(expected_digest)
    try:
        payload = _docker_image_inspect(image_ref, runner=runner)
    except RuntimeError as exc:
        return {
            "image_ref": image_ref,
            "error": str(exc),
            "digest_candidates": [],
            "digest_match": False,
        }
    candidates = _image_digest_candidates(payload)
    return {
        "image_ref": image_ref,
        "image_id": _normalized_digest(payload.get("Id")),
        "repo_digests": [item for item in payload.get("RepoDigests", []) if isinstance(item, str)],
        "digest_candidates": candidates,
        "digest_match": bool(expected and expected in candidates),
    }


def _docker_image_inspect(
    image_ref: str,
    *,
    runner: Callable[[list[str]], subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    result = runner(["docker", "image", "inspect", image_ref])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"docker image inspect failed for {image_ref}")
    payload = json.loads(result.stdout)
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise RuntimeError(f"docker image inspect returned invalid payload for {image_ref}")
    return payload[0]


def _image_digest_candidates(payload: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    image_id = _normalized_digest(payload.get("Id"))
    if image_id:
        candidates.append(image_id)
    repo_digests = payload.get("RepoDigests")
    if isinstance(repo_digests, list):
        for item in repo_digests:
            if not isinstance(item, str) or "@sha256:" not in item:
                continue
            digest = _normalized_digest(item.split("@", 1)[1])
            if digest:
                candidates.append(digest)
    return _dedupe(candidates)


def _health_record(
    *,
    health_url: str,
    expected_commit: Any,
    expected_digest: Any,
    timeout_seconds: float,
) -> dict[str, Any]:
    expected_runtime_commit = _normalized_git_commit(expected_commit)
    expected_runtime_digest = _normalized_digest(expected_digest)
    try:
        with urlopen(health_url, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return {
            "url": health_url,
            "error": str(exc),
            "commit": None,
            "image_digest": None,
            "commit_match": False,
            "image_digest_match": False,
        }
    if not isinstance(payload, dict):
        payload = {}
    commit = _normalized_git_commit(payload.get("commit"))
    digest = _normalized_digest(payload.get("image_digest"))
    return {
        "url": health_url,
        "commit": commit,
        "image_digest": digest,
        "commit_match": bool(expected_runtime_commit and commit == expected_runtime_commit),
        "image_digest_match": bool(expected_runtime_digest and digest == expected_runtime_digest),
    }


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_env_output(path: Path, runtime_env: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in runtime_env.items() if isinstance(value, str) and value]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _finalize(result: dict[str, Any]) -> dict[str, Any]:
    result["missing"] = _dedupe([str(item) for item in result.get("missing", [])])
    result["status"] = "pass" if not result["missing"] else "fail"
    return result


def _failure(missing: list[str], *, release_path: str) -> dict[str, Any]:
    result = _base_result(Path(release_path), release_path)
    result["missing"] = missing
    return _finalize(result)


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


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=REPO_ROOT, check=False, capture_output=True, text=True)


def _env(name: str) -> str:
    import os

    return os.getenv(name, "")


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
