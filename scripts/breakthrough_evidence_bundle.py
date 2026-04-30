#!/usr/bin/env python3
"""Build a hashed breakthrough evidence bundle with replay validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, cast

from scripts import compose_chaos_session
from scripts import production_node_breakthrough_session as node_session
from services.pipeline import FirstSlicePipeline
from shared.mesh_runtime.config import RuntimeConfig
from tests.e2e.chaos.portfolio import select_by_name


@dataclass(frozen=True)
class EvidenceInput:
    kind: str
    path: Path


def main() -> int:
    args = _parse_args()
    repo_root = Path(args.repo_root).resolve()
    output_root = Path(args.output_dir)
    if not output_root.is_absolute():
        output_root = repo_root / output_root
    output_root.mkdir(parents=True, exist_ok=True)

    evidence = discover_evidence(repo_root, args)
    validation_commands = [] if args.skip_validation_commands else _validation_commands(args.validation_command)
    bundle = build_bundle(repo_root, evidence, validation_commands=validation_commands)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_root / f"breakthrough-proof-{stamp}.json"
    output_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "event": "breakthrough_evidence_bundle_written",
        "output": str(output_path),
        "ready": bundle["breakthrough_proof"]["ready"],
        "bundle_sha256": bundle["bundle_sha256"],
    }, sort_keys=True))
    return 0 if bundle["breakthrough_proof"]["ready"] else 1


def discover_evidence(repo_root: Path, args: argparse.Namespace) -> list[EvidenceInput]:
    compose_summary = _resolve_optional(
        repo_root,
        args.compose_summary,
        lambda: _latest(repo_root / ".mesh-runtime-state/compose-chaos", "summary-*.json"),
    )
    compose_events = _resolve_optional(
        repo_root,
        args.compose_events,
        lambda: _events_path_from_summary(repo_root, compose_summary),
    )
    config_drift_proof = _resolve_optional(
        repo_root,
        args.config_drift_proof,
        lambda: _latest(repo_root / ".mesh-runtime-state/compose-chaos", "config-drift-proof-*.json"),
    )
    node_summary = _resolve_optional(
        repo_root,
        args.node_summary,
        lambda: _latest(repo_root / ".mesh-runtime-state/node-breakthrough", "summary-*.json"),
    )
    node_events = _resolve_optional(
        repo_root,
        args.node_events,
        lambda: _events_path_from_summary(repo_root, node_summary),
    )

    return [
        EvidenceInput("compose_summary", compose_summary),
        EvidenceInput("compose_events", compose_events),
        EvidenceInput("config_drift_proof", config_drift_proof),
        EvidenceInput("node_summary", node_summary),
        EvidenceInput("node_events", node_events),
    ]


def build_bundle(
    repo_root: Path,
    evidence: list[EvidenceInput],
    *,
    validation_commands: list[list[str]] | None = None,
) -> dict[str, Any]:
    evidence_by_kind = {item.kind: item.path for item in evidence}
    manifest = [_manifest_entry(repo_root, item) for item in evidence]
    compose_replay = replay_compose_events(evidence_by_kind["compose_events"])
    config_drift_replay = replay_config_drift_proof(evidence_by_kind["config_drift_proof"])
    node_replay = replay_node_events(evidence_by_kind["node_events"])
    summary_checks = [
        _summary_check("compose", evidence_by_kind["compose_summary"]),
        _summary_check("node", evidence_by_kind["node_summary"]),
    ]
    validation_results = run_validation_commands(repo_root, validation_commands or [])
    replay_reports = [compose_replay, config_drift_replay, node_replay]
    proof_ready = (
        all(entry["exists"] and entry["sha256"] for entry in manifest)
        and all(report["passed"] for report in replay_reports)
        and all(check["ready"] for check in summary_checks)
        and all(result["passed"] for result in validation_results)
    )
    body = {
        "schema_version": "mesh.breakthrough_evidence_bundle.v1",
        "generated_at": _now(),
        "git": {
            "commit": _git_commit(repo_root),
            "dirty": _git_dirty(repo_root),
        },
        "evidence_manifest": manifest,
        "summary_checks": summary_checks,
        "replay": {
            "reports": replay_reports,
            "passed": all(report["passed"] for report in replay_reports),
        },
        "validation_commands": validation_results,
        "breakthrough_proof": {
            "ready": proof_ready,
            "status": "regression_protected_breakthrough" if proof_ready else "evidence_incomplete",
        },
    }
    body["bundle_sha256"] = _canonical_sha256(body)
    return body


def replay_compose_events(events_path: Path) -> dict[str, Any]:
    events = _read_jsonl(events_path)
    comparisons: list[dict[str, Any]] = []
    for event in events:
        experiment_name = event.get("experiment")
        if not isinstance(experiment_name, str):
            comparisons.append({"event": event.get("event"), "passed": False, "reason": "missing_experiment"})
            continue
        experiment = select_by_name(experiment_name)
        actual = cast(dict[str, Any], event.get("score")) if isinstance(event.get("score"), dict) else {}
        replayed = compose_chaos_session._score_event(experiment, event)  # noqa: SLF001 - replay validates harness contract.
        comparisons.append({
            "experiment": experiment_name,
            "passed": _score_subset_matches(actual, replayed),
            "recorded": _score_signature(actual),
            "replayed": _score_signature(replayed),
        })
    return {
        "kind": "compose_chaos_score_replay",
        "events_path": str(events_path),
        "events_total": len(events),
        "events_passed": sum(1 for item in comparisons if item.get("passed") is True),
        "passed": bool(comparisons) and all(item.get("passed") is True for item in comparisons),
        "comparisons": comparisons,
    }


def replay_config_drift_proof(proof_path: Path) -> dict[str, Any]:
    event = _read_json(proof_path)
    experiment_name = event.get("experiment")
    if experiment_name != "config_drift":
        return {
            "kind": "config_drift_score_replay",
            "proof_path": str(proof_path),
            "passed": False,
            "reason": "proof_is_not_config_drift",
        }
    replayed = compose_chaos_session._score_event(select_by_name("config_drift"), event)  # noqa: SLF001
    actual = cast(dict[str, Any], event.get("score")) if isinstance(event.get("score"), dict) else {}
    passed = _score_subset_matches(actual, replayed)
    return {
        "kind": "config_drift_score_replay",
        "proof_path": str(proof_path),
        "passed": passed,
        "recorded": _score_signature(actual),
        "replayed": _score_signature(replayed),
        "capability_axes": event.get("capability_axes", []),
    }


def replay_node_events(events_path: Path) -> dict[str, Any]:
    recorded_events = {event.get("probe"): event for event in _read_jsonl(events_path)}
    pipeline = FirstSlicePipeline(config=RuntimeConfig(
        evaluation_mode="native",
        orchestration_mode="native",
        state_directory="/tmp/mesh-node-breakthrough-replay-state",
    ))
    comparisons: list[dict[str, Any]] = []
    for probe in node_session.default_probes():
        recorded = recorded_events.get(probe.name)
        if not isinstance(recorded, dict):
            comparisons.append({"probe": probe.name, "passed": False, "reason": "missing_recorded_event"})
            continue
        result = pipeline.run(deepcopy(probe.signal_payload))
        decision = result.get("decision") or {}
        trigger = result.get("trigger") or {}
        replayed_event = {
            "mesh_run": {
                "trigger_type": trigger.get("trigger_type"),
                "decision_type": decision.get("decision_type"),
                "execution_system": (decision.get("execution_plan") or {}).get("system"),
                "execution_action": (decision.get("execution_plan") or {}).get("action"),
                "autonomy_tier": decision.get("autonomy_tier"),
            }
        }
        replayed_event["score"] = node_session.score_event(probe, replayed_event)
        comparisons.append({
            "probe": probe.name,
            "passed": (
                _node_signature(recorded) == _node_signature(replayed_event)
                and sorted(recorded.get("capability_axes", [])) == sorted(probe.capability_axes)
            ),
            "capability_axes": sorted(probe.capability_axes),
            "recorded": _node_signature(recorded),
            "replayed": _node_signature(replayed_event),
        })
    return {
        "kind": "production_node_pipeline_replay",
        "events_path": str(events_path),
        "events_total": len(comparisons),
        "events_passed": sum(1 for item in comparisons if item.get("passed") is True),
        "passed": bool(comparisons) and all(item.get("passed") is True for item in comparisons),
        "comparisons": comparisons,
    }


def _score_subset_matches(actual: dict[str, Any], replayed: dict[str, Any]) -> bool:
    return _score_signature(actual) == _score_signature(replayed)


def _score_signature(score: dict[str, Any]) -> dict[str, Any]:
    return {
        "passed": score.get("passed"),
        "reason": score.get("reason"),
        "trigger_fired": score.get("trigger_fired"),
        "decision_type": score.get("decision_type"),
    }


def _node_signature(event: dict[str, Any]) -> dict[str, Any]:
    mesh_run = cast(dict[str, Any], event.get("mesh_run")) if isinstance(event.get("mesh_run"), dict) else {}
    score = cast(dict[str, Any], event.get("score")) if isinstance(event.get("score"), dict) else {}
    return {
        "trigger_type": mesh_run.get("trigger_type"),
        "decision_type": mesh_run.get("decision_type"),
        "execution_system": mesh_run.get("execution_system"),
        "execution_action": mesh_run.get("execution_action"),
        "autonomy_tier": mesh_run.get("autonomy_tier"),
        "score": {
            "passed": score.get("passed"),
            "reason": score.get("reason"),
            "decision_type": score.get("decision_type"),
        },
    }


def _summary_check(kind: str, summary_path: Path) -> dict[str, Any]:
    summary = _read_json(summary_path)
    probe = (
        cast(dict[str, Any], summary.get("breakthrough_probe"))
        if isinstance(summary.get("breakthrough_probe"), dict)
        else {}
    )
    metrics = cast(dict[str, Any], summary.get("metrics")) if isinstance(summary.get("metrics"), dict) else {}
    return {
        "kind": kind,
        "summary_path": str(summary_path),
        "schema_version": summary.get("schema_version"),
        "ready": probe.get("ready") is True,
        "status": probe.get("status"),
        "metrics": metrics,
    }


def run_validation_commands(repo_root: Path, commands: list[list[str]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                cwd=repo_root,
                env={
                    **os.environ,
                    "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", "/tmp/uv-cache"),
                    "UV_TOOL_DIR": os.environ.get("UV_TOOL_DIR", "/tmp/uv-tools"),
                    "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
                    "MYPY_CACHE_DIR": os.environ.get("MYPY_CACHE_DIR", "/tmp/mypy-cache"),
                },
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            stdout = completed.stdout[-12000:]
            stderr = completed.stderr[-12000:]
            results.append({
                "command": command,
                "exit_code": completed.returncode,
                "passed": completed.returncode == 0,
                "stdout": stdout,
                "stderr": stderr,
                "output_sha256": hashlib.sha256((completed.stdout + completed.stderr).encode("utf-8")).hexdigest(),
            })
        except subprocess.TimeoutExpired as exc:
            results.append({
                "command": command,
                "exit_code": None,
                "passed": False,
                "stdout": (exc.stdout or "")[-12000:] if isinstance(exc.stdout, str) else "",
                "stderr": (exc.stderr or "")[-12000:] if isinstance(exc.stderr, str) else "",
                "timed_out": True,
                "output_sha256": None,
            })
        except OSError as exc:
            results.append({
                "command": command,
                "exit_code": None,
                "passed": False,
                "stdout": "",
                "stderr": repr(exc),
                "output_sha256": None,
            })
    return results


def _manifest_entry(repo_root: Path, item: EvidenceInput) -> dict[str, Any]:
    data = item.path.read_bytes()
    payload: dict[str, Any] | None = None
    if item.path.suffix == ".json":
        payload = json.loads(data.decode("utf-8"))
    return {
        "kind": item.kind,
        "path": _display_path(repo_root, item.path),
        "exists": item.path.exists(),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "schema_version": payload.get("schema_version") if isinstance(payload, dict) else None,
    }


def _events_path_from_summary(repo_root: Path, summary_path: Path) -> Path:
    summary = _read_json(summary_path)
    events_path = summary.get("events_path")
    if not isinstance(events_path, str) or not events_path:
        raise SystemExit(f"{summary_path} does not include events_path")
    try:
        return _resolve_path(repo_root, events_path)
    except SystemExit:
        sibling = summary_path.with_name(Path(events_path).name)
        if sibling.exists():
            return sibling.resolve()
        raise


def _resolve_optional(repo_root: Path, value: str | None, fallback: Callable[[], Path]) -> Path:
    if value:
        return _resolve_path(repo_root, value)
    return fallback()


def _resolve_path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = repo_root / path
    path = path.resolve()
    if not path.exists():
        raise SystemExit(f"required evidence file not found: {path}")
    return path


def _latest(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if not matches:
        raise SystemExit(f"no evidence files match {directory / pattern}")
    return matches[-1].resolve()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"{path} did not contain a JSON object")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise SystemExit(f"{path}:{line_number} did not contain a JSON object")
        events.append(payload)
    return events


def _canonical_sha256(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _git_commit(repo_root: Path) -> str | None:
    return _git_output(repo_root, ["git", "rev-parse", "HEAD"])


def _git_dirty(repo_root: Path) -> bool:
    return bool(_git_output(repo_root, ["git", "status", "--porcelain"]))


def _git_output(repo_root: Path, command: list[str]) -> str | None:
    import subprocess

    try:
        result = subprocess.run(command, cwd=repo_root, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _display_path(repo_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="Repository root. Defaults to current directory.")
    parser.add_argument(
        "--output-dir",
        default=".mesh-runtime-state/proofs",
        help="Directory for breakthrough proof bundles.",
    )
    parser.add_argument("--compose-summary")
    parser.add_argument("--compose-events")
    parser.add_argument("--config-drift-proof")
    parser.add_argument("--node-summary")
    parser.add_argument("--node-events")
    parser.add_argument(
        "--validation-command",
        action="append",
        default=[],
        help="Validation command to run and embed. May be repeated. Defaults to unittest, ruff, and focused strict mypy breakthrough checks.",
    )
    parser.add_argument("--skip-validation-commands", action="store_true")
    return parser.parse_args()


def _validation_commands(overrides: list[str]) -> list[list[str]]:
    if overrides:
        return [shlex.split(command) for command in overrides]
    return [
        [
            "python3",
            "-m",
            "unittest",
            "tests.test_breakthrough_evidence_bundle",
            "tests.test_production_node_breakthrough_session",
            "tests.test_compose_chaos_session",
        ],
        [
            "ruff",
            "check",
            "scripts/breakthrough_evidence_bundle.py",
            "scripts/production_node_breakthrough_session.py",
            "tests/test_breakthrough_evidence_bundle.py",
            "tests/test_production_node_breakthrough_session.py",
        ],
        [
            "uvx",
            "--with-editable",
            ".",
            "--with",
            "deepagents",
            "--with",
            "mypy",
            "mypy",
            "--strict",
            "scripts/breakthrough_evidence_bundle.py",
            "scripts/production_node_breakthrough_session.py",
            "tests/test_breakthrough_evidence_bundle.py",
            "tests/test_production_node_breakthrough_session.py",
        ],
    ]


if __name__ == "__main__":
    raise SystemExit(main())
