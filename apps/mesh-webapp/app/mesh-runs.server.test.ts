import type { LoaderFunctionArgs } from "@remix-run/node";
import { describe, expect, it, vi } from "vitest";

import { loadRunDetailWorkspace, loadRunsWorkspace, MESH_RUN_DETAIL_STATE_SLICE } from "./mesh-runs.server";
import { loader as loadRunDetailRoute } from "./routes/mesh.runs.$runId";

describe("mesh.operator_ui.run_detail loaders", () => {
  it("rejects a missing route run id before contacting Mesh resources", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    try {
      await loadRunDetailRoute({
        context: {},
        params: {},
        request: new Request("https://mesh.example/mesh/runs")
      } as LoaderFunctionArgs);
      throw new Error("Expected missing run id to be rejected");
    } catch (error) {
      expect(error).toBeInstanceOf(Response);
      expect((error as Response).status).toBe(400);
      expect(await (error as Response).text()).toContain("mesh.operator_ui.run_detail");
    }

    expect(fetchMock).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("loads the runs index through the Mesh runs resource route", async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = input instanceof URL ? input : new URL(input.toString());
      expect(`${url.pathname}${url.search}`).toBe("/resources/mesh/runs?summary=1");
      return Response.json({ runs: [{ run_id: "run-1", status: "running", stage: "evidence" }] });
    });
    vi.stubGlobal("fetch", fetchMock);

    const workspace = await loadRunsWorkspace(new Request("https://mesh.example/mesh/runs"));

    expect(workspace.stateSlice).toBe(MESH_RUN_DETAIL_STATE_SLICE);
    expect(workspace.runs.state).toBe("ready");
    expect(workspace.runs.data[0].run_id).toBe("run-1");

    vi.unstubAllGlobals();
  });

  it("loads detail, timeline, Merkle, evidence, events, and vault previews through BFF resources", async () => {
    const seen: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const url = input instanceof URL ? input : new URL(input.toString());
        const path = `${url.pathname}${url.search}`;
        seen.push(path);
        if (path === "/resources/mesh/runs/run%2Fencoded") return Response.json({ run_id: "run/encoded", status: "running", stage: "execution" });
        if (path === "/resources/mesh/runs/run%2Fencoded/events") return Response.json({ events: [{ event_id: "evt-1", sequence: 1, stage: "trigger" }] });
        if (path === "/resources/mesh/runs/run%2Fencoded/evidence-graph") return Response.json({ nodes: [{ id: "evidence" }], edges: [] });
        if (path === "/resources/mesh/runs/run%2Fencoded/merkle") return Response.json({ root_hash: "root", leaf_count: 1 });
        if (path === "/resources/mesh/runs/run%2Fencoded/timeline-proof") return Response.json({ status: "ready", timeline: [] });
        if (path === "/resources/mesh/vault/tree") return Response.json({ tree: [{ path: "run/summary.json" }] });
        return Response.json({ error: path }, { status: 404 });
      })
    );

    const workspace = await loadRunDetailWorkspace(new Request("https://mesh.example/mesh/runs/run%2Fencoded"), "run/encoded");

    expect(workspace.stateSlice).toBe(MESH_RUN_DETAIL_STATE_SLICE);
    expect(workspace.run.data.run_id).toBe("run/encoded");
    expect(workspace.events.data).toHaveLength(1);
    expect(workspace.merkle.data.root_hash).toBe("root");
    expect(workspace.vaultTree.data[0].path).toBe("run/summary.json");
    expect(seen).toEqual([
      "/resources/mesh/runs/run%2Fencoded",
      "/resources/mesh/runs/run%2Fencoded/events",
      "/resources/mesh/runs/run%2Fencoded/evidence-graph",
      "/resources/mesh/runs/run%2Fencoded/merkle",
      "/resources/mesh/runs/run%2Fencoded/timeline-proof",
      "/resources/mesh/vault/tree"
    ]);

    vi.unstubAllGlobals();
  });
});
