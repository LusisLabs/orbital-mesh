import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { DeliveryContextPanel } from "./App";
import type { AgentTask, DeliveryContextGraph, RunDetail } from "./types";

describe("DeliveryContextPanel", () => {
  it("renders delivery timeline, evidence gaps, Zaxy mirror, LangGraph workflow, and AgentAttempt refs", () => {
    const graph: DeliveryContextGraph = {
      schema_version: "delivery_context.v1",
      run_id: "run_delivery_console",
      service: "checkout-api",
      repository: "LusisLabs/lusis-mesh",
      generated_at: "2026-05-18T12:00:00Z",
      summary: "Promotion held until artifact digest and runtime evidence were linked.",
      nodes: [
        {
          id: "pr_42",
          kind: "pull_request",
          stage: "pr",
          title: "PR #42",
          status: "passed",
          summary: "Rollback guard change",
          occurred_at: "2026-05-18T11:00:00Z",
          refs: [{ label: "PR", value: "42", url: "https://github.com/LusisLabs/lusis-mesh/pull/42" }],
        },
        {
          id: "ci_42",
          kind: "ci",
          stage: "ci",
          title: "CI checks",
          status: "passed",
          summary: "Focused tests passed",
          occurred_at: "2026-05-18T11:10:00Z",
        },
        {
          id: "build_42",
          kind: "build",
          stage: "build",
          title: "Build artifact",
          status: "missing",
          summary: "Digest not attached",
          occurred_at: "2026-05-18T11:20:00Z",
        },
        {
          id: "deploy_42",
          kind: "deploy",
          stage: "deploy",
          title: "Staging deploy",
          status: "running",
          summary: "Canary pending",
          occurred_at: "2026-05-18T11:30:00Z",
        },
        {
          id: "runtime_42",
          kind: "runtime",
          stage: "runtime",
          title: "Runtime signal",
          status: "degraded",
          summary: "Latency regression candidate",
          occurred_at: "2026-05-18T11:40:00Z",
        },
        {
          id: "policy_42",
          kind: "policy",
          stage: "policy",
          title: "Policy decision",
          status: "blocked",
          summary: "Promotion blocked",
          occurred_at: "2026-05-18T11:50:00Z",
        },
        {
          id: "agent_42",
          kind: "agent_attempt",
          stage: "agent",
          title: "Patch proposal",
          status: "pending",
          summary: "Scoped remediation proposal",
          metadata: { agent_attempt_id: "attempt_delivery_patch" },
        },
        {
          id: "feedback_42",
          kind: "feedback",
          stage: "feedback",
          title: "Operator feedback",
          status: "pending",
          summary: "Awaiting incident review",
        },
      ],
      edges: [
        {
          id: "edge_pr_ci",
          source: "pr_42",
          target: "ci_42",
          relation: "validated_by",
          status: "passed",
        },
      ],
      evidence_gaps: [
        {
          id: "gap_digest",
          title: "Artifact digest missing",
          severity: "blocker",
          summary: "Build artifact is not linked to release provenance.",
          missing_ref: "build_artifact.digest",
          owner: "release",
        },
      ],
      zaxy_mirror: {
        enabled: true,
        status: "mirrored",
        latest_sequence: 8,
        latest_event_id: "event_delivery_8",
        merkle_root: "abc123def456",
        projection_lag_ms: 42,
        graph_available: true,
        redaction_status: "redacted",
      },
      langgraph_workflows: [
        {
          workflow_id: "workflow_delivery_patch",
          thread_id: "thread_checkout_api",
          status: "completed",
          evidence_packet_id: "packet_delivery_42",
          zaxy_checkout_ref: "zaxy://checkout/run_delivery_console",
          agent_attempt_ids: ["attempt_delivery_patch"],
        },
      ],
      agent_attempt_refs: ["attempt_delivery_patch"],
    };
    const task: AgentTask = {
      task_id: "task_delivery_patch",
      run_id: "run_delivery_console",
      kind: "patch",
      status: "completed",
      created_at: "2026-05-18T11:50:00Z",
      updated_at: "2026-05-18T11:55:00Z",
      allowed_paths: ["meshapp/frontend/src/App.tsx"],
      test_commands: ["pnpm --prefix meshapp/frontend test -- App.deliveryContext.test.tsx"],
      kubernetes_scope: {},
      memory_scope: {},
      memory_packet: {},
      memory_write_policy: {},
      open_questions: [],
      agents: ["codex"],
      orchestration_topology: {},
      lane_routing: {},
      selected_attempt_id: "attempt_delivery_patch",
      attempts: [
        {
          attempt_id: "attempt_delivery_patch",
          task_id: "task_delivery_patch",
          run_id: "run_delivery_console",
          agent: "codex",
          adapter: "langgraph",
          status: "completed",
          started_at: "2026-05-18T11:52:00Z",
          completed_at: "2026-05-18T11:55:00Z",
          summary: "Proposed scoped digest-link remediation.",
          changed_files: [],
          test_results: [],
          risk_flags: [],
          recommended_action: "review_patch",
          output: {},
          observations_proposed: [],
          claims_proposed: [],
          procedures_proposed: [],
          citations: [],
          contradictions_detected: [],
          memory_actions_requested: [],
        },
      ],
    };
    const run: RunDetail = {
      run_id: "run_delivery_console",
      created_at: "2026-05-18T11:00:00Z",
      updated_at: "2026-05-18T12:00:00Z",
      goal_id: null,
      scenario_key: "checkout_latency_regression",
      stage: "awaiting_operator",
      status: "running",
      steering_mode: "approval_gate",
      auto_mode: false,
      pause_points: [],
      pending_pause_stage: null,
      evaluation_mode: "native",
      orchestration_mode: "native_hermes",
      latest_event_id: null,
      latest_event_sequence: 0,
      latest_merkle_root: null,
      operator_notes: [],
      artifacts: {},
      events: [],
      merkle: {
        run_id: "run_delivery_console",
        root_hash: "abc123def456",
        leaf_count: 0,
        event_ids: [],
      },
    };

    const html = renderToStaticMarkup(
      <DeliveryContextPanel run={run} graph={graph} tasks={[task]} />,
    );

    expect(html).toContain("Delivery Context");
    expect(html).toContain("PR #42");
    expect(html).toContain("CI checks");
    expect(html).toContain("Build artifact");
    expect(html).toContain("Staging deploy");
    expect(html).toContain("Runtime signal");
    expect(html).toContain("Policy decision");
    expect(html).toContain("Operator feedback");
    expect(html).toContain("Artifact digest missing");
    expect(html).toContain("Zaxy Mirror");
    expect(html).toContain("LangGraph workflow_delivery_patch");
    expect(html).toContain("AgentAttempt attempt_delivery_patch");
  });
});
