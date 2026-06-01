import { normalizeLoopbackBaseUrl } from "./product/api";

import type {
  ApprovalQueuePacket,
  GoalRecord,
  ConnectorCertificationPacket,
  DarkharnessPilotPacket,
  DeliveryContextGraph,
  HealthSnapshot,
  IntegrationReadiness,
  EvidenceGraph,
  KillSwitchStatus,
  MerkleProof,
  MerkleSnapshot,
  PilotGoNoGoPacket,
  PolicySimulationResult,
  ScenarioAnalysis,
  ResearchCorpusIntelligence,
  ResearchSessionDetail,
  ResearchSessionRecord,
  RecursiveChaosProfilesResponse,
  RunDetail,
  RunExportPackage,
  RunSessionRecord,
  ScenarioRecord,
  BenchmarkRecord,
  ServiceAgentRecord,
  SimulationScenarioRecord,
  SystemSnapshot,
  TrustLadderEntry,
  VaultTreeEntry,
  WatcherStatus,
} from "./types";

const DEFAULT_API_BASE_URL = process.env.NEXT_PUBLIC_MESH_API_URL ?? "http://127.0.0.1:8787";
const DEFAULT_LOCAL_OPERATOR_ID = "local-operator";
const DEFAULT_LOCAL_OPERATOR_ROLES = "viewer,launcher,approver";
const LOCAL_OPERATOR_HOSTS = new Set(["localhost", "127.0.0.1", "::1"]);

export function resolveBaseUrl(): string {
  if (typeof window === "undefined") {
    return DEFAULT_API_BASE_URL;
  }
  const params = new URLSearchParams(window.location.search);
  const server = params.get("server");
  if (server) {
    return server.replace(/\/+$/, "");
  }
  const configured = process.env.NEXT_PUBLIC_MESH_API_URL?.trim();
  if (configured) {
    return normalizeLoopbackBaseUrl(configured, window.location);
  }
  if (window.location.protocol === "http:" || window.location.protocol === "https:") {
    return window.location.origin;
  }
  return normalizeLoopbackBaseUrl(DEFAULT_API_BASE_URL, window.location);
}

function isLocalOperatorSurface(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return LOCAL_OPERATOR_HOSTS.has(window.location.hostname);
}

function queryOrStorageValue(params: URLSearchParams, queryName: string, storageName: string): string {
  const queryValue = params.get(queryName);
  if (queryValue !== null) {
    return queryValue.trim();
  }
  try {
    return window.localStorage.getItem(storageName)?.trim() ?? "";
  } catch {
    return "";
  }
}

function operatorIdentityHeaders(): Record<string, string> {
  const envOperator = process.env.NEXT_PUBLIC_MESH_OPERATOR_ID?.trim() ?? "";
  const envRoles = process.env.NEXT_PUBLIC_MESH_OPERATOR_ROLES?.trim() ?? "";
  if (typeof window === "undefined") {
    return envOperator && envRoles
      ? { "X-Mesh-Operator": envOperator, "X-Mesh-Roles": envRoles }
      : {};
  }

  const params = new URLSearchParams(window.location.search);
  const operatorId =
    queryOrStorageValue(params, "operator", "mesh.operator.id") ||
    queryOrStorageValue(params, "operator_id", "mesh.operator.id") ||
    envOperator ||
    (isLocalOperatorSurface() ? DEFAULT_LOCAL_OPERATOR_ID : "");
  const roles =
    queryOrStorageValue(params, "roles", "mesh.operator.roles") ||
    queryOrStorageValue(params, "operator_roles", "mesh.operator.roles") ||
    envRoles ||
    (isLocalOperatorSurface() ? DEFAULT_LOCAL_OPERATOR_ROLES : "");

  return operatorId && roles
    ? { "X-Mesh-Operator": operatorId, "X-Mesh-Roles": roles }
    : {};
}

function jsonHeaders(init?: RequestInit): HeadersInit {
  return {
    "Content-Type": "application/json",
    ...operatorIdentityHeaders(),
    ...(init?.headers ?? {}),
  };
}

async function request<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    headers: jsonHeaders(init),
    ...init,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
      else if (body?.error) detail = body.error;
      else if (body?.message) detail = body.message;
    } catch {
      /* body not JSON */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

async function requestAllowingStatus<T>(
  baseUrl: string,
  path: string,
  allowedStatuses: number[],
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    headers: jsonHeaders(init),
    ...init,
  });
  if (!response.ok && !allowedStatuses.includes(response.status)) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
      else if (body?.error) detail = body.error;
      else if (body?.message) detail = body.message;
    } catch {
      /* body not JSON */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

async function requestBlob(baseUrl: string, path: string, init?: RequestInit): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${baseUrl}${path}`, {
    headers: jsonHeaders(init),
    ...init,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
      else if (body?.error) detail = body.error;
      else if (body?.message) detail = body.message;
    } catch {
      /* body not JSON */
    }
    throw new Error(detail);
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = disposition.match(/filename="([^"]+)"/);
  return {
    blob: await response.blob(),
    filename: match?.[1] ?? "mesh-run-export.zip",
  };
}

export const api = {
  getHealth(baseUrl: string) {
    return request<HealthSnapshot>(baseUrl, "/api/health");
  },

  getReadiness(baseUrl: string) {
    return request<IntegrationReadiness>(baseUrl, "/api/readiness");
  },

  getConnectorCertification(baseUrl: string) {
    return request<ConnectorCertificationPacket>(baseUrl, "/api/connectors/certification");
  },

  getApprovals(baseUrl: string) {
    return request<ApprovalQueuePacket>(baseUrl, "/api/approvals");
  },

  getKillSwitch(baseUrl: string) {
    return request<KillSwitchStatus>(baseUrl, "/api/kill-switch");
  },

  applyKillSwitch(baseUrl: string, payload: Record<string, unknown>) {
    return request<KillSwitchStatus>(baseUrl, "/api/kill-switch", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  simulatePolicy(baseUrl: string, payload: Record<string, unknown>) {
    return request<PolicySimulationResult>(baseUrl, "/api/policy/simulate", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getPilotGoNoGo(baseUrl: string) {
    return request<PilotGoNoGoPacket>(baseUrl, "/api/pilot/go-no-go");
  },

  getTrustLadder(baseUrl: string) {
    return request<{ entries: TrustLadderEntry[] }>(baseUrl, "/api/trust-ladder");
  },

  getScenarios(baseUrl: string) {
    return request<{ scenarios: ScenarioRecord[] }>(baseUrl, "/api/scenarios");
  },

  getSimulations(baseUrl: string) {
    return request<{ simulations: SimulationScenarioRecord[] }>(baseUrl, "/api/simulations");
  },

  runSimulation(baseUrl: string, scenarioId: string, payload: Record<string, unknown>) {
    return request<RunDetail>(baseUrl, `/api/simulations/${encodeURIComponent(scenarioId)}/run`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getBenchmarks(baseUrl: string) {
    return request<{ benchmarks: BenchmarkRecord[] }>(baseUrl, "/api/benchmarks");
  },

  getBenchmark(baseUrl: string, benchmarkId: string) {
    return request<BenchmarkRecord>(baseUrl, `/api/benchmarks/${encodeURIComponent(benchmarkId)}`);
  },

  getServiceAgents(baseUrl: string) {
    return request<{ service_agents: ServiceAgentRecord[] }>(baseUrl, "/api/service-agents");
  },

  getGoals(baseUrl: string) {
    return request<{ goals: GoalRecord[] }>(baseUrl, "/api/goals");
  },

  createGoal(baseUrl: string, payload: Record<string, unknown>) {
    return request<GoalRecord>(baseUrl, "/api/goals", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getRuns(baseUrl: string) {
    return request<{ runs: RunSessionRecord[] }>(baseUrl, "/api/runs");
  },

  getRecursiveChaosProfiles(baseUrl: string) {
    return request<RecursiveChaosProfilesResponse>(baseUrl, "/api/recursive-chaos/profiles");
  },

  runRecursiveChaosArenaSession(
    baseUrl: string,
    payload: {
      profile_ids?: string[];
      max_cycles?: number;
      seed?: number;
      targets?: Array<Record<string, unknown>>;
      execute?: boolean;
    } = {},
  ) {
    return request<RunDetail>(baseUrl, "/api/recursive-chaos/sessions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getResearchSessions(baseUrl: string) {
    return request<{ sessions: ResearchSessionRecord[] }>(baseUrl, "/api/research-sessions");
  },

  getResearchCorpus(baseUrl: string) {
    return request<ResearchCorpusIntelligence>(baseUrl, "/api/research-corpus");
  },

  getResearchSession(baseUrl: string, sessionId: string) {
    const id = encodeURIComponent(sessionId);
    return request<ResearchSessionDetail>(baseUrl, `/api/research-sessions/${id}`);
  },

  createRun(baseUrl: string, payload: Record<string, unknown>) {
    return request<RunDetail>(baseUrl, "/api/runs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  runMeshBrainModelKernelProbe(baseUrl: string, payload: { benchmark_iterations?: number } = {}) {
    return request<RunDetail>(baseUrl, "/api/mesh-brain/model-kernel-probe", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  runMeshBrainLiveServingSmoke(
    baseUrl: string,
    payload: {
      base_url?: string;
      model?: string;
      tenant_id?: string;
      task_type?: string;
      hardware_tier?: string;
      prompt?: string;
      timeout_seconds?: number;
      latency_budget_ms?: number;
      max_total_tokens?: number;
      response_eval_min_score?: number;
      judge_enabled?: boolean;
      judge_base_url?: string;
      judge_model?: string;
      deterministic_release_decision?: "block" | "manual_review" | "canary" | "promote";
    } = {},
  ) {
    return request<RunDetail>(baseUrl, "/api/mesh-brain/live-serving-smoke", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  runMeshBrainRollbackDrill(
    baseUrl: string,
    payload: {
      tenant_id?: string;
      task_type?: string;
    } = {},
  ) {
    return request<RunDetail>(baseUrl, "/api/mesh-brain/rollback-drill", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  runMeshBrainBackendMatrix(
    baseUrl: string,
    payload: {
      base_url?: string;
      model?: string;
      target_name?: string;
      tenant_id?: string;
      task_type?: string;
      hardware_tier?: string;
      prompt?: string;
      timeout_seconds?: number;
      deterministic_release_decision?: "block" | "manual_review" | "canary" | "promote";
      targets?: Array<{
        name?: string;
        base_url: string;
        model?: string;
        hardware_tier?: string;
        task_type?: string;
        enabled?: boolean;
        metadata?: Record<string, unknown>;
      }>;
    } = {},
  ) {
    return request<RunDetail>(baseUrl, "/api/mesh-brain/backend-matrix", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getRun(baseUrl: string, runId: string) {
    return request<RunDetail>(baseUrl, `/api/runs/${runId}`);
  },

  getRunExport(baseUrl: string, runId: string) {
    return request<RunExportPackage>(baseUrl, `/api/runs/${runId}/export`, {
      method: "POST",
      body: JSON.stringify({}),
    });
  },

  getRunDarkharnessPacket(baseUrl: string, runId: string) {
    return requestAllowingStatus<DarkharnessPilotPacket>(
      baseUrl,
      `/api/runs/${runId}/darkharness-packet`,
      [409],
    );
  },

  getRunDeliveryContext(baseUrl: string, runId: string) {
    return request<DeliveryContextGraph>(baseUrl, `/api/runs/${encodeURIComponent(runId)}/delivery-context`);
  },

  getRunExportArchive(baseUrl: string, runId: string) {
    return requestBlob(baseUrl, `/api/runs/${runId}/export/archive`, {
      method: "POST",
      body: JSON.stringify({}),
    });
  },

  steerRun(baseUrl: string, runId: string, payload: Record<string, unknown>) {
    return request<RunDetail>(baseUrl, `/api/runs/${runId}/steer`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getRunEvents(baseUrl: string, runId: string) {
    return request<{ events: import("./types").RunEventRecord[] }>(baseUrl, `/api/runs/${runId}/events`);
  },

  getRunMerkle(baseUrl: string, runId: string) {
    return request<MerkleSnapshot>(baseUrl, `/api/runs/${runId}/merkle`);
  },

  getScenarioAnalysis(baseUrl: string, runId: string) {
    return request<ScenarioAnalysis>(baseUrl, `/api/runs/${runId}/scenario-analysis`);
  },

  getEvidenceGraph(baseUrl: string, runId: string) {
    return request<EvidenceGraph>(baseUrl, `/api/runs/${runId}/evidence-graph`);
  },

  getMemoryCrystallization(baseUrl: string, runId: string) {
    return request<Record<string, unknown>>(baseUrl, `/api/runs/${runId}/memory-crystallization`);
  },

  getAgentTasks(baseUrl: string, runId: string) {
    return request<{ tasks: import("./types").AgentTask[] }>(baseUrl, `/api/runs/${runId}/agent-tasks`);
  },

  getWatchers(baseUrl: string) {
    return request<WatcherStatus>(baseUrl, "/api/watchers");
  },

  getMerkleProof(baseUrl: string, runId: string, eventId: string) {
    return request<MerkleProof>(baseUrl, `/api/runs/${runId}/merkle/proof/${eventId}`);
  },

  getVaultTree(baseUrl: string) {
    return request<{ tree: VaultTreeEntry[] }>(baseUrl, "/api/vault/tree");
  },

  getVaultDocument(baseUrl: string, path: string) {
    const query = new URLSearchParams({ path });
    return request<{ path: string; content: string }>(baseUrl, `/api/vault/document?${query.toString()}`);
  },
};

export function connectSystemStream(
  baseUrl: string,
  handlers: {
    onSnapshot: (snapshot: SystemSnapshot) => void;
    onOpen?: () => void;
    onError?: () => void;
  },
) {
  const source = new EventSource(`${baseUrl}/api/stream/system`);
  source.onopen = () => handlers.onOpen?.();
  source.onerror = () => handlers.onError?.();
  source.onmessage = (event) => {
    handlers.onSnapshot(JSON.parse(event.data) as SystemSnapshot);
  };
  source.addEventListener("system", (event) => {
    const message = event as MessageEvent<string>;
    handlers.onSnapshot(JSON.parse(message.data) as SystemSnapshot);
  });
  return () => source.close();
}

export function connectRunStream(
  baseUrl: string,
  runId: string,
  handlers: {
    onEvent: () => void;
    onOpen?: () => void;
    onError?: () => void;
  },
) {
  const source = new EventSource(`${baseUrl}/api/stream/runs/${runId}`);
  source.onopen = () => handlers.onOpen?.();
  source.onerror = () => handlers.onError?.();
  source.onmessage = () => handlers.onEvent();
  source.addEventListener("complete", () => handlers.onEvent());
  return () => source.close();
}
