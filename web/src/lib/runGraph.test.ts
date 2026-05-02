import { describe, expect, it } from "vitest";

import {
  buildArtifactGraph,
  buildEvidenceGraph,
  buildKubernetesGraph,
  buildLabyrinthGraph,
  buildMerkleGraph,
  buildRethSignalGraph,
  buildRunGraph,
  buildUnifiedGraph,
  toneForStage,
} from "./runGraph";

describe("runGraph", () => {
  it("builds ordered nodes and edges from run events", () => {
    const graph = buildRunGraph([
      {
        event_id: "evt-1",
        run_id: "run-1",
        sequence: 1,
        stage: "queued",
        event_type: "run_queued",
        recorded_at: "2026-04-06T00:00:00Z",
        payload: {},
      },
      {
        event_id: "evt-2",
        run_id: "run-1",
        sequence: 2,
        stage: "evaluation_ready",
        event_type: "evaluation_ready",
        recorded_at: "2026-04-06T00:00:01Z",
        payload: {},
      },
      {
        event_id: "evt-3",
        run_id: "run-1",
        sequence: 3,
        stage: "completed",
        event_type: "run_completed",
        recorded_at: "2026-04-06T00:00:02Z",
        payload: {},
      },
    ]);

    expect(graph.nodes).toHaveLength(3);
    expect(graph.edges).toHaveLength(2);
    expect(graph.edges[0].source).toBe("evt-1");
    expect(graph.edges[1].target).toBe("evt-3");
  });

  it("emphasizes the selected node and adjacent edge", () => {
    const graph = buildRunGraph([
      {
        event_id: "evt-1",
        run_id: "run-1",
        sequence: 1,
        stage: "queued",
        event_type: "run_queued",
        recorded_at: "2026-04-06T00:00:00Z",
        payload: {},
      },
      {
        event_id: "evt-2",
        run_id: "run-1",
        sequence: 2,
        stage: "evaluation_ready",
        event_type: "evaluation_ready",
        recorded_at: "2026-04-06T00:00:01Z",
        payload: {},
      },
    ], "evt-2");

    expect(graph.nodes[1].selected).toBe(true);
    expect(graph.nodes[1].type).toBe("runEvent");
    expect(graph.nodes[1].style?.width).toBe(212);
    expect(graph.edges[0].style?.strokeWidth).toBe(2.2);
  });

  it("assigns stable tones by stage", () => {
    expect(toneForStage("completed")).toBe("#83d37d");
    expect(toneForStage("awaiting_operator")).toBe("#f2b84b");
    expect(toneForStage("failed")).toBe("#ff6b5f");
  });

  it("builds a kubernetes topology from a live deployment signal", () => {
    const graph = buildKubernetesGraph({
      signal_type: "kubernetes_deployment_issue",
      cluster: "k3d-mesh-e2e",
      environment: "local",
      namespace: "search",
      service: "semantic-search",
      deployment: {
        name: "semantic-search",
        rollout_status: "degraded",
        available_replicas: 1,
        desired_replicas: 3,
        revision: 18,
      },
      pods: [{ name: "semantic-search-7c8d", ready: false, phase: "CrashLoopBackOff", restarts: 5 }],
      events: [{ reason: "BackOff", type: "Warning", message: "Back-off restarting failed container", count: 4 }],
    });

    expect(graph.nodes.map((node) => node.id)).toContain("deployment");
    expect(graph.nodes.some((node) => node.data.nodeKind === "kubernetes")).toBe(true);
    expect(graph.edges.some((edge) => edge.source === "deployment")).toBe(true);
  });

  it("builds merkle proof and artifact canvases from run state", () => {
    const merkleGraph = buildMerkleGraph(
      {
        root_hash: "root-hash",
        leaf_count: 4,
        event_ids: ["evt-1", "evt-2", "evt-3", "evt-4"],
      },
      {
        event_id: "evt-3",
        leaf_hash: "leaf-hash",
        root_hash: "root-hash",
        valid: true,
        proof: [{ position: "left", hash: "sibling-hash" }],
      },
    );
    const artifactGraph = buildArtifactGraph({
      stage: "executing",
      status: "running",
      artifacts: {
        input_signal: { signal_type: "kubernetes_deployment_issue" },
        trigger: { trigger_id: "trig-1", trigger_type: "kubernetes_deployment_unhealthy" },
        decision: { decision_type: "reduce_rollout" },
        evaluation: { final_recommendation: "approve" },
        execution: { executor: "goose" },
        feedback: { outcome: "successful" },
      },
    });

    expect(merkleGraph.nodes.map((node) => node.id)).toContain("merkle-root");
    expect(merkleGraph.nodes.map((node) => node.id)).toContain("merkle-leaf");
    expect(artifactGraph.nodes[0].id).toBe("artifact-run");
    expect(artifactGraph.nodes.some((node) => node.data.artifactKey === "trigger")).toBe(true);
  });

  it("builds a unified canvas from run, kubernetes, merkle, and artifact graphs", () => {
    const flow = buildRunGraph([
      {
        event_id: "evt-1",
        run_id: "run-1",
        sequence: 1,
        stage: "queued",
        event_type: "run_queued",
        recorded_at: "2026-04-06T00:00:00Z",
        payload: {},
        artifact_key: "input_signal",
      },
      {
        event_id: "evt-2",
        run_id: "run-1",
        sequence: 2,
        stage: "completed",
        event_type: "run_completed",
        recorded_at: "2026-04-06T00:00:01Z",
        payload: {},
        artifact_key: "execution",
      },
    ]);
    const kubernetes = buildKubernetesGraph({
      signal_type: "kubernetes_deployment_issue",
      cluster: "k3d-mesh-e2e",
      namespace: "search",
      service: "semantic-search",
      deployment: {
        name: "semantic-search",
        rollout_status: "healthy",
        available_replicas: 3,
        desired_replicas: 3,
      },
    });
    const merkle = buildMerkleGraph(
      {
        root_hash: "root-hash",
        leaf_count: 2,
        event_ids: ["evt-1", "evt-2"],
      },
      null,
    );
    const artifacts = buildArtifactGraph({
      stage: "completed",
      status: "completed",
      artifacts: {
        input_signal: { signal_type: "kubernetes_deployment_issue" },
        execution: { status: "succeeded" },
      },
    });

    const unified = buildUnifiedGraph({ flow, kubernetes, merkle, artifacts });

    expect(unified.nodes.map((node) => node.id)).toContain("flow:evt-1");
    expect(unified.nodes.map((node) => node.id)).toContain("section:flow");
    expect(unified.nodes.map((node) => node.id)).toContain("section:kubernetes");
    expect(unified.nodes.map((node) => node.id)).toContain("section:merkle");
    expect(unified.nodes.map((node) => node.id)).toContain("section:artifacts");
    expect(unified.nodes.map((node) => node.id)).toContain("kubernetes:cluster");
    expect(unified.nodes.map((node) => node.id)).toContain("merkle:merkle-root");
    expect(unified.nodes.map((node) => node.id)).toContain("artifacts:artifact-run");
    expect(unified.edges.some((edge) => edge.id === "unified:input-signal-kubernetes")).toBe(true);
    expect(unified.edges.some((edge) => edge.id === "unified:execution-merkle-root")).toBe(true);
  });

  it("builds a labyrinth graph from normalized crossings", () => {
    const graph = buildLabyrinthGraph([
      {
        id: "c1",
        journey_id: "run-1",
        type: "run_queued",
        label: "Run queued",
        status: "recorded",
        thread: "main",
        sequence: 1,
        evidence_refs: [],
        severity: "success",
      },
      {
        id: "c2",
        journey_id: "run-1",
        type: "approval_blocked",
        label: "Approval blocked",
        status: "requires_review",
        thread: "threshold",
        sequence: 2,
        event_id: "evt-2",
        evidence_refs: ["ev-1"],
        severity: "warning",
      },
    ], "evt-2");

    expect(graph.nodes).toHaveLength(2);
    expect(graph.nodes[1].selected).toBe(true);
    expect(graph.edges[0].animated).toBe(true);
  });

  it("builds scenario evidence and reth signal canvases", () => {
    const evidence = buildEvidenceGraph({
      nodes: [
        { id: "ev-1", type: "evidence", label: "Historical outcome", confidence: 0.75 },
        { id: "sub-1", type: "subdecision", label: "approval_required", requires_review: true },
        { id: "analysis-1", type: "scenario_analysis", label: "escalate" },
      ],
      edges: [
        { source: "ev-1", target: "sub-1", kind: "supports" },
        { source: "sub-1", target: "analysis-1", kind: "feeds" },
      ],
    });
    const reth = buildRethSignalGraph({
      signal_type: "reth_node",
      service: "el-1-reth-lighthouse",
      environment: "production",
      node: { client_version: "reth/v1.9.3", deployment_mode: "docker", role: "full" },
      execution: { peer_count: 0, min_peer_count: 1, head_block: 417, block_lag: 0 },
      consensus: { consensus_client: "lighthouse", engine_api_reachable: true },
      storage: { disk_used_pct: 97, diagnostic_source: "live" },
      rpc: { http_reachable: true, error_rate: 0 },
    });

    expect(evidence.nodes.map((node) => node.id)).toContain("sub-1");
    expect(evidence.edges.some((edge) => edge.animated)).toBe(true);
    expect(reth.nodes.map((node) => node.id)).toContain("reth-storage");
    expect(reth.edges.some((edge) => edge.target === "reth-storage" && edge.animated)).toBe(true);
  });
});
