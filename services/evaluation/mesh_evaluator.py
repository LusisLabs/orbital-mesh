"""Mesh-native trajectory evaluation primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shared.mesh_runtime import Decision, Trigger
from shared.mesh_runtime.phoenix_trace import build_phoenix_spans
from shared.mesh_runtime.temperature_policy import fixed_temperature, generator_temperature


@dataclass
class TraceScore:
    passed: bool
    score: float
    notes: list[str]
    artifacts: dict[str, Any]


class ContractCheckAdapter:
    """Formats deterministic contract checks as the first evaluation layer."""

    def summarize(
        self,
        *,
        schema_validation: dict[str, Any],
        policy_validation: dict[str, Any],
        business_rules: dict[str, Any],
        execution_readiness: dict[str, Any],
        remediation_safety: dict[str, Any],
    ) -> dict[str, Any]:
        checks = {
            "schema_validation": schema_validation,
            "policy_validation": policy_validation,
            "business_rules": business_rules,
            "execution_readiness": execution_readiness,
            "remediation_safety": remediation_safety,
        }
        passed = all(_stage_passed(stage) for stage in checks.values())
        return {
            "passed": passed,
            "score": 1.0 if passed else 0.0,
            "temperature": fixed_temperature("verifier"),
            "checks": checks,
        }


class TrajectoryEvaluator:
    """Builds an ordered task trace from Mesh artifacts and run events."""

    def build_trace(
        self,
        *,
        trigger: Trigger | dict[str, Any] | None,
        decision: Decision | dict[str, Any] | None,
        evaluation: dict[str, Any] | None = None,
        execution: dict[str, Any] | None = None,
        feedback: dict[str, Any] | None = None,
        run_events: list[Any] | None = None,
        artifacts: dict[str, Any] | None = None,
        failure_cause: str | None = None,
    ) -> dict[str, Any]:
        artifact_payload = dict(artifacts or {})
        events = [_event_to_dict(event) for event in (run_events or [])]
        events.sort(key=lambda item: item.get("sequence", 0))
        trigger_payload = _model_to_dict(trigger) or artifact_payload.get("trigger")
        decision_payload = _model_to_dict(decision) or artifact_payload.get("decision")
        decision_reasoning = decision_payload.get("reasoning", {}) if isinstance(decision_payload, dict) else {}
        reasoning_evidence = decision_reasoning.get("evidence_pack", {}) if isinstance(decision_reasoning, dict) else {}
        evaluation_payload = evaluation or artifact_payload.get("evaluation")
        execution_payload = execution or artifact_payload.get("execution")
        feedback_payload = feedback or artifact_payload.get("feedback")
        return {
            "trace_version": "mesh_task_trace_v1",
            "mesh_eval": artifact_payload.get("mesh_eval"),
            "task": {
                "trigger_id": _get(trigger_payload, "trigger_id"),
                "trigger_type": _get(trigger_payload, "trigger_type"),
                "service": _get(trigger_payload, "service"),
                "endpoint": _get(trigger_payload, "endpoint"),
            },
            "context": {
                "evidence_pack": artifact_payload.get("evidence_pack") or reasoning_evidence,
                "reasoning_bank_packet": artifact_payload.get("reasoning_bank_packet"),
                "scenario_analysis": artifact_payload.get("scenario_analysis")
                or (reasoning_evidence.get("scenario_analysis") if isinstance(reasoning_evidence, dict) else None),
                "service_agent": artifact_payload.get("service_agent"),
            },
            "decision": decision_payload,
            "evaluation": evaluation_payload,
            "execution": execution_payload,
            "feedback": feedback_payload,
            "events": events,
            "tool_calls": _tool_calls(events, execution_payload),
            "failure_cause": failure_cause or _failure_cause(evaluation_payload, execution_payload, feedback_payload),
        }


class BehavioralScorer:
    """Scores process quality without requiring one exact prompt output."""

    def score(self, trace: dict[str, Any]) -> TraceScore:
        scores = [
            self._evidence_inspection(trace),
            self._tool_sequence(trace),
            self._known_failure_avoidance(trace),
            self._outcome(trace),
        ]
        numeric_scores = [float(item["score"]) for item in scores]
        aggregate = sum(numeric_scores) / len(numeric_scores)
        passed = all(item["passed"] for item in scores if item["blocking"])
        return TraceScore(
            passed=passed,
            score=round(aggregate, 4),
            notes=[str(item["note"]) for item in scores],
            artifacts={
                "scorers": scores,
                "temperature": fixed_temperature("scorer"),
            },
        )

    def _evidence_inspection(self, trace: dict[str, Any]) -> dict[str, Any]:
        context = trace.get("context") if isinstance(trace.get("context"), dict) else {}
        evidence_pack = context.get("evidence_pack") if isinstance(context, dict) else None
        events = trace.get("events") if isinstance(trace.get("events"), list) else []
        inspected = bool(evidence_pack) or any(
            event.get("event_type") in {"evidence_pack_ready", "evidence_probe_completed", "evidence_node_recorded"}
            for event in events
            if isinstance(event, dict)
        )
        return {
            "name": "evidence_inspection",
            "passed": inspected,
            "blocking": True,
            "score": 1.0 if inspected else 0.0,
            "note": "agent inspected evidence" if inspected else "agent reached evaluation without evidence inspection",
            "evidence_refs": _event_refs(events, {"evidence_pack_ready", "evidence_probe_completed", "evidence_node_recorded"}),
        }

    def _tool_sequence(self, trace: dict[str, Any]) -> dict[str, Any]:
        tool_calls = trace.get("tool_calls") if isinstance(trace.get("tool_calls"), list) else []
        decision = trace.get("decision") if isinstance(trace.get("decision"), dict) else {}
        action = _nested(decision, "execution_plan", "action")
        has_action = bool(action)
        blind_restart = action == "restart_deployment" and not _has_kubernetes_diagnostic_context(trace)
        passed = has_action and not blind_restart
        return {
            "name": "tool_sequence",
            "passed": passed,
            "blocking": True,
            "score": 1.0 if passed else 0.0,
            "note": (
                "tool/action sequence matches task context"
                if passed
                else "tool/action sequence is missing or restarts without diagnostic context"
            ),
            "evidence_refs": tool_calls,
        }

    def _known_failure_avoidance(self, trace: dict[str, Any]) -> dict[str, Any]:
        context = trace.get("context") if isinstance(trace.get("context"), dict) else {}
        packet = context.get("reasoning_bank_packet") if isinstance(context, dict) else None
        decision = trace.get("decision") if isinstance(trace.get("decision"), dict) else {}
        action = _nested(decision, "execution_plan", "action")
        guardrails = []
        if isinstance(packet, dict):
            guardrails.extend(packet.get("claims", []) if isinstance(packet.get("claims"), list) else [])
            guardrails.extend(packet.get("contradictions", []) if isinstance(packet.get("contradictions"), list) else [])
        avoid_blind_restart = action != "restart_deployment" or _has_kubernetes_diagnostic_context(trace)
        passed = avoid_blind_restart
        return {
            "name": "known_failure_avoidance",
            "passed": passed,
            "blocking": True,
            "score": 1.0 if passed else 0.0,
            "note": "known failure modes avoided" if passed else "known blind restart failure mode was not avoided",
            "evidence_refs": [
                {"claim_id": item.get("claim_id"), "statement": item.get("statement")}
                for item in guardrails[:5]
                if isinstance(item, dict)
            ],
        }

    def _outcome(self, trace: dict[str, Any]) -> dict[str, Any]:
        execution = trace.get("execution") if isinstance(trace.get("execution"), dict) else {}
        feedback = trace.get("feedback") if isinstance(trace.get("feedback"), dict) else {}
        if not execution and not feedback:
            return {
                "name": "system_outcome",
                "passed": True,
                "blocking": False,
                "score": 0.5,
                "note": "outcome pending at evaluation gate",
                "evidence_refs": [],
            }
        passed = execution.get("status") in {None, "succeeded", "rejected"} and feedback.get("outcome") in {
            None,
            "successful",
            "rolled_back",
        }
        return {
            "name": "system_outcome",
            "passed": passed,
            "blocking": False,
            "score": 1.0 if passed else 0.0,
            "note": "system outcome matches verifier state" if passed else "system outcome indicates failed execution or feedback",
            "evidence_refs": [
                {"artifact_key": "execution", "status": execution.get("status")},
                {"artifact_key": "feedback", "outcome": feedback.get("outcome")},
            ],
        }


class Verifier:
    """Deterministic verifier for execution and feedback state."""

    def verify(self, trace: dict[str, Any]) -> dict[str, Any]:
        execution = trace.get("execution") if isinstance(trace.get("execution"), dict) else {}
        feedback = trace.get("feedback") if isinstance(trace.get("feedback"), dict) else {}
        evaluation = trace.get("evaluation") if isinstance(trace.get("evaluation"), dict) else {}
        facts = {
            "evaluation_recommendation": evaluation.get("final_recommendation"),
            "evaluation_passed": evaluation.get("passed"),
            "execution_status": execution.get("status"),
            "feedback_outcome": feedback.get("outcome"),
        }
        if not execution and not feedback:
            passed = True
            note = "post-action verifier pending"
        else:
            passed = (
                execution.get("status") in {"succeeded", "rejected"}
                and feedback.get("outcome") in {"successful", "rolled_back", "not_executed"}
            )
            note = "verifier accepted observed state" if passed else "verifier rejected observed state"
        return {
            "passed": passed,
            "score": 1.0 if passed else 0.0,
            "temperature": fixed_temperature("verifier"),
            "facts": facts,
            "notes": [note],
        }


def evaluate_trajectory(
    *,
    trigger: Trigger | dict[str, Any] | None,
    decision: Decision | dict[str, Any] | None,
    evaluation: dict[str, Any] | None = None,
    execution: dict[str, Any] | None = None,
    feedback: dict[str, Any] | None = None,
    run_events: list[Any] | None = None,
    artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trace = TrajectoryEvaluator().build_trace(
        trigger=trigger,
        decision=decision,
        evaluation=evaluation,
        execution=execution,
        feedback=feedback,
        run_events=run_events,
        artifacts=artifacts,
    )
    score = BehavioralScorer().score(trace)
    verifier = Verifier().verify(trace)
    return {
        "task_trace": trace,
        "trajectory_score": {
            "passed": score.passed,
            "score": score.score,
            "notes": score.notes,
            "artifacts": score.artifacts,
        },
        "verifier_output": verifier,
        "phoenix_spans": build_phoenix_spans(trace),
    }


def temperature_policy_for_trace(trace: dict[str, Any]) -> dict[str, Any]:
    decision = trace.get("decision") if isinstance(trace.get("decision"), dict) else {}
    context = trace.get("context") if isinstance(trace.get("context"), dict) else {}
    packet = context.get("reasoning_bank_packet") if isinstance(context, dict) else {}
    risk_level = str(_nested(decision, "risk", "level") or "medium")
    risk = {"low": 0.2, "medium": 0.5, "high": 1.0}.get(risk_level, 0.5)
    strictness = 1.0 if _nested(decision, "execution_plan", "system") in {"kubernetes_service", "systemd_service"} else 0.5
    prior_similarity = 0.0
    if isinstance(packet, dict) and (packet.get("claims") or packet.get("procedures") or packet.get("contradictions")):
        prior_similarity = 0.8
    return generator_temperature(
        {
            "novelty": 0.3 if prior_similarity else 0.7,
            "ambiguity": 1.0 - float(decision.get("confidence", 0.5) or 0.5),
            "search_need": 0.6 if not context.get("evidence_pack") else 0.2,
            "risk": risk,
            "contract_strictness": strictness,
            "prior_failure_similarity": prior_similarity,
        }
    )


def _stage_passed(stage: dict[str, Any]) -> bool:
    if not isinstance(stage, dict):
        return False
    if "passed" in stage:
        return bool(stage["passed"])
    hard_stops = stage.get("hard_stops")
    return not hard_stops


def _model_to_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return None


def _event_to_dict(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return dict(event)
    if hasattr(event, "to_dict"):
        return event.to_dict()
    payload = getattr(event, "__dict__", None)
    return dict(payload) if isinstance(payload, dict) else {}


def _tool_calls(events: list[dict[str, Any]], execution: dict[str, Any] | None) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for event in events:
        if event.get("event_type") in {
            "evidence_probe_completed",
            "subdecision_recorded",
            "agent_task_recorded",
            "execution_recorded",
        }:
            calls.append(
                {
                    "stage": event.get("stage"),
                    "event_type": event.get("event_type"),
                    "artifact_key": event.get("artifact_key"),
                    "summary": event.get("summary"),
                }
            )
    if isinstance(execution, dict):
        applied = execution.get("applied_action")
        if isinstance(applied, dict):
            calls.append({"stage": "executing", "event_type": "applied_action", "summary": applied})
    return calls


def _failure_cause(
    evaluation: dict[str, Any] | None,
    execution: dict[str, Any] | None,
    feedback: dict[str, Any] | None,
) -> str | None:
    if isinstance(evaluation, dict) and evaluation.get("blocking_reasons"):
        reasons = evaluation.get("blocking_reasons")
        if isinstance(reasons, list) and reasons:
            return str(reasons[0])
    if isinstance(execution, dict) and execution.get("failure"):
        return str(execution["failure"])
    if isinstance(feedback, dict) and feedback.get("outcome") not in (None, "successful"):
        return str(feedback.get("outcome"))
    return None


def _event_refs(events: list[dict[str, Any]], event_types: set[str]) -> list[dict[str, Any]]:
    return [
        {
            "event_id": event.get("event_id"),
            "stage": event.get("stage"),
            "event_type": event.get("event_type"),
            "artifact_key": event.get("artifact_key"),
        }
        for event in events
        if event.get("event_type") in event_types
    ]


def _has_kubernetes_diagnostic_context(trace: dict[str, Any]) -> bool:
    task = trace.get("task") if isinstance(trace.get("task"), dict) else {}
    context = trace.get("context") if isinstance(trace.get("context"), dict) else {}
    evidence_pack = context.get("evidence_pack") if isinstance(context, dict) else {}
    trigger = trace.get("decision", {})
    if task.get("trigger_type") != "kubernetes_deployment_unhealthy":
        return True
    if isinstance(evidence_pack, dict) and (
        evidence_pack.get("probe_results")
        or evidence_pack.get("fast_path_signatures")
        or evidence_pack.get("evidence_nodes")
    ):
        return True
    reasoning = trigger.get("reasoning") if isinstance(trigger, dict) else {}
    return isinstance(reasoning, dict) and bool(reasoning.get("evidence"))


def _get(payload: Any, key: str) -> Any:
    return payload.get(key) if isinstance(payload, dict) else None


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
