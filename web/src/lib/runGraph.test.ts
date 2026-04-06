import { describe, expect, it } from "vitest";

import { buildRunGraph, toneForStage } from "./runGraph";

describe("runGraph", () => {
  it("builds ordered nodes and edges from run events", () => {
    const graph = buildRunGraph([
      {
        event_id: "evt-1",
        run_id: "run-1",
        sequence: 1,
        stage: "queued",
        event_type: "run_queued",
        recorded_at: "2026-04-06T00:00:00Z",
        payload: {},
      },
      {
        event_id: "evt-2",
        run_id: "run-1",
        sequence: 2,
        stage: "evaluation_ready",
        event_type: "evaluation_ready",
        recorded_at: "2026-04-06T00:00:01Z",
        payload: {},
      },
      {
        event_id: "evt-3",
        run_id: "run-1",
        sequence: 3,
        stage: "completed",
        event_type: "run_completed",
        recorded_at: "2026-04-06T00:00:02Z",
        payload: {},
      },
    ]);

    expect(graph.nodes).toHaveLength(3);
    expect(graph.edges).toHaveLength(2);
    expect(graph.edges[0].source).toBe("evt-1");
    expect(graph.edges[1].target).toBe("evt-3");
  });

  it("assigns stable tones by stage", () => {
    expect(toneForStage("completed")).toBe("#7fb685");
    expect(toneForStage("awaiting_operator")).toBe("#f0be6a");
    expect(toneForStage("failed")).toBe("#f06a6a");
  });
});

