import type {
  GoalRecord,
  HealthSnapshot,
  IntegrationReadiness,
  MerkleProof,
  MerkleSnapshot,
  ResearchCorpusIntelligence,
  ResearchSessionDetail,
  ResearchSessionRecord,
  RunDetail,
  RunSessionRecord,
  ScenarioRecord,
  SystemSnapshot,
  VaultTreeEntry,
} from "./types";

export function resolveBaseUrl(): string {
  const params = new URLSearchParams(window.location.search);
  const server = params.get("server");
  if (!server) {
    return window.location.origin;
  }
  return server.replace(/\/+$/, "");
}

async function request<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
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

export const api = {
  getHealth(baseUrl: string) {
    return request<HealthSnapshot>(baseUrl, "/api/health");
  },

  getReadiness(baseUrl: string) {
    return request<IntegrationReadiness>(baseUrl, "/api/readiness");
  },

  getScenarios(baseUrl: string) {
    return request<{ scenarios: ScenarioRecord[] }>(baseUrl, "/api/scenarios");
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

  getRun(baseUrl: string, runId: string) {
    return request<RunDetail>(baseUrl, `/api/runs/${runId}`);
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

  getAgentTasks(baseUrl: string, runId: string) {
    return request<{ tasks: import("./types").AgentTask[] }>(baseUrl, `/api/runs/${runId}/agent-tasks`);
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
