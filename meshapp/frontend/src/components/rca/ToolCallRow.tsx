import { humanize } from "../../lib/format";
import type { RcaGraphToolCall } from "../../lib/runGraph";

interface ToolCallRowProps {
  tool: RcaGraphToolCall;
  rank: number;
  isActive?: boolean;
}

export function ToolCallRow({ tool, rank, isActive = false }: ToolCallRowProps) {
  const statusLabel = humanize(tool.status || "recorded");
  const state = isActive ? "running" : tool.valid ? "ready" : "degraded";

  return (
    <article
      className={`rca-tool-row ${tool.valid ? "valid" : "invalid"} mesh-row-enter mesh-row-enter-stagger${
        isActive ? " mesh-active-pulse" : ""
      }`}
    >
      <span className="rca-rank">{rank}</span>
      <div>
        <strong>{tool.name}</strong>
        <small>{tool.summary || statusLabel}</small>
        {tool.citationIds.length > 0 ? <code>{tool.citationIds.slice(0, 3).join(" / ")}</code> : null}
      </div>
      <span className={`mesh-status-pill ${state}`}>{statusLabel}</span>
    </article>
  );
}
