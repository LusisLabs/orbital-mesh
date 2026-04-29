import { humanize } from "./format";
import type {
  EvidenceGraph,
  LabyrinthCrossing,
  LabyrinthGuidepost,
  LabyrinthJourney,
  LabyrinthSeverity,
  LabyrinthThread,
  ResearchSessionRecord,
  RunDetail,
  RunEventRecord,
  RunSessionRecord,
  ScenarioAnalysis,
  WatcherStatus,
} from "../types";

export function buildLabyrinthJourneys({
  runs,
  researchSessions,
  watchers,
  activeRunId,
  activeResearchSessionId,
}: {
  runs: RunSessionRecord[];
  researchSessions: ResearchSessionRecord[];
  watchers: WatcherStatus | null;
  activeRunId: string;
  activeResearchSessionId: string;
}): LabyrinthJourney[] {
  const runJourneys = runs.map((run) => ({
    id: run.run_id,
    kind: "run" as const,
    source: run.scenario_key ? "scenario" : "manual",
    title: run.scenario_key ? humanize(run.scenario_key) : "Manual run",
    status: run.status,
    summary: `${humanize(run.stage)} - ${run.latest_event_sequence} events`,
    updated_at: run.updated_at,
    event_count: run.latest_event_sequence,
    risk_level: riskFromArtifacts(run.artifacts),
    selected: run.run_id === activeRunId,
  }));

  const researchJourneys = researchSessions.map((session) => ({
    id: session.session_id,
    kind: "research" as const,
    source: session.minimax_route ?? "research",
    title: session.question || session.directory,
    status: session.status,
    summary: session.research_intelligence
      ? humanize(session.research_intelligence.classification)
      : session.has_final_report
        ? "Final report ready"
        : "Research in progress",
    updated_at: session.updated_at,
    event_count: session.has_final_report ? 1 : 0,
    risk_level: session.research_intelligence?.classification === "off_domain" ? "medium" : null,
    selected: session.session_id === activeResearchSessionId,
  }));

  const watcherJourneys = (watchers?.watchers ?? []).map((watcher) => ({
    id: watcher.name,
    kind: "watcher" as const,
    source: watcher.signal_source,
    title: watcher.name,
    status: watcher.running ? "running" : "stopped",
    summary: `${watcher.signal_source} every ${watcher.interval_seconds}s`,
    updated_at: "",
    event_count: Number(watcher.detail?.dedup_entries ?? 0),
    risk_level: watcher.running ? null : "medium",
    selected: false,
  }));

  return [...runJourneys, ...researchJourneys, ...watcherJourneys];
}

export function buildLabyrinthCrossings({
  run,
  scenarioAnalysis,
  evidenceGraph,
  memoryCrystallization,
  watchers,
}: {
  run: RunDetail | null;
  scenarioAnalysis: ScenarioAnalysis | null;
  evidenceGraph: EvidenceGraph | null;
  memoryCrystallization: Record<string, unknown> | null;
  watchers: WatcherStatus | null;
}): LabyrinthCrossing[] {
  const crossings: LabyrinthCrossing[] = [];
  const journeyId = run?.run_id ?? "mesh";

  (run?.events ?? []).forEach((event) => {
    crossings.push(crossingFromEvent(event));
  });

  (scenarioAnalysis?.evidence_nodes ?? []).forEach((node, index) => {
    const evidenceId = String(node.evidence_id ?? `evidence-${index}`);
    crossings.push({
      id: evidenceId,
      journey_id: journeyId,
      type: "evidence",
      label: String(node.summary ?? node.kind ?? "Evidence"),
      status: node.trusted === false ? "untrusted" : "trusted",
      thread: "evidence",
      sequence: crossings.length + 1,
      actor: String(node.analyzer ?? "analyzer"),
      target: String(node.kind ?? "evidence"),
      preview_in: formatPreview(node.payload),
      preview_out: String(node.summary ?? ""),
      event_id: null,
      artifact_key: "scenario_analysis",
      evidence_refs: [evidenceId],
      severity: severityFromConfidence(Number(node.confidence ?? 0.5), node.trusted === false),
    });
  });

  (evidenceGraph?.nodes ?? [])
    .filter((node) => node.type === "subdecision" || node.type === "scenario_analysis")
    .forEach((node) => {
      crossings.push({
        id: node.id,
        journey_id: journeyId,
        type: node.type,
        label: String(node.label ?? humanize(node.type)),
        status: node.requires_review ? "requires_review" : "recorded",
        thread: node.requires_review ? "threshold" : "evidence",
        sequence: crossings.length + 1,
        actor: node.analyzer ?? "scenario_analysis",
        target: node.type,
        preview_in: node.confidence != null ? `confidence ${node.confidence}` : null,
        preview_out: node.merkle_root ?? null,
        event_id: null,
        artifact_key: "evidence_graph",
        evidence_refs: evidenceGraph ? evidenceRefsForNode(evidenceGraph, node.id) : [],
        severity: node.requires_review ? "warning" : "info",
      });
    });

  if (memoryCrystallization) {
    crossings.push({
      id: `${journeyId}:memory-crystallization`,
      journey_id: journeyId,
      type: "memory_crystallization",
      label: "Memory crystallization",
      status: "recorded",
      thread: "memory",
      sequence: crossings.length + 1,
      actor: "memory",
      target: "vault",
      preview_in: formatPreview(memoryCrystallization),
      preview_out: `${Object.keys(memoryCrystallization).length} fields`,
      event_id: null,
      artifact_key: "memory_crystallization",
      evidence_refs: [],
      severity: "success",
    });
  }

  (watchers?.watchers ?? []).forEach((watcher) => {
    crossings.push({
      id: `watcher:${watcher.name}`,
      journey_id: watcher.name,
      type: "watcher",
      label: watcher.name,
      status: watcher.running ? "running" : "stopped",
      thread: "watcher",
      sequence: crossings.length + 1,
      actor: watcher.signal_source,
      target: "control_plane",
      preview_in: formatPreview(watcher.detail),
      preview_out: `${watcher.signal_source} / ${watcher.interval_seconds}s`,
      event_id: null,
      artifact_key: null,
      evidence_refs: [],
      severity: watcher.running ? "success" : "warning",
    });
  });

  return crossings;
}

export function buildLabyrinthGuideposts({
  run,
  scenarioAnalysis,
  evidenceGraph,
  watchers,
}: {
  run: RunDetail | null;
  scenarioAnalysis: ScenarioAnalysis | null;
  evidenceGraph: EvidenceGraph | null;
  watchers: WatcherStatus | null;
}): LabyrinthGuidepost[] {
  const journeyId = run?.run_id ?? "mesh";
  const guideposts: LabyrinthGuidepost[] = [];

  if (run?.stage === "awaiting_operator") {
    guideposts.push({
      id: `${journeyId}:operator-gate`,
      journey_id: journeyId,
      severity: "warning",
      title: "Operator gate is active",
      detail: "The run is paused at a threshold and requires steering before actuation continues.",
      evidence_refs: [run.latest_event_id ?? ""].filter(Boolean),
    });
  }

  if (run?.status === "failed" || run?.stage === "failed") {
    guideposts.push({
      id: `${journeyId}:failed`,
      journey_id: journeyId,
      severity: "danger",
      title: "Run failed",
      detail: run.error ?? "The run reached a failed terminal state.",
      evidence_refs: [run.latest_event_id ?? ""].filter(Boolean),
    });
  }

  const scenarioEvidenceRefs = scenarioAnalysis?.evidence_refs ?? [];
  (scenarioAnalysis?.required_review_reasons ?? []).forEach((reason, index) => {
    guideposts.push({
      id: `${journeyId}:review-${index}`,
      journey_id: journeyId,
      severity: "warning",
      title: "Review required",
      detail: reason,
      evidence_refs: scenarioEvidenceRefs,
    });
  });

  (scenarioAnalysis?.evidence_nodes ?? [])
    .filter((node) => node.trusted === false || Number(node.confidence ?? 1) < 0.6)
    .forEach((node, index) => {
      guideposts.push({
        id: `${journeyId}:weak-evidence-${index}`,
        journey_id: journeyId,
        severity: "warning",
        title: "Weak evidence",
        detail: String(node.summary ?? "Evidence has low confidence or is untrusted."),
        evidence_refs: [String(node.evidence_id ?? "")].filter(Boolean),
      });
    });

  const reviewSubdecisions = (evidenceGraph?.nodes ?? []).filter((node) => node.requires_review);
  if (reviewSubdecisions.length > 0) {
    guideposts.push({
      id: `${journeyId}:subdecision-review`,
      journey_id: journeyId,
      severity: "warning",
      title: "Subdecision routed to review",
      detail: `${reviewSubdecisions.length} scenario analysis subdecision(s) require review.`,
      evidence_refs: reviewSubdecisions.map((node) => node.id),
    });
  }

  const stoppedWatchers = (watchers?.watchers ?? []).filter((watcher) => !watcher.running);
  if (stoppedWatchers.length > 0) {
    guideposts.push({
      id: "watchers:stopped",
      journey_id: "watchers",
      severity: "warning",
      title: "Watcher coverage reduced",
      detail: `${stoppedWatchers.length} registered watcher(s) are stopped.`,
      evidence_refs: stoppedWatchers.map((watcher) => watcher.name),
    });
  }

  return guideposts.slice(0, 12);
}

export function crossingFromEvent(event: RunEventRecord): LabyrinthCrossing {
  return {
    id: event.event_id,
    journey_id: event.run_id,
    type: event.event_type,
    label: humanize(event.event_type),
    status: event.status ?? "recorded",
    thread: threadForEvent(event),
    sequence: event.sequence,
    recorded_at: event.recorded_at,
    actor: event.integration_name ?? "mesh",
    target: event.artifact_key ?? event.stage,
    preview_in: formatPreview(event.payload),
    preview_out: formatPreview(event.summary),
    event_id: event.event_id,
    artifact_key: event.artifact_key ?? null,
    evidence_refs: event.merkle_leaf_hash ? [event.merkle_leaf_hash] : [],
    severity: severityForEvent(event),
  };
}

function threadForEvent(event: RunEventRecord): LabyrinthThread {
  if (event.stage === "awaiting_operator" || event.event_type.includes("approval")) return "threshold";
  if (event.artifact_key === "scenario_analysis" || event.event_type.includes("evidence")) return "evidence";
  if (event.artifact_key === "memory_crystallization" || event.event_type.includes("memory")) return "memory";
  if (event.stage === "executing" || event.artifact_key === "execution") return "execution";
  return "main";
}

function severityForEvent(event: RunEventRecord): LabyrinthSeverity {
  if (event.stage === "failed" || event.status === "failed" || event.event_type.includes("blocked")) return "danger";
  if (event.stage === "awaiting_operator" || event.status === "requires_review") return "warning";
  if (event.stage === "completed" || event.status === "recorded") return "success";
  return "info";
}

function severityFromConfidence(confidence: number, untrusted: boolean): LabyrinthSeverity {
  if (untrusted) return "danger";
  if (confidence < 0.6) return "warning";
  if (confidence >= 0.8) return "success";
  return "info";
}

function evidenceRefsForNode(graph: EvidenceGraph, nodeId: string): string[] {
  return graph.edges
    .filter((edge) => edge.target === nodeId || edge.source === nodeId)
    .flatMap((edge) => [edge.source, edge.target])
    .filter((id) => id !== nodeId);
}

function riskFromArtifacts(artifacts: Record<string, any>): string | null {
  const scenario = artifacts.scenario_analysis;
  if (scenario && typeof scenario === "object" && typeof scenario.risk_level === "string") return scenario.risk_level;
  const decision = artifacts.decision;
  if (decision && typeof decision === "object" && typeof decision.risk?.level === "string") return decision.risk.level;
  return null;
}

function formatPreview(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? "" : "s"}`;
  if (typeof value === "object") return `${Object.keys(value as Record<string, unknown>).length} fields`;
  return "";
}
