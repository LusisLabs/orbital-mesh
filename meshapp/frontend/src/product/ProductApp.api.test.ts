import { describe, expect, it } from "vitest";

import { normalizeLoopbackBaseUrl } from "./api";

describe("product API base URL", () => {
  it("keeps loopback API cookies same-site with the opened frontend hostname", () => {
    expect(normalizeLoopbackBaseUrl("http://127.0.0.1:8787", { hostname: "localhost" })).toBe("http://localhost:8787");
    expect(normalizeLoopbackBaseUrl("http://localhost:8787", { hostname: "127.0.0.1" })).toBe("http://127.0.0.1:8787");
  });

  it("does not rewrite non-loopback API hosts", () => {
    expect(normalizeLoopbackBaseUrl("https://mesh.example.com/api", { hostname: "localhost" })).toBe("https://mesh.example.com/api");
    expect(normalizeLoopbackBaseUrl("http://127.0.0.1:8787", { hostname: "operator.local" })).toBe("http://127.0.0.1:8787");
  });
});
