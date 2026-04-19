import { Position, type Edge, type Node } from "@xyflow/react";

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
    accent: "#65a7ff",
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
    accent: "#41d6b1",
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

  edges.push(canvasEdge("cluster-namespace", "cluster", "namespace", "#65a7ff"));
  edges.push(canvasEdge("namespace-deployment", "namespace", "deployment", deploymentTone));

  (signal.pods ?? []).slice(0, 6).forEach((pod: Record<string, any>, index: number) => {
    const tone = pod.ready ? "#83d37d" : "#ff6b5f";
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
    const tone = String(event.type ?? "").toLowerCase() === "warning" ? "#f2b84b" : "#65a7ff";
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
    accent: proof?.valid ? "#83d37d" : "#65a7ff",
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
    accent: "#41d6b1",
    meta: compact([snapshot.event_ids[0], snapshot.event_ids[snapshot.event_ids.length - 1]]),
    position: { x: 180, y: 20 },
    eventId: proof?.event_id,
  }));

  edges.push(canvasEdge("merkle-snapshot-root", "merkle-snapshot", "merkle-root", "#41d6b1"));

  let previousId = "merkle-root";
  proof?.proof.forEach((step, index) => {
    const stepId = `merkle-step-${index}`;
    const siblingId = `merkle-sibling-${index}`;
    const tone = step.position === "left" ? "#65a7ff" : "#f2b84b";
    const y = 150 + index * 132;

    nodes.push(canvasNode({
      id: stepId,
      kind: "merkle",
      title: `Proof Step ${index + 1}`,
      statusLabel: "Branch",
      preview: `combine ${step.position} sibling`,
      accent: "#41d6b1",
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

    edges.push(canvasEdge(`${previousId}-${stepId}`, previousId, stepId, "#41d6b1"));
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
      accent: "#83d37d",
      meta: compact([proof.event_id]),
      position: { x: centerX, y: 170 + (proof.proof.length + 1) * 132 },
      eventId: proof.event_id,
    }));
    edges.push(canvasEdge(`${previousId}-merkle-leaf`, previousId, "merkle-leaf", "#83d37d"));
  }

  return { nodes, edges };
}

export function buildArtifactGraph(run: { artifacts: Record<string, any>; stage: string; status: string } | null | undefined): CanvasGraph {
  if (!run) return { nodes: [], edges: [] };

  const orderedArtifacts = [
    ["input_signal", "Input Signal", "#65a7ff"],
    ["integration_readiness", "Readiness", "#41d6b1"],
    ["normalized_event", "Normalized Event", "#8d8cff"],
    ["trigger", "Trigger", "#65a7ff"],
    ["decision", "Decision", "#65a7ff"],
    ["evaluation", "Evaluation", "#f2b84b"],
    ["promptfoo_artifact", "Promptfoo Artifact", "#f2b84b"],
    ["hermes_explanation", "Hermes Explanation", "#4aa8ff"],
    ["execution", "Execution", "#41d6b1"],
    ["goose_review", "Goose Review", "#57d5c8"],
    ["hermes_review", "Hermes Review", "#4aa8ff"],
    ["feedback", "Feedback", "#83d37d"],
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
      { graph: flow, id: "flow", title: "Run Flow", preview: "Stage-by-stage run event timeline", accent: "#65a7ff" },
      { graph: kubernetes, id: "kubernetes", title: "Kubernetes", preview: "Cluster, namespace, deployment, pods, and events", accent: "#41d6b1" },
      { graph: merkle, id: "merkle", title: "Merkle", preview: "Run log root, snapshot, and proof material", accent: "#8d8cff" },
      { graph: artifacts, id: "artifacts", title: "Artifacts", preview: "Input, readiness, trigger, decision, execution, and feedback records", accent: "#f2b84b" },
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
  if (stage === "completed") return "#83d37d";
  if (stage === "failed" || stage === "cancelled") return "#ff6b5f";
  if (stage === "awaiting_operator") return "#f2b84b";
  if (stage === "executing") return "#41d6b1";
  if (stage === "evaluation_ready" || stage === "decision_ready") return "#65a7ff";
  return "#a69f90";
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
}): RunGraphNode {
  return {
    id,
    type: "runEvent",
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
    style: { width: 204 },
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
    edges.push(canvasEdge(`unified:${node.id}-${artifactNodeId}`, node.id, artifactNodeId, String(node.data.accent || "#65a7ff"), true));
  });

  const inputSignalNodeId = artifactByKey.get("input_signal");
  if (inputSignalNodeId && nodeIds.has("kubernetes:cluster")) {
    edges.push(canvasEdge("unified:input-signal-kubernetes", inputSignalNodeId, "kubernetes:cluster", "#65a7ff", true));
  }

  const executionNodeId = artifactByKey.get("execution");
  if (executionNodeId && nodeIds.has("merkle:merkle-root")) {
    edges.push(canvasEdge("unified:execution-merkle-root", executionNodeId, "merkle:merkle-root", "#41d6b1", true));
  } else if (flow.nodes.length > 0 && nodeIds.has("merkle:merkle-root")) {
    edges.push(canvasEdge("unified:flow-merkle-root", flow.nodes[flow.nodes.length - 1].id, "merkle:merkle-root", "#41d6b1", true));
  }

  return edges;
}

function kubernetesTone(rolloutStatus?: string): string {
  if (rolloutStatus === "healthy") return "#83d37d";
  if (rolloutStatus === "degraded" || rolloutStatus === "failed") return "#ff6b5f";
  return "#65a7ff";
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
