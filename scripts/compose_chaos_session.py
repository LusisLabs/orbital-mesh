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
from tests.e2e.chaos.portfolio import DEFAULT_PORTFOLIO, SEVERITY_HIGH, SEVERITY_SEVERE, ChaosExperiment


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
    output_root = Path(os.environ.get("MESH_STACK_CHAOS_OUTPUT_DIR", "/workspace/mesh-intel/.mesh-runtime-state/compose-chaos"))
    output_root.mkdir(parents=True, exist_ok=True)

    _wait_for_mesh(base_url)
    rng = random.Random(seed)
    history: list[Prior] = []
    started = time.monotonic()
    deadline = started + duration
    events_path = output_root / f"events-{_stamp_compact()}.jsonl"

    print(json.dumps({
        "event": "session_started",
        "targets": [target.__dict__ for target in targets],
        "duration_seconds": duration,
        "seed": seed,
        "output": str(events_path),
    }, sort_keys=True), flush=True)

    while time.monotonic() < deadline:
        now = time.monotonic() - started
        pick = _pick(rng, targets, history, now)
        if pick is None:
            time.sleep(min_sleep)
            continue
        experiment, target = pick
        injector = ChaosInjector(kube_context=target.context, timeout_seconds=45)
        event: dict[str, Any] = {
            "event": "chaos_cycle",
            "observed_at": _now(),
            "experiment": experiment.name,
            "severity": experiment.severity,
            "target": target.__dict__,
        }
        try:
            result = getattr(injector, f"inject_{experiment.name}")(target.deployment, target.namespace)
            event["injection"] = {
                "mode": result.mode,
                "injected_at": result.injected_at,
                "observed_at": result.observed_at,
            }
            time.sleep(hold_seconds)
            event["mesh_run"] = _launch_mesh_run(base_url, target)
        except (ChaosError, URLError, TimeoutError, OSError) as exc:
            event["error"] = repr(exc)
        finally:
            injector.revert_all()
        history.append(Prior(experiment.name, _target_key(target), experiment.severity, now))
        _append_jsonl(events_path, event)
        print(json.dumps(event, sort_keys=True), flush=True)
        time.sleep(rng.uniform(min_sleep, max_sleep))

    print(json.dumps({"event": "session_completed", "observed_at": _now(), "output": str(events_path)}, sort_keys=True), flush=True)
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


def _pick(rng: random.Random, targets: list[Target], history: list[Prior], now: float) -> tuple[ChaosExperiment, Target] | None:
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
            weights.append(experiment.weight)
    if not eligible:
        return None
    return eligible[_weighted_index(rng, weights)]


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
