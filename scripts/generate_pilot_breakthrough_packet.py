#!/usr/bin/env python3
"""Generate a reproducible production-pilot breakthrough packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from scripts import verify_pilot_clearance


SCHEMA_VERSION = "mesh.production_pilot_breakthrough_packet.v1"
DEFAULT_RUN_ID = "run_20260508T033245_ad9bd5ac"
PRODUCT_CLAIM = (
    "Mesh can execute a controlled production-pilot remediation loop with evidence-backed policy, bounded action, "
    "recovery feedback, Merkle/audit proof, and release-bound go/no-go clearance."
)
EXPANSION_ORDER = [
    "second service class",
    "real external incident provider",
    "real feature flag provider",
    "external audit sink",
    "multi-operator pilot",
    "longer-running watch mode",
    "production SLO/error-budget reporting",
]
DEFAULT_PILOT_SCOPE = {
    "workload": "search/semantic-search",
    "namespace": "search",
    "kubernetes_context": "mesh-compose",
    "service_class": "Kubernetes deployment",
    "operator_approval_path": (
        "operator identity with approver/launcher roles; Mesh policy/evaluation/admission gates before bounded live action"
    ),
    "allowed_action_class_for_drill": (
        "rollback_deployment on one allowlisted deployment with rollback metadata and recovery feedback"
    ),
}
RequestJson = Callable[[str, float, dict[str, str] | None], dict[str, Any]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="Repository root. Defaults to current directory.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8787", help="Control-plane base URL.")
    parser.add_argument("--timeout-seconds", type=float, default=30.0, help="HTTP request timeout.")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Closed-loop run id to summarize.")
    parser.add_argument("--proof-bundle", default="", help="Breakthrough proof bundle. Defaults to latest ready proof.")
    parser.add_argument("--chaos-summary", default="", help="Compose chaos summary. Defaults to latest summary.")
    parser.add_argument("--node-summary", default="", help="Node breakthrough summary. Defaults to latest summary.")
    parser.add_argument("--expected-head", default="", help="Expected git commit. Defaults to `git rev-parse HEAD`.")
    parser.add_argument(
        "--output-dir",
        default=".mesh-runtime-state/pilot-packets/production-pilot-breakthrough-latest",
        help="Directory where packet files are written.",
    )
    parser.add_argument(
        "--allow-release-bound-runtime",
        action="store_true",
        help="Do not require /api/health commit to equal current repo HEAD. Intended only for historical release-bound packets.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable result JSON.")
    args = parser.parse_args()

    result = generate_pilot_breakthrough_packet(
        repo_root=Path(args.repo_root),
        output_dir=Path(args.output_dir),
        base_url=args.base_url,
        timeout_seconds=args.timeout_seconds,
        run_id=args.run_id,
        proof_bundle=Path(args.proof_bundle) if args.proof_bundle else None,
        chaos_summary=Path(args.chaos_summary) if args.chaos_summary else None,
        node_summary=Path(args.node_summary) if args.node_summary else None,
        require_runtime_head=not args.allow_release_bound_runtime,
        current_head=args.expected_head.strip() or None,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"{result['status']}: {result['packet_path']}")
        if result["missing"]:
            print(f"missing: {', '.join(result['missing'])}")
    return 0 if result["status"] == "pass" else 1


def generate_pilot_breakthrough_packet(
    *,
    repo_root: Path,
    output_dir: Path,
    base_url: str,
    timeout_seconds: float,
    run_id: str,
    proof_bundle: Path | None = None,
    chaos_summary: Path | None = None,
    node_summary: Path | None = None,
    require_runtime_head: bool = True,
    requester: RequestJson | None = None,
    current_head: str | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = _resolve_output_dir(repo_root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_base_url = base_url.rstrip("/")
    fetch = requester or _request_json
    head = current_head or _git_output(repo_root, ["git", "rev-parse", "HEAD"])

    proof_path = _resolve_optional_path(repo_root, proof_bundle, repo_root / ".mesh-runtime-state/proofs", "breakthrough-proof-*.json")
    chaos_path = _resolve_optional_path(repo_root, chaos_summary, repo_root / ".mesh-runtime-state/compose-chaos", "summary-*.json")
    node_path = _resolve_optional_path(repo_root, node_summary, repo_root / ".mesh-runtime-state/node-breakthrough", "summary-*.json")

    clearance = verify_pilot_clearance.verify_pilot_clearance(
        base_url=normalized_base_url,
        timeout_seconds=timeout_seconds,
        requester=lambda url, timeout: fetch(url, timeout, None),
    )
    run_export = _safe_request(
        f"{normalized_base_url}/api/runs/{run_id}/export",
        timeout_seconds,
        fetch,
        {"X-Mesh-Operator": "mesh-compose-chaos", "X-Mesh-Roles": "viewer,launcher"},
    )

    health_path = _write_json(output_dir / "health-binding.json", _health_binding(clearance))
    pilot_path = _write_json(output_dir / "pilot-clearance.json", clearance)
    proof_summary = _proof_summary(repo_root, proof_path, current_head=head)
    proof_path_out = _write_json(output_dir / "breakthrough-proof-summary.json", proof_summary)
    chaos_path_out = _write_json(output_dir / "chaos-summary.json", _chaos_summary(repo_root, chaos_path))
    node_path_out = _write_json(output_dir / "node-summary.json", _node_summary(repo_root, node_path))
    run_path_out = _write_json(output_dir / "closed-loop-run-summary.json", _closed_loop_summary(run_export, run_id=run_id))

    component_paths = [health_path, pilot_path, proof_path_out, chaos_path_out, node_path_out, run_path_out]
    checks = _packet_checks(
        clearance=clearance,
        proof_summary=proof_summary,
        run_export=run_export,
        current_head=head,
        require_runtime_head=require_runtime_head,
    )
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) else "blocked",
        "missing": [name for name, passed in checks.items() if not passed],
        "checks": checks,
        "repo": {
            "head": head,
            "runtime_head_required": require_runtime_head,
        },
        "product_claim": PRODUCT_CLAIM,
        "claim_boundaries": [
            "This packet does not claim broad production autonomy.",
            "The runtime must be bound to a complete release provenance packet before pilot promotion.",
            "When runtime-head binding is required, /api/health commit must match the checked-out repo HEAD.",
        ],
        "pilot_scope": DEFAULT_PILOT_SCOPE,
        "evidence_files": [
            {
                "path": _display_path(repo_root, path),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in component_paths
        ],
        "commands": _commands(
            normalized_base_url,
            run_id,
            proof_path,
            chaos_path,
            node_path,
            output_dir,
            timeout_seconds=timeout_seconds,
        ),
        "regression_guard": {
            "ci_job": "breakthrough-proof-replay",
            "ci_scope": "focused replay tests, focused ruff, syntax compilation, and packet generator tests",
            "live_gate": "live breakthrough proof plus pilot clearance before promotion",
        },
        "expansion_order": EXPANSION_ORDER,
    }
    packet_path = _write_json(output_dir / "packet.json", packet)
    return {
        "schema_version": "mesh.production_pilot_breakthrough_packet_generation.v1",
        "status": packet["status"],
        "missing": packet["missing"],
        "packet_path": _display_path(repo_root, packet_path),
        "output_dir": _display_path(repo_root, output_dir),
        "files": [_display_path(repo_root, path) for path in [*component_paths, packet_path]],
    }


def _request_json(url: str, timeout_seconds: float, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("endpoint returned non-object JSON")
    return payload


def _safe_request(
    url: str,
    timeout_seconds: float,
    requester: RequestJson,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        return requester(url, timeout_seconds, headers)
    except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}


def _health_binding(clearance: dict[str, Any]) -> dict[str, Any]:
    artifacts = clearance.get("artifacts") if isinstance(clearance.get("artifacts"), dict) else {}
    health = artifacts.get("health") if isinstance(artifacts.get("health"), dict) else {}
    runtime = artifacts.get("runtime_binding") if isinstance(artifacts.get("runtime_binding"), dict) else {}
    return {
        "schema_version": "mesh.health_binding_capture.v1",
        "captured_at": _timestamp(),
        "source_endpoint": "/api/health",
        "health": health,
        "runtime_binding": runtime,
        "checks": {
            "status_ok": health.get("status_ok") is True,
            "build_commit_match": runtime.get("build_commit_match") is True,
            "image_digest_match": runtime.get("image_digest_match") is True,
        },
    }


def _proof_summary(repo_root: Path, path: Path, *, current_head: str | None) -> dict[str, Any]:
    proof = _load_json(path)
    replay_reports = proof.get("replay", {}).get("reports", []) if isinstance(proof.get("replay"), dict) else []
    summary_checks = proof.get("summary_checks") if isinstance(proof.get("summary_checks"), list) else []
    validation = proof.get("validation_commands") if isinstance(proof.get("validation_commands"), list) else []
    git_record = proof.get("git") if isinstance(proof.get("git"), dict) else {}
    return {
        "schema_version": "mesh.breakthrough_proof_summary.v1",
        "source_path": _display_path(repo_root, path),
        "source_sha256": _sha256(path),
        "bundle_sha256": proof.get("bundle_sha256"),
        "git": git_record,
        "current_head": current_head,
        "checks": {
            "ready": (proof.get("breakthrough_proof") or {}).get("ready") is True,
            "replay_passed": (proof.get("replay") or {}).get("passed") is True,
            "git_dirty_false": git_record.get("dirty") is False,
            "git_commit_matches_head": bool(current_head and git_record.get("commit") == current_head),
            "summary_checks_ready": bool(summary_checks) and all(item.get("ready") is True for item in summary_checks),
            "validation_commands_passed": bool(validation) and all(item.get("passed") is True for item in validation),
        },
        "replay_reports": [{"kind": item.get("kind"), "passed": item.get("passed")} for item in replay_reports],
        "summary_checks": [
            {"kind": item.get("kind"), "ready": item.get("ready"), "coverage_checks": item.get("coverage_checks")}
            for item in summary_checks
        ],
        "validation_commands": [
            {
                "command": item.get("command"),
                "passed": item.get("passed"),
                "exit_code": item.get("exit_code"),
                "output_sha256": item.get("output_sha256"),
            }
            for item in validation
        ],
    }


def _chaos_summary(repo_root: Path, path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else {}
    events_path = _resolve_event_path(repo_root, path, payload.get("events_path"))
    return {
        "schema_version": "mesh.chaos_breakthrough_evidence_summary.v1",
        "source_path": _display_path(repo_root, path),
        "source_sha256": _sha256(path),
        "generated_at": payload.get("generated_at"),
        "events_path": _display_path(repo_root, events_path),
        "events_sha256": _sha256(events_path),
        "experiments_total": payload.get("experiments_total"),
        "experiments_passed": payload.get("experiments_passed"),
        "metrics": payload.get("metrics"),
        "breakthrough_probe": payload.get("breakthrough_probe"),
        "capability_axis_counts": _axis_counts(capabilities),
        "substrate_coverage": payload.get("substrate_coverage"),
        "multi_fault_coverage": payload.get("multi_fault_coverage"),
    }


def _node_summary(repo_root: Path, path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else {}
    events_path = _resolve_event_path(repo_root, path, payload.get("events_path"))
    return {
        "schema_version": "mesh.production_node_breakthrough_evidence_summary.v1",
        "source_path": _display_path(repo_root, path),
        "source_sha256": _sha256(path),
        "generated_at": payload.get("generated_at"),
        "events_path": _display_path(repo_root, events_path),
        "events_sha256": _sha256(events_path),
        "experiments_total": payload.get("experiments_total"),
        "experiments_passed": payload.get("experiments_passed"),
        "metrics": payload.get("metrics"),
        "breakthrough_probe": payload.get("breakthrough_probe"),
        "capability_axis_counts": _axis_counts(capabilities),
    }


def _closed_loop_summary(run_export: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    artifacts = run_export.get("artifacts") if isinstance(run_export.get("artifacts"), dict) else {}
    decision = artifacts.get("decision") if isinstance(artifacts.get("decision"), dict) else {}
    execution = artifacts.get("execution") if isinstance(artifacts.get("execution"), dict) else {}
    feedback = artifacts.get("feedback") if isinstance(artifacts.get("feedback"), dict) else {}
    operator = artifacts.get("operator") if isinstance(artifacts.get("operator"), dict) else {}
    admission = artifacts.get("run_admission") if isinstance(artifacts.get("run_admission"), dict) else {}
    trigger = artifacts.get("trigger") if isinstance(artifacts.get("trigger"), dict) else {}
    merkle = run_export.get("merkle") if isinstance(run_export.get("merkle"), dict) else {}
    return {
        "schema_version": "mesh.closed_loop_run_summary.v1",
        "run_id": run_export.get("run_id") or run_id,
        "source_endpoint": f"/api/runs/{run_id}/export",
        "status": run_export.get("status"),
        "stage": run_export.get("stage"),
        "scenario_key": run_export.get("scenario_key"),
        "event_count": run_export.get("event_count"),
        "events_truncated": run_export.get("events_truncated"),
        "latest_event_id": run_export.get("latest_event_id"),
        "latest_event_sequence": run_export.get("latest_event_sequence"),
        "latest_merkle_root": run_export.get("latest_merkle_root"),
        "merkle": {
            "run_id": merkle.get("run_id"),
            "leaf_count": merkle.get("leaf_count"),
            "root_hash": merkle.get("root_hash"),
        },
        "trigger": {
            "trigger_id": trigger.get("trigger_id"),
            "trigger_type": trigger.get("trigger_type"),
            "service": trigger.get("service"),
        },
        "run_admission": {
            "schema_version": admission.get("schema_version"),
            "decision": admission.get("decision"),
            "blockers": admission.get("blockers"),
            "target_lock_key": admission.get("target_lock_key"),
        },
        "operator": {
            "operator_id": operator.get("operator_id"),
            "roles": operator.get("roles"),
        },
        "decision": {
            "decision_id": decision.get("decision_id"),
            "decision_type": decision.get("decision_type"),
            "autonomy_tier": decision.get("autonomy_tier"),
            "confidence": decision.get("confidence"),
            "execution_plan": decision.get("execution_plan"),
            "risk": decision.get("risk"),
        },
        "execution": {
            "execution_id": execution.get("execution_id"),
            "status": execution.get("status"),
            "executor": execution.get("executor"),
            "applied_action": execution.get("applied_action"),
            "idempotency_key": execution.get("idempotency_key"),
            "failure": execution.get("failure"),
            "external_refs": execution.get("external_refs"),
        },
        "feedback": {
            "feedback_id": feedback.get("feedback_id"),
            "outcome": feedback.get("outcome"),
            "metric_comparison": feedback.get("metric_comparison"),
            "prediction_accuracy": feedback.get("prediction_accuracy"),
            "recommended_follow_up": feedback.get("recommended_follow_up"),
            "world_model_updates": feedback.get("world_model_updates"),
        },
        "error": run_export.get("error"),
    }


def _packet_checks(
    *,
    clearance: dict[str, Any],
    proof_summary: dict[str, Any],
    run_export: dict[str, Any],
    current_head: str | None,
    require_runtime_head: bool,
) -> dict[str, bool]:
    proof_checks = proof_summary.get("checks") if isinstance(proof_summary.get("checks"), dict) else {}
    artifacts = clearance.get("artifacts") if isinstance(clearance.get("artifacts"), dict) else {}
    runtime = artifacts.get("runtime_binding") if isinstance(artifacts.get("runtime_binding"), dict) else {}
    decision = _nested(run_export, "artifacts", "decision")
    execution_plan = decision.get("execution_plan") if isinstance(decision, dict) else {}
    parameters = execution_plan.get("parameters") if isinstance(execution_plan, dict) else {}
    feedback = _nested(run_export, "artifacts", "feedback")
    operator = _nested(run_export, "artifacts", "operator")
    roles = operator.get("roles") if isinstance(operator.get("roles"), list) else []
    metric_comparison = feedback.get("metric_comparison") if isinstance(feedback, dict) else {}
    runtime_head_match = bool(current_head and runtime.get("build_commit") == current_head)
    return {
        "pilot_clearance_pass": clearance.get("status") == "pass",
        "proof_ready": proof_checks.get("ready") is True,
        "proof_replay_passed": proof_checks.get("replay_passed") is True,
        "proof_git_clean": proof_checks.get("git_dirty_false") is True,
        "proof_git_commit_matches_head": proof_checks.get("git_commit_matches_head") is True,
        "proof_validation_commands_passed": proof_checks.get("validation_commands_passed") is True,
        "runtime_build_commit_matches_head": runtime_head_match if require_runtime_head else True,
        "closed_loop_run_completed": run_export.get("status") == "completed",
        "closed_loop_scope_workload": run_export.get("scenario_key") == "live_kubernetes:search/semantic-search",
        "closed_loop_scope_namespace": parameters.get("namespace") == "search",
        "closed_loop_action_class": execution_plan.get("action") == "rollback_deployment",
        "closed_loop_operator_path": bool(roles),
        "closed_loop_feedback_successful": feedback.get("outcome") == "successful" if isinstance(feedback, dict) else False,
        "closed_loop_rollback_verified": metric_comparison.get("rollout_status") == "healthy",
    }


def _commands(
    base_url: str,
    run_id: str,
    proof_path: Path,
    chaos_path: Path,
    node_path: Path,
    output_dir: Path,
    *,
    timeout_seconds: float,
) -> dict[str, str]:
    timeout_value = f"{timeout_seconds:g}"
    return {
        "packet_generation": (
            "scripts/generate_pilot_breakthrough_packet.py "
            f"--base-url {base_url} --timeout-seconds {timeout_value} --run-id {run_id} --proof-bundle {proof_path} "
            f"--chaos-summary {chaos_path} --node-summary {node_path} --output-dir {output_dir} --json"
        ),
        "pilot_clearance": (
            f"scripts/verify_pilot_clearance.py --base-url {base_url} --timeout-seconds {timeout_value} --json"
        ),
        "branch_tip_replay_proof": "scripts/run_breakthrough_proof.sh --replay-only",
        "run_export": f"GET /api/runs/{run_id}/export with X-Mesh-Operator and X-Mesh-Roles headers",
        "live_gate_before_pilot_promotion": (
            "scripts/run_breakthrough_proof.sh && "
            f"scripts/verify_pilot_clearance.py --base-url {base_url} --timeout-seconds {timeout_value} --json"
        ),
    }


def _axis_counts(capabilities: dict[str, Any]) -> dict[str, int]:
    return {
        "known": len(capabilities.get("known_axes") or []),
        "passed": len(capabilities.get("passed_axes") or []),
        "missing": len(capabilities.get("missing_axes") or []),
        "failed_or_unproven": len(capabilities.get("failed_or_unproven_axes") or []),
    }


def _resolve_optional_path(repo_root: Path, value: Path | None, directory: Path, pattern: str) -> Path:
    if value is not None:
        return _resolve_existing(repo_root, value)
    candidates = sorted(directory.glob(pattern))
    if not candidates:
        raise SystemExit(f"no files match {directory / pattern}")
    return candidates[-1].resolve()


def _resolve_existing(repo_root: Path, value: Path) -> Path:
    path = value if value.is_absolute() else repo_root / value
    path = path.resolve()
    if not path.exists():
        raise SystemExit(f"required file not found: {path}")
    return path


def _resolve_output_dir(repo_root: Path, output_dir: Path) -> Path:
    return output_dir if output_dir.is_absolute() else repo_root / output_dir


def _resolve_event_path(repo_root: Path, summary_path: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise SystemExit(f"{summary_path} does not include events_path")
    path = Path(value)
    path = path if path.is_absolute() else repo_root / path
    if path.exists():
        return path.resolve()
    sibling = summary_path.with_name(Path(value).name)
    if sibling.exists():
        return sibling.resolve()
    raise SystemExit(f"events file not found for {summary_path}: {value}")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"{path} did not contain a JSON object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _display_path(repo_root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root))
    except ValueError:
        return str(path)


def _git_output(repo_root: Path, command: list[str]) -> str | None:
    try:
        return subprocess.check_output(command, cwd=repo_root, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
