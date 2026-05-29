import { describe, expect, it } from "vitest";

import { normalizeLoopbackBaseUrl, resolveBaseUrl } from "./api";

describe("product API base URL", () => {
  it("keeps loopback API cookies same-site with the opened frontend hostname", () => {
    expect(normalizeLoopbackBaseUrl("http://127.0.0.1:8787", { hostname: "localhost" })).toBe("http://localhost:8787");
    expect(normalizeLoopbackBaseUrl("http://localhost:8787", { hostname: "127.0.0.1" })).toBe("http://127.0.0.1:8787");
  });

  it("does not rewrite non-loopback API hosts", () => {
    expect(normalizeLoopbackBaseUrl("https://mesh.example.com/api", { hostname: "localhost" })).toBe("https://mesh.example.com/api");
    expect(normalizeLoopbackBaseUrl("http://127.0.0.1:8787", { hostname: "operator.local" })).toBe("http://127.0.0.1:8787");
  });

  it("uses same-origin when no explicit server or configured API URL", () => {
    const originalWindow = globalThis.window;
    const originalEnv = process.env.NEXT_PUBLIC_MESH_API_URL;
    process.env.NEXT_PUBLIC_MESH_API_URL = "";
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: {
        location: {
          search: "",
          protocol: "http:",
          origin: "http://localhost:3000",
          hostname: "localhost",
        },
      },
    });
    try {
      expect(resolveBaseUrl()).toBe("http://localhost:3000");
    } finally {
      process.env.NEXT_PUBLIC_MESH_API_URL = originalEnv;
      Object.defineProperty(globalThis, "window", { configurable: true, value: originalWindow });
    }
  });
});
