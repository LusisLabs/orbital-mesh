/**
 * WebSocket/SSE connection state machine for Mesh realtime updates.
 *
 * Manages connection lifecycle states (connecting, connected, reconnecting, stale, terminal),
 * provides a reducer for processing connection events, and utilities for parsing
 * realtime payloads and stream resource paths.
 *
 * @module
 */

export const MESH_REALTIME_STATE_SLICE = "mesh.operator_ui.realtime";

/** Connection state for realtime transport. */
export type MeshRealtimeConnection = "connecting" | "connected" | "reconnecting" | "stale" | "terminal";

/**
 * Snapshot of realtime connection state.
 *
 * @template T - Type of payload data carried in messages.
 */
export interface MeshRealtimeSnapshot<T = unknown> {
  /** State slice identifier for this state. */
  stateSlice: typeof MESH_REALTIME_STATE_SLICE;
  /** Current connection lifecycle state. */
  connection: MeshRealtimeConnection;
  /** Number of reconnection attempts made. */
  reconnectAttempts: number;
  /** ISO timestamp of last received event. */
  lastEventAt?: string;
  /** Type of last received event. */
  lastEventType?: string;
  /** Reason for entering terminal state, if applicable. */
  terminalReason?: string;
  /** Latest parsed payload data. */
  data?: T;
}

/**
 * Events that drive the realtime state machine.
 *
 * @template T - Type of payload data carried in message events.
 */
export type MeshRealtimeEvent<T = unknown> =
  | { type: "open"; now: string }
  | { type: "message"; eventType?: string; data: T; now: string }
  | { type: "error"; now: string }
  | { type: "stale"; now: string }
  | { type: "terminal"; reason: string; now: string };

/** Creates initial snapshot with connecting state and zero reconnect attempts. */
export function initialRealtimeSnapshot<T = unknown>(): MeshRealtimeSnapshot<T> {
  return {
    stateSlice: MESH_REALTIME_STATE_SLICE,
    connection: "connecting",
    reconnectAttempts: 0
  };
}

/** Reduces snapshot state based on incoming event. */
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

/** Resource path for system-wide realtime stream. */
export function systemStreamResourcePath(): string {
  return "/resources/mesh/stream/system";
}

/** Resource path for run-specific realtime stream. */
export function runStreamResourcePath(runId: string): string {
  return `/resources/mesh/stream/runs/${encodeURIComponent(runId)}`;
}

/**
 * Parses raw SSE message payload.
 * @returns Parsed JSON payload, or null if input is empty/whitespace only.
 */
export function parseRealtimePayload<T = unknown>(raw: string): T | null {
  if (!raw.trim()) return null;
  return JSON.parse(raw) as T;
}

/**
 * Checks if payload represents a terminal run event (complete, failed, cancelled).
 * @param payload - Raw payload object from stream message.
 */
export function isTerminalRunEvent(payload: unknown): boolean {
  if (!payload || typeof payload !== "object") return false;
  const record = payload as Record<string, unknown>;
  const status = typeof record.status === "string" ? record.status.toLowerCase() : "";
  const eventType = typeof record.event_type === "string" ? record.event_type.toLowerCase() : "";
  return ["complete", "completed", "failed", "cancelled", "terminal"].includes(status)
    || ["complete", "run_complete", "run_failed", "terminal"].includes(eventType);
}

/** Determines if connection should be marked stale based on elapsed time since last event. */
export function shouldMarkRealtimeStale(lastEventAt: string | undefined, nowMs: number, staleAfterMs: number): boolean {
  if (!lastEventAt) return false;
  return nowMs - Date.parse(lastEventAt) >= staleAfterMs;
}
