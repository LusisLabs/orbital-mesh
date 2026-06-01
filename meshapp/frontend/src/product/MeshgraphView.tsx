"use client";

import {
  AlertTriangle,
  Box,
  Boxes,
  Braces,
  CheckCircle2,
  CircleDot,
  Cpu,
  Database,
  GitBranch,
  Layers,
  LocateFixed,
  Maximize2,
  Network,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Workflow,
  XCircle,
} from "lucide-react";
import { type PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  type DashboardPayload,
  type LoadState,
  loadStateFromError,
  productApi,
} from "./api";

type MeshgraphKind =
  | "root"
  | "domain"
  | "health"
  | "readiness"
  | "policy"
  | "watcher"
  | "approval"
  | "kill_switch"
  | "infra"
  | "chaos_profile"
  | "chaos_run"
  | "hardened_profile"
  | "hardened_catalog"
  | "run"
  | "evidence";

export type MeshgraphNode = {
  id: string;
  label: string;
  kind: MeshgraphKind;
  group: string;
  state: "ready" | "blocked" | "degraded" | "running" | "unknown";
  detail: string;
  sourcePath: string;
  payload: Record<string, any>;
  x: number;
  y: number;
  radius: number;
  weight: number;
};

export type MeshgraphEdge = {
  id: string;
  source: string;
  target: string;
  kind: string;
  strength: number;
};

export type MeshgraphModel = {
  schemaVersion: "mesh.product.meshgraph.v1";
  generatedAt: string;
  nodes: MeshgraphNode[];
  edges: MeshgraphEdge[];
  stats: {
    nodeCount: number;
    edgeCount: number;
    infraNodes: number;
    chaosProfiles: number;
    hardenedCatalogEntries: number;
    runCount: number;
    blockedCount: number;
  };
  sources: string[];
  errors: string[];
};

type MeshgraphPayload = {
  health?: Record<string, any>;
  readiness?: Record<string, any>;
  approvals?: Record<string, any>;
  killSwitch?: Record<string, any>;
  watchers?: Record<string, any>;
  graphStatus?: Record<string, any>;
  graphSnapshot?: Record<string, any>;
  runs?: { runs?: Array<Record<string, any>> };
  recursiveChaosProfiles?: Record<string, any>;
  hardenedProfiles?: Record<string, any>;
  hardenedCatalog?: Record<string, any>;
  errors?: string[];
};

type GraphTransform = { x: number; y: number; scale: number };

const GROUP_FILTERS = [
  { key: "all", label: "All" },
  { key: "infra", label: "Infra" },
  { key: "chaos", label: "Chaos" },
  { key: "hardened", label: "Arena" },
  { key: "runs", label: "Runs" },
  { key: "control", label: "Control" },
];

const NODE_COLORS: Record<MeshgraphNode["state"], string> = {
  ready: "#84c7b2",
  blocked: "#df9f74",
  degraded: "#c4a85f",
  running: "#82a9c9",
  unknown: "#9ca3a5",
};

const KIND_COLORS: Partial<Record<MeshgraphKind, string>> = {
  root: "#f2f1e8",
  domain: "#d8d2bf",
  infra: "#78a6bf",
  chaos_profile: "#9fc7a6",
  chaos_run: "#d9b36f",
  hardened_profile: "#c0b58d",
  hardened_catalog: "#9caca6",
  run: "#82a9c9",
  evidence: "#b3a0c6",
};

export function buildMeshgraphModel(dashboard: DashboardPayload, payload: MeshgraphPayload): MeshgraphModel {
  const nodes = new Map<string, MeshgraphNode>();
  const edges = new Map<string, MeshgraphEdge>();
  const errors = payload.errors?.filter(Boolean) || [];

  function addNode(node: Omit<MeshgraphNode, "x" | "y" | "radius" | "weight"> & { weight?: number }) {
    if (nodes.has(node.id)) return;
    nodes.set(node.id, {
      ...node,
      x: 0,
      y: 0,
      radius: radiusForKind(node.kind),
      weight: node.weight ?? weightForKind(node.kind),
    });
  }

  function addEdge(source: string, target: string, kind: string, strength = 1) {
    if (!nodes.has(source) || !nodes.has(target)) return;
    const id = `${source}->${target}:${kind}`;
    if (!edges.has(id)) edges.set(id, { id, source, target, kind, strength });
  }

  addNode({
    id: "mesh",
    label: "Mesh",
    kind: "root",
    group: "control",
    state: payload.health?.status === "ok" ? "ready" : "degraded",
    detail: "Whole-system control graph assembled from live Mesh read models.",
    sourcePath: "meshgraph.client",
    payload: { scope: dashboard.scope, health: payload.health },
    weight: 3,
  });

  const domains = [
    ["domain:control", "Control Plane", "control", "Runtime API, readiness, policy, approvals."],
    ["domain:infra", "Infra Graph", "infra", "Kubernetes topology snapshot and infrastructure relationships."],
    ["domain:chaos", "Recursive Chaos", "chaos", "Chaos arena profiles, runs, sealed packets, and feedback gates."],
    ["domain:hardened", "Build Arena", "hardened", "Hardened image, chart, and profile catalog."],
    ["domain:runs", "Evidence Runs", "runs", "Run sessions, stages, Merkle state, and evidence entry points."],
    ["domain:operators", "Operators", "control", "Session, team, role, and approval boundary."],
  ] as const;
  domains.forEach(([id, label, group, detail]) => {
    addNode({ id, label, kind: "domain", group, state: "ready", detail, sourcePath: "meshgraph.domain", payload: {} });
    addEdge("mesh", id, "owns", 1.5);
  });

  addNode({
    id: "health",
    label: "Health",
    kind: "health",
    group: "control",
    state: payload.health?.status === "ok" ? "ready" : "degraded",
    detail: `Commit ${payload.health?.commit || "unknown"} / ${payload.health?.version || "version unavailable"}`,
    sourcePath: "/api/health",
    payload: payload.health || {},
  });
  addEdge("domain:control", "health", "reports");

  const readinessBlockers = asArray(payload.readiness?.blockers);
  addNode({
    id: "readiness",
    label: "Readiness",
    kind: "readiness",
    group: "control",
    state: readinessBlockers.length ? "blocked" : "ready",
    detail: readinessBlockers.length ? `${readinessBlockers.length} blocker(s)` : "No top-level readiness blockers reported.",
    sourcePath: "/api/readiness",
    payload: payload.readiness || {},
  });
  addEdge("domain:control", "readiness", "reports");

  addNode({
    id: "policy:kill-switch",
    label: "Kill Switch",
    kind: "kill_switch",
    group: "control",
    state: payload.killSwitch?.live_execution_enabled ? "running" : "ready",
    detail: payload.killSwitch?.live_execution_enabled ? "Live execution enabled by policy." : "Live execution disabled or approval gated.",
    sourcePath: "/api/kill-switch",
    payload: payload.killSwitch || {},
  });
  addEdge("domain:control", "policy:kill-switch", "gates");

  addNode({
    id: "approvals",
    label: "Approvals",
    kind: "approval",
    group: "control",
    state: Number(payload.approvals?.pending_count || 0) > 0 ? "running" : "ready",
    detail: `${payload.approvals?.pending_count || 0} pending / ${payload.approvals?.blocked_count || 0} blocked`,
    sourcePath: "/api/approvals",
    payload: payload.approvals || {},
  });
  addEdge("domain:operators", "approvals", "reviews");

  const watcherRows = asArray(payload.watchers?.watchers);
  watcherRows.slice(0, 32).forEach((watcher, index) => {
    const id = `watcher:${safeId(watcher.name || watcher.id || index)}`;
    addNode({
      id,
      label: String(watcher.name || watcher.id || `watcher-${index + 1}`),
      kind: "watcher",
      group: "control",
      state: watcher.running ? "running" : "ready",
      detail: String(watcher.signal_source || watcher.status || "watcher read model"),
      sourcePath: "/api/watchers",
      payload: watcher,
    });
    addEdge("domain:control", id, "observes");
  });

  const graphSnapshot = payload.graphSnapshot || {};
  const infraNodes = asArray(graphSnapshot.nodes);
  const infraIdByRaw = new Map<string, string>();
  infraNodes.forEach((item, index) => {
    const rawId = String(item.id || item.key || item.node_id || `${item.kind || "node"}:${item.namespace || "_cluster"}:${item.name || index}`);
    const id = `infra:${safeId(rawId)}`;
    infraIdByRaw.set(rawId, id);
    addNode({
      id,
      label: String(item.name || item.id || item.key || `infra-${index + 1}`),
      kind: "infra",
      group: "infra",
      state: "ready",
      detail: `${item.kind || "resource"} ${item.namespace || "_cluster"}`,
      sourcePath: "/api/graph/snapshot",
      payload: item,
      weight: 0.76,
    });
    addEdge("domain:infra", id, "contains", 0.55);
  });
  asArray(graphSnapshot.edges).forEach((edge, index) => {
    const sourceRaw = String(edge.source || edge.from || edge.source_id || "");
    const targetRaw = String(edge.target || edge.to || edge.target_id || "");
    const source = infraIdByRaw.get(sourceRaw) || (nodes.has(`infra:${safeId(sourceRaw)}`) ? `infra:${safeId(sourceRaw)}` : "");
    const target = infraIdByRaw.get(targetRaw) || (nodes.has(`infra:${safeId(targetRaw)}`) ? `infra:${safeId(targetRaw)}` : "");
    if (source && target) addEdge(source, target, String(edge.kind || edge.type || `infra-edge-${index}`), 0.35);
  });

  const chaosProfiles = asArray(payload.recursiveChaosProfiles?.profiles);
  chaosProfiles.forEach((profile, index) => {
    const profileId = String(profile.profile_id || `chaos-profile-${index + 1}`);
    const id = `chaos:profile:${safeId(profileId)}`;
    const blockers = asArray(profile.blockers);
    addNode({
      id,
      label: String(profile.display_name || profileId),
      kind: "chaos_profile",
      group: "chaos",
      state: blockers.length ? "blocked" : "ready",
      detail: `${profile.priority_phase || "phase unknown"} / ${profile.safety_class || profile.mutation_posture || "safety class unknown"}`,
      sourcePath: "/api/recursive-chaos/profiles",
      payload: profile,
      weight: profile.priority_phase === "p0" ? 1.25 : 0.9,
    });
    addEdge("domain:chaos", id, "profiles");
  });

  const runs = asArray(payload.runs?.runs).slice(0, 80);
  runs.forEach((run, index) => {
    const runId = String(run.run_id || run.id || `run-${index + 1}`);
    const scenario = String(run.scenario_key || "run");
    const isChaos = scenario.includes("recursive_chaos");
    const id = `${isChaos ? "chaos:run" : "run"}:${safeId(runId)}`;
    addNode({
      id,
      label: runId,
      kind: isChaos ? "chaos_run" : "run",
      group: isChaos ? "chaos" : "runs",
      state: stateFromStatus(run.status || run.stage),
      detail: `${scenario} / ${run.stage || run.status || "unknown"}`,
      sourcePath: `/api/runs/${runId}`,
      payload: run,
      weight: isChaos ? 1.1 : 0.85,
    });
    addEdge(isChaos ? "domain:chaos" : "domain:runs", id, "records");
  });

  const hardenedProfiles = asArray(payload.hardenedProfiles?.profiles);
  hardenedProfiles.forEach((profile, index) => {
    const profileId = String(profile.profile_id || `hardened-profile-${index + 1}`);
    const id = `hardened:profile:${safeId(profileId)}`;
    addNode({
      id,
      label: String(profile.display_name || profileId),
      kind: "hardened_profile",
      group: "hardened",
      state: asArray(profile.blockers).length ? "blocked" : "ready",
      detail: `${profile.lifecycle_state || "state unknown"} / ${profile.readiness_posture || "readiness unknown"}`,
      sourcePath: "/api/hardened-arena/profiles",
      payload: profile,
    });
    addEdge("domain:hardened", id, "profiles");
  });

  const catalogEntries = asArray(payload.hardenedCatalog?.entries);
  catalogEntries.forEach((entry, index) => {
    const entryId = String(entry.id || entry.image_ref || entry.name || entry.chart_ref || `catalog-${index + 1}`);
    const id = `hardened:catalog:${safeId(entryId)}:${index}`;
    addNode({
      id,
      label: String(entry.name || entry.image_ref || entry.chart_ref || entryId),
      kind: "hardened_catalog",
      group: "hardened",
      state: entry.claim_status === "blocked" ? "blocked" : "ready",
      detail: `${entry.kind || entry.type || "catalog"} / ${entry.registry || entry.source || "source unknown"}`,
      sourcePath: "/api/hardened-arena/catalog",
      payload: entry,
      weight: 0.62,
    });
    addEdge("domain:hardened", id, "catalogs", 0.35);
  });

  const model = materializeLayout(nodes, edges);
  const nodeRows = Array.from(model.nodes.values());
  const edgeRows = Array.from(model.edges.values());
  return {
    schemaVersion: "mesh.product.meshgraph.v1",
    generatedAt: new Date().toISOString(),
    nodes: nodeRows,
    edges: edgeRows,
    stats: {
      nodeCount: nodeRows.length,
      edgeCount: edgeRows.length,
      infraNodes: infraNodes.length,
      chaosProfiles: chaosProfiles.length,
      hardenedCatalogEntries: catalogEntries.length,
      runCount: runs.length,
      blockedCount: nodeRows.filter((node) => node.state === "blocked" || node.state === "degraded").length,
    },
    sources: [
      "/api/health",
      "/api/readiness",
      "/api/graph/snapshot",
      "/api/runs?summary=1",
      "/api/recursive-chaos/profiles",
      "/api/hardened-arena/profiles",
      "/api/hardened-arena/catalog",
    ],
    errors,
  };
}

export default function MeshgraphView({ dashboard }: { dashboard: DashboardPayload }) {
  const [payloadState, setPayloadState] = useState<LoadState<MeshgraphPayload>>({ state: "loading" });
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState("all");
  const [selectedId, setSelectedId] = useState("mesh");
  const [runDrillState, setRunDrillState] = useState<LoadState<Record<string, any>>>({ state: "empty", message: "Select a run node to load its detail graph." });
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function loadMeshgraph() {
      setPayloadState({ state: "loading" });
      const calls: Array<[keyof MeshgraphPayload, Promise<Record<string, any>>]> = [
        ["health", productApi.health()],
        ["readiness", productApi.readiness()],
        ["approvals", productApi.approvals()],
        ["killSwitch", productApi.killSwitch()],
        ["watchers", productApi.watchers()],
        ["graphStatus", productApi.graphStatus()],
        ["graphSnapshot", productApi.graphSnapshot()],
        ["runs", productApi.runsSummary()],
        ["recursiveChaosProfiles", productApi.recursiveChaosProfiles()],
        ["hardenedProfiles", productApi.hardenedArenaProfiles()],
        ["hardenedCatalog", productApi.hardenedArenaCatalog()],
      ];
      const settled = await Promise.allSettled(calls.map(([, promise]) => promise));
      if (cancelled) return;
      const nextPayload: MeshgraphPayload = { errors: [] };
      settled.forEach((result, index) => {
        const key = calls[index][0];
        if (result.status === "fulfilled") {
          nextPayload[key] = result.value as any;
        } else {
          nextPayload.errors?.push(`${String(key)}: ${result.reason instanceof Error ? result.reason.message : String(result.reason)}`);
        }
      });
      const fulfilledCount = settled.filter((item) => item.status === "fulfilled").length;
      setPayloadState(fulfilledCount ? { state: "ready", data: nextPayload } : { state: "error", message: nextPayload.errors?.join("; ") || "Meshgraph sources unavailable." });
    }
    loadMeshgraph().catch((error) => {
      if (!cancelled) setPayloadState(loadStateFromError(error));
    });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const model = useMemo(() => (
    payloadState.state === "ready" ? buildMeshgraphModel(dashboard, payloadState.data) : null
  ), [dashboard, payloadState]);

  const selectedNode = model?.nodes.find((node) => node.id === selectedId) || model?.nodes[0] || null;

  useEffect(() => {
    if (!model || !selectedNode) return;
    if (model.nodes.some((node) => node.id === selectedId)) return;
    setSelectedId(model.nodes[0]?.id || "mesh");
  }, [model, selectedId, selectedNode]);

  useEffect(() => {
    let cancelled = false;
    async function loadRunDrill(runId: string) {
      setRunDrillState({ state: "loading" });
      const [detail, evidence, timeline] = await Promise.allSettled([
        productApi.runDetail(runId),
        productApi.evidenceGraph(runId),
        productApi.timelineProof(runId),
      ]);
      if (cancelled) return;
      const data: Record<string, any> = {};
      const errors: string[] = [];
      if (detail.status === "fulfilled") data.detail = detail.value;
      else errors.push(`detail: ${detail.reason instanceof Error ? detail.reason.message : String(detail.reason)}`);
      if (evidence.status === "fulfilled") data.evidence_graph = evidence.value;
      else errors.push(`evidence_graph: ${evidence.reason instanceof Error ? evidence.reason.message : String(evidence.reason)}`);
      if (timeline.status === "fulfilled") data.timeline_proof = timeline.value;
      else errors.push(`timeline_proof: ${timeline.reason instanceof Error ? timeline.reason.message : String(timeline.reason)}`);
      data.errors = errors;
      setRunDrillState({ state: "ready", data });
    }
    const runId = selectedNode?.payload?.run_id || selectedNode?.payload?.id;
    if (selectedNode && ["run", "chaos_run"].includes(selectedNode.kind) && runId) {
      loadRunDrill(String(runId)).catch((error) => {
        if (!cancelled) setRunDrillState(loadStateFromError(error));
      });
    } else {
      setRunDrillState({ state: "empty", message: "Select a run node to load run detail, evidence graph, and timeline proof." });
    }
    return () => {
      cancelled = true;
    };
  }, [selectedNode?.id]);

  if (payloadState.state === "loading") {
    return <MeshgraphSkeleton />;
  }

  if (payloadState.state !== "ready" || !model) {
    return (
      <div className="content-stack">
        <div className="meshgraph-alert" role="alert">
          <AlertTriangle size={16} />
          <span>{payloadState.state === "error" || payloadState.state === "backend-unavailable" ? payloadState.message : "Meshgraph read models are unavailable."}</span>
          <button type="button" onClick={() => setReloadKey((key) => key + 1)}>Retry</button>
        </div>
      </div>
    );
  }

  return (
    <section className="meshgraph-shell" aria-label="Meshgraph">
      <div className="meshgraph-toolbar">
        <div>
          <span>mesh.product.meshgraph.v1</span>
          <strong>Canvas graph of Mesh runtime, infrastructure, chaos, profiles, catalogs, and proof surfaces.</strong>
        </div>
        <div className="meshgraph-actions">
          <label className="meshgraph-search">
            <Search size={14} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter nodes, payloads, runs" />
          </label>
          <button type="button" onClick={() => setReloadKey((key) => key + 1)} title="Refresh Meshgraph" aria-label="Refresh Meshgraph">
            <RefreshCw size={15} />
          </button>
        </div>
      </div>

      <div className="meshgraph-summary" aria-label="Meshgraph summary">
        <MetricTile icon={Network} label="Nodes" value={model.stats.nodeCount} detail={`${model.stats.edgeCount} edges`} />
        <MetricTile icon={GitBranch} label="Infra" value={model.stats.infraNodes} detail="live graph nodes" />
        <MetricTile icon={Workflow} label="Chaos" value={model.stats.chaosProfiles} detail="arena profiles" />
        <MetricTile icon={Boxes} label="Catalog" value={model.stats.hardenedCatalogEntries} detail="hardened entries" />
        <MetricTile icon={ShieldCheck} label="Blocked" value={model.stats.blockedCount} detail="gated surfaces" />
      </div>

      <div className="meshgraph-filter-row" aria-label="Meshgraph filters">
        {GROUP_FILTERS.map((item) => (
          <button key={item.key} type="button" className={group === item.key ? "active" : ""} onClick={() => setGroup(item.key)}>
            {item.label}
          </button>
        ))}
      </div>

      <div className="meshgraph-workspace">
        <MeshgraphCanvas
          model={model}
          query={query}
          group={group}
          selectedId={selectedNode?.id || selectedId}
          onSelect={setSelectedId}
        />
        <MeshgraphInspector node={selectedNode} runDrillState={runDrillState} errors={model.errors} />
      </div>
    </section>
  );
}

function MeshgraphCanvas({
  model,
  query,
  group,
  selectedId,
  onSelect,
}: {
  model: MeshgraphModel;
  query: string;
  group: string;
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 1, height: 1 });
  const [transform, setTransform] = useState<GraphTransform>({ x: 0, y: 0, scale: 0.86 });
  const dragRef = useRef<{ pointerId: number; lastX: number; lastY: number; moved: boolean } | null>(null);

  const visible = useMemo(() => filterGraph(model, query, group), [model, query, group]);
  const nodeById = useMemo(() => new Map(model.nodes.map((node) => [node.id, node])), [model.nodes]);

  useEffect(() => {
    const element = wrapRef.current;
    if (!element) return undefined;
    const observer = new ResizeObserver(([entry]) => {
      const box = entry.contentRect;
      setSize({ width: Math.max(1, box.width), height: Math.max(1, box.height) });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    const ratio = Math.max(window.devicePixelRatio || 1, 1);
    canvas.width = Math.floor(size.width * ratio);
    canvas.height = Math.floor(size.height * ratio);
    canvas.style.width = `${size.width}px`;
    canvas.style.height = `${size.height}px`;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    drawGraph(context, {
      width: size.width,
      height: size.height,
      transform,
      nodes: visible.nodes,
      edges: visible.edges,
      nodeById,
      selectedId,
    });
  }, [size, transform, visible, nodeById, selectedId]);

  function screenToWorld(clientX: number, clientY: number): { x: number; y: number } {
    const rect = canvasRef.current?.getBoundingClientRect();
    const x = clientX - (rect?.left || 0) - size.width / 2 - transform.x;
    const y = clientY - (rect?.top || 0) - size.height / 2 - transform.y;
    return { x: x / transform.scale, y: y / transform.scale };
  }

  function hitNode(clientX: number, clientY: number): MeshgraphNode | null {
    const point = screenToWorld(clientX, clientY);
    for (let index = visible.nodes.length - 1; index >= 0; index -= 1) {
      const node = visible.nodes[index];
      const distance = Math.hypot(point.x - node.x, point.y - node.y);
      if (distance <= node.radius + 6 / transform.scale) return node;
    }
    return null;
  }

  function onPointerDown(event: ReactPointerEvent<HTMLCanvasElement>) {
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { pointerId: event.pointerId, lastX: event.clientX, lastY: event.clientY, moved: false };
  }

  function onPointerMove(event: ReactPointerEvent<HTMLCanvasElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const dx = event.clientX - drag.lastX;
    const dy = event.clientY - drag.lastY;
    if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
    drag.lastX = event.clientX;
    drag.lastY = event.clientY;
    setTransform((current) => ({ ...current, x: current.x + dx, y: current.y + dy }));
  }

  function onPointerUp(event: ReactPointerEvent<HTMLCanvasElement>) {
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag || drag.pointerId !== event.pointerId || drag.moved) return;
    const node = hitNode(event.clientX, event.clientY);
    if (node) onSelect(node.id);
  }

  function onWheel(event: React.WheelEvent<HTMLCanvasElement>) {
    event.preventDefault();
    const nextScale = clamp(transform.scale * (event.deltaY > 0 ? 0.92 : 1.08), 0.28, 2.8);
    setTransform((current) => ({ ...current, scale: nextScale }));
  }

  return (
    <div className="meshgraph-canvas-panel" ref={wrapRef}>
      <canvas
        ref={canvasRef}
        role="img"
        aria-label="Interactive Meshgraph canvas"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onWheel={onWheel}
      />
      <div className="meshgraph-canvas-controls">
        <button type="button" onClick={() => setTransform({ x: 0, y: 0, scale: 0.86 })} title="Reset view" aria-label="Reset Meshgraph view">
          <LocateFixed size={14} />
        </button>
        <button type="button" onClick={() => setTransform((current) => ({ ...current, scale: clamp(current.scale * 1.18, 0.28, 2.8) }))} title="Zoom in" aria-label="Zoom in">
          <Maximize2 size={14} />
        </button>
        <button type="button" onClick={() => setTransform((current) => ({ ...current, scale: clamp(current.scale * 0.84, 0.28, 2.8) }))} title="Zoom out" aria-label="Zoom out">
          <SlidersHorizontal size={14} />
        </button>
      </div>
      <div className="meshgraph-canvas-status">
        <span>{visible.nodes.length} visible nodes</span>
        <span>{Math.round(transform.scale * 100)}%</span>
      </div>
    </div>
  );
}

function MeshgraphInspector({
  node,
  runDrillState,
  errors,
}: {
  node: MeshgraphNode | null;
  runDrillState: LoadState<Record<string, any>>;
  errors: string[];
}) {
  if (!node) {
    return (
      <aside className="meshgraph-inspector">
        <div className="empty-inline">Select a node to inspect its payload.</div>
      </aside>
    );
  }
  const Icon = iconForKind(node.kind);
  return (
    <aside className="meshgraph-inspector" aria-label="Meshgraph inspector">
      <div className="meshgraph-node-heading">
        <span className={`meshgraph-node-icon ${node.state}`}><Icon size={16} /></span>
        <div>
          <span>{node.kind.replaceAll("_", " ")}</span>
          <strong>{node.label}</strong>
        </div>
      </div>
      <div className="meshgraph-inspector-grid">
        <Field label="State" value={node.state} />
        <Field label="Group" value={node.group} />
        <Field label="Source" value={node.sourcePath} />
      </div>
      <p>{node.detail}</p>
      {errors.length ? (
        <div className="meshgraph-alert compact">
          <AlertTriangle size={14} />
          <span>{errors.slice(0, 2).join("; ")}</span>
        </div>
      ) : null}
      <JsonBlock title="Node Payload" value={node.payload} />
      {["run", "chaos_run"].includes(node.kind) ? <RunDrill state={runDrillState} /> : null}
    </aside>
  );
}

function RunDrill({ state }: { state: LoadState<Record<string, any>> }) {
  if (state.state === "loading") {
    return <div className="meshgraph-drill-loading">Loading run detail graph</div>;
  }
  if (state.state !== "ready") {
    return <div className="empty-inline">{state.state === "empty" ? state.message : "Run detail graph unavailable."}</div>;
  }
  return <JsonBlock title="Run Drilldown" value={state.data} />;
}

function MetricTile({ icon: Icon, label, value, detail }: { icon: any; label: string; value: number; detail: string }) {
  return (
    <div className="meshgraph-metric">
      <Icon size={16} />
      <span>{label}</span>
      <strong>{value.toLocaleString()}</strong>
      <small>{detail}</small>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function JsonBlock({ title, value }: { title: string; value: Record<string, any> }) {
  return (
    <details className="meshgraph-json" open={title === "Run Drilldown"}>
      <summary><Braces size={14} /> {title}</summary>
      <pre>{JSON.stringify(value, null, 2).slice(0, 16_000)}</pre>
    </details>
  );
}

function MeshgraphSkeleton() {
  return (
    <div className="meshgraph-shell">
      <div className="meshgraph-toolbar skeleton" />
      <div className="meshgraph-summary">
        {Array.from({ length: 5 }).map((_, index) => <div className="meshgraph-metric skeleton" key={index} />)}
      </div>
      <div className="meshgraph-workspace">
        <div className="meshgraph-canvas-panel skeleton" />
        <aside className="meshgraph-inspector skeleton" />
      </div>
    </div>
  );
}

function materializeLayout(nodes: Map<string, MeshgraphNode>, edges: Map<string, MeshgraphEdge>) {
  const domainOrder = ["domain:control", "domain:infra", "domain:chaos", "domain:hardened", "domain:runs", "domain:operators"];
  const domainCenters: Record<string, { x: number; y: number }> = {};
  const root = nodes.get("mesh");
  if (root) {
    root.x = 0;
    root.y = 0;
  }
  domainOrder.forEach((id, index) => {
    const node = nodes.get(id);
    if (!node) return;
    const angle = -Math.PI / 2 + (index * Math.PI * 2) / domainOrder.length;
    const center = { x: Math.cos(angle) * 390, y: Math.sin(angle) * 300 };
    node.x = center.x;
    node.y = center.y;
    domainCenters[node.group] = center;
  });

  const childGroups = new Map<string, MeshgraphNode[]>();
  Array.from(nodes.values()).forEach((node) => {
    if (node.kind === "root" || node.kind === "domain") return;
    const groupNodes = childGroups.get(node.group) || [];
    groupNodes.push(node);
    childGroups.set(node.group, groupNodes);
  });

  childGroups.forEach((groupNodes, groupKey) => {
    const center = domainCenters[groupKey] || { x: 0, y: 0 };
    const sorted = groupNodes.sort((a, b) => (b.weight - a.weight) || a.label.localeCompare(b.label));
    sorted.forEach((node, index) => {
      const ring = Math.floor(index / 28);
      const ringStart = ring * 28;
      const ringCount = Math.min(28, sorted.length - ringStart);
      const angle = -Math.PI / 2 + ((index - ringStart) * Math.PI * 2) / Math.max(ringCount, 1);
      const radius = 102 + ring * 72 + (node.kind === "hardened_catalog" ? 18 : 0);
      node.x = center.x + Math.cos(angle) * radius;
      node.y = center.y + Math.sin(angle) * radius;
    });
  });
  return { nodes, edges };
}

function drawGraph(
  context: CanvasRenderingContext2D,
  options: {
    width: number;
    height: number;
    transform: GraphTransform;
    nodes: MeshgraphNode[];
    edges: MeshgraphEdge[];
    nodeById: Map<string, MeshgraphNode>;
    selectedId: string;
  },
) {
  const { width, height, transform, nodes, edges, nodeById, selectedId } = options;
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#080909";
  context.fillRect(0, 0, width, height);
  context.save();
  context.translate(width / 2 + transform.x, height / 2 + transform.y);
  context.scale(transform.scale, transform.scale);

  context.lineCap = "round";
  edges.forEach((edge) => {
    const source = nodeById.get(edge.source);
    const target = nodeById.get(edge.target);
    if (!source || !target) return;
    context.beginPath();
    context.moveTo(source.x, source.y);
    const midX = (source.x + target.x) / 2;
    const midY = (source.y + target.y) / 2;
    context.quadraticCurveTo(midX * 1.02, midY * 1.02, target.x, target.y);
    context.strokeStyle = edge.strength > 1 ? "rgba(189, 183, 156, 0.35)" : "rgba(126, 136, 132, 0.18)";
    context.lineWidth = Math.max(0.9, edge.strength) / transform.scale;
    context.stroke();
  });

  nodes.forEach((node) => {
    const selected = node.id === selectedId;
    const base = KIND_COLORS[node.kind] || NODE_COLORS[node.state];
    context.beginPath();
    context.arc(node.x, node.y, node.radius + (selected ? 5 : 0), 0, Math.PI * 2);
    context.fillStyle = selected ? "rgba(242, 241, 232, 0.11)" : "rgba(255, 255, 255, 0.025)";
    context.fill();
    context.lineWidth = selected ? 2.2 / transform.scale : 1.1 / transform.scale;
    context.strokeStyle = selected ? "#f2f1e8" : base;
    context.stroke();

    context.beginPath();
    context.arc(node.x, node.y, Math.max(3, node.radius * 0.38), 0, Math.PI * 2);
    context.fillStyle = base;
    context.fill();

    if (node.kind === "domain" || node.kind === "root" || selected || transform.scale > 0.72) {
      context.font = `${selected ? 700 : 600} ${Math.max(10, 11 / transform.scale)}px ui-sans-serif, system-ui`;
      context.fillStyle = selected ? "#f5f3ea" : "rgba(235, 232, 218, 0.78)";
      context.textAlign = "center";
      context.textBaseline = "top";
      const label = node.label.length > 28 ? `${node.label.slice(0, 25)}...` : node.label;
      context.fillText(label, node.x, node.y + node.radius + 7 / transform.scale);
    }
  });
  context.restore();
}

function filterGraph(model: MeshgraphModel, query: string, group: string): { nodes: MeshgraphNode[]; edges: MeshgraphEdge[] } {
  const lowerQuery = query.trim().toLowerCase();
  const nodes = model.nodes.filter((node) => {
    const groupMatches = group === "all" || node.group === group || (group === "runs" && node.kind.includes("run"));
    if (!groupMatches) return false;
    if (!lowerQuery) return true;
    return `${node.label} ${node.kind} ${node.group} ${node.detail} ${node.sourcePath}`.toLowerCase().includes(lowerQuery);
  });
  const ids = new Set(nodes.map((node) => node.id));
  const edges = model.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
  return { nodes, edges };
}

function iconForKind(kind: MeshgraphKind) {
  if (kind === "root") return Network;
  if (kind === "domain") return Layers;
  if (kind === "infra") return GitBranch;
  if (kind === "chaos_profile" || kind === "chaos_run") return Workflow;
  if (kind === "hardened_profile" || kind === "hardened_catalog") return Boxes;
  if (kind === "run" || kind === "evidence") return ActivityIcon;
  if (kind === "readiness") return CheckCircle2;
  if (kind === "kill_switch") return ShieldCheck;
  if (kind === "watcher") return CircleDot;
  if (kind === "health") return Cpu;
  if (kind === "approval") return SlidersHorizontal;
  if (kind === "policy") return ShieldCheck;
  return Box;
}

function ActivityIcon({ size }: { size: number }) {
  return <Database size={size} />;
}

function stateFromStatus(status: any): MeshgraphNode["state"] {
  const text = String(status || "").toLowerCase();
  if (["completed", "pass", "ready", "ok", "succeeded"].some((item) => text.includes(item))) return "ready";
  if (["running", "queued", "executing", "pending"].some((item) => text.includes(item))) return "running";
  if (["fail", "failed", "blocked", "error"].some((item) => text.includes(item))) return "blocked";
  if (text.includes("degraded") || text.includes("unavailable")) return "degraded";
  return "unknown";
}

function radiusForKind(kind: MeshgraphKind): number {
  if (kind === "root") return 36;
  if (kind === "domain") return 26;
  if (kind === "hardened_catalog") return 8;
  if (kind === "infra") return 9;
  return 13;
}

function weightForKind(kind: MeshgraphKind): number {
  if (kind === "root") return 3;
  if (kind === "domain") return 2;
  if (kind === "hardened_catalog") return 0.58;
  if (kind === "infra") return 0.7;
  return 1;
}

function asArray(value: any): any[] {
  return Array.isArray(value) ? value : [];
}

function safeId(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9_.:-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 90) || "unknown";
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}
