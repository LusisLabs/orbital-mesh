"""Execute approved plans through a Goose integration boundary."""

from __future__ import annotations

from datetime import datetime, timezone

from shared.mesh_runtime import EvaluationResult, ExecutionRecord, RemediationPlan, RuntimeConfig

from .goose_adapter import GooseAdapter, GooseCliAdapter, MockGooseAdapter


class OrchestratorService:
    def __init__(self, adapter: GooseAdapter | None = None, config: RuntimeConfig | None = None):
        self.config = config or RuntimeConfig.from_env()
        self.adapter = adapter or self._build_adapter()

    def _build_adapter(self) -> GooseAdapter:
        if self.config.orchestration_mode == "goose":
            return GooseCliAdapter()
        return MockGooseAdapter()

    def execute(self, plan: RemediationPlan, evaluation: EvaluationResult) -> ExecutionRecord:
        if not evaluation.passed:
            record = ExecutionRecord(
                execution_id=f"exe_{plan.plan_id}",
                plan_id=plan.plan_id,
                status="rejected",
                started_at=datetime.now(timezone.utc).isoformat(),
                completed_at=datetime.now(timezone.utc).isoformat(),
                executor=self.config.orchestration_mode,
                step_history=[],
                failure={"reason": "evaluation_failed"},
            )
            record.validate()
            return record

        step_results = self.adapter.execute_plan(plan)
        status = "completed"
        if any(step.status == "failed" for step in step_results):
            status = "failed"

        record = ExecutionRecord(
            execution_id=f"exe_{plan.plan_id}",
            plan_id=plan.plan_id,
            status=status,
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            executor=self.config.orchestration_mode,
            step_history=[
                {
                    "step_id": step.step_id,
                    "status": step.status,
                    "idempotency_key": f"{plan.plan_id}:{step.step_id}" if step.status != "skipped" else None,
                    "external_refs": step.external_refs,
                    "checkpoint_result": step.checkpoint_result,
                    "reason": step.reason,
                }
                for step in step_results
            ],
            failure=None if status == "completed" else {"reason": "step_failure"},
        )
        record.validate()
        return record
