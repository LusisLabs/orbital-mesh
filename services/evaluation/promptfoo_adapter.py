"""Promptfoo integration boundary with native and CLI-backed modes."""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from shared.mesh_runtime import Decision, Trigger


MESH_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class PromptfooResult:
    passed: bool
    score: float
    notes: list[str]
    mode: str
    artifacts: dict | None = None


class PromptfooAdapter:
    def evaluate_decision(self, trigger: Trigger, decision: Decision) -> PromptfooResult:
        raise NotImplementedError


class NativePromptfooAdapter(PromptfooAdapter):
    def evaluate_decision(self, trigger: Trigger, decision: Decision) -> PromptfooResult:
        return evaluate_decision_contract(trigger, decision, mode="native")


class PromptfooCliAdapter(PromptfooAdapter):
    def __init__(self, command: str | None = None):
        self.command = command

    def evaluate_decision(self, trigger: Trigger, decision: Decision) -> PromptfooResult:
        payload = json.dumps({"trigger": trigger.to_dict(), "decision": decision.to_dict()})
        command = self._resolve_command()
        try:
            completed = subprocess.run(
                command,
                input=payload,
                capture_output=True,
                text=True,
                cwd=MESH_ROOT,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return PromptfooResult(
                passed=False,
                score=0.0,
                notes=[f"promptfoo subprocess failed: {exc}"],
                mode="cli_error",
            )

        if completed.returncode != 0:
            stderr = completed.stderr.strip() or "promptfoo subprocess returned a non-zero exit code"
            return PromptfooResult(
                passed=False,
                score=0.0,
                notes=[stderr],
                mode="cli_error",
            )

        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            return PromptfooResult(
                passed=False,
                score=0.0,
                notes=[f"promptfoo subprocess returned invalid JSON: {exc}"],
                mode="cli_error",
            )

        return PromptfooResult(
            passed=bool(result["passed"]),
            score=float(result["score"]),
            notes=list(result["notes"]),
            mode=result.get("mode", "cli"),
            artifacts=result.get("artifacts"),
        )

    def _resolve_command(self) -> list[str]:
        if not self.command:
            raise OSError("promptfoo command is not configured")
        return shlex.split(self.command)


def evaluate_decision_contract(trigger: Trigger, decision: Decision, mode: str) -> PromptfooResult:
    notes: list[str] = []
    assertion_results: list[dict[str, object]] = []
    passed = True

    def add_check(name: str, condition: bool, success_reason: str, failure_reason: str) -> None:
        nonlocal passed
        if condition:
            notes.append(success_reason)
            assertion_results.append({"name": name, "passed": True, "reason": success_reason, "score": 1.0})
        else:
            passed = False
            notes.append(failure_reason)
            assertion_results.append({"name": name, "passed": False, "reason": failure_reason, "score": 0.0})

    add_check(
        "confidence_threshold",
        decision.confidence >= 0.75,
        "confidence meets the minimum threshold",
        "confidence is below the minimum threshold",
    )
    add_check(
        "risk_threshold",
        decision.risk["level"] != "high",
        "risk remains inside the automated boundary",
        "risk is too high for automated execution",
    )
    add_check(
        "grounded_regression",
        _grounded_regression(trigger),
        "reasoning references observed metrics",
        "reasoning is not grounded in an observed regression",
    )
    add_check(
        "allowed_action",
        decision.execution_plan["action"]
        in {
            "set_rollout",
            "open_incident",
            "record_no_action",
            "investigate_and_patch",
            "rollback_deployment",
            "restart_deployment",
        },
        "action matches allowed contract",
        "action falls outside the allowed contract",
    )
    return PromptfooResult(
        passed=passed,
        score=0.93 if passed else 0.42,
        notes=notes,
        mode=mode,
        artifacts={
            "assertion_results": assertion_results,
            "provider": mode,
        },
    )


def _grounded_regression(trigger: Trigger) -> bool:
    if trigger.trigger_type == "kubernetes_deployment_unhealthy":
        error_signatures = trigger.related_context.get("error_signatures", [])
        rollout_status = trigger.related_context.get("rollout_status")
        restarts = trigger.metrics.get("restart_count_total") or 0
        return rollout_status in {"degraded", "failed"} or bool(error_signatures) or restarts > 0
    baseline = trigger.metrics["baseline_p95_latency_ms"]
    observed = trigger.metrics["observed_p95_latency_ms"]
    if baseline is None or observed is None:
        return False
    return observed > baseline
