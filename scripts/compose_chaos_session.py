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
from typing import Any
from urllib.error import URLError

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
    output_root = Path(os.environ.get("MESH_STACK_CHAOS_OUTPUT_DIR", "/workspace/mesh-intel/.mesh-runtime-state/compose-chaos"))
    output_root.mkdir(parents=True, exist_ok=True)

    _wait_for_mesh(base_url)
    rng = random.Random(seed)
    history: list[Prior] = []
    session_events: list[dict[str, Any]] = []
    started = time.monotonic()
    deadline = started + duration
    events_path = output_root / f"events-{_stamp_compact()}.jsonl"
    summary_path = events_path.with_name(events_path.name.replace("events-", "summary-").replace(".jsonl", ".json"))

    print(json.dumps({
        "event": "session_started",
        "targets": [target.__dict__ for target in targets],
        "duration_seconds": duration,
        "seed": seed,
        "output": str(events_path),
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
        }
        try:
            _wait_for_target_ready(injector, target)
            result = getattr(injector, f"inject_{experiment.name}")(target.deployment, target.namespace)
            event["injection"] = {
                "mode": result.mode,
                "injected_at": result.injected_at,
                "observed_at": result.observed_at,
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
        history.append(
            Prior(
                experiment.name,
                _target_key(target),
                experiment.severity,
                now,
                experiment.capability_axes,
                bool(event["score"].get("passed")),
            )
        )
        _append_jsonl(events_path, event)
        session_events.append(event)
        summary = _session_summary(events_path, session_events)
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(event, sort_keys=True), flush=True)
        if stop_on_breakthrough and summary["breakthrough_probe"]["ready"]:
            break
        time.sleep(rng.uniform(min_sleep, max_sleep))

    summary = _session_summary(events_path, session_events)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "event": "session_completed",
        "observed_at": _now(),
        "output": str(events_path),
        "summary": str(summary_path),
        "breakthrough_probe": summary["breakthrough_probe"],
    }, sort_keys=True), flush=True)
    return 0


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


def _pick(
    rng: random.Random,
    targets: list[Target],
    history: list[Prior],
    now: float,
    *,
    coverage_first: bool = True,
) -> tuple[ChaosExperiment, Target] | None:
    last_high = next((prior.completed_at for prior in reversed(history) if prior.severity in {SEVERITY_HIGH, SEVERITY_SEVERE}), None)
    eligible: list[tuple[ChaosExperiment, Target]] = []
    weights: list[float] = []
    for experiment in DEFAULT_PORTFOLIO:
        if experiment.severity in {SEVERITY_HIGH, SEVERITY_SEVERE} and last_high is not None and now - last_high < 60:
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
    frontier: list[tuple[int, int, float, str, str, tuple[ChaosExperiment, Target]]] = []
    for experiment, target in eligible:
        missing_axes = set(experiment.capability_axes) - covered_axes
        if not missing_axes:
            continue
        never_attempted = 1 if experiment.name not in attempted_experiments else 0
        frontier.append((
            len(missing_axes),
            never_attempted,
            experiment.weight,
            experiment.name,
            _target_key(target),
            (experiment, target),
        ))
    if not frontier:
        return None
    frontier.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3], item[4]))
    return frontier[0][5]


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
    mesh_run = event.get("mesh_run") if isinstance(event.get("mesh_run"), dict) else {}
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


def _session_summary(events_path: Path, events: list[dict[str, Any]]) -> dict[str, Any]:
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
            and len(running_ready) == desired
        ):
            return last_state
        time.sleep(2)
    raise ChaosError(
        f"target {target.context}/{target.namespace}/{target.deployment} did not become ready "
        f"within {timeout_seconds}s: {last_state}"
    )


def _pod_ready(pod: dict[str, Any]) -> bool:
    for condition in pod.get("conditions", []):
        if condition.get("type") == "Ready":
            return condition.get("status") == "True"
    return False


def _launch_mesh_run(base_url: str, target: Target) -> dict[str, Any]:
    payload = {
        "goal_id": "goal_default",
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
        headers={"Content-Type": "application/json"},
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
            with urllib.request.urlopen(f"{base_url}/api/runs/{run_id}", timeout=request_timeout_seconds) as response:
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
            return {
                "run_id": run_id,
                "stage": current.get("stage"),
                "status": current.get("status"),
                "decision_type": (artifacts.get("decision") or {}).get("decision_type"),
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
