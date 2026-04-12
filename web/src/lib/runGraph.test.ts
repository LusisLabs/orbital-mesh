import { describe, expect, it } from "vitest";

import {
  buildArtifactGraph,
  buildKubernetesGraph,
  buildMerkleGraph,
  buildRunGraph,
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
});
