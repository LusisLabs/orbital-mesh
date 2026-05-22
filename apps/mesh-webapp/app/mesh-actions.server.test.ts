import { describe, expect, it, vi } from "vitest";

import {
  killSwitchPayload,
  MESH_OPERATOR_ACTIONS_STATE_SLICE,
  proxyMeshJsonAction,
  readOperatorActionPayload,
  runLaunchPayload,
  steeringPayload
} from "./mesh-actions.server";

describe("mesh.operator_actions", () => {
  it("maps approval and steering actions to Mesh run steering payloads", () => {
    expect(steeringPayload("approve", { reason: "looks good" })).toMatchObject({
      command: "approve",
      reason: "looks good",
      backend_resource: "RunSession.steering",
      would_touch_state_slice: "mesh.run_steering.v1"
    });
    expect(steeringPayload("reject")).toMatchObject({ command: "cancel", mutation: "reject" });
    expect(steeringPayload("pause")).toMatchObject({ command: "pause" });
    expect(steeringPayload("resume")).toMatchObject({ command: "resume" });
  });

  it("names backend resources for kill switch and run launch mutations", () => {
    expect(killSwitchPayload({ live_execution_enabled: false })).toMatchObject({
      backend_resource: "KillSwitchStatus",
      would_touch_state_slice: "mesh.kill_switch.v1"
    });
    expect(runLaunchPayload({ scenario_key: "smoke" })).toMatchObject({
      backend_resource: "RunSession",
      would_touch_state_slice: "mesh.run_admission.v1"
    });
  });

  it("reads JSON and form payloads", async () => {
    expect(await readOperatorActionPayload(new Request("https://mesh/actions", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ reason: "json" })
    }))).toEqual({ reason: "json" });

    const form = new FormData();
    form.set("reason", "form");
    expect(await readOperatorActionPayload(new Request("https://mesh/actions", { method: "POST", body: form }))).toEqual({ reason: "form" });
  });

  it("proxies a named Mesh action with state-slice metadata", async () => {
    const fetchMock = vi.fn(async (_input: URL, init?: RequestInit) => {
      const payload = JSON.parse(Buffer.from(init?.body as ArrayBuffer).toString("utf8"));
      expect(payload.state_slice).toBe(MESH_OPERATOR_ACTIONS_STATE_SLICE);
      expect(payload.backend_resource).toBe("RunSession");
      return Response.json({ run_id: "run-1" }, { status: 201 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await proxyMeshJsonAction(
      new Request("https://mesh.example/resources/mesh/runs", { method: "POST" }),
      "/api/runs",
      runLaunchPayload({ scenario_key: "smoke" })
    );

    expect(response.status).toBe(201);
    expect(fetchMock).toHaveBeenCalledWith(new URL("http://127.0.0.1:8000/api/runs"), expect.objectContaining({ method: "POST" }));

    vi.unstubAllGlobals();
  });
});
