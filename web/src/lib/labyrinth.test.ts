import { describe, expect, it } from "vitest";

import { buildAsciiSignalFrame } from "./asciiSignal";
import { buildLabyrinthCrossings, buildLabyrinthGuideposts, crossingFromEvent } from "./labyrinth";
import type { EvidenceGraph, RunDetail, ScenarioAnalysis, WatcherStatus } from "../types";

const baseRun: RunDetail = {
  run_id: "run-1",
  created_at: "2026-04-26T00:00:00Z",
  updated_at: "2026-04-26T00:00:02Z",
  goal_id: "goal-1",
  scenario_key: "reth_disk_pressure",
  stage: "awaiting_operator",
  status: "running",
  steering_mode: "approval_gate",
  auto_mode: false,
  pause_points: ["evaluation_ready"],
  pending_pause_stage: "evaluation_ready",
  evaluation_mode: "native",
  orchestration_mode: "goose",
  latest_event_id: "evt-2",
  latest_event_sequence: 2,
  latest_merkle_root: "root",
  operator_notes: [],
  artifacts: {
    input_signal: {
      signal_type: "reth_node",
      service: "el-1-reth-lighthouse",
      execution: { peer_count: 0, min_peer_count: 1, block_lag: 0 },
      storage: { disk_used_pct: 97 },
    },
  },
  events: [
    {
      event_id: "evt-1",
      run_id: "run-1",
      sequence: 1,
      stage: "queued",
      event_type: "run_queued",
      recorded_at: "2026-04-26T00:00:00Z",
      payload: {},
      summary: null,
    },
    {
      event_id: "evt-2",
      run_id: "run-1",
      sequence: 2,
      stage: "awaiting_operator",
      event_type: "approval_blocked",
      recorded_at: "2026-04-26T00:00:01Z",
      payload: { final_recommendation: "human_review" },
      summary: { risk_level: "high" },
      artifact_key: "evaluation",
      status: "requires_review",
    },
  ],
  merkle: { run_id: "run-1", root_hash: "root", leaf_count: 2, event_ids: ["evt-1", "evt-2"] },
};

const scenarioAnalysis: ScenarioAnalysis = {
  analysis_id: "analysis-1",
  trigger_id: "trigger-1",
  created_at: "2026-04-26T00:00:01Z",
  suggested_decision_type: "escalate",
  confidence: 0.67,
  risk_level: "medium",
  autonomy_tier_hint: "escalated",
  required_review_reasons: ["historical success rate is weak"],
  evidence_refs: ["ev-1"],
  evidence_nodes: [
    {
      evidence_id: "ev-1",
      analyzer: "historical_outcome",
      kind: "historical_outcomes",
      confidence: 0.75,
      trusted: true,
      summary: "Historical remediation outcomes summarized for this service.",
      payload: { success_rates: { restart_systemd_service: 0.182 } },
    },
  ],
  subdecisions: [],
};

const evidenceGraph: EvidenceGraph = {
  nodes: [
    { id: "ev-1", type: "evidence", label: "Historical outcomes", confidence: 0.75 },
    { id: "sub-1", type: "subdecision", label: "approval_required", requires_review: true },
    { id: "analysis-1", type: "scenario_analysis", label: "escalate" },
  ],
  edges: [
    { source: "ev-1", target: "sub-1", kind: "supports" },
    { source: "sub-1", target: "analysis-1", kind: "feeds" },
  ],
};

const watchers: WatcherStatus = {
  watchers: [
    { name: "reth", signal_source: "reth", interval_seconds: 20, running: true, detail: { dedup_entries: 2 } },
    { name: "k8s", signal_source: "kubernetes", interval_seconds: 30, running: false },
  ],
};

describe("labyrinth normalization", () => {
  it("maps run events into crossings with threshold severity", () => {
    const crossing = crossingFromEvent(baseRun.events[1]);

    expect(crossing.id).toBe("evt-2");
    expect(crossing.thread).toBe("threshold");
    expect(crossing.severity).toBe("danger");
    expect(crossing.artifact_key).toBe("evaluation");
  });

  it("combines events, scenario evidence, subdecisions, memory, and watchers", () => {
    const crossings = buildLabyrinthCrossings({
      run: baseRun,
      scenarioAnalysis,
      evidenceGraph,
      memoryCrystallization: { claims_created: 2 },
      watchers,
    });

    expect(crossings.map((crossing) => crossing.id)).toContain("evt-1");
    expect(crossings.map((crossing) => crossing.id)).toContain("ev-1");
    expect(crossings.map((crossing) => crossing.id)).toContain("sub-1");
    expect(crossings.map((crossing) => crossing.id)).toContain("run-1:memory-crystallization");
    expect(crossings.map((crossing) => crossing.id)).toContain("watcher:k8s");
  });

  it("derives guideposts from review reasons, review subdecisions, and stopped watchers", () => {
    const guideposts = buildLabyrinthGuideposts({ run: baseRun, scenarioAnalysis, evidenceGraph, watchers });

    expect(guideposts.some((guidepost) => guidepost.title === "Operator gate is active")).toBe(true);
    expect(guideposts.some((guidepost) => guidepost.detail === "historical success rate is weak")).toBe(true);
    expect(guideposts.some((guidepost) => guidepost.id === "watchers:stopped")).toBe(true);
  });

  it("renders stable ASCII frames for healthy, warning, and failed states", () => {
    const allRunningWatchers: WatcherStatus = {
      watchers: watchers.watchers.map((watcher) => ({ ...watcher, running: true })),
    };
    const stable = buildAsciiSignalFrame({ stage: "completed", status: "completed", crossings: [], guideposts: [], watchers: allRunningWatchers });
    const warning = buildAsciiSignalFrame({
      stage: "awaiting_operator",
      status: "running",
      signal: baseRun.artifacts.input_signal,
      crossings: [],
      guideposts: [],
      watchers,
    });
    const danger = buildAsciiSignalFrame({
      stage: "failed",
      status: "failed",
      crossings: [],
      guideposts: [{ id: "g", journey_id: "run-1", severity: "danger", title: "Run failed", detail: "failed", evidence_refs: [] }],
      watchers,
    });

    expect(stable.tone).toBe("stable");
    expect(warning.tone).toBe("warning");
    expect(warning.lines.join("\n")).toContain("reth peers:0 lag:0 disk:97");
    expect(danger.tone).toBe("danger");
  });
});
