export const MESH_OPERATOR_OVERVIEW_STATE_SLICE = "mesh.operator_ui.overview";

type SectionState = "ready" | "empty" | "blocked" | "unauthorized" | "backend-unavailable" | "degraded";

export interface DashboardSection<T> {
  state: SectionState;
  data: T;
  error?: string;
  statusCode?: number;
}

export interface OverviewRun {
  run_id: string;
  scenario_key?: string | null;
  stage?: string | null;
  status?: string | null;
  steering_mode?: string | null;
  latest_merkle_root?: string | null;
  updated_at?: string | null;
}

export interface OverviewApproval {
  queue_id?: string;
  run_id?: string;
  stage?: string;
  approval_state?: string;
  risk_level?: string | null;
  final_recommendation?: string | null;
}

export interface OverviewDashboardData {
  stateSlice: typeof MESH_OPERATOR_OVERVIEW_STATE_SLICE;
  loadedAt: string;
  readiness: DashboardSection<Record<string, unknown>>;
  runs: DashboardSection<OverviewRun[]>;
  approvals: DashboardSection<OverviewApproval[]>;
  killSwitch: DashboardSection<Record<string, unknown>>;
  connectorCertification: DashboardSection<Record<string, unknown>>;
}

const EMPTY_RECORD: Record<string, unknown> = {};
const MESH_FORWARD_HEADERS = new Set([
  "cookie",
  "x-mesh-operator",
  "x-mesh-roles",
  "x-mesh-scope",
  "x-mesh-tenant",
  "x-mesh-operator-identity"
]);

export async function loadOverviewDashboard(request: Request): Promise<OverviewDashboardData> {
  const [readiness, runs, approvals, killSwitch, connectorCertification] = await Promise.all([
    loadMeshResource<Record<string, unknown>>(request, "/resources/mesh/readiness", EMPTY_RECORD, dashboardRecordState),
    loadMeshResource<{ runs?: OverviewRun[] }>(request, "/resources/mesh/runs?summary=1", { runs: [] }, (payload) =>
      Array.isArray(payload.runs) && payload.runs.length > 0 ? "ready" : "empty"
    ),
    loadMeshResource<{ items?: OverviewApproval[]; status?: string }>(
      request,
      "/resources/mesh/approvals",
      { items: [] },
      (payload) => {
        if (payload.status === "blocked") return "blocked";
        return Array.isArray(payload.items) && payload.items.length > 0 ? "ready" : "empty";
      }
    ),
    loadMeshResource<Record<string, unknown>>(request, "/resources/mesh/kill-switch", EMPTY_RECORD, dashboardRecordState),
    loadMeshResource<Record<string, unknown>>(
      request,
      "/resources/mesh/connector-certification",
      EMPTY_RECORD,
      dashboardRecordState
    )
  ]);

  return {
    stateSlice: MESH_OPERATOR_OVERVIEW_STATE_SLICE,
    loadedAt: new Date().toISOString(),
    readiness,
    runs: { ...runs, data: Array.isArray(runs.data.runs) ? runs.data.runs : [] },
    approvals: { ...approvals, data: Array.isArray(approvals.data.items) ? approvals.data.items : [] },
    killSwitch,
    connectorCertification
  };
}

export async function loadMeshResource<T>(
  request: Request,
  path: string,
  fallback: T,
  classify: (payload: T) => SectionState
): Promise<DashboardSection<T>> {
  const url = new URL(path, request.url);
  try {
    const response = await fetch(url, { headers: forwardedDashboardHeaders(request) });
    const payload = (await parseJsonBody(response)) as T | null;
    if (!response.ok) {
      return {
        state: response.status === 401 || response.status === 403 ? "unauthorized" : "degraded",
        data: fallback,
        error: errorMessage(payload) || `${response.status} ${response.statusText}`,
        statusCode: response.status
      };
    }
    const data = payload ?? fallback;
    return { state: classify(data), data, statusCode: response.status };
  } catch (error) {
    return {
      state: "backend-unavailable",
      data: fallback,
      error: error instanceof Error ? error.message : String(error)
    };
  }
}

export function forwardedDashboardHeaders(request: Request): Headers {
  const headers = new Headers();
  for (const [name, value] of request.headers.entries()) {
    if (MESH_FORWARD_HEADERS.has(name.toLowerCase()) && value.trim()) {
      headers.set(name, value);
    }
  }
  headers.set("accept", "application/json");
  return headers;
}

export function dashboardRecordState(payload: Record<string, unknown>): SectionState {
  if (Array.isArray(payload.blockers) && payload.blockers.length > 0) return "blocked";
  if (payload.status === "blocked") return "blocked";
  if (payload.status === "fail" || payload.status === "degraded") return "degraded";
  return Object.keys(payload).length > 0 ? "ready" : "empty";
}

async function parseJsonBody(response: Response): Promise<unknown | null> {
  const text = await response.text();
  if (!text.trim()) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return { error: text };
  }
}

function errorMessage(payload: unknown): string | undefined {
  if (!payload || typeof payload !== "object") return undefined;
  const record = payload as Record<string, unknown>;
  return typeof record.error === "string"
    ? record.error
    : typeof record.detail === "string"
      ? record.detail
      : typeof record.message === "string"
        ? record.message
        : undefined;
}
