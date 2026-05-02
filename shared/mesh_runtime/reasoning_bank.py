from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast
from uuid import uuid4

from .contracts import ClaimRecord, ObservationRecord, RelationshipRecord, Trigger
from .memory_scoring import confidence_from_factors, freshness_score, support_score

_SUCCESSFUL_OUTCOMES = {"successful"}
_ACTIONLESS_DECISIONS = {"no_action"}
_DEFAULT_CHANNELS = ["lexical", "graph", "vector"]


class ReasoningBankService:
    """Strategy-level memory over Mesh run outcomes.

    The service stores ReasoningBank lessons as ordinary Mesh observations and
    claims. Successful runs become procedural strategy claims; failed, blocked,
    or escalated runs become semantic guardrail claims.
    """

    def __init__(self, state_store: Any, *, max_strategies: int = 5, scaling_mode: str = "off") -> None:
        self.state_store = state_store
        self.max_strategies = max(1, min(int(max_strategies or 5), 25))
        self.scaling_mode = _normalize_scaling_mode(scaling_mode)

    def retrieve_for_trigger(
        self,
        trigger: Trigger,
        *,
        run_id: str | None = None,
        evidence_pack: dict[str, Any] | None = None,
        scenario_analysis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not hasattr(self.state_store, "retrieve_memory"):
            return self.disabled_artifact(reason="state_store_missing_memory_retrieval")
        query = self.build_query(
            trigger,
            evidence_pack=evidence_pack,
            scenario_analysis=scenario_analysis,
        )
        response = self.state_store.retrieve_memory(
            {
                "query": query,
                "scope": {"service": trigger.service},
                "limit": self.max_strategies,
                "channels": _DEFAULT_CHANNELS,
            }
        )
        packet = dict(response.get("packet", {}))
        strategies = _selected_strategies(packet, self.max_strategies)
        contradictions = list(response.get("contradictions", []))
        channels = list(response.get("channels", _DEFAULT_CHANNELS))
        if len(strategies) < self.max_strategies:
            shared_response = self.state_store.retrieve_memory(
                {
                    "query": query,
                    "scope": {"shared": True},
                    "limit": self.max_strategies,
                    "channels": _DEFAULT_CHANNELS,
                }
            )
            packet = _merge_packets(packet, dict(shared_response.get("packet", {})), self.max_strategies)
            strategies = _selected_strategies(packet, self.max_strategies)
            contradictions.extend(list(shared_response.get("contradictions", [])))
            channels = sorted(set(channels) | set(shared_response.get("channels", _DEFAULT_CHANNELS)))
        return {
            "enabled": True,
            "query": query,
            "run_id": run_id,
            "service": trigger.service,
            "scaling_mode": self.scaling_mode,
            "packet": packet,
            "strategies": strategies,
            "formatted_context": format_strategy_context(strategies),
            "contradictions": contradictions[: self.max_strategies],
            "channels": channels,
        }

    def distill_run(self, run_id: str) -> dict[str, Any]:
        if not _has_memory_write_api(self.state_store):
            return self.disabled_artifact(reason="state_store_missing_memory_write_api")
        session = self.state_store.get_run_session(run_id)
        if session is None:
            raise ValueError(f"run {run_id!r} not found")
        existing = session.artifacts.get("reasoning_bank")
        if isinstance(existing, dict) and existing.get("lessons"):
            return existing

        artifacts = session.artifacts if isinstance(session.artifacts, dict) else {}
        trigger = artifacts.get("trigger", {})
        decision = artifacts.get("decision", {})
        evaluation = artifacts.get("evaluation", {})
        execution = artifacts.get("execution", {})
        feedback = artifacts.get("feedback", {})
        trajectory_score = artifacts.get("trajectory_score", {})
        if not isinstance(trigger, dict) or not isinstance(decision, dict):
            return {"enabled": True, "run_id": run_id, "lessons": [], "reason": "missing_trigger_or_decision"}

        events = self.state_store.list_run_events(run_id)
        source_refs = _source_refs(events)
        lesson = self._build_lesson(
            run_id=run_id,
            trigger=trigger,
            decision=decision,
            evaluation=evaluation if isinstance(evaluation, dict) else {},
            execution=execution if isinstance(execution, dict) else {},
            feedback=feedback if isinstance(feedback, dict) else {},
            trajectory_score=trajectory_score if isinstance(trajectory_score, dict) else {},
            source_refs=source_refs,
            session_status=session.status,
        )
        observation = self.state_store.append_observation(lesson["observation"])
        claim_payload = dict(lesson["claim"])
        claim_payload["supporting_observation_ids"] = [observation["observation_id"]]
        claim = self.state_store.save_claim(claim_payload)
        relationship = _relationship_for_claim(trigger, claim, observation)
        if relationship is not None:
            self.state_store.save_relationship(relationship)
        return {
            "enabled": True,
            "run_id": run_id,
            "service": trigger.get("service"),
            "scaling_mode": self.scaling_mode,
            "lessons": [
                {
                    "title": lesson["title"],
                    "description": lesson["description"],
                    "content": lesson["content"],
                    "lesson_type": lesson["lesson_type"],
                    "claim_id": claim["claim_id"],
                    "observation_id": observation["observation_id"],
                    "statement": claim["statement"],
                    "tier": claim["tier"],
                    "confidence": claim["confidence"],
                    "scorer_impact": lesson["scorer_impact"],
                    "source_refs": source_refs,
                }
            ],
        }

    def disabled_artifact(self, *, reason: str = "disabled") -> dict[str, Any]:
        return {
            "enabled": False,
            "reason": reason,
            "packet": {},
            "strategies": [],
            "formatted_context": "",
            "scaling_mode": self.scaling_mode,
        }

    def build_query(
        self,
        trigger: Trigger,
        *,
        evidence_pack: dict[str, Any] | None = None,
        scenario_analysis: dict[str, Any] | None = None,
    ) -> str:
        related = trigger.related_context if isinstance(trigger.related_context, dict) else {}
        parts: list[str] = [
            trigger.service,
            trigger.endpoint,
            trigger.trigger_type,
            str(trigger.flag_key or ""),
            _signature_text(related),
        ]
        metric_regression = related.get("metric_regression")
        if isinstance(metric_regression, dict):
            parts.extend(str(metric_regression.get(key, "")) for key in ("metric_name", "direction"))
        if isinstance(evidence_pack, dict):
            parts.extend(str(item) for item in evidence_pack.get("fast_path_signatures", [])[:5])
        if isinstance(scenario_analysis, dict):
            parts.append(str(scenario_analysis.get("suggested_decision_type") or ""))
        return " ".join(part for part in parts if part).strip()

    def _build_lesson(
        self,
        *,
        run_id: str,
        trigger: dict[str, Any],
        decision: dict[str, Any],
        evaluation: dict[str, Any],
        execution: dict[str, Any],
        feedback: dict[str, Any],
        trajectory_score: dict[str, Any],
        source_refs: list[dict[str, Any]],
        session_status: str,
    ) -> dict[str, Any]:
        service = str(trigger.get("service") or "unknown_service")
        trigger_type = str(trigger.get("trigger_type") or "unknown_trigger")
        decision_type = str(decision.get("decision_type") or "unknown_decision")
        outcome = str(feedback.get("outcome") or session_status or "unknown")
        execution_status = str(execution.get("status") or "unknown")
        evaluation_passed = bool(evaluation.get("passed", False))
        failure_mode = _failure_mode(trigger, evaluation, execution, feedback, session_status)
        scorer_impact = _scorer_impact(trajectory_score)
        success = (
            outcome in _SUCCESSFUL_OUTCOMES
            and execution_status == "succeeded"
            and evaluation_passed
            and decision_type not in _ACTIONLESS_DECISIONS
        )
        lesson_type = "success_strategy" if success else "failure_guardrail"
        signature = _signature_text(trigger.get("related_context", {}))
        if success:
            statement = (
                f"When {trigger_type} affects {service}"
                f"{_with_signature(signature)}, {decision_type} is a reusable strategy; "
                f"the run passed evaluation and feedback outcome was {outcome}."
            )
            title = f"Reuse {decision_type} for {trigger_type}"
            description = f"Successful recovery pattern for {service}."
            tier = "procedural"
            confidence_inputs = {
                "support_score": support_score(max(1, len(source_refs))),
                "recency_score": freshness_score(_timestamp(), half_life_days=45.0),
                "authority_score": 0.82,
                "consistency_score": 0.85,
                "verification_score": 0.86,
            }
        else:
            blockers = evaluation.get("blocking_reasons", [])
            blocker_text = ", ".join(str(item) for item in blockers[:3]) if isinstance(blockers, list) else ""
            statement = (
                f"Before applying {decision_type} for {trigger_type} on {service}"
                f"{_with_signature(signature)}, verify the guardrail '{failure_mode}'"
                f"{f' and blockers: {blocker_text}' if blocker_text else ''}."
            )
            title = f"Guardrail for {decision_type} on {trigger_type}"
            description = f"Failure or blocked-run lesson for {service}."
            tier = "semantic"
            confidence_inputs = {
                "support_score": support_score(max(1, len(source_refs))),
                "recency_score": freshness_score(_timestamp(), half_life_days=30.0),
                "authority_score": 0.78,
                "consistency_score": 0.72,
                "verification_score": 0.74,
            }
        confidence = confidence_from_factors(confidence_inputs)
        content = (
            f"{statement} Scorer impact: score={scorer_impact.get('score')}, "
            f"failed={', '.join(scorer_impact.get('failed_scorers', [])) or 'none'}."
        )
        observation = ObservationRecord(
            observation_id=f"obs_{uuid4().hex[:12]}",
            scope={"shared": True, "service": service, "run_id": run_id},
            kind="reasoning_bank_lesson",
            content=content,
            service=service,
            run_id=run_id,
            source_type="reasoning_bank",
            source_refs=source_refs,
            created_at=_timestamp(),
            author="reasoning_bank:deterministic",
            tags=["reasoning_bank", lesson_type, trigger_type, decision_type],
            metadata={
                "reasoning_bank": True,
                "outcome": outcome,
                "lesson_type": lesson_type,
                "source_stage": "completed",
                "failure_mode": failure_mode,
                "title": title,
                "description": description,
                "content": content,
                "scorer_impact": scorer_impact,
                "decision_type": decision_type,
                "execution_status": execution_status,
                "evaluation_passed": evaluation_passed,
                "scaling_mode": self.scaling_mode,
            },
        )
        claim = ClaimRecord(
            claim_id=f"claim_{uuid4().hex[:12]}",
            statement=statement,
            entity_refs=[service, trigger_type, decision_type, "reasoning_bank", lesson_type],
            supporting_observation_ids=[],
            contradicting_claim_ids=[],
            superseded_by=None,
            confidence=confidence,
            confidence_factors=confidence_inputs,
            freshness=confidence_inputs["recency_score"],
            tier=tier,
            state="active",
            created_at=_timestamp(),
            updated_at=_timestamp(),
        )
        observation.validate()
        claim.validate()
        return {
            "title": title,
            "description": description,
            "content": content,
            "lesson_type": lesson_type,
            "scorer_impact": scorer_impact,
            "observation": observation.to_dict(),
            "claim": claim.to_dict(),
        }


def format_strategy_context(strategies: list[dict[str, Any]]) -> str:
    if not strategies:
        return ""
    lines = ["ReasoningBank strategies are advisory and do not bypass live evidence or policy gates."]
    for index, strategy in enumerate(strategies, start=1):
        tier = strategy.get("tier") or strategy.get("type") or "memory"
        statement = str(strategy.get("statement") or strategy.get("content") or "").strip()
        if statement:
            lines.append(f"{index}. [{tier}] {statement}")
    return "\n".join(lines)


def _selected_strategies(packet: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    procedures = list(packet.get("procedures", [])) if isinstance(packet, dict) else []
    claims = list(packet.get("claims", [])) if isinstance(packet, dict) else []
    selected: list[dict[str, Any]] = []
    for record in procedures + claims:
        if not isinstance(record, dict):
            continue
        selected.append(
            {
                "claim_id": record.get("claim_id"),
                "tier": record.get("tier"),
                "statement": record.get("statement"),
                "confidence": record.get("confidence"),
                "entity_refs": list(record.get("entity_refs", [])),
            }
        )
        if len(selected) >= limit:
            break
    return selected


def _merge_packets(primary: dict[str, Any], fallback: dict[str, Any], limit: int) -> dict[str, Any]:
    merged = dict(primary or {})
    for key in ("observations", "claims", "procedures", "contradictions", "citations"):
        primary_records = list(merged.get(key, [])) if isinstance(merged.get(key), list) else []
        fallback_records = list(fallback.get(key, [])) if isinstance(fallback.get(key), list) else []
        merged[key] = _dedupe_records(primary_records, fallback_records, limit)
    if not merged.get("packet_id") and fallback.get("packet_id"):
        merged["packet_id"] = fallback["packet_id"]
    if not merged.get("scope") and fallback.get("scope"):
        merged["scope"] = fallback["scope"]
    if not merged.get("generated_at") and fallback.get("generated_at"):
        merged["generated_at"] = fallback["generated_at"]
    return merged


def _dedupe_records(primary: list[dict[str, Any]], fallback: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for record in primary + fallback:
        if not isinstance(record, dict):
            continue
        key = str(
            record.get("claim_id")
            or record.get("observation_id")
            or record.get("item_id")
            or record.get("statement")
            or record.get("content")
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(record)
        if len(merged) >= limit:
            break
    return merged


def _has_memory_write_api(state_store: Any) -> bool:
    return all(
        hasattr(state_store, name)
        for name in ("get_run_session", "list_run_events", "append_observation", "save_claim", "save_relationship")
    )


def _source_refs(events: list[Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for event in events:
        if event.event_type not in {
            "trigger_ready",
            "evidence_pack_ready",
            "scenario_analysis_ready",
            "decision_ready",
            "evaluation_ready",
            "execution_recorded",
            "feedback_recorded",
            "run_completed",
        }:
            continue
        refs.append(
            {
                "run_id": event.run_id,
                "event_id": event.event_id,
                "stage": event.stage,
                "event_type": event.event_type,
                "artifact_key": event.artifact_key,
            }
        )
    return refs


def _relationship_for_claim(
    trigger: dict[str, Any],
    claim: dict[str, Any],
    observation: dict[str, Any],
) -> dict[str, Any] | None:
    service = trigger.get("service")
    claim_id = claim.get("claim_id")
    observation_id = observation.get("observation_id")
    if not service or not claim_id or not observation_id:
        return None
    relationship = RelationshipRecord(
        relationship_id=f"rel_{uuid4().hex[:12]}",
        from_id=str(service),
        to_id=str(claim_id),
        type="uses_strategy",
        confidence=float(claim.get("confidence", 0.0) or 0.0),
        supporting_observation_ids=[str(observation_id)],
        state="active",
    )
    relationship.validate()
    return cast(dict[str, Any], relationship.to_dict())


def _failure_mode(
    trigger: dict[str, Any],
    evaluation: dict[str, Any],
    execution: dict[str, Any],
    feedback: dict[str, Any],
    session_status: str,
) -> str:
    blockers = evaluation.get("blocking_reasons", [])
    if isinstance(blockers, list) and blockers:
        return str(blockers[0])
    if execution.get("failure"):
        failure = execution.get("failure")
        return str(failure.get("reason") if isinstance(failure, dict) else failure)
    outcome = feedback.get("outcome")
    if outcome and outcome not in _SUCCESSFUL_OUTCOMES:
        return str(outcome)
    related = trigger.get("related_context", {})
    signature = _signature_text(related)
    return signature or str(session_status or "unknown")


def _scorer_impact(trajectory_score: dict[str, Any]) -> dict[str, Any]:
    artifacts = trajectory_score.get("artifacts", {}) if isinstance(trajectory_score, dict) else {}
    scorers = artifacts.get("scorers", []) if isinstance(artifacts, dict) else []
    failed = [
        str(item.get("name"))
        for item in scorers
        if isinstance(item, dict) and not item.get("passed", False) and item.get("name")
    ]
    return {
        "score": trajectory_score.get("score") if isinstance(trajectory_score, dict) else None,
        "passed": trajectory_score.get("passed") if isinstance(trajectory_score, dict) else None,
        "failed_scorers": failed,
    }


def _signature_text(related_context: Any) -> str:
    if not isinstance(related_context, dict):
        return ""
    signatures = related_context.get("error_signatures")
    if isinstance(signatures, list) and signatures:
        return " ".join(str(item) for item in signatures)
    trigger_signals = related_context.get("trigger_signals")
    if isinstance(trigger_signals, list) and trigger_signals:
        return " ".join(str(item) for item in trigger_signals)
    rollout = related_context.get("rollout_status")
    return str(rollout) if rollout else ""


def _with_signature(signature: str) -> str:
    return f" with signatures {signature}" if signature else ""


def _normalize_scaling_mode(raw: str) -> str:
    mode = (raw or "off").strip().lower()
    return mode if mode in {"off", "sequential", "parallel"} else "off"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
