import { describe, expect, it } from "vitest";

import { evidenceTraceSteps, operatorWorkflowPosture, readModelCardPayload, readModelSummary, workflowForView } from "./ProductApp";

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
    expect(operatorWorkflowPosture("launch")).toMatchObject({ callPath: expect.stringContaining("/api/runs"), posture: "delegated" });
    expect(operatorWorkflowPosture("approval")).toMatchObject({ callPath: expect.stringContaining("/api/approvals"), posture: "delegated" });
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
