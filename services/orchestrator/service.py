"""Execute approved plans through a Goose integration boundary."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable

from shared.mesh_runtime import (
    Decision,
    EvaluationResult,
    ExecutionRecord,
    RuntimeConfig,
    resolve_integrations_config,
)

from .goose_adapter import GooseAdapter, GooseCliAdapter, NativeGooseAdapter


class OrchestratorService:
    def __init__(
        self,
        adapter: GooseAdapter | None = None,
        config: RuntimeConfig | None = None,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ):
        self.config = config or RuntimeConfig.from_env()
        self.adapter = adapter or self._build_adapter()
        self.clock = clock or time.monotonic
        self.sleeper = sleeper or time.sleep

    def _build_adapter(self) -> GooseAdapter:
        if self.config.orchestration_mode == "goose":
            resolved = resolve_integrations_config(self.config)
            return GooseCliAdapter(command=resolved.goose_command)
        return NativeGooseAdapter()

    def execute(self, decision: Decision, evaluation: EvaluationResult) -> ExecutionRecord:
        started_at = datetime.now(timezone.utc).isoformat()
        idempotency_key = f"{decision.decision_id}:{decision.execution_plan['action']}"
        if not evaluation.passed or evaluation.final_recommendation != "execute":
            record = ExecutionRecord(
                execution_id=f"exe_{decision.decision_id}",
                decision_id=decision.decision_id,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
                executor="goose",
                status="rejected",
                idempotency_key=idempotency_key,
                applied_action={
                    "system": decision.execution_plan["system"],
                    "action": decision.execution_plan["action"],
                    "parameters": decision.execution_plan["parameters"],
                },
                external_refs={},
                failure={"reason": evaluation.final_recommendation},
            )
            record.validate()
            return record

        result = None
        attempts = 0
        retry_window_started_at = self.clock()
        while attempts <= self.config.max_transient_retries:
            attempts += 1
            candidate = self.adapter.execute_decision(decision, idempotency_key)
            result = candidate
            if candidate.status == "succeeded":
                break
            if not candidate.retryable:
                break
            if attempts > self.config.max_transient_retries:
                break
            retry_after_seconds = float((candidate.failure or {}).get("retry_after_seconds", 0.0))
            if self.clock() - retry_window_started_at + retry_after_seconds > self.config.max_retry_window_seconds:
                break
            if retry_after_seconds > 0:
                self.sleeper(retry_after_seconds)

        if result is None:
            raise RuntimeError("execution did not produce a result")

        external_refs = dict(result.external_refs)
        failure = result.failure
        if result.status != "succeeded" and result.retryable:
            external_refs.update(
                self.adapter.open_execution_incident(
                    decision,
                    failure["reason"] if failure else "transient_execution_failure",
                )
            )
            failure = {
                **(failure or {"reason": "transient_execution_failure"}),
                "human_review_route": "human_review",
                "attempts": attempts,
            }
        elif failure:
            failure = {**failure, "attempts": attempts}

        record = ExecutionRecord(
            execution_id=f"exe_{decision.decision_id}",
            decision_id=decision.decision_id,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
            executor="goose",
            status=result.status,
            idempotency_key=idempotency_key,
            applied_action={
                "system": decision.execution_plan["system"],
                "action": decision.execution_plan["action"],
                "parameters": decision.execution_plan["parameters"],
            },
            external_refs=external_refs,
            failure=failure,
        )
        record.validate()
        return record
