export const MESH_REALTIME_STATE_SLICE = "mesh.operator_ui.realtime";

export type MeshRealtimeConnection = "connecting" | "connected" | "reconnecting" | "stale" | "terminal";

export interface MeshRealtimeSnapshot<T = unknown> {
  stateSlice: typeof MESH_REALTIME_STATE_SLICE;
  connection: MeshRealtimeConnection;
  reconnectAttempts: number;
  lastEventAt?: string;
  lastEventType?: string;
  terminalReason?: string;
  data?: T;
}

export type MeshRealtimeEvent<T = unknown> =
  | { type: "open"; now: string }
  | { type: "message"; eventType?: string; data: T; now: string }
  | { type: "error"; now: string }
  | { type: "stale"; now: string }
  | { type: "terminal"; reason: string; now: string };

export function initialRealtimeSnapshot<T = unknown>(): MeshRealtimeSnapshot<T> {
  return {
    stateSlice: MESH_REALTIME_STATE_SLICE,
    connection: "connecting",
    reconnectAttempts: 0
  };
}

export function reduceRealtimeSnapshot<T>(
  current: MeshRealtimeSnapshot<T>,
  event: MeshRealtimeEvent<T>
): MeshRealtimeSnapshot<T> {
  if (current.connection === "terminal" && event.type !== "open") {
    return current;
  }
  switch (event.type) {
    case "open":
      return {
        ...current,
        connection: "connected",
        reconnectAttempts: 0,
        lastEventAt: event.now,
        terminalReason: undefined
      };
    case "message":
      return {
        ...current,
        connection: "connected",
        data: event.data,
        lastEventAt: event.now,
        lastEventType: event.eventType ?? "message"
      };
    case "error":
      return {
        ...current,
        connection: "reconnecting",
        reconnectAttempts: current.reconnectAttempts + 1,
        lastEventAt: event.now
      };
    case "stale":
      return {
        ...current,
        connection: "stale",
        lastEventAt: event.now
      };
    case "terminal":
      return {
        ...current,
        connection: "terminal",
        terminalReason: event.reason,
        lastEventAt: event.now
      };
  }
}

export function systemStreamResourcePath(): string {
  return "/resources/mesh/stream/system";
}

export function runStreamResourcePath(runId: string): string {
  return `/resources/mesh/stream/runs/${encodeURIComponent(runId)}`;
}

export function parseRealtimePayload<T = unknown>(raw: string): T | null {
  if (!raw.trim()) return null;
  return JSON.parse(raw) as T;
}

export function isTerminalRunEvent(payload: unknown): boolean {
  if (!payload || typeof payload !== "object") return false;
  const record = payload as Record<string, unknown>;
  const status = typeof record.status === "string" ? record.status.toLowerCase() : "";
  const eventType = typeof record.event_type === "string" ? record.event_type.toLowerCase() : "";
  return ["complete", "completed", "failed", "cancelled", "terminal"].includes(status)
    || ["complete", "run_complete", "run_failed", "terminal"].includes(eventType);
}

export function shouldMarkRealtimeStale(lastEventAt: string | undefined, nowMs: number, staleAfterMs: number): boolean {
  if (!lastEventAt) return false;
  return nowMs - Date.parse(lastEventAt) >= staleAfterMs;
}
