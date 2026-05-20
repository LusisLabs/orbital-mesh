from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .contracts import ClaimRecord, ObservationRecord, RelationshipRecord, SupersessionRecord
from .infra_graph import _node_key as _infra_node_key
from .memory_scoring import confidence_from_factors, freshness_score, support_score


class MemoryLifecycleService:
    def __init__(self, state_store: Any):
        self.state_store = state_store

    def crystallize_run(self, run_id: str) -> dict[str, Any]:
        session = self.state_store.get_run_session(run_id)
        if session is None:
            raise ValueError(f"run {run_id!r} not found")
        events = self.state_store.list_run_events(run_id)
        observations: list[dict[str, Any]] = []
        claims: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []

        for event in events:
            observation = ObservationRecord(
                observation_id=f"obs_{uuid4().hex[:12]}",
                scope=_scope_for_session(session, event.payload.get("service") if isinstance(event.payload, dict) else None),
                kind=event.event_type,
                content=_observation_content(event),
                service=_service_for_event(session, event.payload),
                run_id=run_id,
                source_type="run_event",
                source_refs=[{"run_id": run_id, "event_id": event.event_id, "artifact_key": event.artifact_key}],
                created_at=event.recorded_at,
                author="mesh_control_plane",
                tags=[event.stage, event.event_type],
                metadata={"summary": event.summary or {}, "integration_name": event.integration_name, "status": event.status},
            )
            observation.validate()
            observations.append(self.state_store.append_observation(observation.to_dict()))

        for note in session.operator_notes:
            note_observation = ObservationRecord(
                observation_id=f"obs_{uuid4().hex[:12]}",
                scope=_scope_for_session(session, _service_from_artifacts(session.artifacts)),
                kind="operator_note",
                content=note,
                service=_service_from_artifacts(session.artifacts),
                run_id=run_id,
                source_type="operator_note",
                source_refs=[{"run_id": run_id, "note": note}],
                created_at=session.updated_at,
                author="operator",
                tags=["operator", "note"],
                metadata={},
            )
            note_observation.validate()
            observations.append(self.state_store.append_observation(note_observation.to_dict()))

        decision = session.artifacts.get("decision", {}) if isinstance(session.artifacts, dict) else {}
        feedback = session.artifacts.get("feedback", {}) if isinstance(session.artifacts, dict) else {}
        if isinstance(decision, dict) and decision.get("summary"):
            service = _service_from_artifacts(session.artifacts)
            factors = {
                "support_score": support_score(len(observations)),
                "recency_score": freshness_score(session.updated_at, half_life_days=21.0),
                "authority_score": 0.9,
                "consistency_score": 0.8 if feedback.get("outcome") == "successful" else 0.6,
                "verification_score": 0.85,
            }
            claim = ClaimRecord(
                claim_id=f"claim_{uuid4().hex[:12]}",
                statement=str(decision.get("summary")),
                entity_refs=[value for value in [service, str(decision.get("decision_type")) if decision.get("decision_type") else None] if value],
                supporting_observation_ids=[item["observation_id"] for item in observations[-5:]],
                contradicting_claim_ids=[],
                superseded_by=None,
                confidence=confidence_from_factors(factors),
                confidence_factors=factors,
                freshness=factors["recency_score"],
                tier="episodic",
                state="active",
                created_at=_timestamp(),
                updated_at=_timestamp(),
            )
            claim.validate()
            claims.append(self.state_store.save_claim(claim.to_dict()))

        for attempt in _agent_attempts(session.artifacts):
            summary = str(attempt.get("summary", "")).strip()
            if not summary:
                continue
            service = _service_from_artifacts(session.artifacts)
            factors = {
                "support_score": 0.45,
                "recency_score": freshness_score(session.updated_at, half_life_days=14.0),
                "authority_score": 0.6,
                "consistency_score": 0.7,
                "verification_score": 0.55 if attempt.get("citations") else 0.35,
            }
            claim = ClaimRecord(
                claim_id=f"claim_{uuid4().hex[:12]}",
                statement=summary,
                entity_refs=[value for value in [service, str(attempt.get("agent")) if attempt.get("agent") else None] if value],
                supporting_observation_ids=[item["observation_id"] for item in observations[-3:]],
                contradicting_claim_ids=[],
                superseded_by=None,
                confidence=confidence_from_factors(factors),
                confidence_factors=factors,
                freshness=factors["recency_score"],
                tier="semantic",
                state="active",
                created_at=_timestamp(),
                updated_at=_timestamp(),
            )
            claim.validate()
            claims.append(self.state_store.save_claim(claim.to_dict()))

        # Bridge to InfraGraph: stamp the canonical service node key on
        # each relationship row. ``_namespace_from_artifacts`` falls
        # back to the cloudopsbench / k8s common shapes; missing
        # namespace is fine — ``_node_key`` substitutes ``_cluster``
        # and the retrieval expander treats the result as a graph
        # anchor regardless. Only services get a bridge in v1; the
        # ``from_id`` here is always a service name. A follow-up can
        # bridge pod/node/deployment-level claims when those start
        # being emitted (currently crystallization only emits
        # service-scoped claims).
        for claim in claims:
            service = _service_from_artifacts(session.artifacts)
            if not service:
                continue
            namespace = _namespace_from_artifacts(session.artifacts)
            infra_key = _infra_node_key("service", namespace, service)
            relationship = RelationshipRecord(
                relationship_id=f"rel_{uuid4().hex[:12]}",
                from_id=service,
                to_id=claim["claim_id"],
                type="describes",
                confidence=float(claim["confidence"]),
                supporting_observation_ids=list(claim["supporting_observation_ids"]),
                state="active",
                infra_node_key=infra_key,
            )
            relationship.validate()
            relationships.append(self.state_store.save_relationship(relationship.to_dict()))

        return {
            "run_id": run_id,
            "observations_recorded": len(observations),
            "claims_recorded": len(claims),
            "relationships_recorded": len(relationships),
        }

    def run_memory_maintenance(self, now: str | None = None) -> dict[str, Any]:
        current_time = _parse_now(now)
        claims = self.state_store.list_claims({}, {"limit": 1000})
        updated = 0
        superseded = 0
        promoted = 0
        for claim in claims:
            previous_state = claim.get("state")
            previous_tier = claim.get("tier")
            recency = freshness_score(claim.get("updated_at"), now=current_time, half_life_days=_half_life_days(claim))
            claim["freshness"] = recency
            claim["confidence_factors"] = dict(claim.get("confidence_factors", {}))
            claim["confidence_factors"]["recency_score"] = recency
            claim["confidence"] = confidence_from_factors(claim["confidence_factors"])
            if (
                claim.get("tier") == "semantic"
                and float(claim.get("confidence", 0.0) or 0.0) >= 0.75
                and len(claim.get("supporting_observation_ids", [])) >= 3
            ):
                claim["tier"] = "procedural"
            if recency < 0.2 and claim.get("state") == "active":
                claim["state"] = "stale"
            sibling = self._find_superseding_claim(claim, claims)
            if sibling is not None and sibling.get("claim_id") != claim.get("claim_id"):
                supersession = SupersessionRecord(
                    supersession_id=f"sup_{uuid4().hex[:12]}",
                    old_claim_id=str(claim["claim_id"]),
                    new_claim_id=str(sibling["claim_id"]),
                    reason="newer supported claim supersedes older equivalent statement",
                    created_at=_timestamp(),
                    created_by="memory_maintenance",
                )
                supersession.validate()
                self.state_store.save_supersession(supersession.to_dict())
                claim["state"] = "superseded"
                claim["superseded_by"] = sibling["claim_id"]
                superseded += 1
            claim["updated_at"] = _timestamp()
            if claim.get("state") != previous_state or claim.get("tier") != previous_tier or claim["freshness"] != recency:
                updated += 1
            if previous_tier != claim.get("tier") and claim.get("tier") == "procedural":
                promoted += 1
            self.state_store.save_claim(claim)
        return {
            "claims_scanned": len(claims),
            "claims_updated": updated,
            "claims_promoted": promoted,
            "claims_superseded": superseded,
            "ran_at": _timestamp(),
        }

    def _find_superseding_claim(self, claim: dict[str, Any], claims: list[dict[str, Any]]) -> dict[str, Any] | None:
        for candidate in claims:
            if candidate.get("claim_id") == claim.get("claim_id"):
                continue
            if str(candidate.get("state")) != "active":
                continue
            if str(candidate.get("statement", "")).strip().lower() != str(claim.get("statement", "")).strip().lower():
                continue
            if float(candidate.get("confidence", 0.0) or 0.0) > float(claim.get("confidence", 0.0) or 0.0):
                return candidate
        return None


def _scope_for_session(session: Any, service: str | None) -> dict[str, Any]:
    return {
        "shared": True,
        "service": service,
        "run_id": session.run_id,
        "goal_id": session.goal_id,
    }


def _service_from_artifacts(artifacts: dict[str, Any]) -> str | None:
    trigger = artifacts.get("trigger", {}) if isinstance(artifacts, dict) else {}
    if isinstance(trigger, dict):
        service = trigger.get("service")
        if service:
            return str(service)
    return None


def _namespace_from_artifacts(artifacts: dict[str, Any]) -> str | None:
    """Best-effort namespace extraction for ``InfraGraph`` node-key stamping.

    Triggers don't carry a top-level ``namespace`` field — it's hidden
    in ``related_context``. Mesh's two common shapes are:

    * CloudOpsBench-style triggers stamp ``cloudopsbench_namespace``
      (e.g. ``"boutique"``).
    * Native Kubernetes triggers populate ``namespace`` directly.

    Returns ``None`` if neither is present; ``_node_key`` substitutes
    ``_cluster`` so the resulting key is still well-formed.
    """
    if not isinstance(artifacts, dict):
        return None
    trigger = artifacts.get("trigger") if isinstance(artifacts.get("trigger"), dict) else {}
    related = trigger.get("related_context") if isinstance(trigger.get("related_context"), dict) else {}
    for key in ("namespace", "cloudopsbench_namespace", "k8s_namespace"):
        value = related.get(key) if isinstance(related, dict) else None
        if value:
            return str(value)
    direct = trigger.get("namespace") if isinstance(trigger, dict) else None
    if direct:
        return str(direct)
    return None


def _service_for_event(session: Any, payload: dict[str, Any]) -> str | None:
    if isinstance(payload, dict) and payload.get("service"):
        return str(payload.get("service"))
    return _service_from_artifacts(session.artifacts if hasattr(session, "artifacts") else {})


def _observation_content(event: Any) -> str:
    if isinstance(event.summary, dict) and event.summary:
        pairs = ", ".join(f"{key}={value}" for key, value in event.summary.items())
        return f"{event.event_type}: {pairs}"
    return f"{event.event_type}: recorded during {event.stage}"


def _agent_attempts(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = artifacts.get("agent_tasks", []) if isinstance(artifacts, dict) else []
    attempts: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for attempt in task.get("attempts", []):
            if isinstance(attempt, dict):
                attempts.append(attempt)
    return attempts


def _half_life_days(claim: dict[str, Any]) -> float:
    tier = str(claim.get("tier", "semantic"))
    if tier == "procedural":
        return 180.0
    if tier == "episodic":
        return 14.0
    return 45.0


def _parse_now(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
