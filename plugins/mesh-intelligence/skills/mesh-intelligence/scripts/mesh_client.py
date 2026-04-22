#!/usr/bin/env python3
"""Read-only Mesh Intelligence API helper for Codex workers."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:8787"
DEFAULT_TIMEOUT_SECONDS = 5.0


def _base_url(raw: str | None = None) -> str:
    return (raw or os.getenv("MESH_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def _get_json(base_url: str, path: str, timeout: float) -> dict[str, Any]:
    url = f"{base_url}{path}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Mesh API returned HTTP {exc.code} for {path}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach Mesh API at {url}: {exc}") from exc
    return json.loads(body)


def _latest_run_id(base_url: str, timeout: float) -> str:
    runs = _get_json(base_url, "/api/runs", timeout).get("runs", [])
    if not runs:
        raise SystemExit("Mesh API returned no runs.")
    return str(runs[0]["run_id"])


def _summarize_agent_tasks(payload: dict[str, Any]) -> dict[str, Any]:
    tasks = payload.get("tasks")
    stale_route = False
    if tasks is None:
        stale_route = "run_id" in payload and "artifacts" in payload
        tasks = payload.get("artifacts", {}).get("agent_tasks", [])
    if not isinstance(tasks, list):
        tasks = []

    agents_seen: list[str] = []
    selected_attempts: list[str] = []
    risk_flags: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        selected = task.get("selected_attempt_id")
        if selected:
            selected_attempts.append(str(selected))
        for attempt in task.get("attempts", []):
            if not isinstance(attempt, dict):
                continue
            agent = attempt.get("agent")
            if agent and str(agent) not in agents_seen:
                agents_seen.append(str(agent))
            for flag in attempt.get("risk_flags", []):
                if str(flag) not in risk_flags:
                    risk_flags.append(str(flag))

    return {
        "task_count": len(tasks),
        "agents_seen": agents_seen,
        "selected_attempts": selected_attempts,
        "risk_flags": risk_flags,
        "stale_agent_tasks_route": stale_route,
    }


def _summary(base_url: str, run_id: str | None, timeout: float) -> dict[str, Any]:
    health = _get_json(base_url, "/api/health", timeout)
    selected_run_id = run_id or _latest_run_id(base_url, timeout)
    encoded_run_id = urllib.parse.quote(selected_run_id)
    run = _get_json(base_url, f"/api/runs/{encoded_run_id}", timeout)
    agent_payload = _get_json(base_url, f"/api/runs/{encoded_run_id}/agent-tasks", timeout)
    artifacts = run.get("artifacts", {})
    decision = artifacts.get("decision", {})
    evaluation = artifacts.get("evaluation", {})
    execution = artifacts.get("execution", {})
    feedback = artifacts.get("feedback", {})
    agent_summary = _summarize_agent_tasks(agent_payload)
    return {
        "connected": health.get("status") == "ok",
        "mesh_status": health.get("status"),
        "environment": health.get("environment"),
        "version": health.get("version"),
        "commit": health.get("commit"),
        "run": {
            "run_id": run.get("run_id", selected_run_id),
            "scenario_key": run.get("scenario_key"),
            "stage": run.get("stage"),
            "status": run.get("status"),
            "orchestration_mode": run.get("orchestration_mode"),
            "evaluation_mode": run.get("evaluation_mode"),
        },
        "decision": {
            "decision_type": decision.get("decision_type"),
            "summary": decision.get("summary"),
        },
        "evaluation": {
            "passed": evaluation.get("passed"),
            "final_recommendation": evaluation.get("final_recommendation"),
            "blocking_reasons": evaluation.get("blocking_reasons", []),
        },
        "execution": {
            "status": execution.get("status"),
            "executor": execution.get("executor"),
        },
        "feedback": {
            "outcome": feedback.get("outcome"),
            "recommended_follow_up": feedback.get("recommended_follow_up"),
        },
        "agent_tasks": agent_summary,
    }


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Read Mesh Intelligence API state.")
    parser.add_argument("--base-url", default=None, help="Mesh base URL. Defaults to MESH_BASE_URL or http://127.0.0.1:8787.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health")
    subparsers.add_parser("readiness")
    subparsers.add_parser("runs")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--run-id", required=True)

    events_parser = subparsers.add_parser("events")
    events_parser.add_argument("--run-id", required=True)

    tasks_parser = subparsers.add_parser("agent-tasks")
    tasks_parser.add_argument("--run-id", required=True)

    summary_parser = subparsers.add_parser("summary")
    summary_parser.add_argument("--run-id")

    args = parser.parse_args()
    base_url = _base_url(args.base_url)

    if args.command == "health":
        _print_json(_get_json(base_url, "/api/health", args.timeout))
    elif args.command == "readiness":
        _print_json(_get_json(base_url, "/api/readiness", args.timeout))
    elif args.command == "runs":
        payload = _get_json(base_url, "/api/runs", args.timeout)
        runs = payload.get("runs", [])
        _print_json(
            {
                "run_count": len(runs),
                "runs": [
                    {
                        "run_id": run.get("run_id"),
                        "scenario_key": run.get("scenario_key"),
                        "stage": run.get("stage"),
                        "status": run.get("status"),
                    }
                    for run in runs
                ],
            }
        )
    elif args.command == "run":
        _print_json(_get_json(base_url, f"/api/runs/{urllib.parse.quote(args.run_id)}", args.timeout))
    elif args.command == "events":
        _print_json(_get_json(base_url, f"/api/runs/{urllib.parse.quote(args.run_id)}/events", args.timeout))
    elif args.command == "agent-tasks":
        payload = _get_json(base_url, f"/api/runs/{urllib.parse.quote(args.run_id)}/agent-tasks", args.timeout)
        _print_json(_summarize_agent_tasks(payload))
    elif args.command == "summary":
        _print_json(_summary(base_url, args.run_id, args.timeout))
    else:
        parser.error(f"unknown command: {args.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
