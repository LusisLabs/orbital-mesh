import type { AuthConfig, DashboardPayload, LogoutResponse, OperatorPreferencesUpdateResponse, SessionPayload, SettingsUpdateResponse } from "./types";
export type { AuthConfig, DashboardPayload, LogoutResponse, OperatorPreferencesUpdateResponse, SessionPayload, SettingsUpdateResponse, TeamProfile, UserProfile } from "./types";

export type LoadState<T> =
  | { state: "loading" }
  | { state: "ready"; data: T }
  | { state: "empty"; message: string }
  | { state: "unauthorized"; message: string }
  | { state: "forbidden"; message: string }
  | { state: "backend-unavailable"; message: string }
  | { state: "error"; message: string };

export class HttpError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export type RunAdmissionPacket = {
  schema_version?: string;
  decision?: "admitted" | "blocked" | string;
  blockers?: string[];
  tenant_id?: string;
  target_lock_key?: string;
  queue?: {
    current_depth?: number;
    max_size?: number;
    worker_count?: number;
  };
  quotas?: {
    tenant_active_runs?: number;
    tenant_active_run_quota?: number;
  };
  lock?: {
    granted?: boolean;
    holder_run_id?: string | null;
  };
};

export type RunLaunchPayload = {
  scenario_key: string;
  audit_reason: string;
  evaluation_mode?: string;
  orchestration_mode?: string;
  steering_mode?: string;
  require_target_lock?: boolean;
  pause_points?: string[];
  simulation_context?: Record<string, any>;
};

export type RunLaunchResponse = {
  run_id: string;
  scenario_key?: string;
  status?: string;
  stage?: string;
  error?: string;
  artifacts?: {
    run_admission?: RunAdmissionPacket;
    operator_audit?: {
      reason?: string;
      state_slice?: string;
      operator_id?: string;
    };
  };
};

export type RunDetailResponse = RunLaunchResponse & {
  events?: Array<Record<string, any>>;
  artifacts?: Record<string, any>;
  merkle?: Record<string, any>;
};

export type ApprovalCommand = "approve" | "resume" | "cancel" | "explain_blockers" | "override_decision";

export type PraxisSourceInput = {
  source_type: "openapi" | "postman_json" | "sop_markdown" | "redacted_traffic_ref" | string;
  filename?: string;
  content?: string | Record<string, any>;
  source_ref?: string;
};

export type PraxisGenerationPayload = {
  team_id?: string | null;
  sources: PraxisSourceInput[];
};

export type PraxisMcpRequest = {
  jsonrpc: "2.0";
  id: string | number;
  method: "initialize" | "tools/list" | "tools/call" | string;
  params?: Record<string, any>;
};

const DEFAULT_API_BASE_URL = process.env.NEXT_PUBLIC_MESH_API_URL?.trim() || "http://127.0.0.1:8787";
const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);

function isLoopbackHost(hostname: string): boolean {
  return LOOPBACK_HOSTS.has(hostname.toLowerCase());
}

export function normalizeLoopbackBaseUrl(baseUrl: string, pageLocation?: Pick<Location, "hostname">): string {
  const trimmed = baseUrl.replace(/\/+$/, "");
  if (!pageLocation?.hostname || !isLoopbackHost(pageLocation.hostname)) return trimmed;
  try {
    const parsed = new URL(trimmed);
    if (!isLoopbackHost(parsed.hostname) || parsed.hostname === pageLocation.hostname) return trimmed;
    parsed.hostname = pageLocation.hostname;
    return parsed.toString().replace(/\/+$/, "");
  } catch {
    return trimmed;
  }
}

export function resolveBaseUrl(): string {
  if (typeof window === "undefined") return DEFAULT_API_BASE_URL;
  const params = new URLSearchParams(window.location.search);
  const explicitServer = params.get("server");
  if (explicitServer) return explicitServer.replace(/\/+$/, "");
  return normalizeLoopbackBaseUrl(DEFAULT_API_BASE_URL, window.location);
}

export function backendUnavailableMessage(): string {
  return `Mesh API unavailable at ${resolveBaseUrl()}. Start the control-plane API, then reload. Local dev: MESH_AUTH_MODE=app_session MESH_CAPTCHA_DEV_BYPASS=1 python run_server.py`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 8_000);
  try {
    const response = await fetch(`${resolveBaseUrl()}${path}`, {
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
      signal: init?.signal ?? controller.signal,
      ...init,
    });
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const body = await response.json();
        detail = body?.error || body?.detail || body?.message || detail;
      } catch {
        /* non-json error */
      }
      throw new HttpError(response.status, detail);
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof HttpError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new HttpError(0, `Mesh API timed out at ${resolveBaseUrl()}`);
    }
    throw new HttpError(0, backendUnavailableMessage());
  } finally {
    window.clearTimeout(timeout);
  }
}

export function loadStateFromError<T>(error: unknown): LoadState<T> {
  if (error instanceof HttpError) {
    if (error.status === 0) return { state: "backend-unavailable", message: error.message };
    if (error.status === 401) return { state: "unauthorized", message: error.message };
    if (error.status === 403) return { state: "forbidden", message: error.message };
    if (error.status >= 500) return { state: "backend-unavailable", message: error.message };
    return { state: "error", message: error.message };
  }
  return { state: "backend-unavailable", message: error instanceof Error ? error.message : "Backend unavailable" };
}

export const productApi = {
  authConfig() {
    return request<AuthConfig>("/api/auth/config");
  },
  me() {
    return request<SessionPayload>("/api/auth/me");
  },
  signup(payload: { email: string; password: string; display_name?: string; captcha_token?: string; invite_code?: string; accepted_terms?: boolean }) {
    return request<SessionPayload>("/api/auth/signup", { method: "POST", body: JSON.stringify(payload) });
  },
  login(payload: { email: string; password: string }) {
    return request<SessionPayload>("/api/auth/login", { method: "POST", body: JSON.stringify(payload) });
  },
  logout() {
    return request<LogoutResponse>("/api/auth/logout", { method: "POST", body: "{}" });
  },
  oauthStart(provider: "google" | "github") {
    return request<{ authorize_url: string }>(`/api/auth/oauth/${provider}/start`);
  },
  createTeam(payload: { name: string; display_name?: string; members?: { email: string; role: string }[] }) {
    return request<SessionPayload>("/api/auth/team", { method: "POST", body: JSON.stringify(payload) });
  },
  updateTeam(payload: { team_id?: string | null; name: string; display_name?: string }) {
    return request<SessionPayload>("/api/auth/team/update", { method: "POST", body: JSON.stringify(payload) });
  },
  upsertTeamMembers(payload: { team_id?: string | null; members: { email: string; role: string }[] }) {
    return request<SessionPayload>("/api/auth/team/members", { method: "POST", body: JSON.stringify(payload) });
  },
  switchTeam(teamId: string | null) {
    return request<SessionPayload>("/api/auth/switch-team", { method: "POST", body: JSON.stringify({ team_id: teamId }) });
  },
  dashboard(teamId?: string | null) {
    const query = teamId ? `?team_id=${encodeURIComponent(teamId)}` : "";
    return request<DashboardPayload>(`/api/operator/dashboard${query}`);
  },
  updateSettings(teamId: string | null, settings: Record<string, string>, reason: string) {
    return request<SettingsUpdateResponse>("/api/operator/settings", {
      method: "POST",
      body: JSON.stringify({ team_id: teamId, settings, reason }),
    });
  },
  updateOperatorPreferences(teamId: string | null, operatorPreferences: Record<string, string | boolean | string[]>, reason: string) {
    return request<OperatorPreferencesUpdateResponse>("/api/operator/preferences", {
      method: "POST",
      body: JSON.stringify({ team_id: teamId, operator_preferences: operatorPreferences, reason }),
    });
  },
  createRun(payload: RunLaunchPayload) {
    return request<RunLaunchResponse>("/api/runs", { method: "POST", body: JSON.stringify(payload) });
  },
  steerRun(runId: string, payload: { command: ApprovalCommand; reason?: string }) {
    return request<RunDetailResponse>(`/api/runs/${encodeURIComponent(runId)}/steer`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  runDetail(runId: string) {
    return request<RunDetailResponse>(`/api/runs/${encodeURIComponent(runId)}`);
  },
  runEvents(runId: string) {
    return request<{ events: Array<Record<string, any>> }>(`/api/runs/${encodeURIComponent(runId)}/events`);
  },
  evidenceGraph(runId: string) {
    return request<Record<string, any>>(`/api/runs/${encodeURIComponent(runId)}/evidence-graph`);
  },
  scenarioAnalysis(runId: string) {
    return request<Record<string, any>>(`/api/runs/${encodeURIComponent(runId)}/scenario-analysis`);
  },
  merkle(runId: string) {
    return request<Record<string, any>>(`/api/runs/${encodeURIComponent(runId)}/merkle`);
  },
  timelineProof(runId: string) {
    return request<Record<string, any>>(`/api/runs/${encodeURIComponent(runId)}/timeline-proof`);
  },
  exportRun(runId: string) {
    return request<Record<string, any>>(`/api/runs/${encodeURIComponent(runId)}/export`, { method: "POST", body: "{}" });
  },
  praxisRuns(teamId?: string | null) {
    const query = teamId ? `?team_id=${encodeURIComponent(teamId)}` : "";
    return request<Record<string, any>>(`/api/operator/praxis/runs${query}`);
  },
  createPraxisGenerationRequest(payload: PraxisGenerationPayload) {
    return request<Record<string, any>>("/api/operator/praxis/generation-requests", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  importPraxisAktoEvidence(requestId: string, payload: { team_id?: string | null; akto_result: Record<string, any>; evidence_id?: string }) {
    return request<Record<string, any>>(`/api/operator/praxis/generation-requests/${encodeURIComponent(requestId)}/akto-evidence`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  buildPraxisCertificationBinding(requestId: string, payload: { team_id?: string | null }) {
    return request<Record<string, any>>(`/api/operator/praxis/generation-requests/${encodeURIComponent(requestId)}/certification-binding`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  startPraxisDryRunEndpoint(requestId: string, payload: { team_id?: string | null }) {
    return request<Record<string, any>>(`/api/operator/praxis/generation-requests/${encodeURIComponent(requestId)}/dry-run/start`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  callPraxisDryRunTool(requestId: string, payload: { team_id?: string | null; tool_id: string; arguments?: Record<string, any> }) {
    return request<Record<string, any>>(`/api/operator/praxis/generation-requests/${encodeURIComponent(requestId)}/dry-run/call`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  praxisMcp(requestId: string, payload: PraxisMcpRequest & { team_id?: string | null }) {
    return request<Record<string, any>>(`/api/operator/praxis/generation-requests/${encodeURIComponent(requestId)}/mcp`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  revokePraxisGeneratedConnector(requestId: string, payload: { team_id?: string | null; reason?: string }) {
    return request<Record<string, any>>(`/api/operator/praxis/generation-requests/${encodeURIComponent(requestId)}/revoke`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  exportPraxisP10Proof(requestId: string, teamId?: string | null) {
    const query = teamId ? `?team_id=${encodeURIComponent(teamId)}` : "";
    return request<Record<string, any>>(`/api/operator/praxis/runs/${encodeURIComponent(requestId)}/p10-proof${query}`);
  },
};
