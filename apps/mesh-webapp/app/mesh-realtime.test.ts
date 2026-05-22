import { describe, expect, it } from "vitest";

import {
  initialRealtimeSnapshot,
  isTerminalRunEvent,
  MESH_REALTIME_STATE_SLICE,
  parseRealtimePayload,
  reduceRealtimeSnapshot,
  runStreamResourcePath,
  shouldMarkRealtimeStale,
  systemStreamResourcePath
} from "./mesh-realtime";

describe("mesh.operator_ui.realtime", () => {
  it("uses Remix resource routes while preserving Mesh stream endpoint semantics", () => {
    expect(systemStreamResourcePath()).toBe("/resources/mesh/stream/system");
    expect(runStreamResourcePath("run/1")).toBe("/resources/mesh/stream/runs/run%2F1");
  });

  it("tracks connect, message, reconnect, stale, and terminal states", () => {
    let snapshot = initialRealtimeSnapshot<{ status: string }>();
    expect(snapshot.stateSlice).toBe(MESH_REALTIME_STATE_SLICE);
    expect(snapshot.connection).toBe("connecting");

    snapshot = reduceRealtimeSnapshot(snapshot, { type: "open", now: "2026-05-22T00:00:00Z" });
    expect(snapshot.connection).toBe("connected");

    snapshot = reduceRealtimeSnapshot(snapshot, {
      type: "message",
      eventType: "system",
      data: { status: "ready" },
      now: "2026-05-22T00:00:01Z"
    });
    expect(snapshot.data).toEqual({ status: "ready" });
    expect(snapshot.lastEventType).toBe("system");

    snapshot = reduceRealtimeSnapshot(snapshot, { type: "error", now: "2026-05-22T00:00:02Z" });
    expect(snapshot.connection).toBe("reconnecting");
    expect(snapshot.reconnectAttempts).toBe(1);

    snapshot = reduceRealtimeSnapshot(snapshot, { type: "stale", now: "2026-05-22T00:00:30Z" });
    expect(snapshot.connection).toBe("stale");

    snapshot = reduceRealtimeSnapshot(snapshot, { type: "terminal", reason: "run completed", now: "2026-05-22T00:00:40Z" });
    expect(snapshot.connection).toBe("terminal");
    expect(snapshot.terminalReason).toBe("run completed");

    const unchanged = reduceRealtimeSnapshot(snapshot, { type: "error", now: "2026-05-22T00:00:41Z" });
    expect(unchanged).toBe(snapshot);
  });

  it("parses payloads and detects terminal run events", () => {
    expect(parseRealtimePayload('{"status":"completed"}')).toEqual({ status: "completed" });
    expect(parseRealtimePayload("   ")).toBeNull();
    expect(isTerminalRunEvent({ status: "completed" })).toBe(true);
    expect(isTerminalRunEvent({ event_type: "run_failed" })).toBe(true);
    expect(isTerminalRunEvent({ status: "running" })).toBe(false);
  });

  it("marks streams stale after the configured interval", () => {
    expect(shouldMarkRealtimeStale("2026-05-22T00:00:00Z", Date.parse("2026-05-22T00:00:10Z"), 5_000)).toBe(true);
    expect(shouldMarkRealtimeStale("2026-05-22T00:00:00Z", Date.parse("2026-05-22T00:00:03Z"), 5_000)).toBe(false);
    expect(shouldMarkRealtimeStale(undefined, Date.now(), 5_000)).toBe(false);
  });
});
