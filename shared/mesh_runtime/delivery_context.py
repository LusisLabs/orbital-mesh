from __future__ import annotations

import hashlib
import time
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


DELIVERY_CONTEXT_GRAPH_SCHEMA = "delivery-context-graph.schema.json"
DELIVERY_CONTEXT_GRAPH_VERSION = "mesh.delivery_context_graph.v1"
DELIVERY_CONTEXT_STATE_SLICE = "delivery-context-graph-contracts"

DELIVERY_NODE_KINDS = (
    "PullRequest",
    "Commit",
    "CheckSuite",
    "WorkflowRun",
    "BuildArtifact",
    "DeploymentEvent",
    "RuntimeSignal",
    "PolicyDecision",
    "AgentAttempt",
    "FeedbackEvent",
    "EvidenceGap",
    "ZaxyMirror",
)

DELIVERY_EDGE_KINDS = (
    "pr_contains_commit",
    "commit_has_check_suite",
    "check_suite_runs_workflow",
    "workflow_produces_build",
    "build_released_to_deployment",
    "deployment_emits_runtime_signal",
    "runtime_signal_informs_policy",
    "policy_routes_agent",
    "agent_attempt_addresses_gap",
    "node_has_evidence_gap",
    "policy_records_gap",
    "feedback_updates_policy",
    "feedback_confirms_deployment",
    "zaxy_mirrors_node",
)

DELIVERY_GATE_OUTCOMES = ("allow", "require_approval", "require_canary", "block_promotion")
DELIVERY_GATE_MODES = ("observe", "enforce")
DELIVERY_LANES = ("patch", "review", "staging", "remediation")

_EDGE_ENDPOINTS: dict[str, tuple[str, str]] = {
    "pr_contains_commit": ("PullRequest", "Commit"),
    "commit_has_check_suite": ("Commit", "CheckSuite"),
    "check_suite_runs_workflow": ("CheckSuite", "WorkflowRun"),
    "workflow_produces_build": ("WorkflowRun", "BuildArtifact"),
    "build_released_to_deployment": ("BuildArtifact", "DeploymentEvent"),
    "deployment_emits_runtime_signal": ("DeploymentEvent", "RuntimeSignal"),
    "runtime_signal_informs_policy": ("RuntimeSignal", "PolicyDecision"),
    "policy_routes_agent": ("PolicyDecision", "AgentAttempt"),
    "agent_attempt_addresses_gap": ("AgentAttempt", "EvidenceGap"),
    "node_has_evidence_gap": ("*", "EvidenceGap"),
    "policy_records_gap": ("PolicyDecision", "EvidenceGap"),
    "feedback_updates_policy": ("FeedbackEvent", "PolicyDecision"),
    "feedback_confirms_deployment": ("FeedbackEvent", "DeploymentEvent"),
    "zaxy_mirrors_node": ("*", "ZaxyMirror"),
}

_LANE_NODE_KINDS: dict[str, set[str]] = {
    "patch": {"PullRequest", "Commit", "RuntimeSignal", "EvidenceGap", "AgentAttempt", "PolicyDecision"},
    "review": {"PullRequest", "Commit", "CheckSuite", "WorkflowRun", "EvidenceGap", "AgentAttempt", "PolicyDecision"},
    "staging": {"WorkflowRun", "BuildArtifact", "DeploymentEvent", "RuntimeSignal", "PolicyDecision", "EvidenceGap"},
    "remediation": {"DeploymentEvent", "RuntimeSignal", "PolicyDecision", "FeedbackEvent", "EvidenceGap", "AgentAttempt"},
}


def build_delivery_context_graph(
    *,
    graph_id: str,
    service: str,
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    environment: str | None = None,
    generated_at: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    packet = {
        "schema_version": DELIVERY_CONTEXT_GRAPH_VERSION,
        "state_slice": DELIVERY_CONTEXT_STATE_SLICE,
        "graph_id": _required_text(graph_id, "graph_id"),
        "generated_at": generated_at or _timestamp(),
        "service": _required_text(service, "service"),
        "environment": _optional_text(environment),
        "nodes": [normalize_delivery_node(node) for node in nodes],
        "edges": [normalize_delivery_edge(edge) for edge in edges],
        "metadata": dict(metadata or {}),
    }
    validate_delivery_context_graph(packet)
    return packet


def validate_delivery_context_graph(packet: dict[str, Any]) -> None:
    validate_payload(DELIVERY_CONTEXT_GRAPH_SCHEMA, packet)
    if packet.get("schema_version") != DELIVERY_CONTEXT_GRAPH_VERSION:
        raise SchemaValidationError("$.schema_version: unsupported delivery context graph version")
    if packet.get("state_slice") != DELIVERY_CONTEXT_STATE_SLICE:
        raise SchemaValidationError("$.state_slice: unexpected state slice")

    nodes = packet.get("nodes")
    edges = packet.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise SchemaValidationError("$.nodes/$.edges: graph requires node and edge arrays")

    node_by_id: dict[str, dict[str, Any]] = {}
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise SchemaValidationError(f"$.nodes[{index}]: expected object")
        _validate_node_semantics(node, f"$.nodes[{index}]")
        node_id = node["id"]
        if node_id in node_by_id:
            raise SchemaValidationError(f"$.nodes[{index}].id: duplicate node id {node_id!r}")
        node_by_id[node_id] = node

    edge_ids: set[str] = set()
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            raise SchemaValidationError(f"$.edges[{index}]: expected object")
        _validate_edge_semantics(edge, node_by_id, f"$.edges[{index}]")
        edge_id = edge["id"]
        if edge_id in edge_ids:
            raise SchemaValidationError(f"$.edges[{index}].id: duplicate edge id {edge_id!r}")
        edge_ids.add(edge_id)


def validate_delivery_context_node_packet(node: dict[str, Any]) -> None:
    packet = {
        "schema_version": DELIVERY_CONTEXT_GRAPH_VERSION,
        "state_slice": DELIVERY_CONTEXT_STATE_SLICE,
        "graph_id": "node-validation",
        "generated_at": _timestamp(),
        "service": "validation",
        "environment": None,
        "nodes": [node],
        "edges": [],
        "metadata": {"validation_scope": "node"},
    }
    validate_delivery_context_graph(packet)


def validate_delivery_context_edge_packet(edge: dict[str, Any], *, from_kind: str, to_kind: str) -> None:
    from_node_id = edge.get("from_node_id") if isinstance(edge.get("from_node_id"), str) else "from"
    to_node_id = edge.get("to_node_id") if isinstance(edge.get("to_node_id"), str) else "to"
    packet = {
        "schema_version": DELIVERY_CONTEXT_GRAPH_VERSION,
        "state_slice": DELIVERY_CONTEXT_STATE_SLICE,
        "graph_id": "edge-validation",
        "generated_at": _timestamp(),
        "service": "validation",
        "environment": None,
        "nodes": [
            build_delivery_node(node_id=from_node_id, kind=from_kind, summary="from", source="validation"),
            build_delivery_node(node_id=to_node_id, kind=to_kind, summary="to", source="validation"),
        ],
        "edges": [edge],
        "metadata": {"validation_scope": "edge"},
    }
    validate_delivery_context_graph(packet)


def build_delivery_node(
    *,
    node_id: str,
    kind: str,
    summary: str,
    source: str,
    observed_at: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    evidence_refs: Sequence[str] | None = None,
) -> dict[str, Any]:
    node = {
        "id": _required_text(node_id, "node_id"),
        "kind": _required_text(kind, "kind"),
        "observed_at": observed_at or _timestamp(),
        "source": _required_text(source, "source"),
        "summary": _required_text(summary, "summary"),
        "metadata": dict(metadata or {}),
        "evidence_refs": [str(item) for item in evidence_refs or [] if str(item).strip()],
    }
    _validate_node_semantics(node, "$")
    return node


def normalize_delivery_node(node: Mapping[str, Any]) -> dict[str, Any]:
    return build_delivery_node(
        node_id=str(node.get("id") or ""),
        kind=str(node.get("kind") or ""),
        observed_at=str(node.get("observed_at") or "") or None,
        source=str(node.get("source") or ""),
        summary=str(node.get("summary") or ""),
        metadata=_mapping_or_empty(node.get("metadata")),
        evidence_refs=_sequence_or_empty(node.get("evidence_refs")),
    )


def build_delivery_edge(
    *,
    edge_id: str,
    kind: str,
    from_node_id: str,
    to_node_id: str,
    source: str,
    observed_at: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    edge = {
        "id": _required_text(edge_id, "edge_id"),
        "kind": _required_text(kind, "kind"),
        "from_node_id": _required_text(from_node_id, "from_node_id"),
        "to_node_id": _required_text(to_node_id, "to_node_id"),
        "observed_at": observed_at or _timestamp(),
        "source": _required_text(source, "source"),
        "metadata": dict(metadata or {}),
    }
    if edge["kind"] not in DELIVERY_EDGE_KINDS:
        raise SchemaValidationError(f"$.kind: unsupported delivery edge kind {edge['kind']!r}")
    return edge


def normalize_delivery_edge(edge: Mapping[str, Any]) -> dict[str, Any]:
    return build_delivery_edge(
        edge_id=str(edge.get("id") or ""),
        kind=str(edge.get("kind") or ""),
        from_node_id=str(edge.get("from_node_id") or ""),
        to_node_id=str(edge.get("to_node_id") or ""),
        observed_at=str(edge.get("observed_at") or "") or None,
        source=str(edge.get("source") or ""),
        metadata=_mapping_or_empty(edge.get("metadata")),
    )


def bind_release_provenance_to_build_artifact(
    release_provenance: Mapping[str, Any],
    *,
    artifact_id: str | None = None,
    observed_at: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    git = _mapping_or_empty(release_provenance.get("git"))
    image = _mapping_or_empty(release_provenance.get("image"))
    ci = _mapping_or_empty(release_provenance.get("ci"))
    commit = _optional_text(git.get("commit"))
    image_digest = _optional_text(image.get("digest"))
    packet_sha = _optional_text(release_provenance.get("packet_sha256"))
    node_id = artifact_id or _stable_id("build", commit, image_digest, packet_sha)
    artifact = build_delivery_node(
        node_id=node_id,
        kind="BuildArtifact",
        observed_at=observed_at or _optional_text(release_provenance.get("generated_at")),
        source="release_provenance",
        summary=f"Build artifact for {commit or image_digest or 'unbound release provenance'}",
        metadata={
            "release_provenance_schema_version": release_provenance.get("schema_version"),
            "release_provenance_status": release_provenance.get("status"),
            "release_provenance_packet_sha256": packet_sha,
            "git_commit": commit,
            "image_tag": image.get("tag"),
            "image_digest": image_digest,
            "ci_provider": ci.get("provider"),
            "ci_workflow": ci.get("workflow"),
            "ci_run_id": ci.get("run_id"),
        },
        evidence_refs=[item for item in (packet_sha, _optional_text(ci.get("attestation_path"))) if item],
    )
    gaps = []
    for field_name, field_value in (
        ("release_git_commit", commit),
        ("release_image_digest", image_digest),
        ("release_provenance_packet_sha256", packet_sha),
    ):
        if not field_value:
            gaps.append(
                build_evidence_gap_node(
                    gap_id=_stable_id("gap", node_id, field_name),
                    subject_node_id=node_id,
                    missing_evidence=field_name,
                    severity="hard",
                    source="release_provenance",
                    observed_at=observed_at,
                )
            )
    return artifact, gaps


def bind_runtime_signal_to_deployment_event(
    signal: Mapping[str, Any],
    *,
    deployment_id: str | None = None,
    runtime_signal_id: str | None = None,
) -> dict[str, Any]:
    deployment = _mapping_or_empty(signal.get("deployment"))
    service = _optional_text(signal.get("service")) or "unknown-service"
    environment = _optional_text(signal.get("environment"))
    image = _optional_text(deployment.get("image"))
    revision = _optional_text(deployment.get("revision"))
    observed_at = _optional_text(signal.get("observed_at"))
    deployment_node_id = deployment_id or _stable_id("deploy", service, environment, deployment.get("name"), revision, image)
    signal_node_id = runtime_signal_id or _stable_id("runtime", signal.get("signal_id"), service, observed_at)
    deployment_node = build_delivery_node(
        node_id=deployment_node_id,
        kind="DeploymentEvent",
        observed_at=observed_at,
        source="runtime_signal_binding",
        summary=f"Deployment event for {service}",
        metadata={
            "service": service,
            "environment": environment,
            "cluster": signal.get("cluster"),
            "namespace": signal.get("namespace"),
            "deployment_name": deployment.get("name"),
            "revision": revision,
            "image": image,
            "rollout_status": deployment.get("rollout_status"),
            "artifact_ref": _artifact_ref_from_image(image),
        },
        evidence_refs=[str(signal.get("signal_id"))] if signal.get("signal_id") else [],
    )
    runtime_node = build_delivery_node(
        node_id=signal_node_id,
        kind="RuntimeSignal",
        observed_at=observed_at,
        source=str(signal.get("signal_type") or "runtime_signal"),
        summary=f"Runtime signal for {service}",
        metadata={
            "signal_id": signal.get("signal_id"),
            "signal_type": signal.get("signal_type"),
            "service": service,
            "environment": environment,
            "cluster": signal.get("cluster"),
            "namespace": signal.get("namespace"),
        },
        evidence_refs=[str(signal.get("signal_id"))] if signal.get("signal_id") else [],
    )
    edge = build_delivery_edge(
        edge_id=_stable_id("edge", deployment_node_id, signal_node_id, "deployment_emits_runtime_signal"),
        kind="deployment_emits_runtime_signal",
        from_node_id=deployment_node_id,
        to_node_id=signal_node_id,
        observed_at=observed_at,
        source="runtime_signal_binding",
        metadata={"correlation": "artifact_or_release_identifier_present" if image or revision else "missing_identifier"},
    )
    gaps = []
    if not image:
        gaps.append(
            build_evidence_gap_node(
                gap_id=_stable_id("gap", deployment_node_id, "deployment_image"),
                subject_node_id=deployment_node_id,
                missing_evidence="deployment_image_or_artifact_digest",
                severity="hard",
                source="runtime_signal_binding",
                observed_at=observed_at,
            )
        )
    if not revision:
        gaps.append(
            build_evidence_gap_node(
                gap_id=_stable_id("gap", deployment_node_id, "deployment_revision"),
                subject_node_id=deployment_node_id,
                missing_evidence="deployment_release_identifier",
                severity="medium",
                source="runtime_signal_binding",
                observed_at=observed_at,
            )
        )
    return {
        "deployment_event": deployment_node,
        "runtime_signal": runtime_node,
        "edge": edge,
        "evidence_gaps": gaps,
    }


def build_evidence_gap_node(
    *,
    gap_id: str,
    subject_node_id: str,
    missing_evidence: str,
    severity: str = "medium",
    source: str = "delivery_context",
    observed_at: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_severity = _required_text(severity, "severity")
    if normalized_severity not in {"low", "medium", "high", "hard"}:
        raise ValueError(f"unsupported evidence gap severity: {severity}")
    return build_delivery_node(
        node_id=gap_id,
        kind="EvidenceGap",
        observed_at=observed_at,
        source=source,
        summary=f"Missing {missing_evidence} for {subject_node_id}",
        metadata={
            "subject_node_id": _required_text(subject_node_id, "subject_node_id"),
            "missing_evidence": _required_text(missing_evidence, "missing_evidence"),
            "severity": normalized_severity,
            "details": dict(details or {}),
        },
    )


def build_policy_gate_decision_node(
    *,
    decision_id: str,
    gate_name: str,
    outcome: str,
    mode: str = "observe",
    subject_node_id: str | None = None,
    missing_evidence: Sequence[str] | None = None,
    hard_missing_evidence: Sequence[str] | None = None,
    policy_exception_refs: Sequence[str] | None = None,
    observed_at: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_outcome = _required_text(outcome, "outcome")
    normalized_mode = _required_text(mode, "mode")
    if normalized_outcome not in DELIVERY_GATE_OUTCOMES:
        raise ValueError(f"unsupported delivery gate outcome: {outcome}")
    if normalized_mode not in DELIVERY_GATE_MODES:
        raise ValueError(f"unsupported delivery gate mode: {mode}")

    hard_missing = [str(item) for item in hard_missing_evidence or [] if str(item).strip()]
    exception_refs = [str(item) for item in policy_exception_refs or [] if str(item).strip()]
    if normalized_outcome == "allow" and hard_missing and not exception_refs:
        raise ValueError("hard evidence gaps require an explicit policy exception before allow")

    missing = [str(item) for item in missing_evidence or [] if str(item).strip()]
    return build_delivery_node(
        node_id=decision_id,
        kind="PolicyDecision",
        observed_at=observed_at,
        source="delivery_policy_gate",
        summary=f"{gate_name} -> {normalized_outcome}",
        metadata={
            "gate_name": _required_text(gate_name, "gate_name"),
            "mode": normalized_mode,
            "outcome": normalized_outcome,
            "subject_node_id": _optional_text(subject_node_id),
            "missing_evidence": missing,
            "hard_missing_evidence": hard_missing,
            "policy_exception_refs": exception_refs,
            "details": dict(details or {}),
        },
        evidence_refs=exception_refs,
    )


def evaluate_delivery_policy_gate(
    graph: Mapping[str, Any],
    *,
    decision_id: str,
    gate_name: str,
    mode: str = "observe",
    require_canary: bool = False,
    policy_exception_refs: Sequence[str] | None = None,
) -> dict[str, Any]:
    validate_delivery_context_graph(dict(graph))
    hard_gaps = _gap_names(graph, severities={"hard"})
    all_gaps = _gap_names(graph, severities={"low", "medium", "high", "hard"})
    exceptions = [str(item) for item in policy_exception_refs or [] if str(item).strip()]
    if hard_gaps and not exceptions:
        outcome = "block_promotion" if mode == "enforce" else "require_approval"
    elif require_canary:
        outcome = "require_canary"
    else:
        outcome = "allow"
    return build_policy_gate_decision_node(
        decision_id=decision_id,
        gate_name=gate_name,
        outcome=outcome,
        mode=mode,
        missing_evidence=all_gaps,
        hard_missing_evidence=hard_gaps,
        policy_exception_refs=exceptions,
        details={"evaluated_graph_id": graph.get("graph_id")},
    )


def build_zaxy_mirror_node(
    *,
    mirror_id: str,
    mesh_event_id: str,
    sequence: int,
    merkle_root: str,
    citation_refs: Sequence[str],
    redaction_status: str,
    observed_at: str | None = None,
    source: str = "zaxy_eventloom_mirror",
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    mirror_metadata = dict(metadata or {})
    mirror_metadata.update(
        {
            "mesh_event_id": _required_text(mesh_event_id, "mesh_event_id"),
            "sequence": sequence,
            "merkle_root": _required_text(merkle_root, "merkle_root"),
            "citation_refs": [str(item) for item in citation_refs if str(item).strip()],
            "redaction_status": _required_text(redaction_status, "redaction_status"),
            "authoritative": False,
            "rebuildable": True,
            "projection_role": "mirror",
        }
    )
    return build_delivery_node(
        node_id=mirror_id,
        kind="ZaxyMirror",
        observed_at=observed_at,
        source=source,
        summary=f"Zaxy mirror for Mesh event {mesh_event_id}",
        metadata=mirror_metadata,
        evidence_refs=mirror_metadata["citation_refs"],
    )


def build_delivery_lane_packet(
    graph: Mapping[str, Any],
    *,
    lane: str,
    packet_id: str,
    task_id: str | None = None,
    run_id: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    validate_delivery_context_graph(dict(graph))
    normalized_lane = _required_text(lane, "lane")
    if normalized_lane not in DELIVERY_LANES:
        raise ValueError(f"unsupported delivery lane: {lane}")
    selected_kinds = _LANE_NODE_KINDS[normalized_lane]
    selected_nodes = [node for node in graph["nodes"] if node["kind"] in selected_kinds]
    selected_ids = {node["id"] for node in selected_nodes}
    selected_edges = [
        edge for edge in graph["edges"] if edge["from_node_id"] in selected_ids and edge["to_node_id"] in selected_ids
    ]
    metadata = dict(_mapping_or_empty(graph.get("metadata")))
    metadata.update(
        {
            "delivery_lane": normalized_lane,
            "delivery_packet_id": _required_text(packet_id, "packet_id"),
            "task_id": _optional_text(task_id),
            "run_id": _optional_text(run_id),
            "proposal_only": True,
            "source_graph_id": graph.get("graph_id"),
            "included_node_kinds": sorted({node["kind"] for node in selected_nodes}),
        }
    )
    return build_delivery_context_graph(
        graph_id=packet_id,
        service=str(graph["service"]),
        environment=graph.get("environment"),
        generated_at=generated_at,
        nodes=selected_nodes,
        edges=selected_edges,
        metadata=metadata,
    )


def delivery_summary_metrics(graph: Mapping[str, Any]) -> dict[str, Any]:
    validate_delivery_context_graph(dict(graph))
    nodes = list(graph["nodes"])
    edges = list(graph["edges"])
    node_by_id = {node["id"]: node for node in nodes}

    runtime_ids = _node_ids(nodes, "RuntimeSignal")
    deployment_ids = _node_ids(nodes, "DeploymentEvent")
    build_ids = _node_ids(nodes, "BuildArtifact")
    agent_ids = _node_ids(nodes, "AgentAttempt")
    linked_runtime_ids = _to_ids(edges, "deployment_emits_runtime_signal")
    deployment_ids_linked_to_build = _to_ids(edges, "build_released_to_deployment")
    build_ids_linked_to_ci = _to_ids(edges, "workflow_produces_build") | {
        node["id"]
        for node in nodes
        if node["kind"] == "BuildArtifact" and node.get("metadata", {}).get("release_provenance_packet_sha256")
    }
    policy_holds = [
        node
        for node in nodes
        if node["kind"] == "PolicyDecision" and node.get("metadata", {}).get("outcome") in {"require_approval", "require_canary", "block_promotion"}
    ]
    accepted_agents = [
        node
        for node in nodes
        if node["kind"] == "AgentAttempt" and node.get("metadata", {}).get("proposal_status") == "accepted"
    ]
    return {
        "schema_version": "mesh.delivery_context_summary.v1",
        "generated_at": _timestamp(),
        "graph_id": graph["graph_id"],
        "node_counts": _counts(nodes, "kind"),
        "edge_counts": _counts(edges, "kind"),
        "runtime_signal_linked_to_deployment_pct": _percentage(len(runtime_ids & linked_runtime_ids), len(runtime_ids)),
        "deployment_event_linked_to_build_artifact_pct": _percentage(len(deployment_ids & deployment_ids_linked_to_build), len(deployment_ids)),
        "build_artifact_linked_to_ci_or_release_provenance_pct": _percentage(len(build_ids & build_ids_linked_to_ci), len(build_ids)),
        "promotion_holds_caused_by_missing_evidence": len(
            [
                node
                for node in policy_holds
                if node.get("metadata", {}).get("missing_evidence") or node.get("metadata", {}).get("hard_missing_evidence")
            ]
        ),
        "evidence_gap_count": len(_node_ids(nodes, "EvidenceGap")),
        "agent_proposal_acceptance_rate": _percentage(len(accepted_agents), len(agent_ids)),
        "zaxy_mirror_count": len(_node_ids(nodes, "ZaxyMirror")),
        "unlinked_runtime_signal_ids": sorted(runtime_ids - linked_runtime_ids),
        "unlinked_deployment_event_ids": sorted(deployment_ids - deployment_ids_linked_to_build),
        "unlinked_build_artifact_ids": sorted(build_ids - build_ids_linked_to_ci),
        "policy_hold_ids": [node["id"] for node in policy_holds],
        "node_ids": sorted(node_by_id),
    }


def _validate_node_semantics(node: Mapping[str, Any], path: str) -> None:
    node_id = node.get("id")
    kind = node.get("kind")
    if not isinstance(node_id, str) or not node_id.strip():
        raise SchemaValidationError(f"{path}.id: node id is required")
    if kind not in DELIVERY_NODE_KINDS:
        raise SchemaValidationError(f"{path}.kind: unsupported delivery node kind {kind!r}")
    metadata = node.get("metadata")
    if not isinstance(metadata, dict):
        raise SchemaValidationError(f"{path}.metadata: expected object")
    if kind == "ZaxyMirror":
        _validate_zaxy_mirror_metadata(metadata, path)


def _validate_edge_semantics(edge: Mapping[str, Any], node_by_id: Mapping[str, Mapping[str, Any]], path: str) -> None:
    kind = edge.get("kind")
    if kind not in DELIVERY_EDGE_KINDS:
        raise SchemaValidationError(f"{path}.kind: unsupported delivery edge kind {kind!r}")
    from_id = edge.get("from_node_id")
    to_id = edge.get("to_node_id")
    from_node = node_by_id.get(from_id)
    to_node = node_by_id.get(to_id)
    if from_node is None:
        raise SchemaValidationError(f"{path}.from_node_id: unknown node id {from_id!r}")
    if to_node is None:
        raise SchemaValidationError(f"{path}.to_node_id: unknown node id {to_id!r}")
    expected_from, expected_to = _EDGE_ENDPOINTS[str(kind)]
    from_kind = from_node.get("kind")
    to_kind = to_node.get("kind")
    if expected_from != "*" and from_kind != expected_from:
        raise SchemaValidationError(f"{path}.from_node_id: {kind!r} requires {expected_from}, got {from_kind}")
    if expected_to != "*" and to_kind != expected_to:
        raise SchemaValidationError(f"{path}.to_node_id: {kind!r} requires {expected_to}, got {to_kind}")


def _validate_zaxy_mirror_metadata(metadata: Mapping[str, Any], path: str) -> None:
    if metadata.get("authoritative") is not False:
        raise SchemaValidationError(f"{path}.metadata.authoritative: Zaxy mirrors must be non-authoritative")
    if metadata.get("rebuildable") is not True:
        raise SchemaValidationError(f"{path}.metadata.rebuildable: Zaxy mirrors must be rebuildable")
    if metadata.get("projection_role") != "mirror":
        raise SchemaValidationError(f"{path}.metadata.projection_role: Zaxy projection role must be mirror")


def _gap_names(graph: Mapping[str, Any], *, severities: set[str]) -> list[str]:
    names = []
    for node in graph["nodes"]:
        if node["kind"] != "EvidenceGap":
            continue
        metadata = node.get("metadata", {})
        if metadata.get("severity") in severities:
            names.append(str(metadata.get("missing_evidence") or node["id"]))
    return sorted(set(names))


def _node_ids(nodes: Iterable[Mapping[str, Any]], kind: str) -> set[str]:
    return {str(node["id"]) for node in nodes if node.get("kind") == kind}


def _to_ids(edges: Iterable[Mapping[str, Any]], kind: str) -> set[str]:
    return {str(edge["to_node_id"]) for edge in edges if edge.get("kind") == kind}


def _counts(items: Iterable[Mapping[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = str(item.get(field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _percentage(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round((numerator / denominator) * 100, 2)


def _mapping_or_empty(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, Mapping) else {}


def _sequence_or_empty(raw: Any) -> list[Any]:
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        return list(raw)
    return []


def _artifact_ref_from_image(image: str | None) -> str | None:
    if not image:
        return None
    if "@sha256:" in image:
        return image.split("@", 1)[1]
    if image.startswith("sha256:"):
        return image
    return None


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts if part is not None and str(part).strip())
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16] if raw else hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _required_text(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
