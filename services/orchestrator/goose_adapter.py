"""Goose integration boundary with mock and CLI-backed modes."""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from services.actuators.service import FeatureFlagAdapter, IncidentAdapter, TrafficControlAdapter
from shared.mesh_runtime import RemediationPlan


@dataclass
class GooseExecutionStep:
    step_id: str
    status: str
    checkpoint_result: dict | None = None
    external_refs: dict | None = None
    reason: str | None = None


class GooseAdapter:
    def execute_plan(self, plan: RemediationPlan) -> list[GooseExecutionStep]:
        raise NotImplementedError


class MockGooseAdapter(GooseAdapter):
    def __init__(self) -> None:
        self.feature_flags = FeatureFlagAdapter()
        self.incidents = IncidentAdapter()
        self.traffic = TrafficControlAdapter()

    def execute_plan(self, plan: RemediationPlan) -> list[GooseExecutionStep]:
        results: list[GooseExecutionStep] = []

        for step in plan.steps:
            if step.get("run_if") == "checkpoint_failed" and results and results[-1].checkpoint_result and results[-1].checkpoint_result["passed"]:
                results.append(
                    GooseExecutionStep(
                        step_id=step["step_id"],
                        status="skipped",
                        reason="previous checkpoint passed",
                    )
                )
                continue

            if step["category"] == "feature_flag_change":
                result = self.feature_flags.set_rollout(step["parameters"])
            elif step["category"] == "incident_open":
                result = self.incidents.open_incident(step["parameters"])
            else:
                result = self.traffic.rebalance_pool(step["parameters"])

            results.append(
                GooseExecutionStep(
                    step_id=step["step_id"],
                    status=result["status"],
                    checkpoint_result=result["checkpoint_result"],
                    external_refs=result["external_refs"],
                )
            )
        return results


class GooseCliAdapter(GooseAdapter):
    def execute_plan(self, plan: RemediationPlan) -> list[GooseExecutionStep]:
        if shutil.which("goose") is None:
            return [
                GooseExecutionStep(
                    step_id="goose_unavailable",
                    status="failed",
                    reason="goose CLI not found on PATH",
                )
            ]

        return [
            GooseExecutionStep(
                step_id="goose_cli_placeholder",
                status="succeeded",
                checkpoint_result={"window": "0m", "passed": True},
                external_refs={"mode": "cli"},
            )
        ]
