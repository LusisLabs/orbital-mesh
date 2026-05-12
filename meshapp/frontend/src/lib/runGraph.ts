import { Position, type Edge, type Node } from "@xyflow/react";

import type { EvidenceGraph, LabyrinthCrossing, RunEventRecord } from "../types";

const STAGE_ORDER = [
  "queued",
  "ingesting",
  "trigger_ready",
  "evidence_pack_ready",
  "investigation_ready",
  "scenario_analysis_ready",
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

const GRAPH_TONE = {
  info: "#548af7",
  active: "#2aacb8",
  cyan: "#2aacb8",
  success: "#73b00a",
  warn: "#e8a33e",
  danger: "#f75464",
  purple: "#c77dbb",
  functionBlue: "#56a8f5",
  neutral: "#7a7e85",
} as const;

export interface RunGraphNodeData extends Record<string, unknown> {
  nodeKind: "run" | "kubernetes" | "merkle" | "artifact" | "section";
  title: string;
  statusLabel: string;
  accent: string;
  meta: string[];
  eventId: string;
  sequence: number;
  eventType: string;
  stage: string;
  recordedAt: string;
  preview: string;
  integrationName?: string | null;
  artifactKey?: string | null;
}

export type RunGraphNode = Node<RunGraphNodeData, "runEvent">;
export type CanvasGraph = { nodes: RunGraphNode[]; edges: Edge[] };

export interface RcaGraphToolCall {
  id: string;
  name: string;
  status: string;
  valid: boolean;
  summary: string;
  citationIds: string[];
}

export interface RcaGraphCandidate {
  id: string;
  rank: number;
  cause: string;
  confidence: number | null;
  support: string[];
  citationIds: string[];
}

export interface RcaGraphBlocker {
  id: string;
  label: string;
  detail: string;
  source: string;
  severity: "warning" | "danger";
}

export interface RcaGraphCitation {
  id: string;
  label: string;
  detail: string;
}

export interface RcaGraphInput {
  tools: RcaGraphToolCall[];
  candidates: RcaGraphCandidate[];
  blockers: RcaGraphBlocker[];
  citations: RcaGraphCitation[];
  stopReason?: string | null;
}

export function buildRunGraph(events: RunEventRecord[], selectedEventId?: string): CanvasGraph {
  const stageCounts = new Map<string, number>();
  const columnCounts = new Map<number, number>();
  const nodes: RunGraphNode[] = events.map((event) => {
    const stageIndex = Math.max(STAGE_ORDER.indexOf(event.stage), 0);
    const rowIndex = stageCounts.get(event.stage) ?? 0;
    stageCounts.set(event.stage, rowIndex + 1);
    const columnIndex = columnCounts.get(stageIndex) ?? 0;
    columnCounts.set(stageIndex, columnIndex + 1);
    const tone = toneForStage(event.stage);
    const isSelected = event.event_id === selectedEventId;
    return {
      id: event.event_id,
      type: "runEvent",
      selected: isSelected,
      data: {
        nodeKind: "run",
        title: humanizeToken(event.event_type),
        statusLabel: humanizeToken(event.stage),
        accent: tone,
        meta: compact([
          `#${event.sequence}`,
          event.integration_name ?? undefined,
          event.artifact_key ?? undefined,
        ]),
        eventId: event.event_id,
        sequence: event.sequence,
        eventType: event.event_type,
        stage: event.stage,
        recordedAt: event.recorded_at,
        preview: summarizeEvent(event),
        integrationName: event.integration_name,
        artifactKey: event.artifact_key,
      },
      position: {
        x: stageIndex * 236,
        y: rowIndex * 146 + (columnIndex % 2 === 0 ? 0 : 18),
      },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      style: {
        width: isSelected ? 212 : 196,
      },
    };
  });

  const edges: Edge[] = events.slice(1).map((event, index) => ({
    id: `edge-${events[index].event_id}-${event.event_id}`,
    source: events[index].event_id,
    target: event.event_id,
    type: "smoothstep",
    animated: event.stage === "executing" || event.stage === "awaiting_operator",
    style: {
      stroke: toneForStage(event.stage),
      strokeWidth: event.event_id === selectedEventId || events[index].event_id === selectedEventId ? 2.2 : 1.5,
      opacity: event.event_id === selectedEventId || events[index].event_id === selectedEventId ? 0.95 : 0.6,
    },
  }));

  return { nodes, edges };
}

export function buildLabyrinthGraph(crossings: LabyrinthCrossing[], selectedCrossingId?: string): CanvasGraph {
  if (crossings.length === 0) return { nodes: [], edges: [] };

  const laneY: Record<string, number> = {
    threshold: 0,
    main: 150,
    evidence: 300,
    execution: 450,
    memory: 600,
    watcher: 750,
  };
  const laneCounts = new Map<string, number>();
  const nodes: RunGraphNode[] = crossings.map((crossing, index) => {
    const lane = crossing.thread;
    const rowCount = laneCounts.get(lane) ?? 0;
    laneCounts.set(lane, rowCount + 1);
    const selected = crossing.id === selectedCrossingId || crossing.event_id === selectedCrossingId;
    const tone = toneForSeverity(crossing.severity);
    return canvasNode({
      id: crossing.id,
      kind: crossing.thread === "watcher" ? "kubernetes" : crossing.thread === "evidence" ? "artifact" : "run",
      title: crossing.label,
      statusLabel: humanizeToken(crossing.status),
      preview: crossing.preview_out || crossing.preview_in || crossing.target || crossing.type,
      accent: tone,
      meta: compact([
        `#${crossing.sequence || index + 1}`,
        humanizeToken(crossing.thread),
        crossing.actor ?? undefined,
      ]),
      position: {
        x: index * 232,
        y: (laneY[lane] ?? laneY.main) + (rowCount % 2) * 28,
      },
      eventId: crossing.event_id ?? crossing.id,
      sequence: crossing.sequence,
      eventType: crossing.type,
      stage: crossing.status,
      recordedAt: crossing.recorded_at ?? undefined,
      artifactKey: crossing.artifact_key,
    }, selected);
  });

  const edges: Edge[] = crossings.slice(1).map((crossing, index) => {
    const previous = crossings[index];
    const threshold = crossing.thread === "threshold" || previous.thread === "threshold";
    return canvasEdge(
      `labyrinth-${previous.id}-${crossing.id}`,
      previous.id,
      crossing.id,
      threshold ? GRAPH_TONE.warn : toneForSeverity(crossing.severity),
      threshold,
    );
  });

  const evidenceByRef = new Map<string, string>();
  crossings.forEach((crossing) => {
    crossing.evidence_refs.forEach((ref) => evidenceByRef.set(ref, crossing.id));
  });
  crossings.forEach((crossing) => {
    crossing.evidence_refs.forEach((ref) => {
      const source = evidenceByRef.get(ref);
      if (source && source !== crossing.id) {
        edges.push(canvasEdge(`evidence-ref-${source}-${crossing.id}`, source, crossing.id, GRAPH_TONE.purple, true));
      }
    });
  });

  return { nodes, edges };
}

export function buildEvidenceGraph(graph: EvidenceGraph | null | undefined): CanvasGraph {
  if (!graph?.nodes?.length) return { nodes: [], edges: [] };

  const nodes: RunGraphNode[] = graph.nodes.map((node, index) => {
    const lane = node.type === "evidence" ? 0 : node.type === "subdecision" ? 1 : 2;
    const tone = node.requires_review ? GRAPH_TONE.warn : node.type === "scenario_analysis" ? GRAPH_TONE.active : GRAPH_TONE.info;
    return canvasNode({
      id: node.id,
      kind: node.type === "scenario_analysis" ? "section" : "artifact",
      title: String(node.label ?? humanizeToken(node.type)),
      statusLabel: humanizeToken(node.type),
      preview: compact([
        node.analyzer ?? undefined,
        typeof node.confidence === "number" ? `confidence ${Math.round(node.confidence * 100)}%` : undefined,
        node.requires_review ? "requires review" : undefined,
      ]).join(" / ") || "evidence graph node",
      accent: tone,
      meta: compact([node.id, node.merkle_root ?? undefined]),
      position: { x: lane * 320, y: 80 + index * 118 },
      artifactKey: "evidence_graph",
    });
  });

  const edges = graph.edges.map((edge, index) =>
    canvasEdge(
      `evidence-${index}-${edge.source}-${edge.target}`,
      edge.source,
      edge.target,
      edge.kind === "feeds" ? GRAPH_TONE.active : GRAPH_TONE.purple,
      edge.kind === "feeds",
    ),
  );

  return { nodes, edges };
}

export function buildRcaGraph(input: RcaGraphInput | null | undefined): CanvasGraph {
  if (!input) return { nodes: [], edges: [] };
  const hasContent = input.tools.length > 0 || input.candidates.length > 0 || input.blockers.length > 0 || input.citations.length > 0;
  if (!hasContent) return { nodes: [], edges: [] };

  const nodes: RunGraphNode[] = [
    canvasNode({
      id: "rca-investigation",
      kind: "section",
      title: "Investigation",
      statusLabel: input.stopReason ? humanizeToken(input.stopReason) : "RCA",
      preview: `${input.tools.length} tools / ${input.candidates.length} candidates`,
      accent: GRAPH_TONE.info,
      meta: compact([`${input.blockers.length} blockers`, `${input.citations.length} citations`]),
      position: { x: 20, y: 210 },
      artifactKey: "investigation_report",
    }),
  ];
  const edges: Edge[] = [];

  input.tools.slice(0, 10).forEach((tool, index) => {
    const id = `rca-tool-${tool.id}`;
    const tone = tool.valid ? GRAPH_TONE.active : GRAPH_TONE.warn;
    nodes.push(canvasNode({
      id,
      kind: "artifact",
      title: tool.name,
      statusLabel: humanizeToken(tool.status || "tool"),
      preview: tool.summary || "read-only diagnostic call",
      accent: tone,
      meta: compact([`#${index + 1}`, ...tool.citationIds.slice(0, 1)]),
      position: { x: 310, y: 40 + index * 112 },
      artifactKey: "tool_trajectory",
    }));
    edges.push(canvasEdge(`rca-investigation-${id}`, "rca-investigation", id, tone, true));
  });

  input.candidates.slice(0, 6).forEach((candidate, index) => {
    const id = `rca-candidate-${candidate.id}`;
    const confidence = typeof candidate.confidence === "number" ? `${Math.round(candidate.confidence * 100)}%` : "unscored";
    const tone = candidate.rank === 1 ? GRAPH_TONE.success : candidate.rank <= 3 ? GRAPH_TONE.active : GRAPH_TONE.info;
    nodes.push(canvasNode({
      id,
      kind: "artifact",
      title: candidate.cause,
      statusLabel: `Rank ${candidate.rank}`,
      preview: `${confidence} confidence${candidate.support.length ? ` / ${candidate.support.slice(0, 2).join(", ")}` : ""}`,
      accent: tone,
      meta: compact(candidate.citationIds.slice(0, 2)),
      position: { x: 650, y: 78 + index * 126 },
      artifactKey: "investigation_report",
    }));
    const linkedTools = input.tools.filter((tool) =>
      tool.citationIds.some((citationId) => candidate.citationIds.includes(citationId)) ||
      candidate.support.some((support) => tool.name.toLowerCase().includes(support.toLowerCase())),
    );
    const sources = linkedTools.length > 0 ? linkedTools : input.tools.slice(0, 1);
    sources.forEach((tool) => {
      edges.push(canvasEdge(`rca-tool-${tool.id}-${id}`, `rca-tool-${tool.id}`, id, tone, candidate.rank <= 3));
    });
    if (sources.length === 0) {
      edges.push(canvasEdge(`rca-investigation-${id}`, "rca-investigation", id, tone, candidate.rank <= 3));
    }
  });

  input.blockers.slice(0, 5).forEach((blocker, index) => {
    const id = `rca-blocker-${blocker.id}`;
    const tone = blocker.severity === "danger" ? GRAPH_TONE.danger : GRAPH_TONE.warn;
    nodes.push(canvasNode({
      id,
      kind: "artifact",
      title: blocker.label,
      statusLabel: humanizeToken(blocker.source),
      preview: blocker.detail,
      accent: tone,
      meta: [],
      position: { x: 1000, y: 80 + index * 122 },
      artifactKey: "evaluation",
    }));
    const candidate = input.candidates[index] ?? input.candidates[0];
    edges.push(canvasEdge(`rca-blocker-${index}`, candidate ? `rca-candidate-${candidate.id}` : "rca-investigation", id, tone, true));
  });

  input.citations.slice(0, 8).forEach((citation, index) => {
    const id = `rca-citation-${citation.id}`;
    nodes.push(canvasNode({
      id,
      kind: "merkle",
      title: citation.label,
      statusLabel: "Citation",
      preview: citation.detail,
      accent: GRAPH_TONE.purple,
      meta: compact([citation.id]),
      position: { x: 1300, y: 50 + index * 104 },
      artifactKey: "investigation_report",
    }));
    const candidate = input.candidates.find((item) => item.citationIds.includes(citation.id)) ?? input.candidates[0];
    const source = candidate ? `rca-candidate-${candidate.id}` : input.blockers[0] ? `rca-blocker-${input.blockers[0].id}` : "rca-investigation";
    edges.push(canvasEdge(`${source}-${id}`, source, id, GRAPH_TONE.purple, true));
  });

  return { nodes, edges };
}

export function buildRethSignalGraph(signal: Record<string, any> | null | undefined): CanvasGraph {
  if (!signal || signal.signal_type !== "reth_node") return { nodes: [], edges: [] };

  const service = String(signal.service ?? signal.node?.name ?? "reth node");
  const executionTone = Number(signal.execution?.peer_count ?? 0) <= Number(signal.execution?.min_peer_count ?? -1) ? GRAPH_TONE.warn : GRAPH_TONE.success;
  const storageTone = Number(signal.storage?.disk_used_pct ?? 0) >= 90 ? GRAPH_TONE.danger : GRAPH_TONE.success;
  const consensusTone = signal.consensus?.engine_api_reachable === false ? GRAPH_TONE.danger : GRAPH_TONE.success;
  const rpcTone = signal.rpc?.http_reachable === false ? GRAPH_TONE.danger : GRAPH_TONE.info;

  const nodes = [
    canvasNode({
      id: "reth-service",
      kind: "kubernetes",
      title: service,
      statusLabel: String(signal.environment ?? "environment"),
      preview: `${signal.node?.client_version ?? signal.node?.network ?? "reth"} / ${signal.node?.deployment_mode ?? "node"}`,
      accent: GRAPH_TONE.info,
      meta: compact([signal.node?.role, signal.related_context?.kurtosis_enclave]),
      position: { x: 40, y: 240 },
      artifactKey: "input_signal",
    }),
    canvasNode({
      id: "reth-execution",
      kind: "kubernetes",
      title: "Execution",
      statusLabel: signal.execution?.syncing ? "Syncing" : "Head",
      preview: `head ${signal.execution?.head_block ?? "?"} / lag ${signal.execution?.block_lag ?? "?"}`,
      accent: executionTone,
      meta: compact([`peers:${signal.execution?.peer_count ?? "?"}`, `min:${signal.execution?.min_peer_count ?? "?"}`]),
      position: { x: 330, y: 90 },
      artifactKey: "input_signal",
    }),
    canvasNode({
      id: "reth-consensus",
      kind: "kubernetes",
      title: "Consensus",
      statusLabel: String(signal.consensus?.consensus_client ?? signal.consensus?.client_kind ?? "consensus"),
      preview: signal.consensus?.engine_api_reachable === false ? "Engine API unreachable" : "Engine API reachable",
      accent: consensusTone,
      meta: compact([signal.consensus?.client_kind, signal.consensus?.forkchoice_updates_recent ? "forkchoice recent" : undefined]),
      position: { x: 330, y: 250 },
      artifactKey: "input_signal",
    }),
    canvasNode({
      id: "reth-storage",
      kind: "kubernetes",
      title: "Storage",
      statusLabel: signal.storage?.disk_used_pct == null ? "Unknown" : `${signal.storage.disk_used_pct}% used`,
      preview: String(signal.storage?.diagnostic_source ?? signal.storage?.snapshot_mode ?? "storage"),
      accent: storageTone,
      meta: compact([signal.storage?.snapshot_mode, signal.storage?.data_dir_free_bytes != null ? `${signal.storage.data_dir_free_bytes} free` : undefined]),
      position: { x: 630, y: 170 },
      artifactKey: "input_signal",
    }),
    canvasNode({
      id: "reth-rpc",
      kind: "kubernetes",
      title: "RPC",
      statusLabel: signal.rpc?.http_reachable === false ? "Unreachable" : "Reachable",
      preview: `error rate ${signal.rpc?.error_rate ?? "?"} / latency ${signal.rpc?.latency_ms ?? "?"}`,
      accent: rpcTone,
      meta: compact([signal.rpc?.publicly_exposed ? "public" : "internal", signal.resource_attributes?.["mesh.node.rpc_url"]]),
      position: { x: 930, y: 240 },
      artifactKey: "input_signal",
    }),
  ];

  const edges = [
    canvasEdge("reth-service-execution", "reth-service", "reth-execution", executionTone),
    canvasEdge("reth-service-consensus", "reth-service", "reth-consensus", consensusTone),
    canvasEdge("reth-execution-storage", "reth-execution", "reth-storage", storageTone, storageTone === GRAPH_TONE.danger),
    canvasEdge("reth-consensus-rpc", "reth-consensus", "reth-rpc", rpcTone, rpcTone === GRAPH_TONE.danger),
  ];

  return { nodes, edges };
}

export function buildKubernetesGraph(signal: Record<string, any> | null | undefined): CanvasGraph {
  if (!isKubernetesSignal(signal)) return { nodes: [], edges: [] };

  const nodes: RunGraphNode[] = [];
  const edges: Edge[] = [];
  const deploymentTone = kubernetesTone(signal.deployment?.rollout_status);

  nodes.push(canvasNode({
    id: "cluster",
    kind: "kubernetes",
    title: String(signal.cluster ?? "cluster"),
    statusLabel: String(signal.environment ?? "cluster"),
    preview: `${signal.service ?? "service"} in ${signal.namespace ?? "default"}`,
    accent: GRAPH_TONE.info,
    meta: compact([signal.signal_type, signal.observed_at]),
    position: { x: 40, y: 180 },
    artifactKey: "input_signal",
  }));

  nodes.push(canvasNode({
    id: "namespace",
    kind: "kubernetes",
    title: String(signal.namespace ?? "default"),
    statusLabel: "Namespace",
    preview: `${signal.service ?? "service"} workload`,
    accent: GRAPH_TONE.active,
    meta: compact([`service:${signal.service ?? "unknown"}`]),
    position: { x: 290, y: 180 },
    artifactKey: "input_signal",
  }));

  nodes.push(canvasNode({
    id: "deployment",
    kind: "kubernetes",
    title: String(signal.deployment?.name ?? signal.service ?? "deployment"),
    statusLabel: humanizeToken(String(signal.deployment?.rollout_status ?? "unknown")),
    preview: `${signal.deployment?.available_replicas ?? 0}/${signal.deployment?.desired_replicas ?? 0} replicas available`,
    accent: deploymentTone,
    meta: compact([
      `rev:${signal.deployment?.revision ?? "?"}`,
      signal.deployment?.image ? truncateInline(String(signal.deployment.image), 26) : undefined,
    ]),
    position: { x: 560, y: 180 },
    artifactKey: "input_signal",
  }));

  edges.push(canvasEdge("cluster-namespace", "cluster", "namespace", GRAPH_TONE.info));
  edges.push(canvasEdge("namespace-deployment", "namespace", "deployment", deploymentTone));

  (signal.pods ?? []).slice(0, 6).forEach((pod: Record<string, any>, index: number) => {
    const tone = pod.ready ? GRAPH_TONE.success : GRAPH_TONE.danger;
    const podId = `pod-${index}`;
    nodes.push(canvasNode({
      id: podId,
      kind: "kubernetes",
      title: String(pod.name ?? `pod-${index + 1}`),
      statusLabel: pod.ready ? "Ready" : String(pod.container_status ?? pod.phase ?? "Unready"),
      preview: `${pod.phase ?? "Unknown"} • ${pod.restarts ?? 0} restarts`,
      accent: tone,
      meta: compact([
        pod.last_state_reason ? String(pod.last_state_reason) : undefined,
        pod.container_status ? String(pod.container_status) : undefined,
      ]),
      position: { x: 880, y: 60 + index * 116 },
      artifactKey: "input_signal",
    }));
    edges.push(canvasEdge(`deployment-${podId}`, "deployment", podId, tone));
  });

  (signal.events ?? []).slice(0, 4).forEach((event: Record<string, any>, index: number) => {
    const tone = String(event.type ?? "").toLowerCase() === "warning" ? GRAPH_TONE.warn : GRAPH_TONE.info;
    const eventId = `cluster-event-${index}`;
    nodes.push(canvasNode({
      id: eventId,
      kind: "kubernetes",
      title: String(event.reason ?? `Event ${index + 1}`),
      statusLabel: String(event.type ?? "Event"),
      preview: truncateInline(String(event.message ?? "No message"), 64),
      accent: tone,
      meta: compact([event.count != null ? `count:${event.count}` : undefined]),
      position: { x: 1170, y: 110 + index * 116 },
      artifactKey: "input_signal",
    }));
    edges.push(canvasEdge(`deployment-${eventId}`, "deployment", eventId, tone, true));
  });

  return { nodes, edges };
}

export function buildMerkleGraph(
  snapshot: { root_hash: string; leaf_count: number; event_ids: string[] } | null | undefined,
  proof: { event_id: string; leaf_hash: string; root_hash: string; proof: Array<{ position: string; hash: string }>; valid: boolean } | null | undefined,
): CanvasGraph {
  if (!snapshot?.root_hash) return { nodes: [], edges: [] };

  const nodes: RunGraphNode[] = [];
  const edges: Edge[] = [];
  const centerX = 560;

  nodes.push(canvasNode({
    id: "merkle-root",
    kind: "merkle",
    title: "Merkle Root",
    statusLabel: proof?.valid ? "Verified" : "Snapshot",
    preview: snapshot.root_hash,
    accent: proof?.valid ? GRAPH_TONE.success : GRAPH_TONE.info,
    meta: compact([`${snapshot.leaf_count} leaves`]),
    position: { x: centerX, y: 20 },
    eventId: proof?.event_id,
  }));

  nodes.push(canvasNode({
    id: "merkle-snapshot",
    kind: "merkle",
    title: "Snapshot",
    statusLabel: "Ledger",
    preview: `${snapshot.event_ids.length} event ids tracked`,
    accent: GRAPH_TONE.active,
    meta: compact([snapshot.event_ids[0], snapshot.event_ids[snapshot.event_ids.length - 1]]),
    position: { x: 180, y: 20 },
    eventId: proof?.event_id,
  }));

  edges.push(canvasEdge("merkle-snapshot-root", "merkle-snapshot", "merkle-root", GRAPH_TONE.active));

  let previousId = "merkle-root";
  proof?.proof.forEach((step, index) => {
    const stepId = `merkle-step-${index}`;
    const siblingId = `merkle-sibling-${index}`;
    const tone = step.position === "left" ? GRAPH_TONE.info : GRAPH_TONE.warn;
    const y = 150 + index * 132;

    nodes.push(canvasNode({
      id: stepId,
      kind: "merkle",
      title: `Proof Step ${index + 1}`,
      statusLabel: "Branch",
      preview: `combine ${step.position} sibling`,
      accent: GRAPH_TONE.active,
      meta: compact([proof?.event_id ?? undefined]),
      position: { x: centerX, y },
      eventId: proof?.event_id,
    }));
    nodes.push(canvasNode({
      id: siblingId,
      kind: "merkle",
      title: `Sibling ${index + 1}`,
      statusLabel: humanizeToken(step.position),
      preview: step.hash,
      accent: tone,
      meta: [],
      position: { x: step.position === "left" ? centerX - 280 : centerX + 280, y },
      eventId: proof?.event_id,
    }));

    edges.push(canvasEdge(`${previousId}-${stepId}`, previousId, stepId, GRAPH_TONE.active));
    edges.push(canvasEdge(`${siblingId}-${stepId}`, siblingId, stepId, tone, true));
    previousId = stepId;
  });

  if (proof?.leaf_hash) {
    nodes.push(canvasNode({
      id: "merkle-leaf",
      kind: "merkle",
      title: "Selected Leaf",
      statusLabel: proof.event_id,
      preview: proof.leaf_hash,
      accent: GRAPH_TONE.success,
      meta: compact([proof.event_id]),
      position: { x: centerX, y: 170 + (proof.proof.length + 1) * 132 },
      eventId: proof.event_id,
    }));
    edges.push(canvasEdge(`${previousId}-merkle-leaf`, previousId, "merkle-leaf", GRAPH_TONE.success));
  }

  return { nodes, edges };
}

export function buildArtifactGraph(run: { artifacts: Record<string, any>; stage: string; status: string } | null | undefined): CanvasGraph {
  if (!run) return { nodes: [], edges: [] };

  const orderedArtifacts = [
    ["input_signal", "Input Signal", GRAPH_TONE.info],
    ["integration_readiness", "Readiness", GRAPH_TONE.active],
    ["normalized_event", "Normalized Event", GRAPH_TONE.purple],
    ["trigger", "Trigger", GRAPH_TONE.info],
    ["investigation_report", "Investigation", GRAPH_TONE.active],
    ["tool_trajectory", "Tool Trajectory", GRAPH_TONE.active],
    ["decision", "Decision", GRAPH_TONE.info],
    ["evaluation", "Evaluation", GRAPH_TONE.warn],
    ["task_trace", "Task Trace", GRAPH_TONE.warn],
    ["trajectory_score", "Trajectory Score", GRAPH_TONE.warn],
    ["verifier_output", "Verifier Output", GRAPH_TONE.warn],
    ["phoenix_spans", "Phoenix Spans", GRAPH_TONE.warn],
    ["hermes_explanation", "Hermes Explanation", GRAPH_TONE.functionBlue],
    ["execution", "Execution", GRAPH_TONE.active],
    ["goose_review", "Goose Review", GRAPH_TONE.cyan],
    ["hermes_review", "Hermes Review", GRAPH_TONE.functionBlue],
    ["feedback", "Feedback", GRAPH_TONE.success],
  ] as const;

  const nodes: RunGraphNode[] = [];
  const edges: Edge[] = [];
  let previousId: string | null = null;

  orderedArtifacts.forEach(([key, label, accent], index) => {
    const artifact = run.artifacts?.[key];
    if (!artifact) return;

    const nodeId = `artifact-${key}`;
    nodes.push(canvasNode({
      id: nodeId,
      kind: "artifact",
      title: label,
      statusLabel: artifact.status ? humanizeToken(String(artifact.status)) : humanizeToken(key),
      preview: summarizeArtifact(artifact),
      accent,
      meta: compact([
        artifact.decision_type ? humanizeToken(String(artifact.decision_type)) : undefined,
        artifact.final_recommendation ? humanizeToken(String(artifact.final_recommendation)) : undefined,
        artifact.executor ? humanizeToken(String(artifact.executor)) : undefined,
      ]),
      position: { x: 110 + index * 248, y: 170 + (index % 2 === 0 ? 0 : 78) },
      artifactKey: key,
    }));

    if (previousId) {
      edges.push(canvasEdge(`${previousId}-${nodeId}`, previousId, nodeId, accent));
    }
    previousId = nodeId;
  });

  if (nodes.length > 0) {
    nodes.unshift(canvasNode({
      id: "artifact-run",
      kind: "artifact",
      title: "Run Session",
      statusLabel: humanizeToken(run.stage),
      preview: `session ${humanizeToken(run.status)}`,
      accent: toneForStage(run.stage),
      meta: [],
      position: { x: 20, y: 170 },
      artifactKey: "run_session",
    }));
    edges.unshift(canvasEdge("artifact-run-first", "artifact-run", nodes[1].id, toneForStage(run.stage)));
  }

  return { nodes, edges };
}

export function buildUnifiedGraph(graphs: {
  flow: CanvasGraph;
  kubernetes: CanvasGraph;
  merkle: CanvasGraph;
  artifacts: CanvasGraph;
}): CanvasGraph {
  const flow = namespaceGraph(graphs.flow, "flow", { x: 0, y: 0 });
  const flowBounds = graphBounds(flow.nodes);

  const lowerY = flow.nodes.length > 0 ? flowBounds.maxY + 260 : 0;
  const kubernetes = namespaceGraph(graphs.kubernetes, "kubernetes", { x: 0, y: lowerY });
  const kubernetesBounds = graphBounds(kubernetes.nodes);

  const merkleX = kubernetes.nodes.length > 0 ? Math.max(kubernetesBounds.maxX + 360, 920) : 0;
  const merkle = namespaceGraph(graphs.merkle, "merkle", { x: merkleX, y: lowerY });
  const merkleBounds = graphBounds(merkle.nodes);

  const artifactY = Math.max(kubernetesBounds.maxY, merkleBounds.maxY, lowerY) + 260;
  const artifacts = namespaceGraph(graphs.artifacts, "artifacts", { x: 0, y: artifactY });

  const nodes = [
    ...unifiedSectionNodes([
      { graph: flow, id: "flow", title: "Run Flow", preview: "Stage-by-stage run event timeline", accent: GRAPH_TONE.info },
      { graph: kubernetes, id: "kubernetes", title: "Kubernetes", preview: "Cluster, namespace, deployment, pods, and events", accent: GRAPH_TONE.active },
      { graph: merkle, id: "merkle", title: "Merkle", preview: "Run log root, snapshot, and proof material", accent: GRAPH_TONE.purple },
      { graph: artifacts, id: "artifacts", title: "Artifacts", preview: "Input, readiness, trigger, decision, execution, and feedback records", accent: GRAPH_TONE.warn },
    ]),
    ...flow.nodes,
    ...kubernetes.nodes,
    ...merkle.nodes,
    ...artifacts.nodes,
  ];
  const edges = [
    ...flow.edges,
    ...kubernetes.edges,
    ...merkle.edges,
    ...artifacts.edges,
    ...unifiedContextEdges(flow, kubernetes, merkle, artifacts),
  ];

  return { nodes, edges };
}

export function toneForStage(stage: string): string {
  if (stage === "completed") return GRAPH_TONE.success;
  if (stage === "failed" || stage === "cancelled") return GRAPH_TONE.danger;
  if (stage === "awaiting_operator") return GRAPH_TONE.warn;
  if (stage === "executing") return GRAPH_TONE.active;
  if (
    stage === "evaluation_ready" ||
    stage === "decision_ready" ||
    stage === "scenario_analysis_ready" ||
    stage === "investigation_ready"
  ) return GRAPH_TONE.info;
  return GRAPH_TONE.neutral;
}

function summarizeEvent(event: RunEventRecord): string {
  const summaryEntries = event.summary ? Object.entries(event.summary) : [];
  for (const [, value] of summaryEntries) {
    const preview = stringifyValue(value);
    if (preview) return preview;
  }

  const payloadEntries = Object.entries(event.payload ?? {});
  for (const [, value] of payloadEntries) {
    const preview = stringifyValue(value);
    if (preview) return preview;
  }

  if (event.integration_name) return event.integration_name;
  if (event.artifact_key) return event.artifact_key;
  return event.recorded_at;
}

function stringifyValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.length === 0 ? "" : `${value.length} items`;
  if (typeof value === "object") return `${Object.keys(value as Record<string, unknown>).length} fields`;
  return "";
}

function canvasNode({
  id,
  kind,
  title,
  statusLabel,
  preview,
  accent,
  meta,
  position,
  eventId,
  sequence,
  eventType,
  stage,
  recordedAt,
  integrationName,
  artifactKey,
}: {
  id: string;
  kind: RunGraphNodeData["nodeKind"];
  title: string;
  statusLabel: string;
  preview: string;
  accent: string;
  meta: string[];
  position: { x: number; y: number };
  eventId?: string;
  sequence?: number;
  eventType?: string;
  stage?: string;
  recordedAt?: string;
  integrationName?: string | null;
  artifactKey?: string | null;
}, selected = false): RunGraphNode {
  return {
    id,
    type: "runEvent",
    selected,
    data: {
      nodeKind: kind,
      title,
      statusLabel,
      accent,
      meta,
      eventId: eventId ?? "",
      sequence: sequence ?? 0,
      eventType: eventType ?? title,
      stage: stage ?? statusLabel,
      recordedAt: recordedAt ?? "",
      preview,
      integrationName,
      artifactKey,
    },
    position,
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    style: { width: selected ? 220 : 204 },
  };
}

function canvasEdge(id: string, source: string, target: string, stroke: string, animated = false): Edge {
  return {
    id,
    source,
    target,
    type: "smoothstep",
    animated,
    style: {
      stroke,
      strokeWidth: 1.6,
      opacity: 0.82,
    },
  };
}

function namespaceGraph(graph: CanvasGraph, prefix: string, offset: { x: number; y: number }): CanvasGraph {
  return {
    nodes: graph.nodes.map((node) => ({
      ...node,
      id: `${prefix}:${node.id}`,
      position: {
        x: node.position.x + offset.x,
        y: node.position.y + offset.y,
      },
    })),
    edges: graph.edges.map((edge) => ({
      ...edge,
      id: `${prefix}:${edge.id}`,
      source: `${prefix}:${edge.source}`,
      target: `${prefix}:${edge.target}`,
    })),
  };
}

function unifiedSectionNodes(sections: Array<{
  graph: CanvasGraph;
  id: string;
  title: string;
  preview: string;
  accent: string;
}>): RunGraphNode[] {
  return sections
    .filter((section) => section.graph.nodes.length > 0)
    .map((section) => {
      const firstNode = section.graph.nodes[0];
      return canvasNode({
        id: `section:${section.id}`,
        kind: "section",
        title: section.title,
        statusLabel: "Unified Section",
        preview: section.preview,
        accent: section.accent,
        meta: compact([`${section.graph.nodes.length} nodes`]),
        position: { x: firstNode.position.x, y: firstNode.position.y - 150 },
      });
    });
}

function graphBounds(nodes: RunGraphNode[]): { maxX: number; maxY: number } {
  if (nodes.length === 0) return { maxX: 0, maxY: 0 };
  return nodes.reduce(
    (bounds, node) => ({
      maxX: Math.max(bounds.maxX, node.position.x + Number(node.style?.width ?? 204)),
      maxY: Math.max(bounds.maxY, node.position.y + 110),
    }),
    { maxX: 0, maxY: 0 },
  );
}

function unifiedContextEdges(
  flow: CanvasGraph,
  kubernetes: CanvasGraph,
  merkle: CanvasGraph,
  artifacts: CanvasGraph,
): Edge[] {
  const edges: Edge[] = [];
  const nodeIds = new Set([...flow.nodes, ...kubernetes.nodes, ...merkle.nodes, ...artifacts.nodes].map((node) => node.id));
  const artifactByKey = new Map<string, string>();

  artifacts.nodes.forEach((node) => {
    const key = node.data.artifactKey;
    if (typeof key === "string" && key) artifactByKey.set(key, node.id);
  });

  flow.nodes.forEach((node) => {
    const key = node.data.artifactKey;
    if (typeof key !== "string" || !key) return;
    const artifactNodeId = artifactByKey.get(key);
    if (!artifactNodeId) return;
    edges.push(canvasEdge(`unified:${node.id}-${artifactNodeId}`, node.id, artifactNodeId, String(node.data.accent || GRAPH_TONE.info), true));
  });

  const inputSignalNodeId = artifactByKey.get("input_signal");
  if (inputSignalNodeId && nodeIds.has("kubernetes:cluster")) {
    edges.push(canvasEdge("unified:input-signal-kubernetes", inputSignalNodeId, "kubernetes:cluster", GRAPH_TONE.info, true));
  }

  const executionNodeId = artifactByKey.get("execution");
  if (executionNodeId && nodeIds.has("merkle:merkle-root")) {
    edges.push(canvasEdge("unified:execution-merkle-root", executionNodeId, "merkle:merkle-root", GRAPH_TONE.active, true));
  } else if (flow.nodes.length > 0 && nodeIds.has("merkle:merkle-root")) {
    edges.push(canvasEdge("unified:flow-merkle-root", flow.nodes[flow.nodes.length - 1].id, "merkle:merkle-root", GRAPH_TONE.active, true));
  }

  return edges;
}

function kubernetesTone(rolloutStatus?: string): string {
  if (rolloutStatus === "healthy") return GRAPH_TONE.success;
  if (rolloutStatus === "degraded" || rolloutStatus === "failed") return GRAPH_TONE.danger;
  return GRAPH_TONE.info;
}

function isKubernetesSignal(signal: Record<string, any> | null | undefined): signal is Record<string, any> {
  return Boolean(signal && signal.signal_type === "kubernetes_deployment_issue" && signal.deployment);
}

function summarizeArtifact(artifact: Record<string, any>): string {
  const keys = ["summary", "decision_type", "final_recommendation", "status", "outcome"];
  for (const key of keys) {
    const value = artifact?.[key];
    const preview = stringifyValue(value);
    if (preview) return preview;
  }
  return `${Object.keys(artifact ?? {}).length} fields`;
}

function compact(values: Array<string | undefined>): string[] {
  return values.filter((value): value is string => Boolean(value && value.trim()));
}

function truncateInline(value: string, max = 36): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1)}…`;
}

function humanizeToken(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function toneForSeverity(severity: string): string {
  if (severity === "danger") return GRAPH_TONE.danger;
  if (severity === "warning") return GRAPH_TONE.warn;
  if (severity === "success") return GRAPH_TONE.success;
  return GRAPH_TONE.info;
}
