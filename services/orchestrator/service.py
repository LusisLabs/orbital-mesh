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
    build_readiness,
    log_runtime_event,
    resolve_integrations_config,
)
from shared.mesh_runtime.execution_attempts import (
    ExecutionAttemptStore,
    dispatched_without_outcome,
    has_terminal_outcome,
)

from .goose_adapter import GooseAdapter, GooseCliAdapter, NativeGooseAdapter
from .hermes_adapter import HermesAdapter, HermesCliAdapter, NativeHermesAdapter


class OrchestratorService:
    def __init__(
        self,
        adapter: GooseAdapter | HermesAdapter | None = None,
        config: RuntimeConfig | None = None,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ):
        self.config = config or RuntimeConfig.from_env()
        self.adapter = adapter or self._build_adapter()
        self.clock = clock or time.monotonic
        self.sleeper = sleeper or time.sleep
        self.attempt_store = ExecutionAttemptStore(self.config.state_directory)

    def _build_adapter(self) -> GooseAdapter | HermesAdapter:
        mode = (self.config.orchestration_mode or "auto").lower()
        if mode == "goose":
            resolved = resolve_integrations_config(self.config)
            return GooseCliAdapter(
                command=resolved.goose_command,
                timeout_seconds=self.config.goose_command_timeout_seconds,
            )
        if mode == "hermes":
            resolved = resolve_integrations_config(self.config)
            return HermesCliAdapter(
                command=resolved.hermes_command,
                timeout_seconds=self.config.hermes_command_timeout_seconds,
            )
        if mode == "native":
            # Explicit ``native`` keeps the legacy in-process Goose adapter.
            return NativeGooseAdapter(config=self.config)
        # auto: prefer Hermes, then Goose, then fall back to the modern native
        # Hermes adapter so offline/dev setups still work.
        readiness = build_readiness(self.config)
        if readiness.hermes.ready:
            resolved = resolve_integrations_config(self.config)
            log_runtime_event("orchestration_adapter_selected", adapter="hermes", reason="auto_ready")
            return HermesCliAdapter(
                command=resolved.hermes_command,
                timeout_seconds=self.config.hermes_command_timeout_seconds,
            )
        if readiness.goose.ready:
            resolved = resolve_integrations_config(self.config)
            log_runtime_event("orchestration_adapter_selected", adapter="goose", reason="auto_ready")
            return GooseCliAdapter(
                command=resolved.goose_command,
                timeout_seconds=self.config.goose_command_timeout_seconds,
            )
        log_runtime_event(
            "orchestration_adapter_selected",
            adapter="native_hermes",
            reason="auto_fallback",
            hermes_detail=readiness.hermes.detail,
            goose_detail=readiness.goose.detail,
        )
        return NativeHermesAdapter(config=self.config)

    def execute(self, decision: Decision, evaluation: EvaluationResult) -> ExecutionRecord:
        started_at = datetime.now(timezone.utc).isoformat()
        idempotency_key = f"{decision.decision_id}:{decision.execution_plan['action']}"
        replay_guarded = _requires_replay_guard(decision)
        if not evaluation.passed or evaluation.final_recommendation != "execute":
            log_runtime_event(
                "execution_rejected",
                mode=self.config.orchestration_mode,
                decision_id=decision.decision_id,
                recommendation=evaluation.final_recommendation,
                blocking_reasons=evaluation.blocking_reasons,
            )
            record = ExecutionRecord(
                execution_id=f"exe_{decision.decision_id}",
                decision_id=decision.decision_id,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat(),
                executor=self.config.orchestration_mode,
                status="rejected",
                idempotency_key=idempotency_key,
                applied_action={
                    "system": decision.execution_plan["system"],
                    "action": decision.execution_plan["action"],
                    "parameters": decision.execution_plan["parameters"],
                },
                external_refs={},
                failure={
                    "reason": evaluation.final_recommendation,
                    "blocking_reasons": list(evaluation.blocking_reasons),
                },
            )
            record.validate()
            return record

        result = None
        attempts = 0
        retry_window_started_at = self.clock()
        while attempts <= self.config.max_transient_retries:
            attempts += 1
            prior_attempt = self.attempt_store.get(idempotency_key) if replay_guarded else None
            if has_terminal_outcome(prior_attempt):
                result = self._result_from_prior_attempt(prior_attempt)
                break
            if dispatched_without_outcome(prior_attempt):
                result = self._unknown_after_dispatch(prior_attempt)
                break
            if replay_guarded:
                self.attempt_store.begin(idempotency_key, decision.decision_id, decision.execution_plan)
                self.attempt_store.mark_dispatched(idempotency_key)
            candidate = self.adapter.execute_decision(decision, idempotency_key)
            result = candidate
            if replay_guarded:
                self.attempt_store.complete(
                    idempotency_key,
                    status=candidate.status,
                    external_refs=candidate.external_refs,
                    failure=candidate.failure,
                )
            if candidate.status == "succeeded":
                break
            if not candidate.retryable:
                break
            if attempts > self.config.max_transient_retries:
                break
            retry_after_seconds = self._retry_delay_seconds(attempts, candidate.failure)
            if self.clock() - retry_window_started_at + retry_after_seconds > self.config.max_retry_window_seconds:
                break
            if retry_after_seconds > 0:
                log_runtime_event(
                    "execution_retry_scheduled",
                    mode=self.config.orchestration_mode,
                    decision_id=decision.decision_id,
                    attempts=attempts,
                    retry_after_seconds=retry_after_seconds,
                    failure_reason=(candidate.failure or {}).get("reason"),
                )
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
                "orchestration_mode": self.config.orchestration_mode,
            }
        elif failure:
            failure = {**failure, "attempts": attempts, "orchestration_mode": self.config.orchestration_mode}

        record = ExecutionRecord(
            execution_id=f"exe_{decision.decision_id}",
            decision_id=decision.decision_id,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
            executor=self.config.orchestration_mode,
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
        log_runtime_event(
            "execution_completed",
            mode=self.config.orchestration_mode,
            decision_id=decision.decision_id,
            status=record.status,
            attempts=(failure or {}).get("attempts", attempts),
        )
        return record

    @staticmethod
    def _result_from_prior_attempt(record: dict) -> object:
        from .adapters_common import CliExecutionResult

        refs = dict(record.get("external_refs") or {})
        refs["idempotency_replayed"] = True
        return CliExecutionResult(
            status=str(record.get("status", "failed")),
            external_refs=refs,
            failure=record.get("failure") if isinstance(record.get("failure"), dict) else None,
            retryable=False,
        )

    @staticmethod
    def _unknown_after_dispatch(record: dict | None) -> object:
        from .adapters_common import CliExecutionResult

        return CliExecutionResult(
            status="failed",
            external_refs={
                "idempotency_guard": "remote_command_dispatched_without_outcome",
                "idempotency_key": (record or {}).get("idempotency_key"),
            },
            failure={
                "reason": "outcome_unknown_after_dispatch",
                "detail": "remote command may already have executed; refusing to retry side-effecting action",
            },
            retryable=False,
        )

    def _retry_delay_seconds(self, attempts: int, failure: dict | None) -> float:
        if failure is not None and failure.get("retry_after_seconds") is not None:
            return float(failure["retry_after_seconds"])
        # Use bounded exponential backoff for transient failures that do not provide
        # an explicit retry hint so unattended runs do not hot-loop integrations.
        return float(min(2 ** max(attempts - 1, 0), 8))


def _requires_replay_guard(decision: Decision) -> bool:
    return (
        decision.execution_plan.get("system") == "systemd_service"
        and decision.execution_plan.get("action") == "restart_systemd_service"
    )
