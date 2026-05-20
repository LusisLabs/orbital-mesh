/**
 * Tool-call row for the RCA snapshot panel.
 *
 * The investigation harness emits one of these per LLM-driven tool call.
 * Three demo concerns the row has to handle:
 *
 *   1. Entrance animation. SSE delivers calls one-by-one; without motion
 *      they pop into a list and the live-streaming nature is invisible
 *      to anyone watching the panel.
 *   2. Active highlight. The currently-running call should pulse so the
 *      eye knows where "the agent is right now".
 *   3. Validity / status coloring through semantic tokens. The previous
 *      inline ``className=`rca-tool-row ${tool.valid ? "valid" : "invalid"}```
 *      conflated validity with status; this component keeps the two
 *      distinct.
 *
 * The component is pure presentation — it receives a shaped tool
 * descriptor and renders. The parent owns the data flow.
 */

import { humanize } from "../../lib/format";
import type { RcaGraphToolCall } from "../../lib/runGraph";

type StatusPillState = "ready" | "degraded" | "running";

interface ToolCallRowProps {
  tool: RcaGraphToolCall;
  rank: number;
  /**
   * When ``true`` the row pulses to indicate the call is currently
   * executing (parent decides this from SSE state — typically "the
   * tool with status=running or the last call when stop_reason is
   * absent"). Keep this narrow: at most one row at a time should be
   * marked active or the panel becomes noisy on stage.
   */
  isActive?: boolean;
}

export function ToolCallRow({ tool, rank, isActive = false }: ToolCallRowProps) {
  const tone = tool.valid ? "valid" : "invalid";
  const statusLabel = humanize(tool.status || "recorded");
  // Running gets a distinct visual treatment — neither success nor
  // failure, just "in flight". Recorded tools that came back valid get
  // the success pill; everything else gets the degraded pill.
  const pillState: StatusPillState = isActive
    ? "running"
    : tool.valid
    ? "ready"
    : "degraded";

  return (
    <article
      className={`rca-tool-row ${tone} mesh-row-enter mesh-row-enter-stagger${
        isActive ? " mesh-active-pulse" : ""
      }`}
    >
      <span className="rca-rank">{rank}</span>
      <div>
        <strong>{tool.name}</strong>
        <small>{tool.summary || statusLabel}</small>
        {tool.citationIds.length > 0 ? (
          <code>{tool.citationIds.slice(0, 3).join(" / ")}</code>
        ) : null}
      </div>
      <span className={`status-pill ${pillState}`}>{statusLabel}</span>
    </article>
  );
}
