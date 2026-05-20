import { describe, expect, it } from "vitest";

import {
  approvalCommands,
  buildDashboardControlModel,
  buildDashboardTiles,
  buildPraxisProductModel,
  dashboardLoadSurfaceState,
  dashboardSectionState,
  evidenceTraceSteps,
  operatorWorkflowPosture,
  readModelCardPayload,
  readModelSummary,
  runtimeProductPage,
  settingsParityRows,
  workflowForView,
} from "./ProductApp";

describe("dashboard read-model fallbacks", () => {
  it("summarizes unavailable read models before empty fallbacks", () => {
    expect(readModelSummary({ error: "readiness failed" }, "Read-only: readiness status unavailable")).toBe("Unavailable: readiness failed");
    expect(readModelSummary({ status: "ready" }, "Read-only: readiness status unavailable")).toBe("ready");
    expect(readModelSummary(null, "Read-only: readiness status unavailable")).toBe("Read-only: readiness status unavailable");
  });

  it("explains empty card payloads as read-only dashboard gaps", () => {
    expect(readModelCardPayload("Memory projection", null)).toEqual({
      state: "empty",
      reason: "Memory projection read model returned no payload. This product surface is read-only until Mesh exposes data.",
    });
    expect(readModelCardPayload("Runtime readiness", { status: "ready" })).toEqual({ status: "ready" });
  });
});

describe("operator workflow posture", () => {
  it("maps launch, approval, evidence, readiness, connector, and settings workflows to bounded Mesh paths", () => {
    expect(operatorWorkflowPosture("launch")).toMatchObject({ callPath: expect.stringContaining("POST /api/runs"), posture: "native" });
    expect(operatorWorkflowPosture("approval")).toMatchObject({ callPath: expect.stringContaining("/api/operator/dashboard"), posture: "read_only" });
    expect(operatorWorkflowPosture("evidence")).toMatchObject({ callPath: expect.stringContaining("/api/runs/{run_id}/evidence-graph"), posture: "read_only" });
    expect(operatorWorkflowPosture("readiness")).toMatchObject({ callPath: expect.stringContaining("/api/readiness"), posture: "read_only" });
    expect(operatorWorkflowPosture("connector")).toMatchObject({ callPath: expect.stringContaining("/api/connectors/certification"), posture: "read_only" });
    expect(operatorWorkflowPosture("settings")).toMatchObject({ callPath: expect.stringContaining("/api/operator/settings"), posture: "native" });
  });

  it("routes product views to the right operator workflow posture", () => {
    expect(workflowForView("evaluations")).toBe("launch");
    expect(workflowForView("environments")).toBe("connector");
    expect(workflowForView("gpu")).toBe("readiness");
    expect(workflowForView("keys")).toBe("settings");
  });
});

describe("approval and runtime product pages", () => {
  it("filters approval queue commands to product-supported Mesh steering actions", () => {
    expect(approvalCommands(["approve", "resume", "cancel", "handoff"])).toEqual(["approve", "resume", "cancel"]);
    expect(approvalCommands(["explain_blockers", "override_decision", "cancel", "handoff"])).toEqual(["explain_blockers", "override_decision", "cancel"]);
  });

  it("maps runtime navigation to product-native read-model pages", () => {
    const dashboard = {
      settings_schema: {},
      mesh: {
        readiness: { status: "ready", orchestration_topology: { mode: "centralized" } },
        graph: { mode: "centralized" },
        connectors: { connectors: { github: { state: "ready" } } },
        memory: { active: { services: {} }, graph: { status: "ready" } },
        kill_switch: { enabled: false },
        approvals: { status: "empty", items: [] },
        trust_ladder: { entries: [] },
        pilot_go_no_go: { status: "blocked" },
        read_model: { authority: "read_only" },
      },
    } as any;

    expect(runtimeProductPage("training", dashboard)).toMatchObject({ title: "Topology" });
    expect(runtimeProductPage("inference", dashboard)).toMatchObject({ title: "Memory Projection" });
    expect(runtimeProductPage("gpu", dashboard)).toMatchObject({ title: "Readiness" });
    expect(runtimeProductPage("clusters", dashboard)).toMatchObject({ title: "Kill Switch" });
    expect(runtimeProductPage("instances", dashboard)).toMatchObject({ title: "Policy State" });
  });
});

describe("settings parity model", () => {
  it("gives every dashboard setting a UI mutation path, CLI path, or read-only reason", () => {
    const rows = settingsParityRows({
      scope: { kind: "team", team: { id: "team-1" } },
      session: { user: { id: "user-1", email: "operator@example.com" } },
      settings: {
        default_evaluation_mode: "native",
        default_orchestration_mode: "hermes",
        default_steering_mode: "approval_gate",
      },
      settings_schema: {
        default_evaluation_mode: { values: ["native", "promptfoo"], default: "native", description: "eval" },
        default_orchestration_mode: { values: ["native", "hermes"], default: "native", description: "orch" },
        default_steering_mode: { values: ["approval_gate"], default: "approval_gate", description: "steer" },
      },
      mesh: { health: { commit: "abc123" }, readiness: { state_backend: "sqlite" } },
    } as any);

    const mutableRows = rows.filter((row) => row.mutable);
    const readonlyRows = rows.filter((row) => !row.mutable);
    expect(mutableRows.map((row) => row.key)).toEqual([
      "default_evaluation_mode",
      "default_orchestration_mode",
      "default_steering_mode",
    ]);
    for (const row of mutableRows) {
      expect(row.uiMutationPath).toBe("/api/operator/settings");
      expect(row.cliPath).toContain("python scripts/operator_config.py set");
      expect(row.cliPath).toContain("--scope team:team-1");
      expect(row.cliPath).toContain("--operator-id operator@example.com");
      expect(row.cliPath).toContain("--reason");
    }
    for (const row of readonlyRows) {
      expect(row.readOnlyReason).toBeTruthy();
      expect(row.uiMutationPath).toBeUndefined();
      expect(row.cliPath).toBeUndefined();
    }
  });
});

describe("dashboard section state coverage", () => {
  it("maps dashboard section payloads into explicit product states", () => {
    expect(dashboardSectionState({ status: "ready" })).toMatchObject({ state: "ready" });
    expect(dashboardSectionState({})).toMatchObject({ state: "empty" });
    expect(dashboardSectionState({ status: "unavailable", error: "readiness failed" })).toMatchObject({ state: "degraded" });
    expect(dashboardSectionState({ status: "blocked", reason: "missing proof" })).toMatchObject({ state: "blocked" });
    expect(dashboardLoadSurfaceState({ state: "unauthorized", message: "session expired" })).toBe("unauthorized");
    expect(dashboardLoadSurfaceState({ state: "backend-unavailable", message: "api down" })).toBe("backend-unavailable");
  });

  it("binds every home dashboard tile to an explicit /api/operator/dashboard section", () => {
    const tiles = buildDashboardTiles({
      settings: {
        default_evaluation_mode: "native",
        default_orchestration_mode: "native",
        default_steering_mode: "approval_gate",
      },
      settings_schema: {
        default_evaluation_mode: { values: ["native", "promptfoo"], default: "native", description: "eval" },
        default_orchestration_mode: { values: ["native", "hermes"], default: "native", description: "orch" },
        default_steering_mode: { values: ["approval_gate"], default: "approval_gate", description: "steer" },
      },
      mesh: {
        praxis: { status: "bounded_dry_run_ready" },
        readiness: { status: "ready", orchestration_topology: { status: "ready" } },
        runs: { runs: [] },
        connectors: { connectors: { github: { state: "ready" } } },
        pilot_go_no_go: { status: "blocked", missing_evidence: ["decision_record_present"] },
        approvals: { items: [] },
        memory: { graph: { status: "ready" } },
        trust_ladder: { entries: [] },
        watchers: { status: "ready" },
      },
    } as any);

    expect(tiles).toHaveLength(11);
    expect(tiles.every((tile) => tile.apiSection)).toBe(true);
    expect(tiles.map((tile) => tile.state)).toEqual(expect.arrayContaining(["ready", "empty", "blocked"]));
    expect(tiles.find((tile) => tile.title === "Evidence packets")).toMatchObject({
      apiSection: "mesh.pilot_go_no_go",
      state: "blocked",
    });
  });
});

describe("dashboard control summary", () => {
  it("merges the most important Mesh control-plane read models into product dashboard cards", () => {
    const model = buildDashboardControlModel({
      mesh: {
        readiness: { status: "ready", detail: "all gates green" },
        runs: {
          runs: [
            { run_id: "run-active", scenario_key: "reth_peer_starvation", status: "awaiting_operator" },
            { run_id: "run-complete", scenario_key: "packet_export", status: "completed" },
          ],
        },
        approvals: { items: [{ queue_id: "approval://run-active", decision_type: "manual_review" }] },
        pilot_go_no_go: { status: "blocked", missing_evidence: ["decision_record_present"], reason: "packet incomplete" },
        connectors: {
          connectors: {
            akto: { state: "ready", authority_posture: "advisory" },
            pagerduty: { state: "staging", authority_posture: "signal only" },
          },
        },
        graph: { mode: "centralized", detail: "single control plane" },
        memory: { graph: { state: "projecting", detail: "runtime projection active" } },
        kill_switch: { enabled: true, reason: "operator configured" },
      },
    } as any);

    expect(model.readiness).toMatchObject({ value: "ready", tone: "good" });
    expect(model.runs).toMatchObject({ value: "1", detail: "reth_peer_starvation", tone: "warn" });
    expect(model.approvals).toMatchObject({ value: "1", detail: "manual_review", tone: "warn" });
    expect(model.evidence).toMatchObject({ value: "1 missing", tone: "warn" });
    expect(model.recentRuns.map((run) => run.id)).toEqual(["run-active", "run-complete"]);
    expect(model.connectors.map((connector) => connector.value)).toEqual(["ready", "staging"]);
    expect(model.systemRows).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "connector-total", value: "1/2" }),
      expect.objectContaining({ id: "topology", value: "centralized" }),
      expect.objectContaining({ id: "memory", value: "projecting" }),
      expect.objectContaining({ id: "kill-switch", value: "enabled" }),
    ]));
  });
});

describe("Praxis product dashboard model", () => {
  it("binds the proof packet, generated tools, and P10 dry-run runtime posture for the home dashboard", () => {
    const model = buildPraxisProductModel({
      mesh: {
        praxis: {
          status: "bounded_dry_run_ready",
          summary: {
            source_packets: 4,
            tool_candidates: 2,
            certified_read_only_tools: 1,
            denied_tools: 1,
          },
          proof_packet: {
            status: "complete",
            mcp_readiness: {
              status: "dry_run_ready",
              certified_tool_ids: ["tool.listorders"],
              denied_tool_ids: ["tool.cancelorder"],
              readiness_blockers: ["operator_approval_missing"],
            },
          },
          generated_contract: {
            tools: [
              { tool_id: "tool.listorders", name: "listorders", method: "GET", path: "/orders", certification_result: "read_only", mutation_class: "read_only", readiness_blockers: [] },
              { tool_id: "tool.cancelorder", name: "cancelorder", method: "POST", path: "/orders/{order_id}/cancel", certification_result: "denied", mutation_class: "mutation", readiness_blockers: ["operator_approval_missing"] },
            ],
          },
          pilot_runtime: {
            status: "dry_run_ready",
            managed_runtime_deployed: false,
            mcp_endpoint_ref: "mcp-dry-run://praxis-demo-generated-mcp",
            controls: [
              { control_id: "start_dry_run", label: "Start dry-run MCP endpoint", state: "ready", requires_mesh_approval: false },
              { control_id: "deploy_managed_runtime", label: "Deploy managed pilot runtime", state: "blocked", requires_mesh_approval: true, reason: "proof required" },
            ],
          },
        },
      },
    } as any);

    expect(model).toMatchObject({
      status: "bounded dry run ready",
      proofStatus: "complete",
      sourcePackets: "4",
      toolCandidates: "2",
      certifiedTools: "1",
      deniedTools: "1",
      runtimeStatus: "dry run ready",
      managedRuntime: false,
      blockerCount: 1,
    });
    expect(model.tools.map((tool) => tool.tone)).toEqual(["good", "warn"]);
    expect(model.controls).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "start_dry_run", state: "ready", requiresMeshApproval: false }),
      expect.objectContaining({ id: "deploy_managed_runtime", state: "blocked", requiresMeshApproval: true }),
    ]));
  });
});

describe("evidence trace rail", () => {
  it("keeps signal, evidence, policy, and decision authority with Mesh", () => {
    const steps = evidenceTraceSteps({
      mesh: {
        runs: { runs: [{ scenario_key: "reth_peer_starvation", status: "awaiting_operator" }] },
        approvals: { items: [{ queue_id: "approval://run_1" }] },
        pilot_go_no_go: { missing_evidence: ["decision_record_present"] },
      },
    } as any);

    expect(steps.map((step) => step.label)).toEqual(["Signal", "Evidence", "Policy", "Decision"]);
    expect(steps[0].authority).toBe("Mesh run state");
    expect(steps[1].detail).toContain("1 missing proof");
    expect(steps[2].authority).toBe("Mesh policy and approvals");
    expect(steps[3].detail).toContain("awaiting_operator");
  });
});
