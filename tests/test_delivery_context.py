from __future__ import annotations

import unittest

from shared.mesh_runtime.delivery_context import (
    DELIVERY_EDGE_KINDS,
    DELIVERY_NODE_KINDS,
    bind_release_provenance_to_build_artifact,
    bind_runtime_signal_to_deployment_event,
    build_delivery_context_graph,
    build_delivery_edge,
    build_delivery_lane_packet,
    build_delivery_node,
    build_evidence_gap_node,
    build_policy_gate_decision_node,
    build_zaxy_mirror_node,
    delivery_summary_metrics,
    evaluate_delivery_policy_gate,
    validate_delivery_context_edge_packet,
    validate_delivery_context_graph,
    validate_delivery_context_node_packet,
)
from shared.mesh_runtime.schema_validation import SchemaValidationError, load_schema


class DeliveryContextContractTests(unittest.TestCase):
    def test_delivery_context_schema_exposes_required_node_and_edge_kinds(self) -> None:
        schema = load_schema("delivery-context-graph.schema.json")

        self.assertEqual(schema["title"], "DeliveryContextGraph")
        self.assertTrue(
            {
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
            }.issubset(set(DELIVERY_NODE_KINDS))
        )
        self.assertTrue(
            {
                "pr_contains_commit",
                "commit_has_check_suite",
                "check_suite_runs_workflow",
                "workflow_produces_build",
                "build_released_to_deployment",
                "deployment_emits_runtime_signal",
                "runtime_signal_informs_policy",
                "policy_routes_agent",
                "feedback_updates_policy",
                "zaxy_mirrors_node",
            }.issubset(set(DELIVERY_EDGE_KINDS))
        )

    def test_full_delivery_graph_validates_and_summarizes_links(self) -> None:
        graph = _full_graph()

        validate_delivery_context_graph(graph)
        metrics = delivery_summary_metrics(graph)

        self.assertEqual(graph["schema_version"], "mesh.delivery_context_graph.v1")
        self.assertEqual(metrics["runtime_signal_linked_to_deployment_pct"], 100.0)
        self.assertEqual(metrics["deployment_event_linked_to_build_artifact_pct"], 100.0)
        self.assertEqual(metrics["build_artifact_linked_to_ci_or_release_provenance_pct"], 100.0)
        self.assertEqual(metrics["zaxy_mirror_count"], 1)

    def test_invalid_graph_packet_fails_closed_on_unknown_kind(self) -> None:
        graph = _full_graph()
        graph["nodes"][0]["kind"] = "RepositoryWrite"

        with self.assertRaises(SchemaValidationError):
            validate_delivery_context_graph(graph)

    def test_invalid_graph_packet_fails_closed_on_wrong_edge_endpoints(self) -> None:
        graph = _full_graph()
        graph["edges"][0]["kind"] = "workflow_produces_build"

        with self.assertRaises(SchemaValidationError):
            validate_delivery_context_graph(graph)

    def test_standalone_node_and_edge_packet_validation_rejects_extra_fields(self) -> None:
        node = build_delivery_node(node_id="pr:extra", kind="PullRequest", source="github", summary="PR")
        edge = build_delivery_edge(
            edge_id="edge:extra",
            kind="pr_contains_commit",
            from_node_id="pr:extra",
            to_node_id="commit:extra",
            source="github",
        )

        validate_delivery_context_node_packet(node)
        validate_delivery_context_edge_packet(edge, from_kind="PullRequest", to_kind="Commit")

        node["unexpected"] = True
        edge["unexpected"] = True
        with self.assertRaises(SchemaValidationError):
            validate_delivery_context_node_packet(node)
        with self.assertRaises(SchemaValidationError):
            validate_delivery_context_edge_packet(edge, from_kind="PullRequest", to_kind="Commit")

    def test_zaxy_mirror_metadata_is_non_authoritative_and_rebuildable(self) -> None:
        mirror = build_zaxy_mirror_node(
            mirror_id="zaxy:1",
            mesh_event_id="evt_1",
            sequence=1,
            merkle_root="abc123",
            citation_refs=["run://evt_1"],
            redaction_status="redacted",
        )

        self.assertFalse(mirror["metadata"]["authoritative"])
        self.assertTrue(mirror["metadata"]["rebuildable"])

        mirror["metadata"]["authoritative"] = True
        with self.assertRaises(SchemaValidationError):
            build_delivery_context_graph(graph_id="bad-zaxy", service="checkout", nodes=[mirror], edges=[])

    def test_release_provenance_binds_to_build_artifact_and_emits_gaps(self) -> None:
        artifact, gaps = bind_release_provenance_to_build_artifact(
            {
                "schema_version": "mesh.release_provenance.v1",
                "generated_at": "2026-05-18T12:00:00Z",
                "status": "complete",
                "packet_sha256": "a" * 64,
                "git": {"commit": "abc123"},
                "image": {"tag": "mesh:test", "digest": "sha256:123"},
                "ci": {"provider": "github-actions", "workflow": "ci", "run_id": "1234"},
            },
            artifact_id="build:release",
        )

        self.assertEqual(artifact["kind"], "BuildArtifact")
        self.assertEqual(artifact["metadata"]["image_digest"], "sha256:123")
        self.assertEqual(gaps, [])

        _, incomplete_gaps = bind_release_provenance_to_build_artifact({"git": {}, "image": {}, "ci": {}})
        self.assertEqual({gap["metadata"]["missing_evidence"] for gap in incomplete_gaps}, {"release_git_commit", "release_image_digest", "release_provenance_packet_sha256"})

    def test_runtime_signal_binding_attaches_deployment_and_emits_missing_identifier_gaps(self) -> None:
        binding = bind_runtime_signal_to_deployment_event(
            {
                "signal_type": "kubernetes_deployment_issue",
                "signal_id": "sig_1",
                "observed_at": "2026-05-18T12:00:00Z",
                "environment": "production",
                "cluster": "prod",
                "namespace": "checkout",
                "service": "checkout-api",
                "deployment": {
                    "name": "checkout-api",
                    "revision": "",
                    "image": "",
                    "rollout_status": "failed",
                },
            }
        )

        self.assertEqual(binding["deployment_event"]["kind"], "DeploymentEvent")
        self.assertEqual(binding["runtime_signal"]["kind"], "RuntimeSignal")
        self.assertEqual(binding["edge"]["kind"], "deployment_emits_runtime_signal")
        self.assertEqual(
            {gap["metadata"]["missing_evidence"] for gap in binding["evidence_gaps"]},
            {"deployment_image_or_artifact_digest", "deployment_release_identifier"},
        )

    def test_policy_gate_decisions_support_observe_and_enforce_outcomes(self) -> None:
        observe = build_policy_gate_decision_node(
            decision_id="policy:observe",
            gate_name="staging-promotion",
            outcome="require_approval",
            mode="observe",
            missing_evidence=["release_image_digest"],
        )
        enforce = build_policy_gate_decision_node(
            decision_id="policy:enforce",
            gate_name="prod-promotion",
            outcome="block_promotion",
            mode="enforce",
            hard_missing_evidence=["release_image_digest"],
        )
        canary = build_policy_gate_decision_node(
            decision_id="policy:canary",
            gate_name="prod-promotion",
            outcome="require_canary",
        )
        allow = build_policy_gate_decision_node(decision_id="policy:allow", gate_name="prod-promotion", outcome="allow")

        self.assertEqual(observe["metadata"]["outcome"], "require_approval")
        self.assertEqual(enforce["metadata"]["outcome"], "block_promotion")
        self.assertEqual(canary["metadata"]["outcome"], "require_canary")
        self.assertEqual(allow["metadata"]["outcome"], "allow")

        with self.assertRaises(ValueError):
            build_policy_gate_decision_node(
                decision_id="policy:bad",
                gate_name="prod-promotion",
                outcome="allow",
                hard_missing_evidence=["release_image_digest"],
            )

    def test_evaluate_policy_gate_blocks_hard_gaps_only_in_enforce_mode(self) -> None:
        gap = build_evidence_gap_node(
            gap_id="gap:hard",
            subject_node_id="build:1",
            missing_evidence="release_image_digest",
            severity="hard",
        )
        graph = build_delivery_context_graph(graph_id="gap-graph", service="checkout", nodes=[gap], edges=[])

        observed = evaluate_delivery_policy_gate(graph, decision_id="policy:observe", gate_name="prod", mode="observe")
        enforced = evaluate_delivery_policy_gate(graph, decision_id="policy:enforce", gate_name="prod", mode="enforce")

        self.assertEqual(observed["metadata"]["outcome"], "require_approval")
        self.assertEqual(enforced["metadata"]["outcome"], "block_promotion")

    def test_lane_packets_scope_different_delivery_evidence(self) -> None:
        graph = _full_graph()

        patch_packet = build_delivery_lane_packet(graph, lane="patch", packet_id="packet:patch", task_id="task_1", run_id="run_1")
        staging_packet = build_delivery_lane_packet(graph, lane="staging", packet_id="packet:staging")

        self.assertEqual(patch_packet["metadata"]["delivery_lane"], "patch")
        self.assertTrue(patch_packet["metadata"]["proposal_only"])
        self.assertIn("PullRequest", patch_packet["metadata"]["included_node_kinds"])
        self.assertNotIn("BuildArtifact", patch_packet["metadata"]["included_node_kinds"])
        self.assertIn("BuildArtifact", staging_packet["metadata"]["included_node_kinds"])
        self.assertNotIn("PullRequest", staging_packet["metadata"]["included_node_kinds"])


def _full_graph() -> dict[str, object]:
    nodes = [
        build_delivery_node(node_id="pr:1", kind="PullRequest", source="github", summary="PR 1"),
        build_delivery_node(node_id="commit:1", kind="Commit", source="github", summary="Commit 1"),
        build_delivery_node(node_id="check:1", kind="CheckSuite", source="github", summary="Checks passed"),
        build_delivery_node(node_id="workflow:1", kind="WorkflowRun", source="github_actions", summary="CI workflow"),
        build_delivery_node(
            node_id="build:1",
            kind="BuildArtifact",
            source="release_provenance",
            summary="Release image",
            metadata={"release_provenance_packet_sha256": "a" * 64},
        ),
        build_delivery_node(node_id="deploy:1", kind="DeploymentEvent", source="kubernetes", summary="Production deployment"),
        build_delivery_node(node_id="runtime:1", kind="RuntimeSignal", source="otel", summary="Runtime signal"),
        build_policy_gate_decision_node(decision_id="policy:1", gate_name="prod-promotion", outcome="allow"),
        build_delivery_node(node_id="agent:1", kind="AgentAttempt", source="deepagents", summary="Patch proposal", metadata={"proposal_status": "accepted"}),
        build_delivery_node(node_id="feedback:1", kind="FeedbackEvent", source="operator", summary="Deployment confirmed"),
        build_zaxy_mirror_node(
            mirror_id="zaxy:1",
            mesh_event_id="evt_1",
            sequence=1,
            merkle_root="root",
            citation_refs=["run://evt_1"],
            redaction_status="redacted",
        ),
    ]
    edges = [
        build_delivery_edge(edge_id="edge:pr-commit", kind="pr_contains_commit", from_node_id="pr:1", to_node_id="commit:1", source="github"),
        build_delivery_edge(edge_id="edge:commit-check", kind="commit_has_check_suite", from_node_id="commit:1", to_node_id="check:1", source="github"),
        build_delivery_edge(edge_id="edge:check-workflow", kind="check_suite_runs_workflow", from_node_id="check:1", to_node_id="workflow:1", source="github"),
        build_delivery_edge(edge_id="edge:workflow-build", kind="workflow_produces_build", from_node_id="workflow:1", to_node_id="build:1", source="github_actions"),
        build_delivery_edge(edge_id="edge:build-deploy", kind="build_released_to_deployment", from_node_id="build:1", to_node_id="deploy:1", source="kubernetes"),
        build_delivery_edge(edge_id="edge:deploy-runtime", kind="deployment_emits_runtime_signal", from_node_id="deploy:1", to_node_id="runtime:1", source="otel"),
        build_delivery_edge(edge_id="edge:runtime-policy", kind="runtime_signal_informs_policy", from_node_id="runtime:1", to_node_id="policy:1", source="delivery_policy_gate"),
        build_delivery_edge(edge_id="edge:policy-agent", kind="policy_routes_agent", from_node_id="policy:1", to_node_id="agent:1", source="orchestrator"),
        build_delivery_edge(edge_id="edge:feedback-policy", kind="feedback_updates_policy", from_node_id="feedback:1", to_node_id="policy:1", source="operator"),
        build_delivery_edge(edge_id="edge:feedback-deploy", kind="feedback_confirms_deployment", from_node_id="feedback:1", to_node_id="deploy:1", source="operator"),
        build_delivery_edge(edge_id="edge:zaxy", kind="zaxy_mirrors_node", from_node_id="policy:1", to_node_id="zaxy:1", source="zaxy"),
    ]
    return build_delivery_context_graph(
        graph_id="delivery:checkout",
        service="checkout",
        environment="production",
        nodes=nodes,
        edges=edges,
        metadata={"source": "unit_test"},
    )
