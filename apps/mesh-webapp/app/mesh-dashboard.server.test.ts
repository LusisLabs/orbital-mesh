import { describe, expect, it, vi } from "vitest";

import {
  dashboardRecordState,
  forwardedDashboardHeaders,
  loadOverviewDashboard,
  MESH_OPERATOR_OVERVIEW_STATE_SLICE
} from "./mesh-dashboard.server";

describe("mesh.operator_ui.overview dashboard loader", () => {
  it("loads overview data through same-origin Mesh resource routes", async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request, _init?: RequestInit) => {
      const url = input instanceof URL ? input : new URL(input.toString());
      const path = `${url.pathname}${url.search}`;
      if (path === "/resources/mesh/readiness") {
        return Response.json({ status: "ready", blockers: [] });
      }
      if (path === "/resources/mesh/runs?summary=1") {
        return Response.json({ runs: [{ run_id: "run-1", status: "running", stage: "evidence" }] });
      }
      if (path === "/resources/mesh/approvals") {
        return Response.json({ status: "ready", items: [{ queue_id: "approval-1", run_id: "run-1" }] });
      }
      if (path === "/resources/mesh/kill-switch") {
        return Response.json({ live_execution_enabled: false, force_approval_gate: true });
      }
      if (path === "/resources/mesh/connector-certification") {
        return Response.json({ status: "ready", blockers: [], connectors: { hermes: { state: "certified" } } });
      }
      return Response.json({ error: "unexpected" }, { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const dashboard = await loadOverviewDashboard(
      new Request("https://mesh.example/mesh", { headers: { "X-Mesh-Operator": "alice" } })
    );

    expect(dashboard.stateSlice).toBe(MESH_OPERATOR_OVERVIEW_STATE_SLICE);
    expect(dashboard.readiness.state).toBe("ready");
    expect(dashboard.runs.data).toHaveLength(1);
    expect(dashboard.approvals.data).toHaveLength(1);
    expect(dashboard.killSwitch.data.force_approval_gate).toBe(true);
    expect(fetchMock.mock.calls.map(([url]) => `${(url as URL).pathname}${(url as URL).search}`)).toEqual([
      "/resources/mesh/readiness",
      "/resources/mesh/runs?summary=1",
      "/resources/mesh/approvals",
      "/resources/mesh/kill-switch",
      "/resources/mesh/connector-certification"
    ]);
    const init = fetchMock.mock.calls[0][1];
    expect((init?.headers as Headers).get("x-mesh-operator")).toBe("alice");

    vi.unstubAllGlobals();
  });

  it("classifies unavailable Mesh resource calls without throwing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("control plane down")));

    const dashboard = await loadOverviewDashboard(new Request("https://mesh.example/mesh"));

    expect(dashboard.readiness.state).toBe("backend-unavailable");
    expect(dashboard.runs.state).toBe("backend-unavailable");
    expect(dashboard.runs.data).toEqual([]);
    expect(dashboard.approvals.data).toEqual([]);

    vi.unstubAllGlobals();
  });

  it("forwards only Mesh dashboard identity headers", () => {
    const headers = forwardedDashboardHeaders(
      new Request("https://mesh.example/mesh", {
        headers: {
          Authorization: "Bearer should-not-forward",
          Cookie: "mesh_session=abc",
          "X-Mesh-Operator": "alice",
          "X-Mesh-Roles": "viewer"
        }
      })
    );

    expect(headers.get("accept")).toBe("application/json");
    expect(headers.get("authorization")).toBeNull();
    expect(headers.get("cookie")).toBe("mesh_session=abc");
    expect(headers.get("x-mesh-operator")).toBe("alice");
    expect(headers.get("x-mesh-roles")).toBe("viewer");
  });

  it("classifies blocker and degraded packets", () => {
    expect(dashboardRecordState({ status: "ready", blockers: [] })).toBe("ready");
    expect(dashboardRecordState({ status: "ready", blockers: ["missing proof"] })).toBe("blocked");
    expect(dashboardRecordState({ status: "fail" })).toBe("degraded");
  });
});
