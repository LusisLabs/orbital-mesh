from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


REPEATABILITY_PROOF_SCHEMA = "repeatability-proof.schema.json"
REPEATABILITY_PROOF_VERSION = "mesh.repeatability_proof.v1"
REPEATABILITY_VERIFICATION_VERSION = "mesh.repeatability_verification.v1"


def load_repeatability_proof(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    proof_path = Path(path)
    if not proof_path.exists():
        return None
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    validate_payload(REPEATABILITY_PROOF_SCHEMA, payload)
    return payload


def verify_repeatability_proof(
    path: str | Path | None,
    *,
    expected_head: str | None = None,
    require_clean_env: bool = True,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    proof_path = Path(path) if path else None
    load_error: str | None = None
    try:
        proof = load_repeatability_proof(proof_path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        proof = None
        load_error = str(exc)

    resolved_expected_head = expected_head or _git_head(repo_root)
    checks = _proof_checks(proof, expected_head=resolved_expected_head, require_clean_env=require_clean_env)
    if proof is None:
        checks["proof_present"] = False
    if load_error:
        checks["schema_valid"] = False
    return {
        "schema_version": REPEATABILITY_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) else "fail",
        "proof_path": str(proof_path) if proof_path else None,
        "proof_id": proof.get("proof_id") if proof else None,
        "repo_head": proof.get("repo_head") if proof else None,
        "expected_head": resolved_expected_head,
        "image_digest": proof.get("image_digest") if proof else None,
        "run_ids": _run_ids(proof),
        "checks": checks,
        "error": load_error,
    }


def _proof_checks(
    proof: dict[str, Any] | None,
    *,
    expected_head: str | None,
    require_clean_env: bool,
) -> dict[str, bool]:
    if proof is None:
        return {
            "proof_present": False,
            "schema_valid": False,
            "head_present": False,
            "head_matches_expected": expected_head is None,
            "release_packet_matches_head": False,
            "working_tree_clean": not require_clean_env,
            "clean_env_recreated": not require_clean_env,
            "no_manual_env_surgery": False,
            "fresh_image_built": not require_clean_env,
            "image_digest_present": False,
            "release_packet_present": False,
            "no_stale_packet_reuse": False,
            "multiple_runs_recorded": False,
            "run_ids_unique": False,
            "all_runs_passed": False,
            "all_runs_have_artifacts": False,
            "commands_recorded": False,
            "all_commands_passed": False,
            "all_commands_have_artifacts": False,
        }
    run_ids = _run_ids(proof)
    commands = _list(proof.get("commands"))
    runs = _list(proof.get("runs"))
    return {
        "proof_present": True,
        "schema_valid": True,
        "head_present": bool(str(proof.get("repo_head") or "").strip()),
        "head_matches_expected": expected_head is None or proof.get("repo_head") == expected_head,
        "release_packet_matches_head": proof.get("release_packet_head") == proof.get("repo_head"),
        "working_tree_clean": proof.get("working_tree_clean") is True if require_clean_env else True,
        "clean_env_recreated": proof.get("clean_env_recreated") is True if require_clean_env else True,
        "no_manual_env_surgery": proof.get("manual_env_surgery") is False,
        "fresh_image_built": proof.get("fresh_image_built") is True if require_clean_env else True,
        "image_digest_present": str(proof.get("image_digest") or "").startswith("sha256:"),
        "release_packet_present": bool(str(proof.get("release_packet_ref") or "").strip())
        and bool(str(proof.get("release_packet_generated_at") or "").strip()),
        "no_stale_packet_reuse": proof.get("stale_packet_reused") is False,
        "multiple_runs_recorded": len(run_ids) >= 2,
        "run_ids_unique": bool(run_ids) and len(run_ids) == len(set(run_ids)),
        "all_runs_passed": bool(runs) and all(run.get("status") == "pass" for run in runs),
        "all_runs_have_artifacts": bool(runs)
        and all(bool(_strings(run.get("artifact_refs"))) for run in runs),
        "commands_recorded": bool(commands),
        "all_commands_passed": bool(commands) and all(command.get("status") == "pass" for command in commands),
        "all_commands_have_artifacts": bool(commands)
        and all(bool(_strings(command.get("artifact_refs"))) for command in commands),
    }


def _git_head(repo_root: str | Path | None) -> str | None:
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip() or None


def _run_ids(proof: dict[str, Any] | None) -> list[str]:
    if not proof:
        return []
    return [str(run.get("run_id")) for run in _list(proof.get("runs")) if isinstance(run, dict) and run.get("run_id")]


def _list(raw: Any) -> list[Any]:
    return raw if isinstance(raw, list) else []


def _strings(raw: Any) -> list[str]:
    return [str(item) for item in raw if str(item).strip()] if isinstance(raw, list) else []


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
