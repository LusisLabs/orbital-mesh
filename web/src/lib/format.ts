export function relativeTime(iso: string): string {
  const date = new Date(iso);
  const diff = Date.now() - date.getTime();
  if (diff < 0) return "upcoming";
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatDuration(startIso: string, endIso?: string): string {
  const start = new Date(startIso).getTime();
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  const ms = end - start;
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ${Math.floor((ms % 60_000) / 1000)}s`;
  return `${Math.floor(ms / 3_600_000)}h ${Math.floor((ms % 3_600_000) / 60_000)}m`;
}

export function truncateHash(hash: string, len = 12): string {
  if (hash.length <= len) return hash;
  return hash.slice(0, len) + "…";
}

export function humanize(snakeCase: string): string {
  return snakeCase
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function safeJsonParse<T = Record<string, unknown>>(
  text: string,
): { ok: true; data: T } | { ok: false; error: string } {
  try {
    return { ok: true, data: JSON.parse(text) as T };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "Invalid JSON" };
  }
}

export function riskColor(level?: string): string {
  switch (level?.toLowerCase()) {
    case "critical":
    case "high":
      return "var(--accent-danger)";
    case "medium":
      return "var(--accent-warm)";
    case "low":
      return "var(--accent-good)";
    default:
      return "var(--muted)";
  }
}

export function stageIcon(stage: string): string {
  const icons: Record<string, string> = {
    queued: "◦",
    ingesting: "↓",
    trigger_ready: "⚡",
    decision_ready: "◈",
    evaluation_ready: "✓",
    awaiting_operator: "⏸",
    executing: "▶",
    feedback_ready: "◉",
    completed: "●",
    failed: "✕",
    cancelled: "⊘",
    no_trigger: "○",
  };
  return icons[stage] ?? "·";
}
