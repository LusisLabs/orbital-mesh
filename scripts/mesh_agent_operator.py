#!/usr/bin/env python3
"""Bounded non-human operator for Mesh evaluation gates."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any


DEFAULT_AGENT_PRIORITY = ("hermes", "goose", "codex", "claudecode", "openclaw", "evo", "latentmas")
SAFE_EXECUTION_READINESS_NOTES = {"confidence below minimum threshold"}
SAFE_BUSINESS_NOTES = {"approval required before execution"}
SAFE_SAFETY_HARD_STOPS = {"execution readiness failed"}


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _json_request(method: str, url: str, payload: dict[str, Any] | None = None, timeout: float = 10.0) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, sort_keys=True).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def _parse_priority(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return DEFAULT_AGENT_PRIORITY
    parsed = tuple(item.strip().lower() for item in raw.split(",") if item.strip())
    return parsed or DEFAULT_AGENT_PRIORITY


def _run_age_seconds(run: dict[str, Any], now: datetime | None = None) -> float | None:
    created_at = run.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        return None
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    current = now or datetime.now(timezone.utc)
    return (current - parsed).total_seconds()


def _attempt_is_qualified(attempt: dict[str, Any]) -> bool:
    if attempt.get("error"):
        return False
    status = str(attempt.get("status") or "").strip().lower()
    if status and status not in {"completed", "success", "succeeded", "ok"}:
        return False
    if not status and not attempt.get("completed_at"):
        return False
    top_level_flags = {str(flag).lower() for flag in attempt.get("risk_flags", []) if flag}
    if any("unparseable" in flag for flag in top_level_flags):
        return False
    output = attempt.get("output")
    if isinstance(output, dict):
        output_status = str(output.get("status") or "").strip().lower()
        if output_status in {"failed", "error", "cancelled"}:
            return False
        output_flags = {str(flag).lower() for flag in output.get("risk_flags", []) if flag}
        if any("unparseable" in flag for flag in output_flags):
            return False
    return True


def select_operator_agent(tasks: list[dict[str, Any]], priority: tuple[str, ...]) -> str:
    attempts_by_agent: dict[str, dict[str, Any]] = {}
    for task in tasks:
        for raw_attempt in task.get("attempts", []):
            if not isinstance(raw_attempt, dict):
                continue
            agent = str(raw_attempt.get("agent") or "").strip().lower()
            if agent and _attempt_is_qualified(raw_attempt):
                attempts_by_agent.setdefault(agent, raw_attempt)
    for agent in priority:
        if agent in attempts_by_agent:
            return agent
    return "native_mesh"


def _notes_subset(stage_results: dict[str, Any], key: str, allowed: set[str]) -> bool:
    check = stage_results.get(key)
    if not isinstance(check, dict):
        return False
    notes = {str(note) for note in check.get("notes", [])}
    return notes.issubset(allowed)


def _hard_stops_subset(stage_results: dict[str, Any], allowed: set[str]) -> bool:
    safety = stage_results.get("remediation_safety")
    if not isinstance(safety, dict):
        return False
    hard_stops = {str(stop) for stop in safety.get("hard_stops", [])}
    return hard_stops.issubset(allowed)


def run_is_safe_for_agent_override(run: dict[str, Any]) -> bool:
    artifacts = run.get("artifacts") if isinstance(run.get("artifacts"), dict) else {}
    evaluation = artifacts.get("evaluation") if isinstance(artifacts.get("evaluation"), dict) else {}
    decision = artifacts.get("decision") if isinstance(artifacts.get("decision"), dict) else {}
    stage_results = evaluation.get("stage_results") if isinstance(evaluation.get("stage_results"), dict) else {}
    policy = stage_results.get("policy_validation") if isinstance(stage_results.get("policy_validation"), dict) else {}
    schema = stage_results.get("schema_validation") if isinstance(stage_results.get("schema_validation"), dict) else {}
    risk = decision.get("risk") if isinstance(decision.get("risk"), dict) else {}
    plan = decision.get("execution_plan") if isinstance(decision.get("execution_plan"), dict) else {}
    if run.get("stage") != "awaiting_operator" or run.get("pending_pause_stage") != "evaluation_ready":
        return False
    if evaluation.get("final_recommendation") != "human_review":
        return False
    if not schema.get("passed") or not policy.get("passed"):
        return False
    if risk.get("level") == "high":
        return False
    if not plan.get("rollback_plan"):
        return False
    if not _notes_subset(stage_results, "business_rules", SAFE_BUSINESS_NOTES):
        return False
    if not _notes_subset(stage_results, "execution_readiness", SAFE_EXECUTION_READINESS_NOTES):
        return False
    return _hard_stops_subset(stage_results, SAFE_SAFETY_HARD_STOPS)


def build_override_payload(
    run: dict[str, Any],
    *,
    operator_agent: str,
    confidence_floor: float,
    autonomy_tier: str,
) -> dict[str, Any]:
    decision = run.get("artifacts", {}).get("decision", {})
    current_confidence = float(decision.get("confidence") or 0.0)
    confidence = min(1.0, max(current_confidence, confidence_floor))
    return {
        "command": "override_decision",
        "summary": (
            f"Agent operator {operator_agent} accepted full-auto execution after "
            "Mesh verifier, policy, and readiness checks."
        ),
        "autonomy_tier": autonomy_tier,
        "confidence": confidence,
        "operator_agent": operator_agent,
        "operator_mode": "full_auto",
    }


def _poll_once(
    *,
    base_url: str,
    timeout: float,
    priority: tuple[str, ...],
    confidence_floor: float,
    autonomy_tier: str,
    existing_run_max_age_seconds: float,
    acted: set[str],
) -> None:
    runs = _json_request("GET", f"{base_url}/api/runs?summary=1", timeout=timeout).get("runs", [])
    for item in runs:
        run_id = str(item.get("run_id") or "")
        if not run_id or run_id in acted:
            continue
        if item.get("stage") != "awaiting_operator":
            continue
        age_seconds = _run_age_seconds(item)
        if age_seconds is not None and age_seconds > existing_run_max_age_seconds:
            acted.add(run_id)
            continue
        run = _json_request("GET", f"{base_url}/api/runs/{run_id}", timeout=timeout)
        if not run_is_safe_for_agent_override(run):
            continue
        tasks = _json_request("GET", f"{base_url}/api/runs/{run_id}/agent-tasks", timeout=timeout).get("tasks", [])
        operator_agent = select_operator_agent(tasks if isinstance(tasks, list) else [], priority)
        payload = build_override_payload(
            run,
            operator_agent=operator_agent,
            confidence_floor=confidence_floor,
            autonomy_tier=autonomy_tier,
        )
        acted.add(run_id)
        try:
            _json_request("POST", f"{base_url}/api/runs/{run_id}/steer", payload, timeout=timeout)
            print(
                json.dumps(
                    {
                        "event": "agent_operator_override",
                        "run_id": run_id,
                        "operator_agent": operator_agent,
                    }
                ),
                flush=True,
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            print(
                json.dumps(
                    {
                        "event": "agent_operator_override_submitted",
                        "run_id": run_id,
                        "operator_agent": operator_agent,
                        "response_error": str(exc),
                    }
                ),
                flush=True,
            )


def main() -> int:
    if not _bool_env("MESH_AGENT_OPERATOR_ENABLED", True):
        print(json.dumps({"event": "agent_operator_disabled"}), flush=True)
        return 0
    base_url = os.getenv("BASE_URL", "http://127.0.0.1:8787").rstrip("/")
    interval = _float_env("MESH_AGENT_OPERATOR_INTERVAL_SECONDS", 3.0)
    timeout = _float_env("MESH_AGENT_OPERATOR_REQUEST_TIMEOUT_SECONDS", 10.0)
    priority = _parse_priority(os.getenv("MESH_AGENT_OPERATOR_PRIORITY"))
    confidence_floor = _float_env("MESH_AGENT_OPERATOR_CONFIDENCE_FLOOR", 0.86)
    autonomy_tier = os.getenv("MESH_AGENT_OPERATOR_AUTONOMY_TIER", "escalated")
    existing_run_max_age_seconds = _float_env("MESH_AGENT_OPERATOR_EXISTING_RUN_MAX_AGE_SECONDS", 3600.0)
    acted: set[str] = set()
    print(
        json.dumps(
            {
                "event": "agent_operator_started",
                "base_url": base_url,
                "priority": priority,
                "confidence_floor": confidence_floor,
                "autonomy_tier": autonomy_tier,
            }
        ),
        flush=True,
    )
    while True:
        try:
            _poll_once(
                base_url=base_url,
                timeout=timeout,
                priority=priority,
                confidence_floor=confidence_floor,
                autonomy_tier=autonomy_tier,
                existing_run_max_age_seconds=existing_run_max_age_seconds,
                acted=acted,
            )
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            print(json.dumps({"event": "agent_operator_poll_failed", "error": str(exc)}), flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
