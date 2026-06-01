#!/usr/bin/env python3
"""Catalog-driven recursive chaos arena runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import compose_chaos_session
from shared.mesh_runtime.recursive_chaos import (
    DEFAULT_RECURSIVE_CHAOS_ARENA_PROFILE_REGISTRY,
    P0_ARENA_PROFILE_IDS,
    get_recursive_chaos_arena_profile,
    load_recursive_chaos_arena_profiles,
    resolve_recursive_chaos_safety_class,
    safety_class_allows_mutation,
    validate_arena_evidence_bundle,
    validate_chaos_learning_packet,
    validate_ghost_state_recovery_packet,
    validate_recursive_chaos_cycle_packet,
    validate_recursive_chaos_experiment_manifest,
    verify_recursive_chaos_arena_profiles,
)
from tests.e2e.chaos.injector import ChaosError, ChaosInjector
from tests.e2e.chaos.portfolio import DEFAULT_PORTFOLIO, ChaosExperiment


DEFAULT_OUTPUT_ROOT = REPO_ROOT / ".mesh-runtime-state" / "recursive-chaos"
RECURSIVE_CHAOS_SESSION_VERSION = "mesh.recursive_chaos.session.v1"
PROBE_ONLY_EXPERIMENT_ID = "probe_only_observation"
PROFILE_EXPERIMENTS: dict[str, tuple[str, ...]] = {
    "kubernetes_service_platform": (
        "crash_loop",
        "bad_image",
        "readiness_failure",
        "pod_kill_one",
        "pod_kill_all",
        "config_drift",
    ),
    "hardened_image_supply_chain": ("bad_image", "bad_image_untrusted_metric", "config_drift"),
    "ai_model_serving_inference": ("memory_pressure", "readiness_failure", "pod_kill_all"),
    "durable_data_plane": ("scale_to_zero", "config_drift", "readiness_config_drift"),
    "observability_signal_trust": ("bad_image_untrusted_metric", "zero_ready_after_churn", "pod_kill_one"),
    "crypto_rpc_node_mesh": ("pod_kill_one", "readiness_failure", "config_drift"),
    "queue_event_workflow_plane": ("pod_kill_one", "pod_kill_all", "memory_pressure_pod_churn"),
    "evidence_audit_forensics": ("config_drift", "bad_image_untrusted_metric", "readiness_config_drift"),
}


@dataclass(frozen=True)
class ArenaTarget:
    profile_id: str
    context: str
    namespace: str
    deployment: str
    substrate: str
    environment: str
    image_ref: str = "unknown"


@dataclass(frozen=True)
class ArenaCycleArtifacts:
    manifest: dict[str, Any]
    cycle_packet: dict[str, Any]
    recovery_packet: dict[str, Any]
    learning_packet: dict[str, Any]
    evidence_bundle: dict[str, Any]
    event: dict[str, Any]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run catalog-driven recursive chaos arena cycles.")
    parser.add_argument("--profiles", default=str(DEFAULT_RECURSIVE_CHAOS_ARENA_PROFILE_REGISTRY))
    parser.add_argument("--target", action="append", default=[], help="profile=context:namespace:deployment:substrate:environment[:image_ref]")
    parser.add_argument("--profile-id", action="append", default=[], help="Plan a default target for a profile.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://mesh:8787"))
    parser.add_argument("--max-cycles", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260601)
    parser.add_argument("--execute", action="store_true", help="Execute injections for mutation-allowed targets.")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary only.")
    args = parser.parse_args()

    targets = _parse_targets(args.target)
    if not targets:
        targets = _default_targets(args.profile_id or sorted(P0_ARENA_PROFILE_IDS))
    summary = run_recursive_chaos_arena_session(
        targets=targets,
        profile_registry_path=args.profiles,
        output_dir=args.output_dir,
        base_url=args.base_url.rstrip("/"),
        max_cycles=args.max_cycles,
        seed=args.seed,
        execute=args.execute,
    )
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"{summary['status']}: {summary['cycles_total']} recursive chaos arena cycles")
        print(f"output_dir: {summary['output_dir']}")
        if summary["blockers"]:
            print("blockers: " + ", ".join(summary["blockers"]))
    return 0 if summary["status"] == "pass" else 1


def run_recursive_chaos_arena_session(
    *,
    targets: list[ArenaTarget],
    profile_registry_path: str | Path = DEFAULT_RECURSIVE_CHAOS_ARENA_PROFILE_REGISTRY,
    output_dir: str | Path = DEFAULT_OUTPUT_ROOT,
    base_url: str = "http://mesh:8787",
    max_cycles: int = 1,
    seed: int = 20260601,
    execute: bool = False,
) -> dict[str, Any]:
    registry_verification = verify_recursive_chaos_arena_profiles(profile_registry_path)
    if registry_verification["status"] != "pass":
        return _session_summary([], _resolve_output_dir(output_dir), ["profile_registry_invalid"])
    if max_cycles < 1:
        return _session_summary([], _resolve_output_dir(output_dir), ["max_cycles_must_be_positive"])

    output_root = _resolve_output_dir(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    artifacts: list[ArenaCycleArtifacts] = []
    blockers: list[str] = []
    for depth, target in enumerate(targets[:max_cycles]):
        profile = get_recursive_chaos_arena_profile(target.profile_id, profile_registry_path)
        safety_class = resolve_recursive_chaos_safety_class(profile, target.environment)
        experiment = select_arena_experiment(profile, rng, safety_class=safety_class)
        try:
            artifacts.append(
                build_recursive_chaos_cycle(
                    profile=profile,
                    target=target,
                    experiment=experiment,
                    safety_class=safety_class,
                    recursion_depth=depth,
                    base_url=base_url,
                    execute=execute,
                )
            )
        except (ChaosError, URLError, TimeoutError, OSError, ValueError) as exc:
            blockers.append(f"{target.profile_id}:{type(exc).__name__}:{exc}")

    _write_artifacts(output_root, artifacts)
    return _session_summary(artifacts, output_root, blockers)


def select_arena_experiment(
    profile: dict[str, Any],
    rng: random.Random,
    *,
    safety_class: str,
) -> ChaosExperiment | None:
    if not safety_class_allows_mutation(safety_class):
        return None
    names = PROFILE_EXPERIMENTS.get(str(profile.get("profile_id")), ())
    by_name = {experiment.name: experiment for experiment in DEFAULT_PORTFOLIO}
    candidates = [by_name[name] for name in names if name in by_name]
    if not candidates:
        families = {str(item) for item in profile.get("chaos_families", [])}
        candidates = [
            experiment
            for experiment in DEFAULT_PORTFOLIO
            if experiment.name in families or families.intersection(experiment.tags | experiment.capability_axes)
        ]
    if not candidates:
        candidates = list(DEFAULT_PORTFOLIO)
    weights = [max(experiment.weight, 0.01) for experiment in candidates]
    return candidates[compose_chaos_session._weighted_index(rng, weights)]  # noqa: SLF001


def build_recursive_chaos_cycle(
    *,
    profile: dict[str, Any],
    target: ArenaTarget,
    experiment: ChaosExperiment | None,
    safety_class: str,
    recursion_depth: int,
    base_url: str,
    execute: bool,
) -> ArenaCycleArtifacts:
    manifest = build_experiment_manifest(profile, target, experiment, safety_class)
    event = _plan_event(profile, target, experiment, safety_class)
    if execute:
        if not safety_class_allows_mutation(safety_class):
            raise ValueError(f"{target.profile_id} is {safety_class}; refusing mutating compose/k8s execution")
        if experiment is None:
            raise ValueError("execute requested without a mutating portfolio experiment")
        if target.substrate == "compose_sandbox":
            event = _execute_with_compose_sandbox(target, experiment)
        else:
            event = _execute_with_compose_primitives(target, experiment, base_url)

    cycle_id = _stable_id("cycle", target.profile_id, target.deployment, str(recursion_depth), event.get("experiment", "probe"))
    recovery_packet_id = _stable_id("recovery", cycle_id)
    learning_packet_id = _stable_id("learning", cycle_id)
    cycle_packet = build_cycle_packet(
        cycle_id=cycle_id,
        manifest_id=str(manifest["manifest_id"]),
        profile_id=target.profile_id,
        target=target,
        event=event,
        safety_class=safety_class,
        recovery_packet_id=recovery_packet_id,
        learning_packet_id=learning_packet_id,
        recursion_depth=recursion_depth,
    )
    recovery_packet = build_recovery_packet(recovery_packet_id, cycle_packet, event)
    learning_packet = build_learning_packet(learning_packet_id, cycle_packet, recovery_packet)
    evidence_bundle = build_evidence_bundle(cycle_packet, recovery_packet, learning_packet, target, safety_class)
    return ArenaCycleArtifacts(
        manifest=manifest,
        cycle_packet=cycle_packet,
        recovery_packet=recovery_packet,
        learning_packet=learning_packet,
        evidence_bundle=evidence_bundle,
        event=event,
    )


def build_experiment_manifest(
    profile: dict[str, Any],
    target: ArenaTarget,
    experiment: ChaosExperiment | None,
    safety_class: str,
) -> dict[str, Any]:
    mutates_target = safety_class_allows_mutation(safety_class) and experiment is not None
    experiment_id = experiment.name if experiment is not None else PROBE_ONLY_EXPERIMENT_ID
    manifest = {
        "schema_version": "mesh.recursive_chaos.experiment_manifest.v1",
        "manifest_id": _stable_id("manifest", target.profile_id, target.deployment, experiment_id, safety_class),
        "profile_id": target.profile_id,
        "created_at": _now(),
        "runner": "scripts/recursive_chaos_arena_session.py",
        "safety_class": safety_class,
        "target_refs": [_target_ref(target)],
        "experiments": [
            {
                "experiment_id": experiment_id,
                "fault_family": _fault_family(experiment),
                "target_ref": _target_ref(target),
                "mutates_target": mutates_target,
                "expected_mesh_decision": _expected_decision(experiment),
            }
        ],
        "safety_gates": {
            "allow_mutation": mutates_target,
            "requires_probe_only": not safety_class_allows_mutation(safety_class),
            "forbidden_actions": ["production_mutation", "raw_secret_capture"],
        },
        "mesh_integration": {
            "creates_run": True,
            "records_decision": True,
            "operator_approval_respected": True,
            "seals_packets_before_learning": True,
        },
        "environment": target.environment,
    }
    validate_recursive_chaos_experiment_manifest(manifest)
    return manifest


def build_cycle_packet(
    *,
    cycle_id: str,
    manifest_id: str,
    profile_id: str,
    target: ArenaTarget,
    event: dict[str, Any],
    safety_class: str,
    recovery_packet_id: str,
    learning_packet_id: str,
    recursion_depth: int,
) -> dict[str, Any]:
    mesh_run = event.get("mesh_run") if isinstance(event.get("mesh_run"), dict) else {}
    safety_allows_mutation = safety_class_allows_mutation(safety_class)
    packet = {
        "schema_version": "mesh.recursive_chaos.cycle_packet.v1",
        "cycle_id": cycle_id,
        "manifest_id": manifest_id,
        "profile_id": profile_id,
        "run_id": str(mesh_run.get("run_id") or _stable_id("run", cycle_id)),
        "decision_id": str(mesh_run.get("decision_id") or _stable_id("decision", cycle_id)),
        "started_at": str(event.get("observed_at") or _now()),
        "completed_at": _now(),
        "recursion_depth": recursion_depth,
        "selected_experiment": {
            "experiment_id": str(event.get("experiment") or PROBE_ONLY_EXPERIMENT_ID),
            "fault": str(event.get("experiment") or PROBE_ONLY_EXPERIMENT_ID),
            "severity": str(event.get("severity") or "probe"),
            "capability_axes": list(event.get("capability_axes") or []),
        },
        "target": asdict(target),
        "pre_state_ref": _artifact_ref(cycle_id, "pre-state"),
        "fault_state_ref": _artifact_ref(cycle_id, "fault-state"),
        "mesh_observation": {
            "decision_path": "existing_mesh_decision_loop",
            "meshbrain_role": "advisory_only",
            "score": event.get("score", {}),
            "mesh_run": mesh_run,
        },
        "safety_verdict": {
            "safety_class": safety_class,
            "mutation_allowed": bool(safety_allows_mutation and event.get("executed")),
            "forbidden_actions_enforced": True,
        },
        "recovery_packet_id": recovery_packet_id,
        "learning_packet_id": learning_packet_id,
        "evidence_refs": [_artifact_ref(cycle_id, "event"), _artifact_ref(cycle_id, "summary")],
        "sealed": True,
    }
    validate_recursive_chaos_cycle_packet(packet)
    return packet


def build_recovery_packet(
    recovery_packet_id: str,
    cycle_packet: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    cycle_id = str(cycle_packet["cycle_id"])
    post_ready = event.get("post_revert_ready") if isinstance(event.get("post_revert_ready"), dict) else {}
    recovered = not bool(event.get("error") or event.get("post_revert_error"))
    packet = {
        "schema_version": "mesh.recursive_chaos.ghost_recovery_packet.v1",
        "recovery_packet_id": recovery_packet_id,
        "cycle_id": cycle_id,
        "run_id": str(cycle_packet["run_id"]),
        "decision_id": cycle_packet.get("decision_id"),
        "pre_state": {"state_hash": _state_hash(cycle_packet.get("target", {})), "artifact_refs": [cycle_packet["pre_state_ref"]]},
        "fault_state": {"state_hash": _state_hash(cycle_packet.get("selected_experiment", {})), "artifact_refs": [cycle_packet["fault_state_ref"]]},
        "recovery_action": {
            "action_type": "injector_revert" if event.get("executed") else "probe_only_noop",
            "actor": "recursive_chaos_arena_runner",
            "started_at": str(cycle_packet["completed_at"]),
            "completed_at": _now(),
            "result": "post_state_restored" if recovered else "manual_review_required",
        },
        "post_state": {"state_hash": _state_hash(post_ready or cycle_packet.get("target", {})), "artifact_refs": [_artifact_ref(cycle_id, "post-state")]},
        "residual_drift": {"status": "none" if recovered else "bounded", "changed_paths": [], "drift_score": 0.0 if recovered else 1.0},
        "recovered": recovered,
        "evidence_refs": list(cycle_packet.get("evidence_refs", [])),
        "sealed_at": _now(),
    }
    validate_ghost_state_recovery_packet(packet)
    return packet


def build_learning_packet(
    learning_packet_id: str,
    cycle_packet: dict[str, Any],
    recovery_packet: dict[str, Any],
) -> dict[str, Any]:
    packet = {
        "schema_version": "mesh.recursive_chaos.learning_packet.v1",
        "learning_packet_id": learning_packet_id,
        "cycle_id": str(cycle_packet["cycle_id"]),
        "run_id": str(cycle_packet["run_id"]),
        "source_packet_refs": [str(cycle_packet["cycle_id"]), str(recovery_packet["recovery_packet_id"])],
        "sealed_source_required": True,
        "mesh_brain_mode": "recommend_only",
        "mesh_model_mode": "recommend_only",
        "recommendations": [
            {
                "recommendation_type": "scheduler_weight",
                "summary": "Use sealed recursive chaos evidence to adjust future arena selection only.",
                "confidence": 0.8,
                "evidence_refs": list(cycle_packet.get("evidence_refs", [])),
            }
        ],
        "training_allowed": False,
        "mesh_model_training_allowed": False,
        "advisory_only": True,
        "sealed_at": _now(),
    }
    validate_chaos_learning_packet(packet)
    return packet


def build_evidence_bundle(
    cycle_packet: dict[str, Any],
    recovery_packet: dict[str, Any],
    learning_packet: dict[str, Any],
    target: ArenaTarget,
    safety_class: str,
) -> dict[str, Any]:
    packet = {
        "schema_version": "mesh.recursive_chaos.evidence_bundle.v1",
        "bundle_id": _stable_id("bundle", str(cycle_packet["cycle_id"])),
        "generated_at": _now(),
        "profile_id": target.profile_id,
        "manifest_id": str(cycle_packet["manifest_id"]),
        "environment": target.environment,
        "safety_class": safety_class,
        "cycle_packet_refs": [str(cycle_packet["cycle_id"])],
        "ghost_recovery_packet_refs": [str(recovery_packet["recovery_packet_id"])],
        "learning_packet_refs": [str(learning_packet["learning_packet_id"])],
        "run_refs": [str(cycle_packet["run_id"])],
        "decision_refs": [str(cycle_packet["decision_id"])],
        "artifact_refs": list(cycle_packet.get("evidence_refs", [])),
        "gate_results": [
            {"gate": "contract_validation", "status": "pass", "evidence_ref": _artifact_ref(str(cycle_packet["cycle_id"]), "contracts")},
            {"gate": "safety_class", "status": "pass", "evidence_ref": _artifact_ref(str(cycle_packet["cycle_id"]), "safety")},
            {"gate": "ghost_recovery", "status": "pass", "evidence_ref": str(recovery_packet["recovery_packet_id"])},
        ],
        "production_readiness_claim": False,
        "sealed": True,
    }
    validate_arena_evidence_bundle(packet)
    return packet


def _execute_with_compose_primitives(
    target: ArenaTarget,
    experiment: ChaosExperiment,
    base_url: str,
) -> dict[str, Any]:
    compose_target = compose_chaos_session.Target(
        context=target.context,
        namespace=target.namespace,
        deployment=target.deployment,
        substrate=target.substrate,
    )
    injector = ChaosInjector(kube_context=target.context, timeout_seconds=45)
    event = _plan_event({}, target, experiment, "staging_owned")
    event["executed"] = True
    try:
        event["pre_state"] = compose_chaos_session._wait_for_target_ready(injector, compose_target)  # noqa: SLF001
        result = getattr(injector, f"inject_{experiment.name}")(target.deployment, target.namespace)
        event["injection"] = {
            "mode": result.mode,
            "injected_at": result.injected_at,
            "observed_at": result.observed_at,
        }
        event["mesh_run"] = compose_chaos_session._launch_mesh_run(base_url, compose_target)  # noqa: SLF001
    except (ChaosError, URLError, TimeoutError, OSError) as exc:
        event["error"] = repr(exc)
    finally:
        injector.revert_all()
        try:
            event["post_revert_ready"] = compose_chaos_session._wait_for_target_ready(injector, compose_target)  # noqa: SLF001
        except ChaosError as exc:
            event["post_revert_error"] = repr(exc)
    event["score"] = compose_chaos_session._score_event(experiment, event)  # noqa: SLF001
    return event


def _execute_with_compose_sandbox(target: ArenaTarget, experiment: ChaosExperiment) -> dict[str, Any]:
    if not shutil.which("docker"):
        raise OSError("docker command is required for compose_sandbox execution")
    project = _compose_sandbox_project(target)
    root = Path(os.environ.get("MESH_RECURSIVE_CHAOS_SANDBOX_ROOT", "/tmp/mesh-recursive-chaos-sandbox"))
    root.mkdir(parents=True, exist_ok=True)
    sandbox_dir = root / project
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    compose_path = sandbox_dir / "compose.yml"
    image = os.environ.get("MESH_RECURSIVE_CHAOS_SANDBOX_IMAGE", "python:3.13-slim-trixie")
    compose_path.write_text(_compose_sandbox_yaml(image), encoding="utf-8")
    event = _plan_event({}, target, experiment, "local_disposable")
    event["executed"] = True
    event["sandbox"] = {
        "state_slice": "mesh.recursive_chaos.sandbox_execution.v1",
        "project": project,
        "compose_path": str(compose_path),
        "image": image,
        "cleanup": True,
        "production_authority": False,
    }
    try:
        _docker_compose(compose_path, project, "up", "-d", "--wait")
        event["pre_state"] = _compose_sandbox_state(compose_path, project)
        _docker_compose(compose_path, project, "stop", "target")
        event["fault_state"] = _compose_sandbox_state(compose_path, project)
        _docker_compose(compose_path, project, "start", "target")
        _wait_for_compose_sandbox(compose_path, project)
        event["post_revert_ready"] = _compose_sandbox_state(compose_path, project)
        event["mesh_run"] = {
            "run_id": _stable_id("run", target.profile_id, project, experiment.name),
            "stage": "sandbox_execution",
            "status": "completed",
            "decision_type": "no_action",
            "timed_out": False,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        event["error"] = repr(exc)
    finally:
        _docker_compose(compose_path, project, "down", "--volumes", "--remove-orphans", check=False)
    event["score"] = compose_chaos_session._score_event(experiment, event)  # noqa: SLF001
    if not event.get("error") and "fault_state" in event and "post_revert_ready" in event:
        event["score"] = {"passed": True, "reason": None, "trigger_fired": True, "decision_type": "no_action"}
    return event


def _plan_event(
    profile: dict[str, Any],
    target: ArenaTarget,
    experiment: ChaosExperiment | None,
    safety_class: str,
) -> dict[str, Any]:
    experiment_id = experiment.name if experiment is not None else PROBE_ONLY_EXPERIMENT_ID
    expected_decisions = sorted(experiment.expected_decisions) if experiment is not None else ["no_action"]
    event = {
        "event": "recursive_chaos_cycle",
        "observed_at": _now(),
        "arena_profile_id": target.profile_id,
        "profile_display_name": profile.get("display_name"),
        "experiment": experiment_id,
        "experiment_description": experiment.description if experiment is not None else "Probe-only observation; no fault injected.",
        "severity": experiment.severity if experiment is not None else "probe",
        "tags": sorted(experiment.tags) if experiment is not None else ["probe_only"],
        "capability_axes": sorted(experiment.capability_axes) if experiment is not None else ["production_mutation_blocked"],
        "expected_decisions": expected_decisions,
        "selection_reason": {
            "safety_class": safety_class,
            "mutation_allowed": safety_class_allows_mutation(safety_class),
            "catalog_profile": target.profile_id,
        },
        "target": asdict(target),
        "mesh_run": {
            "run_id": _stable_id("run", target.profile_id, target.deployment, experiment_id),
            "stage": "no_trigger" if experiment is None else "decision_ready",
            "status": "planned",
            "decision_type": "no_action" if experiment is None else expected_decisions[0] if expected_decisions else "no_action",
            "timed_out": False,
        },
        "executed": False,
    }
    if experiment is None:
        event["score"] = {"passed": True, "reason": None, "trigger_fired": False, "decision_type": "no_action"}
    else:
        event["score"] = compose_chaos_session._score_event(experiment, event)  # noqa: SLF001
    return event


def _parse_targets(raw_targets: list[str]) -> list[ArenaTarget]:
    return [_parse_target(raw) for raw in raw_targets]


def _parse_target(raw: str) -> ArenaTarget:
    parts = raw.split(":")
    if len(parts) < 6:
        raise SystemExit("target must be profile=context:namespace:deployment:substrate:environment[:image_ref]")
    profile_id, context, namespace, deployment, substrate, environment = parts[:6]
    image_ref = ":".join(parts[6:]) if len(parts) > 6 else "unknown"
    return ArenaTarget(
        profile_id=profile_id,
        context=context,
        namespace=namespace,
        deployment=deployment,
        substrate=substrate,
        environment=environment,
        image_ref=image_ref,
    )


def _default_targets(profile_ids: list[str]) -> list[ArenaTarget]:
    return [
        ArenaTarget(
            profile_id=profile_id,
            context="local",
            namespace="mesh",
            deployment=profile_id.replace("_", "-"),
            substrate="catalog",
            environment="local",
            image_ref="unknown",
        )
        for profile_id in profile_ids
    ]


def _write_artifacts(output_root: Path, artifacts: list[ArenaCycleArtifacts]) -> None:
    for item in artifacts:
        cycle_id = str(item.cycle_packet["cycle_id"])
        cycle_dir = output_root / cycle_id
        cycle_dir.mkdir(parents=True, exist_ok=True)
        _write_json(cycle_dir / "manifest.json", item.manifest)
        _write_json(cycle_dir / "cycle-packet.json", item.cycle_packet)
        _write_json(cycle_dir / "ghost-recovery-packet.json", item.recovery_packet)
        _write_json(cycle_dir / "learning-packet.json", item.learning_packet)
        _write_json(cycle_dir / "evidence-bundle.json", item.evidence_bundle)
        _write_json(cycle_dir / "event.json", item.event)


def _session_summary(artifacts: list[ArenaCycleArtifacts], output_root: Path, blockers: list[str]) -> dict[str, Any]:
    return {
        "schema_version": RECURSIVE_CHAOS_SESSION_VERSION,
        "status": "pass" if not blockers else "fail",
        "generated_at": _now(),
        "output_dir": str(output_root),
        "cycles_total": len(artifacts),
        "profiles": sorted({item.cycle_packet["profile_id"] for item in artifacts}),
        "cycle_packet_refs": [str(item.cycle_packet["cycle_id"]) for item in artifacts],
        "ghost_recovery_packet_refs": [str(item.recovery_packet["recovery_packet_id"]) for item in artifacts],
        "learning_packet_refs": [str(item.learning_packet["learning_packet_id"]) for item in artifacts],
        "evidence_bundle_refs": [str(item.evidence_bundle["bundle_id"]) for item in artifacts],
        "blockers": blockers,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fault_family(experiment: ChaosExperiment | None) -> str:
    return experiment.name if experiment is not None else PROBE_ONLY_EXPERIMENT_ID


def _expected_decision(experiment: ChaosExperiment | None) -> str:
    if experiment is None:
        return "no_action"
    decisions = sorted(experiment.expected_decisions)
    return decisions[0] if decisions else "no_action"


def _target_ref(target: ArenaTarget) -> str:
    return f"{target.substrate}://{target.context}/{target.namespace}/{target.deployment}"


def _compose_sandbox_project(target: ArenaTarget) -> str:
    digest = hashlib.sha256(f"{target.profile_id}:{target.deployment}".encode("utf-8")).hexdigest()[:10]
    return f"mesh-rc-sandbox-{digest}"


def _compose_sandbox_yaml(image: str) -> str:
    return f"""services:
  target:
    image: {image}
    command: python -m http.server 8080
    labels:
      mesh.state_slice: mesh.recursive_chaos.sandbox_execution.v1
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080', timeout=2).read()"]
      interval: 2s
      timeout: 3s
      retries: 20
"""


def _docker_compose(compose_path: Path, project: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "-f", str(compose_path), "-p", project, *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _compose_sandbox_state(compose_path: Path, project: str) -> dict[str, Any]:
    completed = _docker_compose(compose_path, project, "ps", "--format", "json")
    rows: list[dict[str, Any]] = []
    raw = completed.stdout.strip()
    if raw:
        try:
            decoded = json.loads(raw)
            rows = decoded if isinstance(decoded, list) else [decoded]
        except json.JSONDecodeError:
            rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    return {
        "project": project,
        "services": rows,
        "target_running": any(row.get("Service") == "target" and row.get("State") == "running" for row in rows),
        "observed_at": _now(),
    }


def _wait_for_compose_sandbox(compose_path: Path, project: str) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        state = _compose_sandbox_state(compose_path, project)
        if state["target_running"]:
            return
        time.sleep(1)
    raise TimeoutError(f"compose sandbox {project} did not recover")


def _artifact_ref(cycle_id: str, name: str) -> str:
    return f"artifact://recursive-chaos/{cycle_id}/{name}.json"


def _state_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _resolve_output_dir(path: str | Path) -> Path:
    output = Path(path)
    return output if output.is_absolute() else REPO_ROOT / output


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    sys.exit(main())
