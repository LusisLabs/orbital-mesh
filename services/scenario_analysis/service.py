"""Cross-run scenario analysis and advisory decision synthesis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from shared.mesh_runtime import ClaimRecord, EvidenceNode, ObservationRecord, ScenarioAnalysis, Subdecision, Trigger
from shared.mesh_runtime.memory_scoring import confidence_from_factors, freshness_score, support_score
from shared.mesh_runtime.review_blockers import classify_review_reasons
from shared.mesh_runtime.active_memory import ActiveMemoryStore

_ACTIONABLE_RECOMMENDATIONS = {
    "reduce_rollout",
    "disable_flag",
    "escalate",
    "investigate_and_patch",
    "rollback_deployment",
    "restart_deployment",
    "restart_systemd_service",
}


@dataclass
class ScenarioAnalysisInput:
    trigger: Trigger
    run_id: str | None
    source_event_ids: list[str]
    service_context: dict[str, Any]
    learning_context: dict[str, Any]
    historical_success_rates: dict[str, float | None]
    recovery_patterns: dict[str, int]
    memory_packet: dict[str, Any]
    recent_runs: list[dict[str, Any]]
    reasoning_bank_packet: dict[str, Any]
    investigation_report: dict[str, Any]


class Analyzer(Protocol):
    name: str

    def analyze(self, payload: ScenarioAnalysisInput) -> tuple[list[EvidenceNode], Subdecision]: ...


class ScenarioAnalysisService:
    def __init__(
        self,
        *,
        state_store: Any | None = None,
        learning_store: Any | None = None,
        context_store: Any | None = None,
        active_memory: ActiveMemoryStore | None = None,
        analyzers: list[Analyzer] | None = None,
    ) -> None:
        self.state_store = state_store
        self.learning_store = learning_store
        self.context_store = context_store
        self.active_memory = active_memory
        self.analyzers = analyzers or [
            RegressionAnalyzer(),
            KubernetesAnalyzer(),
            RethNodeAnalyzer(),
            InvestigationAnalyzer(),
            HistoricalOutcomeAnalyzer(),
            RiskScopeAnalyzer(),
            MemoryRelevanceAnalyzer(),
            EdgeCaseAnalyzer(),
        ]

    def analyze(
        self,
        trigger: Trigger,
        *,
        run_id: str | None = None,
        reasoning_bank_packet: dict[str, Any] | None = None,
        investigation_report: dict[str, Any] | None = None,
    ) -> tuple[ScenarioAnalysis, Any | None]:
        payload = self._build_input(
            trigger,
            run_id,
            reasoning_bank_packet=reasoning_bank_packet,
            investigation_report=investigation_report,
        )
        evidence_nodes: list[EvidenceNode] = []
        subdecisions: list[Subdecision] = []

        for analyzer in self.analyzers:
            if isinstance(analyzer, InvestigationAnalyzer) and not payload.investigation_report:
                continue
            if (
                isinstance(analyzer, InvestigationAnalyzer)
                and payload.investigation_report.get("stop_reason") == "investigation_failed_existing_path_continues"
            ):
                continue
            analyzer_evidence, subdecision = analyzer.analyze(payload)
            evidence_nodes.extend(analyzer_evidence)
            subdecisions.append(subdecision)
            observation_ids = self._persist_analyzer_observations(trigger.service, analyzer_evidence)
            self._persist_analyzer_claims(trigger.service, analyzer_evidence, observation_ids)

        synthesis = DecisionSynthesisService().synthesize(trigger, subdecisions, evidence_nodes)
        memory_record = None
        if self.active_memory is not None:
            refreshed_packet = (
                payload.memory_packet
                if reasoning_bank_packet is not None
                else self._retrieve_memory_packet(trigger, run_id)
            )
            if not refreshed_packet.get("claims") and not refreshed_packet.get("procedures"):
                refreshed_packet = {
                    "claims": [
                        {
                            "statement": evidence.summary,
                            "tier": evidence.kind,
                            "state": "active",
                            "confidence": evidence.confidence,
                            "supporting_observation_ids": [],
                            "updated_at": _timestamp(),
                        }
                        for evidence in evidence_nodes
                        if _should_persist_evidence(evidence)
                    ],
                    "procedures": [],
                }
            memory_record = self.active_memory.project_packet(
                run_id=run_id,
                service=trigger.service,
                packet=refreshed_packet,
                source_event_ids=payload.source_event_ids,
            )

        analysis = ScenarioAnalysis(
            analysis_id=f"analysis_{trigger.trigger_id}_{uuid4().hex[:8]}",
            trigger_id=trigger.trigger_id,
            created_at=_timestamp(),
            suggested_decision_type=synthesis["suggested_decision_type"],
            confidence=synthesis["confidence"],
            risk_level=synthesis["risk_level"],
            autonomy_tier_hint=synthesis["autonomy_tier_hint"],
            required_review_reasons=synthesis["required_review_reasons"],
            evidence_refs=synthesis["evidence_refs"],
            subdecisions=[item.to_dict() for item in subdecisions],
            evidence_nodes=[item.to_dict() for item in evidence_nodes],
            merkle_root=None,
            merkle_event_ids=[],
            quality_measurements=_quality_measurements(payload),
        )
        analysis.validate()
        return analysis, memory_record

    def _build_input(
        self,
        trigger: Trigger,
        run_id: str | None,
        *,
        reasoning_bank_packet: dict[str, Any] | None = None,
        investigation_report: dict[str, Any] | None = None,
    ) -> ScenarioAnalysisInput:
        source_event_ids = _source_event_ids(self.state_store, run_id)
        service_context = self.context_store.get_service_context(trigger.service) if self.context_store else {}
        learning_context = (
            self.learning_store.enrich_context(trigger.service, trigger.endpoint, trigger.flag_key)
            if self.learning_store
            else {}
        )
        success_rates = {}
        if self.learning_store:
            for action in sorted(_ACTIONABLE_RECOMMENDATIONS - {"escalate"}):
                success_rates[action] = self.learning_store.get_historical_success_rate(action, trigger.service)
        recovery_patterns = self.learning_store.get_recovery_patterns(trigger.service) if self.learning_store else {}
        memory_packet = dict(reasoning_bank_packet or {}) or self._retrieve_memory_packet(trigger, run_id)
        return ScenarioAnalysisInput(
            trigger=trigger,
            run_id=run_id,
            source_event_ids=source_event_ids,
            service_context=service_context,
            learning_context=learning_context,
            historical_success_rates=success_rates,
            recovery_patterns=recovery_patterns,
            memory_packet=memory_packet,
            recent_runs=_recent_runs(self.state_store, trigger.service, run_id),
            reasoning_bank_packet=dict(reasoning_bank_packet or {}),
            investigation_report=investigation_report or {},
        )

    def _retrieve_memory_packet(self, trigger: Trigger, run_id: str | None) -> dict[str, Any]:
        if self.state_store is None or not hasattr(self.state_store, "retrieve_memory"):
            return {}
        response = self.state_store.retrieve_memory(
            {
                "query": " ".join(filter(None, [trigger.service, trigger.endpoint, trigger.trigger_type])),
                "scope": {"service": trigger.service, "run_id": run_id},
                "limit": 8,
            }
        )
        return dict(response.get("packet", {}))

    def _persist_analyzer_observations(self, service: str, evidence_nodes: list[EvidenceNode]) -> dict[str, str]:
        observation_ids: dict[str, str] = {}
        if self.state_store is None or not hasattr(self.state_store, "append_observation"):
            return observation_ids
        for evidence in evidence_nodes:
            if not _should_persist_evidence(evidence):
                continue
            observation = ObservationRecord(
                observation_id=f"obs_{uuid4().hex[:12]}",
                scope={"shared": True, "service": service, "run_id": evidence.run_id},
                kind=evidence.kind,
                content=evidence.summary,
                service=service,
                run_id=evidence.run_id,
                source_type="scenario_analysis",
                source_refs=[{"run_id": evidence.run_id, "event_id": event_id} for event_id in evidence.source_event_ids],
                created_at=_timestamp(),
                author=f"analyzer:{evidence.analyzer}",
                tags=[evidence.analyzer, evidence.kind],
                metadata={"confidence": evidence.confidence, "trusted": evidence.trusted, "payload": evidence.payload},
            )
            observation.validate()
            self.state_store.append_observation(observation.to_dict())
            observation_ids[evidence.evidence_id] = observation.observation_id
        return observation_ids

    def _persist_analyzer_claims(self, service: str, evidence_nodes: list[EvidenceNode], observation_ids: dict[str, str]) -> None:
        if self.state_store is None or not hasattr(self.state_store, "save_claim"):
            return
        for evidence in evidence_nodes:
            if not _should_persist_evidence(evidence) or evidence.confidence < 0.55:
                continue
            if _claim_exists(self.state_store, service, evidence):
                continue
            factors = {
                "support_score": support_score(1),
                "recency_score": freshness_score(_timestamp(), half_life_days=14.0),
                "authority_score": 0.82,
                "consistency_score": 0.75,
                "verification_score": max(0.55, min(float(evidence.confidence), 1.0)),
            }
            claim = ClaimRecord(
                claim_id=f"claim_{uuid4().hex[:12]}",
                statement=evidence.summary,
                entity_refs=[service, evidence.analyzer],
                supporting_observation_ids=[observation_ids[evidence.evidence_id]] if evidence.evidence_id in observation_ids else [],
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
            self.state_store.save_claim(claim.to_dict())


class RegressionAnalyzer:
    name = "regression"

    def analyze(self, payload: ScenarioAnalysisInput) -> tuple[list[EvidenceNode], Subdecision]:
        trigger = payload.trigger
        if trigger.trigger_type != "feature_flag_performance_regression":
            return _single_evidence_subdecision(
                payload,
                self.name,
                kind="not_applicable",
                summary="No feature-flag regression telemetry applies to this trigger.",
                recommendation="no_action",
                confidence=0.6,
                risk_level="low",
                reasons=["trigger is not a feature-flag performance regression"],
                requires_review=False,
            )
        baseline_latency = trigger.metrics.get("baseline_p95_latency_ms") or 0
        observed_latency = trigger.metrics.get("observed_p95_latency_ms") or 0
        baseline_error = trigger.metrics.get("baseline_error_rate") or 0
        observed_error = trigger.metrics.get("observed_error_rate") or 0
        timeout_rate = trigger.metrics.get("observed_timeout_rate") or 0
        latency_delta = _delta_pct(baseline_latency, observed_latency)
        error_ratio = _ratio(baseline_error, observed_error)
        recommendation = "disable_flag" if timeout_rate >= 0.02 or error_ratio >= 2 or latency_delta >= 40 else "reduce_rollout"
        evidence = _evidence(
            payload,
            self.name,
            "telemetry_regression",
            f"Latency delta {latency_delta:.1f}%, error ratio {error_ratio:.2f}x, timeout rate {timeout_rate:.3f}.",
            {
                "latency_delta_pct": latency_delta,
                "error_ratio": error_ratio,
                "timeout_rate": timeout_rate,
                "trigger_signals": trigger.related_context.get("trigger_signals", []),
            },
            0.86,
            True,
        )
        return [evidence], _subdecision(
            self.name,
            recommendation,
            0.86,
            "medium",
            ["feature flag telemetry exceeds bounded remediation thresholds"],
            [evidence.evidence_id],
            False,
        )


class KubernetesAnalyzer:
    name = "kubernetes"

    def analyze(self, payload: ScenarioAnalysisInput) -> tuple[list[EvidenceNode], Subdecision]:
        trigger = payload.trigger
        if trigger.trigger_type != "kubernetes_deployment_unhealthy":
            return _single_evidence_subdecision(
                payload,
                self.name,
                kind="not_applicable",
                summary="No Kubernetes rollout evidence applies to this trigger.",
                recommendation="no_action",
                confidence=0.6,
                risk_level="low",
                reasons=["trigger is not a Kubernetes deployment issue"],
                requires_review=False,
            )
        rc = trigger.related_context
        signatures = list(rc.get("error_signatures", []))
        rollout_status = str(rc.get("rollout_status", "unknown"))
        correlation = rc.get("correlation", {})
        requires_review = correlation.get("type") in {"blast_wave", "cascading"}
        if "image_pull_failure" in signatures or rollout_status == "failed":
            recommendation = "rollback_deployment"
            confidence = 0.9
        elif any(sig in signatures for sig in ("crash_loop", "probe_failure", "oom_killed", "application_error")):
            recommendation = "restart_deployment"
            confidence = 0.78
        else:
            recommendation = "escalate"
            confidence = 0.62
            requires_review = True
        evidence = _evidence(
            payload,
            self.name,
            "kubernetes_rollout",
            f"Rollout status {rollout_status}; signatures: {', '.join(signatures or ['none'])}.",
            {
                "rollout_status": rollout_status,
                "error_signatures": signatures,
                "correlation": correlation,
            },
            confidence,
            bool(signatures or rollout_status != "unknown"),
        )
        reasons = ["Kubernetes rollout evidence maps to a bounded action"]
        if requires_review:
            reasons.append("cross-run correlation requires approval")
        return [evidence], _subdecision(
            self.name,
            recommendation,
            confidence,
            "medium" if recommendation != "escalate" else "high",
            reasons,
            [evidence.evidence_id],
            requires_review,
        )


class RethNodeAnalyzer:
    name = "reth_node"

    def analyze(self, payload: ScenarioAnalysisInput) -> tuple[list[EvidenceNode], Subdecision]:
        trigger = payload.trigger
        if trigger.trigger_type != "reth_node_degraded":
            return _single_evidence_subdecision(
                payload,
                self.name,
                kind="not_applicable",
                summary="No Reth node evidence applies to this trigger.",
                recommendation="no_action",
                confidence=0.6,
                risk_level="low",
                reasons=["trigger is not a Reth node degradation"],
                requires_review=False,
            )

        rc = trigger.related_context
        signatures = set(str(sig) for sig in rc.get("error_signatures", []))
        unsafe = signatures & {
            "authrpc_exposed",
            "consensus_disconnected",
            "db_corruption_suspected",
            "disk_pressure",
            "jwt_missing",
            "jwt_secret_insecure_permissions",
            "restart_frequency_exceeded",
            "rpc_exposed",
        }
        restartable = signatures & {"peer_starvation", "sync_stalled", "rpc_degraded"}
        if unsafe:
            recommendation = "escalate"
            confidence = 0.84
            risk_level = "high"
            requires_review = True
            reasons = [f"Reth unsafe signature(s): {', '.join(sorted(unsafe))}"]
        elif restartable:
            recommendation = "restart_systemd_service"
            confidence = 0.76
            risk_level = "medium"
            requires_review = True
            reasons = ["Reth restartable signature requires approval-gated systemd remediation"]
        else:
            recommendation = "no_action"
            confidence = 0.68
            risk_level = "low"
            requires_review = False
            reasons = ["Reth trigger did not carry actionable signatures"]

        evidence = _evidence(
            payload,
            self.name,
            "reth_node_health",
            f"Reth node signatures: {', '.join(sorted(signatures)) or 'none'}.",
            {
                "error_signatures": sorted(signatures),
                "node": rc.get("node", {}),
                "execution": rc.get("execution", {}),
                "consensus": rc.get("consensus", {}),
                "storage": rc.get("storage", {}),
                "rpc": rc.get("rpc", {}),
            },
            confidence,
            bool(signatures),
        )
        return [evidence], _subdecision(
            self.name,
            recommendation,
            confidence,
            risk_level,
            reasons,
            [evidence.evidence_id],
            requires_review,
        )


class InvestigationAnalyzer:
    name = "investigation"

    def analyze(self, payload: ScenarioAnalysisInput) -> tuple[list[EvidenceNode], Subdecision]:
        report = payload.investigation_report or {}
        if not report:
            return _single_evidence_subdecision(
                payload,
                self.name,
                kind="not_applicable",
                summary="No investigation report is attached to this run.",
                recommendation="no_action",
                confidence=0.6,
                risk_level="low",
                reasons=["investigation stage not present"],
                requires_review=False,
            )
        stop_reason = str(report.get("stop_reason", "unknown"))
        findings = list(report.get("findings", []) or [])
        uncertainty = float(report.get("uncertainty", 0.5) or 0.5)
        failed = stop_reason == "investigation_failed_existing_path_continues"
        summary = (
            "Investigation failed; scenario analysis will continue with existing evidence."
            if failed
            else f"Investigation produced {len(findings)} finding(s) with uncertainty {uncertainty:.2f}."
        )
        evidence = _evidence(
            payload,
            self.name,
            "investigation_report",
            summary,
            {
                "report_id": report.get("report_id"),
                "stop_reason": stop_reason,
                "uncertainty": uncertainty,
                "finding_count": len(findings),
                "citations": list(report.get("citations", []) or [])[:8],
            },
            0.0 if failed else max(0.5, min(1.0 - uncertainty, 0.9)),
            not failed,
        )
        return [evidence], _subdecision(
            self.name,
            "no_action",
            evidence.confidence,
            "low",
            ["investigation is advisory and does not bypass live evidence"],
            [evidence.evidence_id],
            False,
        )


class HistoricalOutcomeAnalyzer:
    name = "historical_outcome"

    def analyze(self, payload: ScenarioAnalysisInput) -> tuple[list[EvidenceNode], Subdecision]:
        best_rate = None
        best_action = None
        weak_actions = []
        recovery_context = _recovery_context(payload)
        corroborating_evidence = int(recovery_context.get("corroborating_evidence_count", 0) or 0)
        for action, rate in payload.historical_success_rates.items():
            if rate is None:
                continue
            if best_rate is None or rate > best_rate:
                best_rate = rate
                best_action = action
            if rate < 0.4:
                weak_actions.append(action)
        evidence = _evidence(
            payload,
            self.name,
            "historical_outcomes",
            "Historical remediation outcomes summarized for this service.",
            {
                "success_rates": payload.historical_success_rates,
                "learning_context": payload.learning_context,
                "recovery_patterns": payload.recovery_patterns,
            },
            0.75 if best_rate is not None else 0.55,
            True,
        )
        if weak_actions and corroborating_evidence < 2:
            return [evidence], _subdecision(
                self.name,
                "approval_required",
                0.68,
                "medium",
                [f"historical success rate is weak for: {', '.join(sorted(weak_actions))}"],
                [evidence.evidence_id],
                True,
            )
        if weak_actions:
            return [evidence], _subdecision(
                self.name,
                best_action or "no_action",
                max(best_rate or 0.55, 0.76),
                "low",
                ["historical weakness is offset by corroborating recovery evidence"],
                [evidence.evidence_id],
                False,
            )
        return [evidence], _subdecision(
            self.name,
            best_action or "no_action",
            best_rate or 0.55,
            "low",
            ["historical outcomes do not add a blocking concern"],
            [evidence.evidence_id],
            False,
        )


class RiskScopeAnalyzer:
    name = "risk_scope"

    def analyze(self, payload: ScenarioAnalysisInput) -> tuple[list[EvidenceNode], Subdecision]:
        rc = payload.trigger.related_context
        reasons: list[str] = []
        if rc.get("rollbacks_last_24h", 0) > 0:
            reasons.append("recent rollback cooldown is active")
        if rc.get("multi_service_impact"):
            reasons.append("signal indicates multi-service impact")
        if rc.get("high_business_impact"):
            reasons.append("signal indicates high business impact")
        if rc.get("feature_flag_credentials_available") is False or rc.get("cluster_access_available") is False:
            reasons.append("required execution credentials are unavailable")
        correlation = rc.get("correlation", {})
        if correlation.get("type") in {"blast_wave", "cascading"}:
            reasons.append(f"correlated failure type is {correlation.get('type')}")
        evidence = _evidence(payload, self.name, "risk_scope", "; ".join(reasons) or "No elevated risk scope detected.", {"risk_reasons": reasons}, 0.8, True)
        return [evidence], _subdecision(
            self.name,
            "approval_required" if reasons else "no_action",
            0.82 if reasons else 0.72,
            "high" if any("high business" in reason for reason in reasons) else "medium" if reasons else "low",
            reasons or ["scope does not require extra approval"],
            [evidence.evidence_id],
            bool(reasons),
        )


class MemoryRelevanceAnalyzer:
    name = "memory_relevance"

    def analyze(self, payload: ScenarioAnalysisInput) -> tuple[list[EvidenceNode], Subdecision]:
        packet = payload.memory_packet or {}
        active_count = len(packet.get("claims", [])) + len(packet.get("procedures", []))
        recent_count = len(payload.recent_runs)
        memory_count = len(packet.get("observations", []))
        evidence = _evidence(
            payload,
            self.name,
            "active_memory",
            f"Active memory has {active_count} fact(s), {recent_count} recent run(s), {memory_count} search hit(s).",
            {
                "active_fact_count": active_count,
                "recent_run_count": recent_count,
                "memory_search_hit_count": memory_count,
                "verified_claims": packet.get("claims", [])[:5],
                "verified_procedures": packet.get("procedures", [])[:3],
                "contradictions": packet.get("contradictions", [])[:3],
            },
            0.7 if active_count or recent_count or memory_count else 0.55,
            True,
        )
        return [evidence], _subdecision(
            self.name,
            "no_action",
            0.7,
            "low",
            ["memory context is advisory and does not bypass live evidence"],
            [evidence.evidence_id],
            False,
        )


class EdgeCaseAnalyzer:
    name = "edge_case"

    def analyze(self, payload: ScenarioAnalysisInput) -> tuple[list[EvidenceNode], Subdecision]:
        trigger = payload.trigger
        recovery_context = _recovery_context(payload)
        corroborating_evidence = int(recovery_context.get("corroborating_evidence_count", 0) or 0)
        reasons: list[str] = []
        resolved: list[str] = []
        if trigger.trigger_type not in {
            "feature_flag_performance_regression",
            "kubernetes_deployment_unhealthy",
            "reth_node_degraded",
        }:
            reasons.append(f"unclassified trigger type {trigger.trigger_type}")
        if trigger.related_context.get("conflicting_signals"):
            if corroborating_evidence >= 2:
                resolved.append("conflicting signals were reduced by corroborating recovery evidence")
            else:
                reasons.append("conflicting signals are present")
        if payload.run_id is not None and not payload.source_event_ids:
            reasons.append("no source run event ids available for analysis provenance")
        if trigger.trigger_type == "kubernetes_deployment_unhealthy" and not trigger.related_context.get("error_signatures"):
            if corroborating_evidence >= 2:
                resolved.append("Kubernetes trigger reused corroborating prior rollout evidence")
            else:
                reasons.append("Kubernetes trigger lacks error signatures")
        evidence = _evidence(
            payload,
            self.name,
            "edge_case_scan",
            "; ".join(reasons or resolved) or "No fail-closed edge case found.",
            {"edge_case_reasons": reasons, "resolved_edge_cases": resolved},
            0.9 if reasons else (0.8 if resolved else 0.75),
            True,
        )
        review_analysis = classify_review_reasons(reasons)
        risk_level = (
            "high"
            if review_analysis["terminal_review_reasons"] or review_analysis["unclassified_review_reasons"]
            else ("medium" if reasons else "low")
        )
        return [evidence], _subdecision(
            self.name,
            "escalate" if reasons else "no_action",
            0.9 if reasons else (0.8 if resolved else 0.75),
            risk_level,
            reasons or resolved or ["edge-case scan passed"],
            [evidence.evidence_id],
            bool(reasons),
        )


class DecisionSynthesisService:
    def synthesize(
        self,
        trigger: Trigger,
        subdecisions: list[Subdecision],
        evidence_nodes: list[EvidenceNode],
    ) -> dict[str, Any]:
        review_reasons: list[str] = []
        for item in subdecisions:
            if item.requires_review:
                review_reasons.extend(item.reasons)
        actionable = [item for item in subdecisions if item.recommendation in _ACTIONABLE_RECOMMENDATIONS]
        review_analysis = classify_review_reasons(review_reasons)
        if review_reasons:
            safe_actionable = [item for item in actionable if item.recommendation != "escalate"]
            conflict_only_review = bool(review_reasons) and all("conflicting signals" in reason for reason in review_reasons)
            if conflict_only_review and safe_actionable:
                suggested = max(safe_actionable, key=lambda item: item.confidence).recommendation
                autonomy = "approval_required"
            elif review_analysis["terminal_review_reasons"] or review_analysis["unclassified_review_reasons"]:
                suggested = "escalate" if any(item.recommendation == "escalate" for item in actionable) else _base_suggestion(trigger)
                autonomy = "approval_required"
            elif safe_actionable:
                suggested = max(safe_actionable, key=lambda item: item.confidence).recommendation
                autonomy = "approval_required"
            else:
                suggested = _base_suggestion(trigger)
                autonomy = "approval_required"
        elif actionable:
            suggested = max(actionable, key=lambda item: item.confidence).recommendation
            autonomy = "autonomous"
        else:
            suggested = _base_suggestion(trigger)
            autonomy = "autonomous"
        confidence_values = [item.confidence for item in subdecisions]
        confidence = round(sum(confidence_values) / len(confidence_values), 2) if confidence_values else 0.5
        if review_analysis["terminal_review_reasons"] or review_analysis["unclassified_review_reasons"]:
            confidence = min(confidence, 0.74)
        risk_level = "high" if any(item.risk_level == "high" for item in subdecisions) else "medium" if any(item.risk_level == "medium" for item in subdecisions) else "low"
        if suggested == "escalate":
            autonomy = "escalated"
        return {
            "suggested_decision_type": suggested,
            "confidence": max(0.5, min(confidence, 0.95)),
            "risk_level": risk_level,
            "autonomy_tier_hint": autonomy,
            "required_review_reasons": sorted(set(review_reasons)),
            "evidence_refs": [item.evidence_id for item in evidence_nodes],
        }


def _source_event_ids(state_store: Any | None, run_id: str | None) -> list[str]:
    if state_store is None or run_id is None:
        return []
    events = state_store.list_run_events(run_id)
    return [event.event_id for event in events if event.event_type in {"trigger_ready", "normalized_event"}]


def _quality_measurements(payload: ScenarioAnalysisInput) -> dict[str, Any]:
    memory_packet = payload.memory_packet
    claims = memory_packet.get("claims", []) if isinstance(memory_packet, dict) else []
    procedures = memory_packet.get("procedures", []) if isinstance(memory_packet, dict) else []
    observations = memory_packet.get("observations", []) if isinstance(memory_packet, dict) else []
    decision_impact = memory_packet.get("decision_impact", {}) if isinstance(memory_packet, dict) else {}
    retrieval_improved = (
        decision_impact.get("retrieval_improved_decision") is True if isinstance(decision_impact, dict) else False
    )
    if payload.trigger.related_context.get("retrieval_improved_decision") is True:
        retrieval_improved = True
    return {
        "retrieval_claim_count": len(claims),
        "retrieval_procedure_count": len(procedures),
        "retrieval_observation_count": len(observations),
        "retrieval_improved_decision": retrieval_improved,
    }


def _recent_runs(state_store: Any | None, service: str, run_id: str | None) -> list[dict[str, Any]]:
    if state_store is None:
        return []
    recent = []
    for session in state_store.list_run_sessions(limit=25):
        if session.run_id == run_id:
            continue
        artifacts = session.artifacts if isinstance(session.artifacts, dict) else {}
        trigger = artifacts.get("trigger", {})
        if trigger.get("service") == service:
            recent.append(
                {
                    "run_id": session.run_id,
                    "stage": session.stage,
                    "status": session.status,
                    "decision_type": artifacts.get("decision", {}).get("decision_type"),
                    "feedback_outcome": artifacts.get("feedback", {}).get("outcome"),
                }
            )
    return recent[:10]


def _single_evidence_subdecision(
    payload: ScenarioAnalysisInput,
    analyzer: str,
    *,
    kind: str,
    summary: str,
    recommendation: str,
    confidence: float,
    risk_level: str,
    reasons: list[str],
    requires_review: bool,
) -> tuple[list[EvidenceNode], Subdecision]:
    evidence = _evidence(payload, analyzer, kind, summary, {}, confidence, True)
    return [evidence], _subdecision(analyzer, recommendation, confidence, risk_level, reasons, [evidence.evidence_id], requires_review)


def _should_persist_evidence(evidence: EvidenceNode) -> bool:
    if not evidence.trusted:
        return False
    if evidence.kind == "not_applicable":
        return False
    if evidence.analyzer == "memory_relevance":
        payload = evidence.payload if isinstance(evidence.payload, dict) else {}
        if not payload.get("verified_claims") and not payload.get("verified_procedures"):
            return False
    if evidence.confidence < 0.7 and evidence.kind in {"active_memory", "historical_outcomes"}:
        return False
    return True


def _claim_exists(state_store: Any, service: str, evidence: EvidenceNode) -> bool:
    if not hasattr(state_store, "list_claims"):
        return False
    for record in state_store.list_claims({"service": service}, {"limit": 200}):
        if (
            record.get("statement") == evidence.summary
            and service in record.get("entity_refs", [])
            and evidence.analyzer in record.get("entity_refs", [])
            and record.get("state", "active") == "active"
        ):
            return True
    return False


def _recovery_context(payload: ScenarioAnalysisInput) -> dict[str, Any]:
    raw = payload.trigger.related_context.get("recovery_context")
    return dict(raw) if isinstance(raw, dict) else {}


def _evidence(
    payload: ScenarioAnalysisInput,
    analyzer: str,
    kind: str,
    summary: str,
    evidence_payload: dict[str, Any],
    confidence: float,
    trusted: bool,
) -> EvidenceNode:
    node = EvidenceNode(
        evidence_id=f"ev_{analyzer}_{uuid4().hex[:10]}",
        run_id=payload.run_id,
        analyzer=analyzer,
        kind=kind,
        summary=summary,
        payload=evidence_payload,
        source_event_ids=list(payload.source_event_ids),
        confidence=max(0.0, min(float(confidence), 1.0)),
        trusted=trusted,
    )
    node.validate()
    return node


def _subdecision(
    analyzer: str,
    recommendation: str,
    confidence: float,
    risk_level: str,
    reasons: list[str],
    evidence_refs: list[str],
    requires_review: bool,
) -> Subdecision:
    item = Subdecision(
        subdecision_id=f"sub_{analyzer}_{uuid4().hex[:10]}",
        analyzer=analyzer,
        recommendation=recommendation,
        confidence=max(0.0, min(float(confidence), 1.0)),
        risk_level=risk_level,
        reasons=list(reasons),
        evidence_refs=list(evidence_refs),
        requires_review=requires_review,
    )
    item.validate()
    return item


def _base_suggestion(trigger: Trigger) -> str:
    if trigger.trigger_type == "kubernetes_deployment_unhealthy":
        signatures = set(trigger.related_context.get("error_signatures", []))
        if "image_pull_failure" in signatures or trigger.related_context.get("rollout_status") == "failed":
            return "rollback_deployment"
        if signatures.intersection({"crash_loop", "probe_failure", "oom_killed", "application_error"}):
            return "restart_deployment"
        return "escalate"
    if trigger.trigger_type == "reth_node_degraded":
        signatures = set(trigger.related_context.get("error_signatures", []))
        if signatures.intersection({"peer_starvation", "sync_stalled", "rpc_degraded"}):
            return "restart_systemd_service"
        if signatures:
            return "escalate"
        return "no_action"
    timeout_rate = trigger.metrics.get("observed_timeout_rate") or 0.0
    latency_delta = _delta_pct(trigger.metrics.get("baseline_p95_latency_ms") or 0, trigger.metrics.get("observed_p95_latency_ms") or 0)
    error_ratio = _ratio(trigger.metrics.get("baseline_error_rate") or 0, trigger.metrics.get("observed_error_rate") or 0)
    return "disable_flag" if timeout_rate >= 0.02 or error_ratio >= 2 or latency_delta >= 40 else "reduce_rollout"


def _delta_pct(baseline: float, observed: float) -> float:
    if baseline == 0:
        return 0.0
    return round(((observed - baseline) / baseline) * 100, 1)


def _ratio(baseline: float, observed: float) -> float:
    if baseline == 0:
        return 0.0 if observed == 0 else float("inf")
    return round(observed / baseline, 2)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
