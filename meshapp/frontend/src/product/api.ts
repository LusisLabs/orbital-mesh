import type { AuthConfig, DashboardPayload, LogoutResponse, SessionPayload, SettingsUpdateResponse } from "./types";
export type { AuthConfig, DashboardPayload, LogoutResponse, SessionPayload, SettingsUpdateResponse, TeamProfile, UserProfile } from "./types";

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

const DEFAULT_API_BASE_URL = process.env.NEXT_PUBLIC_MESH_API_URL?.trim() || "http://127.0.0.1:8787";

export function resolveBaseUrl(): string {
  if (typeof window === "undefined") return DEFAULT_API_BASE_URL;
  const params = new URLSearchParams(window.location.search);
  return (params.get("server") || DEFAULT_API_BASE_URL).replace(/\/+$/, "");
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
  signup(payload: { email: string; password: string; display_name?: string; captcha_token?: string }) {
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
};
