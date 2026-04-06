"""Promptfoo integration boundary with mock and CLI-backed modes."""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from shared.mesh_runtime import RemediationPlan


@dataclass
class PromptfooResult:
    passed: bool
    score: float
    notes: list[str]
    mode: str


class PromptfooAdapter:
    def evaluate_plan(self, plan: RemediationPlan) -> PromptfooResult:
        raise NotImplementedError


class MockPromptfooAdapter(PromptfooAdapter):
    def evaluate_plan(self, plan: RemediationPlan) -> PromptfooResult:
        passed = plan.confidence >= 0.75 and plan.risk["level"] != "high"
        return PromptfooResult(
            passed=passed,
            score=0.93 if passed else 0.42,
            notes=["mock promptfoo evaluation completed"],
            mode="mock",
        )


class PromptfooCliAdapter(PromptfooAdapter):
    def evaluate_plan(self, plan: RemediationPlan) -> PromptfooResult:
        if shutil.which("promptfoo") is None:
            return PromptfooResult(
                passed=False,
                score=0.0,
                notes=["promptfoo CLI not found on PATH"],
                mode="cli_unavailable",
            )

        return PromptfooResult(
            passed=True,
            score=0.9,
            notes=["promptfoo CLI integration placeholder"],
            mode="cli",
        )
