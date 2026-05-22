import { describe, expect, it, vi } from "vitest";

import {
  buildControlPlaneUrl,
  forwardedControlPlaneHeaders,
  MESH_CONTROL_PLANE_PROXY_STATE_SLICE,
  proxyControlPlaneRequest
} from "./mesh-control-plane.server";

const meshEnv = {
  MESH_CONTROL_PLANE_URL: "https://control-plane.mesh.internal/base",
  MESH_OPERATOR_IDENTITY_HEADER: "X-Mesh-Operator-Identity"
};

describe("mesh.control_plane_proxy", () => {
  it("builds an upstream Mesh API URL while preserving the resource route query", () => {
    const url = buildControlPlaneUrl(
      "/api/runs/run-1/timeline-proof",
      "https://mesh.example/resources/mesh/runs/run-1/timeline-proof?include=events",
      meshEnv
    );

    expect(url.toString()).toBe("https://control-plane.mesh.internal/api/runs/run-1/timeline-proof?include=events");
  });

  it("forwards only content negotiation plus Mesh operator identity headers", () => {
    const request = new Request("https://mesh.example/resources/mesh/approvals", {
      headers: {
        Accept: "application/json",
        Authorization: "Bearer browser-token",
        "Content-Type": "application/json",
        "X-Mesh-Operator": "alice",
        "X-Mesh-Roles": "viewer,approver",
        "X-Mesh-Operator-Identity": "signed-operator-context"
      }
    });

    const headers = forwardedControlPlaneHeaders(request, meshEnv);

    expect(headers.get("accept")).toBe("application/json");
    expect(headers.get("authorization")).toBeNull();
    expect(headers.get("content-type")).toBe("application/json");
    expect(headers.get("x-mesh-operator")).toBe("alice");
    expect(headers.get("x-mesh-roles")).toBe("viewer,approver");
    expect(headers.get("x-mesh-operator-identity")).toBe("signed-operator-context");
  });

  it("proxies non-browser Mesh API calls through the Remix server", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ run_id: "run-1" }), {
        status: 201,
        headers: { "content-type": "application/json" }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    const request = new Request("https://mesh.example/resources/mesh/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Mesh-Operator": "alice" },
      body: JSON.stringify({ scenario_key: "smoke" })
    });

    const response = await proxyControlPlaneRequest(request, "/api/runs", meshEnv);

    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ run_id: "run-1" });
    expect(fetchMock).toHaveBeenCalledWith(
      new URL("https://control-plane.mesh.internal/api/runs"),
      expect.objectContaining({ method: "POST" })
    );
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Headers).get("x-mesh-operator")).toBe("alice");
    expect(init.body).toBeInstanceOf(ArrayBuffer);

    vi.unstubAllGlobals();
  });

  it("returns a Mesh proxy state-slice error when the control plane is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));

    const response = await proxyControlPlaneRequest(
      new Request("https://mesh.example/resources/mesh/readiness"),
      "/api/readiness",
      meshEnv
    );

    expect(response.status).toBe(502);
    expect(await response.json()).toMatchObject({
      error: "Mesh control plane unavailable",
      state_slice: MESH_CONTROL_PLANE_PROXY_STATE_SLICE
    });

    vi.unstubAllGlobals();
  });
});
