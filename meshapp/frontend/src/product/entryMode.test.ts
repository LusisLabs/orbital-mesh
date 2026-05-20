import { describe, expect, it } from "vitest";

import { shouldRenderLanding } from "./entryMode";

describe("meshapp frontend entry mode", () => {
  it("uses the marketing landing on lusislabs.com", () => {
    expect(shouldRenderLanding("lusislabs.com")).toBe(true);
    expect(shouldRenderLanding("www.lusislabs.com")).toBe(true);
  });

  it("keeps app.lusislabs.com and local development on the operator app", () => {
    expect(shouldRenderLanding("app.lusislabs.com")).toBe(false);
    expect(shouldRenderLanding("localhost")).toBe(false);
    expect(shouldRenderLanding("127.0.0.1")).toBe(false);
  });

  it("allows explicit local preview and app override", () => {
    expect(shouldRenderLanding("localhost", "?landing=1")).toBe(true);
    expect(shouldRenderLanding("lusislabs.com", "?app=1")).toBe(false);
  });
});
