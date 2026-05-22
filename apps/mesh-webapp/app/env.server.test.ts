import { describe, expect, it } from "vitest";

import { parseMeshWebEnvironment } from "./env.server";

describe("parseMeshWebEnvironment", () => {
  it("defaults to the local Mesh control plane", () => {
    const env = parseMeshWebEnvironment({});

    expect(env.MESH_CONTROL_PLANE_URL).toBe("http://127.0.0.1:8000");
    expect(env.NODE_ENV).toBe("development");
  });

  it("accepts an operator identity header name", () => {
    const env = parseMeshWebEnvironment({
      NODE_ENV: "production",
      MESH_CONTROL_PLANE_URL: "https://mesh.internal",
      MESH_OPERATOR_IDENTITY_HEADER: "X-Mesh-Operator"
    });

    expect(env.MESH_OPERATOR_IDENTITY_HEADER).toBe("X-Mesh-Operator");
  });
});
