import type { Edge, Node } from "@xyflow/react";

import type { RunEventRecord } from "../types";

const STAGE_ORDER = [
  "queued",
  "ingesting",
  "trigger_ready",
  "decision_ready",
  "evaluation_ready",
  "awaiting_operator",
  "executing",
  "feedback_ready",
  "completed",
  "failed",
  "cancelled",
  "no_trigger",
];

export function buildRunGraph(events: RunEventRecord[]): { nodes: Node[]; edges: Edge[] } {
  const stageCounts = new Map<string, number>();
  const nodes: Node[] = events.map((event) => {
    const stageIndex = Math.max(STAGE_ORDER.indexOf(event.stage), 0);
    const rowIndex = stageCounts.get(event.stage) ?? 0;
    stageCounts.set(event.stage, rowIndex + 1);
    const tone = toneForStage(event.stage);
    return {
      id: event.event_id,
      data: {
        label: `${event.sequence}. ${event.event_type.replace(/_/g, " ")}`,
        stage: event.stage,
        recordedAt: event.recorded_at,
      },
      position: {
        x: stageIndex * 240,
        y: rowIndex * 140,
      },
      style: {
        borderRadius: 14,
        border: `1.5px solid ${tone}`,
        background: "rgba(10, 16, 26, 0.94)",
        color: "#f4f1e8",
        padding: "10px 14px",
        width: 210,
        fontSize: "0.82rem",
        fontFamily: "'IBM Plex Sans', sans-serif",
        boxShadow: `0 0 16px ${tone}22`,
        transition: "box-shadow 0.2s ease",
      },
    };
  });

  const edges: Edge[] = events.slice(1).map((event, index) => ({
    id: `edge-${events[index].event_id}-${event.event_id}`,
    source: events[index].event_id,
    target: event.event_id,
    animated: event.stage === "executing" || event.stage === "awaiting_operator",
    style: {
      stroke: toneForStage(event.stage),
      strokeWidth: 1.5,
      opacity: 0.6,
    },
  }));

  return { nodes, edges };
}

export function toneForStage(stage: string): string {
  if (stage === "completed") return "#7fb685";
  if (stage === "failed" || stage === "cancelled") return "#f06a6a";
  if (stage === "awaiting_operator") return "#f0be6a";
  if (stage === "executing") return "#64c7d0";
  if (stage === "evaluation_ready" || stage === "decision_ready") return "#a8d0d6";
  return "#8aa9a0";
}
