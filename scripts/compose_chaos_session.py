#!/usr/bin/env python3
"""Compose-native multi-cluster chaos driver."""

from __future__ import annotations

import json
import os
import random
import socket
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from urllib.error import URLError

from shared.mesh_runtime.recursive_chaos import (
    build_arena_evidence_bundle,
    build_chaos_learning_packet,
    build_ghost_recovery_packet,
    build_recursive_chaos_cycle_packet,
    build_recursive_chaos_experiment_manifest,
    get_recursive_chaos_arena_profile,
    recursive_chaos_safety_verdict,
)
from tests.e2e.chaos.injector import ChaosError, ChaosInjector
from tests.e2e.chaos.portfolio import (
    CAPABILITY_AXES,
    DEFAULT_PORTFOLIO,
    SEVERITY_HIGH,
    SEVERITY_SEVERE,
    ChaosExperiment,
)


@dataclass(frozen=True)
class Target:
    context: str
    namespace: str
    deployment: str
    substrate: str


@dataclass(frozen=True)
class Prior:
    experiment: str
    target_key: str
    severity: str
    completed_at: float
    capability_axes: frozenset[str] = frozenset()
    passed: bool | None = None
    substrate: str = "unknown"


_LONG_RUNNING_RUN_STAGES = {"scenario_analysis_ready", "evaluation_ready"}


def main() -> int:
    targets = _parse_targets(os.environ.get("MESH_STACK_CHAOS_TARGETS", ""))
    if not targets:
        raise SystemExit("MESH_STACK_CHAOS_TARGETS did not define any targets")

    base_url = os.environ.get("BASE_URL", "http://mesh:8787").rstrip("/")
    duration = float(os.environ.get("MESH_STACK_CHAOS_DURATION_SECONDS", str(72 * 60 * 60)))
    min_sleep = float(os.environ.get("MESH_STACK_CHAOS_MIN_SLEEP_SECONDS", "45"))
    max_sleep = float(os.environ.get("MESH_STACK_CHAOS_MAX_SLEEP_SECONDS", "180"))
    hold_seconds = float(os.environ.get("MESH_STACK_CHAOS_HOLD_SECONDS", "30"))
    seed = int(os.environ.get("MESH_STACK_CHAOS_SEED", "20260428"))
    coverage_first = os.environ.get("MESH_STACK_CHAOS_COVERAGE_FIRST", "1").lower() not in {"0", "false", "no"}
    stop_on_breakthrough = os.environ.get("MESH_STACK_CHAOS_STOP_ON_BREAKTHROUGH", "0").lower() in {"1", "true", "yes"}
    arena_profile_id = os.environ.get("MESH_STACK_CHAOS_ARENA_PROFILE_ID", "kubernetes_service_platform")
    arena_environment = os.environ.get("MESH_STACK_CHAOS_ENVIRONMENT", "local")
    require_full_axis_coverage = os.environ.get(
        "MESH_STACK_CHAOS_REQUIRE_FULL_AXIS_COVERAGE",
        "1" if coverage_first else "0",
    ).lower() not in {"0", "false", "no"}
    require_substrate_coverage = os.environ.get(
        "MESH_STACK_CHAOS_REQUIRE_SUBSTRATE_COVERAGE",
        "1" if coverage_first else "0",
    ).lower() not in {"0", "false", "no"}
    require_multi_fault_breadth = os.environ.get(
        "MESH_STACK_CHAOS_REQUIRE_MULTI_FAULT_BREADTH",
        "1" if coverage_first else "0",
    ).lower() not in {"0", "false", "no"}
    output_root = Path(os.environ.get("MESH_STACK_CHAOS_OUTPUT_DIR", "/workspace/orbital-mesh/.mesh-runtime-state/compose-chaos"))
    output_root.mkdir(parents=True, exist_ok=True)

    arena_profile = get_recursive_chaos_arena_profile(arena_profile_id)
    manifest = _build_recursive_chaos_manifest(
        arena_profile=arena_profile,
        arena_environment=arena_environment,
        targets=targets,
    )
    _wait_for_mesh(base_url)
    rng = random.Random(seed)
    history: list[Prior] = []
    session_events: list[dict[str, Any]] = []
    started = time.monotonic()
    deadline = started + duration
    session_stamp = _stamp_compact()
    events_path = output_root / f"events-{session_stamp}.jsonl"
    summary_path = events_path.with_name(events_path.name.replace("events-", "summary-").replace(".jsonl", ".json"))
    manifest_path = events_path.with_name(events_path.name.replace("events-", "manifest-").replace(".jsonl", ".json"))
    packet_root = output_root / f"packets-{session_stamp}"
    packet_root.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({
        "event": "session_started",
        "targets": [target.__dict__ for target in targets],
        "duration_seconds": duration,
        "seed": seed,
        "output": str(events_path),
        "recursive_chaos_manifest": str(manifest_path),
        "recursive_chaos_profile_id": arena_profile_id,
        "recursive_chaos_environment": arena_environment,
    }, sort_keys=True), flush=True)

    while time.monotonic() < deadline:
        now = time.monotonic() - started
        pick = _pick(rng, targets, history, now, coverage_first=coverage_first)
        if pick is None:
            time.sleep(min_sleep)
            continue
        experiment, target = pick
        injector = ChaosInjector(kube_context=target.context, timeout_seconds=45)
        event: dict[str, Any] = {
            "event": "chaos_cycle",
            "observed_at": _now(),
            "experiment": experiment.name,
            "experiment_description": experiment.description,
            "severity": experiment.severity,
            "tags": sorted(experiment.tags),
            "capability_axes": sorted(experiment.capability_axes),
            "expected_decisions": sorted(experiment.expected_decisions),
            "selection_reason": _selection_reason(experiment, history),
            "target": target.__dict__,
            "recursive_chaos": _cycle_catalog_context(manifest, experiment, target),
        }
        verdict = recursive_chaos_safety_verdict(
            safety_class=str(manifest["safety_class"]),
            mutates_target=_experiment_mutates_target(experiment),
            forbidden_actions=list(manifest["safety_gates"]["forbidden_actions"]),
        )
        event["safety_verdict"] = verdict
        if not verdict["mutation_allowed"]:
            event["error"] = verdict["reason"]
            event["score"] = _score_event(experiment, event)
            event["recursive_chaos_packets"] = _emit_recursive_chaos_packets(
                manifest=manifest,
                event=event,
                packet_root=packet_root,
                events_path=events_path,
                cycle_number=len(session_events) + 1,
            )
            history.append(
                Prior(
                    experiment.name,
                    _target_key(target),
                    experiment.severity,
                    now,
                    experiment.capability_axes,
                    False,
                    target.substrate,
                )
            )
            _append_jsonl(events_path, event)
            session_events.append(event)
            summary = _session_summary(events_path, session_events, configured_substrates={target.substrate for target in targets})
            summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps(event, sort_keys=True), flush=True)
            time.sleep(rng.uniform(min_sleep, max_sleep))
            continue
        try:
            event["pre_state"] = _wait_for_target_ready(injector, target)
            result = getattr(injector, f"inject_{experiment.name}")(target.deployment, target.namespace)
            event["injection"] = {
                "mode": result.mode,
                "injected_at": result.injected_at,
                "observed_at": result.observed_at,
            }
            event["fault_state"] = {
                "mode": result.mode,
                "observed_at": result.observed_at,
                "pod_snapshot": result.pod_snapshot,
            }
            observation_delay = _observation_delay_seconds(experiment, hold_seconds)
            event["observation_delay_seconds"] = observation_delay
            time.sleep(observation_delay)
            event["mesh_run"] = _launch_mesh_run(base_url, target)
        except (ChaosError, URLError, TimeoutError, OSError) as exc:
            event["error"] = repr(exc)
        finally:
            injector.revert_all()
            try:
                event["post_revert_ready"] = _wait_for_target_ready(injector, target)
            except ChaosError as exc:
                event["post_revert_error"] = repr(exc)
        event["score"] = _score_event(experiment, event)
        event["recursive_chaos_packets"] = _emit_recursive_chaos_packets(
            manifest=manifest,
            event=event,
            packet_root=packet_root,
            events_path=events_path,
            cycle_number=len(session_events) + 1,
        )
        history.append(
            Prior(
                experiment.name,
                _target_key(target),
                experiment.severity,
                now,
                experiment.capability_axes,
                bool(event["score"].get("passed")),
                target.substrate,
            )
        )
        _append_jsonl(events_path, event)
        session_events.append(event)
        summary = _session_summary(events_path, session_events, configured_substrates={target.substrate for target in targets})
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(event, sort_keys=True), flush=True)
        if stop_on_breakthrough and _should_stop_on_breakthrough(
            summary,
            require_full_axis_coverage=require_full_axis_coverage,
            require_substrate_coverage=require_substrate_coverage,
            require_multi_fault_breadth=require_multi_fault_breadth,
        ):
            break
        time.sleep(rng.uniform(min_sleep, max_sleep))

    summary = _session_summary(events_path, session_events, configured_substrates={target.substrate for target in targets})
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "event": "session_completed",
        "observed_at": _now(),
        "output": str(events_path),
        "summary": str(summary_path),
        "breakthrough_probe": summary["breakthrough_probe"],
    }, sort_keys=True), flush=True)
    return 0


def _should_stop_on_breakthrough(
    summary: dict[str, Any],
    *,
    require_full_axis_coverage: bool,
    require_substrate_coverage: bool,
    require_multi_fault_breadth: bool,
) -> bool:
    breakthrough_probe = summary.get("breakthrough_probe")
    if not isinstance(breakthrough_probe, dict) or not breakthrough_probe.get("ready"):
        return False
    if not require_full_axis_coverage:
        capabilities_clear = True
    else:
        raw_capabilities = summary.get("capabilities")
        capabilities = cast(dict[str, Any], raw_capabilities) if isinstance(raw_capabilities, dict) else {}
        capabilities_clear = not bool(capabilities.get("missing_axes") or capabilities.get("failed_or_unproven_axes"))
    if not capabilities_clear:
        return False
    if not require_substrate_coverage:
        substrates_clear = True
    else:
        raw_substrate_coverage = summary.get("substrate_coverage")
        substrate_coverage = cast(dict[str, Any], raw_substrate_coverage) if isinstance(raw_substrate_coverage, dict) else {}
        if not substrate_coverage:
            return False
        substrates_clear = all(
            isinstance(coverage, dict) and int(coverage.get("passed", 0) or 0) >= 1
            for coverage in substrate_coverage.values()
        )
    if not substrates_clear:
        return False
    if not require_multi_fault_breadth:
        return True
    raw_multi_fault_coverage = summary.get("multi_fault_coverage")
    multi_fault_coverage = cast(dict[str, Any], raw_multi_fault_coverage) if isinstance(raw_multi_fault_coverage, dict) else {}
    return not bool(multi_fault_coverage.get("missing_experiments"))


def _parse_targets(raw: str) -> list[Target]:
    targets: list[Target] = []
    for chunk in raw.split(","):
        item = chunk.strip()
        if not item:
            continue
        parts = item.split(":")
        if len(parts) == 3:
            context, namespace, deployment = parts
            substrate = "kubernetes"
        elif len(parts) == 4:
            context, namespace, deployment, substrate = parts
        else:
            raise SystemExit(f"invalid target {item!r}; expected context:namespace:deployment[:substrate]")
        targets.append(Target(context=context, namespace=namespace, deployment=deployment, substrate=substrate))
    return targets


def _build_recursive_chaos_manifest(
    *,
    arena_profile: dict[str, Any],
    arena_environment: str,
    targets: list[Target],
) -> dict[str, Any]:
    target_refs = [_target_ref(target) for target in targets]
    experiments = [
        _experiment_manifest_entry(experiment, target_ref)
        for target_ref in target_refs
        for experiment in DEFAULT_PORTFOLIO
    ]
    return build_recursive_chaos_experiment_manifest(
        manifest_id=f"compose-chaos-{_stamp_compact()}",
        profile=arena_profile,
        created_at=_now(),
        runner="compose_k8s_catalog_runner",
        environment=arena_environment,
        target_refs=target_refs,
        experiments=experiments,
    )


def _experiment_manifest_entry(experiment: ChaosExperiment, target_ref: str) -> dict[str, Any]:
    expected = sorted(experiment.expected_decisions)
    return {
        "experiment_id": experiment.name,
        "fault_family": _fault_family(experiment),
        "target_ref": target_ref,
        "mutates_target": _experiment_mutates_target(experiment),
        "expected_mesh_decision": expected[0] if expected else "no_action",
    }


def _cycle_catalog_context(
    manifest: dict[str, Any],
    experiment: ChaosExperiment,
    target: Target,
) -> dict[str, Any]:
    return {
        "manifest_id": manifest["manifest_id"],
        "profile_id": manifest["profile_id"],
        "safety_class": manifest["safety_class"],
        "target_ref": _target_ref(target),
        "experiment": _experiment_manifest_entry(experiment, _target_ref(target)),
        "seals_packets_before_learning": manifest["mesh_integration"]["seals_packets_before_learning"],
    }


def _emit_recursive_chaos_packets(
    *,
    manifest: dict[str, Any],
    event: dict[str, Any],
    packet_root: Path,
    events_path: Path,
    cycle_number: int,
) -> dict[str, str]:
    packet_root.mkdir(parents=True, exist_ok=True)
    cycle_id = _safe_token(
        f"{manifest['manifest_id']}-{cycle_number}-{event.get('experiment', 'unknown')}"
    )
    run_id, decision_id = _run_and_decision_refs(event, cycle_id)
    recovery_packet_id = f"recovery-{cycle_id}" if _has_recovery_chain(event) else None
    learning_packet_id = f"learning-{cycle_id}"
    bundle_id = f"bundle-{cycle_id}"
    sealed_at = _now()
    refs: dict[str, str] = {}

    recovery_ref: str | None = None
    if recovery_packet_id is not None:
        recovery_packet = build_ghost_recovery_packet(
            recovery_packet_id=recovery_packet_id,
            cycle_id=cycle_id,
            run_id=run_id,
            decision_id=decision_id,
            pre_state=cast(dict[str, Any], event.get("pre_state") or {}),
            fault_state=cast(dict[str, Any], event.get("fault_state") or {}),
            recovery_action={
                "action_type": "injector_revert",
                "actor": "compose_chaos_runner",
                "started_at": str((event.get("injection") or {}).get("observed_at") or sealed_at),
                "completed_at": sealed_at,
                "result": "post_state_restored" if "post_revert_ready" in event else "manual_review_required",
            },
            post_state=cast(dict[str, Any], event.get("post_revert_ready") or {}),
            residual_drift=_residual_drift(event),
            recovered="post_revert_ready" in event,
            evidence_refs=[str(events_path)],
            sealed_at=sealed_at,
        )
        recovery_ref = _write_packet(packet_root / f"{recovery_packet_id}.json", recovery_packet)
        refs["ghost_recovery_packet"] = recovery_ref

    learning_packet = build_chaos_learning_packet(
        learning_packet_id=learning_packet_id,
        cycle_id=cycle_id,
        run_id=run_id,
        source_packet_refs=[cycle_id] + ([recovery_packet_id] if recovery_packet_id else []),
        recommendations=[_learning_recommendation(event)],
        sealed_at=sealed_at,
    )
    learning_ref = _write_packet(packet_root / f"{learning_packet_id}.json", learning_packet)
    refs["learning_packet"] = learning_ref

    safety_verdict = cast(dict[str, Any], event.get("safety_verdict") or {})
    cycle_packet = build_recursive_chaos_cycle_packet(
        cycle_id=cycle_id,
        manifest_id=str(manifest["manifest_id"]),
        profile_id=str(manifest["profile_id"]),
        run_id=run_id,
        decision_id=decision_id,
        started_at=str(event.get("observed_at") or sealed_at),
        completed_at=sealed_at,
        recursion_depth=1,
        selected_experiment={
            "experiment_id": str(event.get("experiment") or "unknown"),
            "fault": str(event.get("experiment") or "unknown"),
            "severity": str(event.get("severity") or "unknown"),
            "capability_axes": list(event.get("capability_axes") or []),
        },
        target=_cycle_target(event, manifest),
        pre_state_ref=recovery_ref or str(events_path),
        fault_state_ref=recovery_ref or str(events_path),
        mesh_observation=cast(dict[str, Any], event.get("mesh_run") or {"error": event.get("error")}),
        safety_verdict=safety_verdict,
        recovery_packet_id=recovery_packet_id,
        learning_packet_id=learning_packet_id,
        evidence_refs=[str(events_path)],
    )
    cycle_ref = _write_packet(packet_root / f"{cycle_id}.cycle.json", cycle_packet)
    refs["cycle_packet"] = cycle_ref

    bundle = build_arena_evidence_bundle(
        bundle_id=bundle_id,
        generated_at=sealed_at,
        profile_id=str(manifest["profile_id"]),
        manifest_id=str(manifest["manifest_id"]),
        environment=str(manifest.get("environment") or "unknown"),
        safety_class=str(manifest["safety_class"]),
        cycle_packet_refs=[cycle_ref],
        ghost_recovery_packet_refs=[recovery_ref] if recovery_ref else [],
        learning_packet_refs=[learning_ref],
        run_refs=[run_id],
        decision_refs=[decision_id] if decision_id else [],
        artifact_refs=[str(events_path)],
        gate_results=[
            {"gate": "contract_validation", "status": "pass", "evidence_ref": cycle_ref},
            {"gate": "safety_gate", "status": "pass", "evidence_ref": cycle_ref},
        ],
    )
    bundle_ref = _write_packet(packet_root / f"{bundle_id}.json", bundle)
    refs["evidence_bundle"] = bundle_ref
    return refs


def _has_recovery_chain(event: dict[str, Any]) -> bool:
    return all(isinstance(event.get(key), dict) for key in ("pre_state", "fault_state", "post_revert_ready"))


def _run_and_decision_refs(event: dict[str, Any], cycle_id: str) -> tuple[str, str | None]:
    mesh_run = event.get("mesh_run") if isinstance(event.get("mesh_run"), dict) else {}
    run_id = str(mesh_run.get("run_id") or f"run_not_created_{cycle_id}")
    decision_type = mesh_run.get("decision_type")
    decision_id = mesh_run.get("decision_id")
    if decision_id is None and decision_type:
        decision_id = f"decision_{run_id}_{decision_type}"
    return run_id, str(decision_id) if decision_id else None


def _cycle_target(event: dict[str, Any], manifest: dict[str, Any]) -> dict[str, str]:
    target = event.get("target") if isinstance(event.get("target"), dict) else {}
    return {
        "substrate": str(target.get("substrate") or "unknown"),
        "environment": str(manifest.get("environment") or "unknown"),
        "namespace": str(target.get("namespace") or "unknown"),
        "resource_ref": f"deployment/{target.get('deployment') or 'unknown'}",
    }


def _residual_drift(event: dict[str, Any]) -> dict[str, Any]:
    if "post_revert_error" in event:
        return {"status": "unbounded", "changed_paths": ["post_revert_ready"], "drift_score": 1.0}
    return {"status": "none", "changed_paths": [], "drift_score": 0.0}


def _learning_recommendation(event: dict[str, Any]) -> dict[str, Any]:
    score = event.get("score") if isinstance(event.get("score"), dict) else {}
    passed = score.get("passed") is True
    return {
        "recommendation_type": "scheduler_weight",
        "summary": "Keep current weighting" if passed else "Reduce or review this fault until recovery evidence is clean",
        "confidence": 0.8 if passed else 0.5,
        "evidence_refs": list(event.get("evidence_refs") or []),
    }


def _write_packet(path: Path, payload: dict[str, Any]) -> str:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(path)


def _safe_token(raw: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in raw)


def _target_ref(target: Target) -> str:
    return f"{target.substrate}://{target.context}/{target.namespace}/{target.deployment}"


def _fault_family(experiment: ChaosExperiment) -> str:
    if "multi_fault" in experiment.tags:
        return "multi_fault"
    if "subtle_fault" in experiment.tags:
        return "weak_signal"
    return experiment.name


def _experiment_mutates_target(experiment: ChaosExperiment) -> bool:
    return True


def _pick(
    rng: random.Random,
    targets: list[Target],
    history: list[Prior],
    now: float,
    *,
    coverage_first: bool = True,
) -> tuple[ChaosExperiment, Target] | None:
    last_high = next((prior.completed_at for prior in reversed(history) if prior.severity in {SEVERITY_HIGH, SEVERITY_SEVERE}), None)
    covered_axes = _covered_axes(history)
    eligible: list[tuple[ChaosExperiment, Target]] = []
    weights: list[float] = []
    for experiment in DEFAULT_PORTFOLIO:
        missing_axes = set(experiment.capability_axes) - covered_axes
        high_severity_spacing_applies = (
            experiment.severity in {SEVERITY_HIGH, SEVERITY_SEVERE}
            and last_high is not None
            and now - last_high < 60
        )
        if high_severity_spacing_applies and (not coverage_first or not missing_axes):
            continue
        for target in targets:
            prior = next(
                (
                    item for item in reversed(history)
                    if item.experiment == experiment.name and item.target_key == _target_key(target)
                ),
                None,
            )
            if prior is not None and now - prior.completed_at < experiment.cooldown_seconds:
                continue
            eligible.append((experiment, target))
            weights.append(_adaptive_weight(experiment, history))
    if not eligible:
        return None
    if coverage_first:
        coverage_pick = _coverage_frontier_pick(eligible, history)
        if coverage_pick is not None:
            return coverage_pick
    return eligible[_weighted_index(rng, weights)]


def _coverage_frontier_pick(
    eligible: list[tuple[ChaosExperiment, Target]],
    history: list[Prior],
) -> tuple[ChaosExperiment, Target] | None:
    covered_axes = _covered_axes(history)
    attempted_experiments = {prior.experiment for prior in history}
    passed_substrates = _passed_substrates(history)
    configured_substrates = {target.substrate for _, target in eligible}
    frontier: list[tuple[int, int, int, float, str, str, tuple[ChaosExperiment, Target]]] = []
    for experiment, target in eligible:
        missing_axes = set(experiment.capability_axes) - covered_axes
        substrate_uncovered = target.substrate in configured_substrates - passed_substrates
        if not missing_axes and not substrate_uncovered:
            continue
        never_attempted = 1 if experiment.name not in attempted_experiments else 0
        frontier.append((
            len(missing_axes),
            never_attempted,
            1 if substrate_uncovered else 0,
            experiment.weight,
            experiment.name,
            _target_key(target),
            (experiment, target),
        ))
    if not frontier:
        return None
    frontier.sort(key=lambda item: (-item[0], -item[2], -item[1], -item[3], item[4], item[5]))
    return frontier[0][6]


def _adaptive_weight(experiment: ChaosExperiment, history: list[Prior]) -> float:
    covered_axes = _covered_axes(history)
    axes = set(experiment.capability_axes)
    weight = experiment.weight
    if axes:
        missing = axes - covered_axes
        coverage_gap = len(missing) / len(axes)
        weight *= 1.0 + (3.0 * coverage_gap)
        if missing == axes:
            weight *= 1.5
    recent_failures = sum(
        1
        for prior in history[-8:]
        if prior.experiment == experiment.name and prior.passed is False
    )
    if recent_failures:
        weight *= 1.0 / (1.0 + recent_failures)
    return max(weight, 0.01)


def _selection_reason(experiment: ChaosExperiment, history: list[Prior]) -> dict[str, Any]:
    covered_axes = _covered_axes(history)
    missing_axes = sorted(set(experiment.capability_axes) - covered_axes)
    return {
        "base_weight": experiment.weight,
        "adaptive_weight": round(_adaptive_weight(experiment, history), 4),
        "missing_capability_axes": missing_axes,
        "coverage_driven": bool(missing_axes),
        "coverage_first": bool(missing_axes),
    }


def _covered_axes(history: list[Prior]) -> set[str]:
    return {
        axis
        for prior in history
        for axis in prior.capability_axes
        if prior.passed is not False
    }


def _passed_substrates(history: list[Prior]) -> set[str]:
    return {
        prior.substrate
        for prior in history
        if prior.passed is True and prior.substrate != "unknown"
    }


def _observation_delay_seconds(experiment: ChaosExperiment, hold_seconds: float) -> float:
    if experiment.observation_delay_seconds is not None:
        return max(0.0, experiment.observation_delay_seconds)
    return max(0.0, hold_seconds)


def _score_event(experiment: ChaosExperiment, event: dict[str, Any]) -> dict[str, Any]:
    if event.get("error"):
        return {
            "passed": False,
            "reason": "injection_or_mesh_error",
            "trigger_fired": False,
            "decision_type": None,
        }
    raw_mesh_run = event.get("mesh_run")
    mesh_run = cast(dict[str, Any], raw_mesh_run) if isinstance(raw_mesh_run, dict) else {}
    if mesh_run.get("timed_out"):
        return {
            "passed": False,
            "reason": "mesh_run_timeout",
            "trigger_fired": True,
            "decision_type": mesh_run.get("decision_type"),
        }
    stage = mesh_run.get("stage")
    decision_type = mesh_run.get("decision_type")
    trigger_fired = stage not in {"no_trigger", None} or decision_type is not None
    if "false_positive_probe" in experiment.tags:
        passed = (not trigger_fired) or decision_type == "no_action"
        return {
            "passed": passed,
            "reason": None if passed else "false_positive_remediation",
            "trigger_fired": trigger_fired,
            "decision_type": decision_type,
        }
    if not trigger_fired:
        passed = "no_action" in experiment.expected_decisions
        return {
            "passed": passed,
            "reason": None if passed else "missed_fault",
            "trigger_fired": False,
            "decision_type": None,
        }
    passed = decision_type in experiment.expected_decisions
    return {
        "passed": passed,
        "reason": None if passed else "unexpected_decision",
        "trigger_fired": trigger_fired,
        "decision_type": decision_type,
    }


def _session_summary(
    events_path: Path,
    events: list[dict[str, Any]],
    *,
    configured_substrates: set[str] | None = None,
) -> dict[str, Any]:
    scored = [event for event in events if isinstance(event.get("score"), dict)]
    passed = [event for event in scored if event["score"].get("passed") is True]
    pipeline_attempts = [
        event for event in scored if isinstance(event.get("mesh_run"), dict)
    ]
    pipeline_completed = [
        event for event in pipeline_attempts if not event["mesh_run"].get("timed_out")
    ]
    regular = [
        event for event in scored if "false_positive_probe" not in set(event.get("tags") or [])
    ]
    trigger_expected = [
        event for event in regular if "no_action" not in set(event.get("expected_decisions") or [])
    ]
    probes = [
        event for event in scored if "false_positive_probe" in set(event.get("tags") or [])
    ]
    multi_fault = [
        event for event in scored if "multi_fault" in set(event.get("tags") or [])
    ]
    multi_fault_passed = [
        event for event in multi_fault if event["score"].get("passed") is True
    ]
    known_multi_fault_experiments = {
        experiment.name for experiment in DEFAULT_PORTFOLIO if "multi_fault" in experiment.tags
    }
    passed_multi_fault_experiments = {
        event["experiment"]
        for event in multi_fault_passed
        if isinstance(event.get("experiment"), str)
    }
    detection_hits = sum(1 for event in trigger_expected if event["score"].get("trigger_fired"))
    correct_hits = sum(1 for event in regular if event["score"].get("passed"))
    false_positive_hits = sum(
        1
        for event in probes
        if event["score"].get("trigger_fired") and event["score"].get("decision_type") != "no_action"
    )
    axes_exercised = {
        axis
        for event in scored
        for axis in event.get("capability_axes", [])
    }
    axes_passed = {
        axis
        for event in passed
        for axis in event.get("capability_axes", [])
    }
    substrate_coverage = _substrate_coverage(scored, configured_substrates=configured_substrates)
    all_axes = set(CAPABILITY_AXES)
    coverage_rate = (len(axes_passed) / len(all_axes)) if all_axes else 1.0
    detection_rate = (detection_hits / len(trigger_expected)) if trigger_expected else 1.0
    correct_decision_rate = (correct_hits / len(regular)) if regular else 0.0
    false_positive_rate = (false_positive_hits / len(probes)) if probes else 0.0
    pipeline_availability = (
        len(pipeline_completed) / len(pipeline_attempts)
    ) if pipeline_attempts else 1.0
    breakthrough_ready = (
        bool(scored)
        and coverage_rate >= 0.85
        and detection_rate >= 0.90
        and correct_decision_rate >= 0.85
        and false_positive_rate <= 0.10
        and pipeline_availability >= 0.99
    )
    return {
        "schema_version": "mesh.compose_chaos_summary.v1",
        "events_path": str(events_path),
        "generated_at": _now(),
        "experiments_total": len(scored),
        "experiments_passed": len(passed),
        "metrics": {
            "capability_axis_pass_rate": round(coverage_rate, 4),
            "detection_rate": round(detection_rate, 4),
            "correct_decision_rate": round(correct_decision_rate, 4),
            "false_positive_rate": round(false_positive_rate, 4),
            "pipeline_availability": round(pipeline_availability, 4),
        },
        "capabilities": {
            "known_axes": sorted(all_axes),
            "exercised_axes": sorted(axes_exercised),
            "passed_axes": sorted(axes_passed),
            "missing_axes": sorted(all_axes - axes_exercised),
            "failed_or_unproven_axes": sorted(all_axes - axes_passed),
        },
        "substrate_coverage": substrate_coverage,
        "multi_fault_coverage": {
            "known_experiments": sorted(known_multi_fault_experiments),
            "attempted": len(multi_fault),
            "passed": len(multi_fault_passed),
            "experiments": sorted(passed_multi_fault_experiments),
            "missing_experiments": sorted(known_multi_fault_experiments - passed_multi_fault_experiments),
        },
        "breakthrough_probe": {
            "schema_version": "mesh.chaos_breakthrough_probe.v1",
            "status": "breakthrough_signal" if breakthrough_ready else "below_threshold",
            "ready": breakthrough_ready,
            "thresholds": {
                "capability_axis_pass_rate": 0.85,
                "detection_rate": 0.90,
                "correct_decision_rate": 0.85,
                "false_positive_rate_max": 0.10,
                "pipeline_availability": 0.99,
            },
        },
    }


def _substrate_coverage(
    events: list[dict[str, Any]],
    *,
    configured_substrates: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    observed_substrates = {
        target.get("substrate")
        for event in events
        if isinstance(event.get("target"), dict)
        for target in [cast(dict[str, Any], event["target"])]
        if isinstance(target.get("substrate"), str)
    }
    substrates = set(configured_substrates or set()) | cast(set[str], observed_substrates)
    coverage: dict[str, dict[str, Any]] = {
        substrate: {
            "attempted": 0,
            "passed": 0,
            "experiments": [],
        }
        for substrate in sorted(substrates)
    }
    passed_experiments_by_substrate: dict[str, set[str]] = {substrate: set() for substrate in substrates}
    for event in events:
        target = event.get("target")
        if not isinstance(target, dict):
            continue
        substrate = target.get("substrate")
        if not isinstance(substrate, str):
            continue
        coverage.setdefault(substrate, {"attempted": 0, "passed": 0, "experiments": []})
        coverage[substrate]["attempted"] += 1
        score = event.get("score")
        if isinstance(score, dict) and score.get("passed") is True:
            coverage[substrate]["passed"] += 1
            experiment = event.get("experiment")
            if isinstance(experiment, str):
                passed_experiments_by_substrate.setdefault(substrate, set()).add(experiment)
    for substrate, experiments in passed_experiments_by_substrate.items():
        coverage.setdefault(substrate, {"attempted": 0, "passed": 0, "experiments": []})
        coverage[substrate]["experiments"] = sorted(experiments)
    return coverage


def _weighted_index(rng: random.Random, weights: list[float]) -> int:
    total = sum(weights)
    if total <= 0:
        return rng.randrange(len(weights))
    cursor = rng.uniform(0, total)
    accumulated = 0.0
    for index, weight in enumerate(weights):
        accumulated += weight
        if cursor <= accumulated:
            return index
    return len(weights) - 1


def _wait_for_target_ready(
    injector: ChaosInjector,
    target: Target,
    *,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        deployment = injector._kubectl_json(  # noqa: SLF001 - compose driver owns this harness integration.
            "get",
            "deployment",
            target.deployment,
            "-n",
            target.namespace,
            "-o",
            "json",
        )
        pods = injector._list_pods(target.deployment, target.namespace)  # noqa: SLF001
        spec = deployment.get("spec") or {}
        status = deployment.get("status") or {}
        desired = int(spec.get("replicas", 0) or 0)
        total = int(status.get("replicas", 0) or 0)
        updated = int(status.get("updatedReplicas", 0) or 0)
        ready = int(status.get("readyReplicas", 0) or 0)
        available = int(status.get("availableReplicas", 0) or 0)
        running_ready = [
            pod
            for pod in pods
            if pod.get("phase") == "Running" and _pod_ready(pod)
        ]
        last_state = {
            "desired_replicas": desired,
            "total_replicas": total,
            "updated_replicas": updated,
            "ready_replicas": ready,
            "available_replicas": available,
            "running_ready_pods": len(running_ready),
            "pod_count": len(pods),
            "pods": [
                {
                    "name": pod.get("name"),
                    "phase": pod.get("phase"),
                    "ready": _pod_ready(pod),
                }
                for pod in pods
            ],
        }
        if (
            desired > 0
            and total == desired
            and updated >= desired
            and ready >= desired
            and available >= desired
            and len(pods) == desired
            and len(running_ready) == desired
        ):
            return last_state
        time.sleep(2)
    raise ChaosError(
        f"target {target.context}/{target.namespace}/{target.deployment} did not become ready "
        f"within {timeout_seconds}s: {last_state}"
    )


def _pod_ready(pod: dict[str, Any]) -> bool:
    conditions = pod.get("conditions", [])
    if not isinstance(conditions, list):
        return False
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        if condition.get("type") == "Ready":
            return bool(condition.get("status") == "True")
    return False


def _launch_mesh_run(base_url: str, target: Target) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        **_operator_headers(),
    }
    payload = {
        "goal_id": "goal_default",
        "chaos_probe": True,
        "evaluation_mode": os.environ.get("MESH_STACK_CHAOS_EVALUATION_MODE", "native"),
        "orchestration_mode": os.environ.get("MESH_STACK_CHAOS_ORCHESTRATION_MODE", "native"),
        "steering_mode": os.environ.get("MESH_STACK_CHAOS_STEERING_MODE", "interruptible_auto"),
        "live_signal": {
            "source": "kubernetes",
            "deployment_name": target.deployment,
            "namespace": target.namespace,
            "kube_context": target.context,
            "environment": target.substrate,
        },
    }
    request = urllib.request.Request(
        f"{base_url}/api/runs",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    request_timeout_seconds = float(os.environ.get("MESH_STACK_CHAOS_REQUEST_TIMEOUT_SECONDS", "90"))
    with urllib.request.urlopen(request, timeout=request_timeout_seconds) as response:
        run = json.loads(response.read().decode("utf-8"))

    run_id = run["run_id"]
    wait_seconds = float(os.environ.get("MESH_STACK_CHAOS_RUN_WAIT_SECONDS", "600"))
    progress_grace_seconds = float(os.environ.get("MESH_STACK_CHAOS_RUN_PROGRESS_GRACE_SECONDS", "120"))
    stage_grace_seconds = float(os.environ.get("MESH_STACK_CHAOS_RUN_STAGE_GRACE_SECONDS", "600"))
    max_wait_seconds = float(os.environ.get("MESH_STACK_CHAOS_RUN_MAX_WAIT_SECONDS", "1800"))
    started = time.monotonic()
    deadline = started + wait_seconds
    hard_deadline = started + max(max_wait_seconds, wait_seconds)
    terminal = {"completed", "failed", "cancelled", "no_trigger", "awaiting_operator"}
    last_progress: tuple[Any, Any] | None = None
    last_progress_at = started
    current: dict[str, Any] = {"stage": "queued", "status": "queued"}
    request_timeouts = 0
    while True:
        now = time.monotonic()
        try:
            poll_request = urllib.request.Request(
                f"{base_url}/api/runs/{run_id}",
                headers=_operator_headers(),
                method="GET",
            )
            with urllib.request.urlopen(poll_request, timeout=request_timeout_seconds) as response:
                current = json.loads(response.read().decode("utf-8"))
        except (TimeoutError, socket.timeout):
            request_timeouts += 1
            if now >= deadline:
                return {
                    "run_id": run_id,
                    "stage": current.get("stage"),
                    "status": "timeout",
                    "wait_elapsed_seconds": round(now - started, 3),
                    "seconds_since_progress": round(now - last_progress_at, 3),
                    "request_timeouts": request_timeouts,
                    "timed_out": True,
                }
            time.sleep(2)
            continue
        progress = (current.get("stage"), current.get("status"))
        if progress != last_progress:
            last_progress = progress
            last_progress_at = now
            stage = current.get("stage")
            grace = stage_grace_seconds if stage in _LONG_RUNNING_RUN_STAGES else progress_grace_seconds
            deadline = min(hard_deadline, max(deadline, now + grace))
        if current.get("stage") in terminal:
            artifacts = current.get("artifacts") or {}
            decision_type = (artifacts.get("decision") or {}).get("decision_type")
            released = False
            if current.get("stage") == "awaiting_operator":
                released = _cancel_scored_probe_run(base_url, run_id, request_timeout_seconds)
            return {
                "run_id": run_id,
                "stage": current.get("stage"),
                "status": current.get("status"),
                "decision_type": decision_type,
                "released_after_score": released,
                "wait_elapsed_seconds": round(now - started, 3),
                "request_timeouts": request_timeouts,
                "timed_out": False,
            }
        if now >= deadline:
            return {
                "run_id": run_id,
                "stage": current.get("stage"),
                "status": "timeout",
                "wait_elapsed_seconds": round(now - started, 3),
                "seconds_since_progress": round(now - last_progress_at, 3),
                "request_timeouts": request_timeouts,
                "timed_out": True,
            }
        time.sleep(2)


def _cancel_scored_probe_run(base_url: str, run_id: str, request_timeout_seconds: float) -> bool:
    payload = {"command": "cancel", "reason": "compose_chaos_probe_scored"}
    request = urllib.request.Request(
        f"{base_url}/api/runs/{run_id}/steer",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **_operator_headers(),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=request_timeout_seconds) as response:
            run = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        return False
    return run.get("stage") in {"cancelled", "awaiting_operator"}


def _operator_headers() -> dict[str, str]:
    operator_header = os.environ.get("MESH_OPERATOR_HEADER", "X-Mesh-Operator")
    roles_header = os.environ.get("MESH_OPERATOR_ROLES_HEADER", "X-Mesh-Roles")
    operator_id = os.environ.get(
        "MESH_STACK_CHAOS_OPERATOR_ID",
        os.environ.get("MESH_E2E_OPERATOR_ID", "mesh-compose-chaos"),
    )
    operator_roles = os.environ.get(
        "MESH_STACK_CHAOS_OPERATOR_ROLES",
        os.environ.get("MESH_E2E_OPERATOR_ROLES", "launcher,viewer"),
    )
    return {
        operator_header: operator_id,
        roles_header: operator_roles,
    }


def _wait_for_mesh(base_url: str) -> None:
    deadline = time.time() + 240
    while True:
        try:
            with urllib.request.urlopen(f"{base_url}/api/health", timeout=5) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        if time.time() >= deadline:
            raise SystemExit("mesh did not become healthy before chaos session")
        time.sleep(2)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _target_key(target: Target) -> str:
    return f"{target.context}/{target.namespace}/{target.deployment}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stamp_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    raise SystemExit(main())
