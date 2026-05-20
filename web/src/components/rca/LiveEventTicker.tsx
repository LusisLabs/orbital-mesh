/**
 * Top-bar live event ticker.
 *
 * Mesh is event-driven. Without a chrome-level "Mesh is doing
 * something right now" indicator, the agentic-real-time differentiation
 * is invisible until you click into a specific run. The ticker fixes
 * that by surfacing the most-recently-advanced run across the whole
 * fleet — name + stage + a soft flash when the value changes.
 *
 * Implementation notes:
 *   - Input is the ``active_runs`` array from the system SSE snapshot
 *     (already plumbed via ``connectSystemStream``). We don't open a
 *     second SSE subscription; we derive the ticker from the array
 *     the parent already maintains.
 *   - "Most-recently-advanced" = the run with the latest
 *     ``updated_at`` AND whose stage isn't a terminal state. Falls back
 *     to "fleet quiet" copy when nothing is active.
 *   - The flash animation triggers on ``stage + run_id`` change so
 *     two unrelated runs landing on the same stage still flash.
 *   - Truncates at one row, ~36rem wide — sized for the topbar.
 *     Investigators clicking through to a specific run will see the
 *     full run-detail panel; the ticker is glance-only.
 */

import { useEffect, useRef, useState } from "react";
import { humanize, relativeTime } from "../../lib/format";
import type { RunSessionRecord } from "../../types";

const TERMINAL_STAGES = new Set([
  "completed",
  "failed",
  "cancelled",
  "no_trigger",
  "recovery_spawned",
]);

interface LiveEventTickerProps {
  activeRuns: readonly RunSessionRecord[];
}

function pickHeadline(active: readonly RunSessionRecord[]): RunSessionRecord | null {
  // Most-recently-updated non-terminal run. The ``active_runs`` array
  // already filters to "in flight" upstream but we re-check to stay
  // defensive — terminal stages should never light the ticker, and if
  // a future control-plane change leaks one through, the ticker
  // shouldn't lie.
  const live = active.filter((run) => !TERMINAL_STAGES.has(run.stage));
  if (live.length === 0) return null;
  return live.reduce((latest, run) => {
    if (!latest) return run;
    return run.updated_at > latest.updated_at ? run : latest;
  }, live[0]);
}

export function LiveEventTicker({ activeRuns }: LiveEventTickerProps) {
  const headline = pickHeadline(activeRuns);
  const fingerprint = headline ? `${headline.run_id}::${headline.stage}` : "";
  const [flashKey, setFlashKey] = useState<string>("");
  const lastFingerprintRef = useRef<string>("");

  useEffect(() => {
    if (!fingerprint) {
      lastFingerprintRef.current = "";
      return;
    }
    if (fingerprint !== lastFingerprintRef.current) {
      lastFingerprintRef.current = fingerprint;
      // Re-trigger the CSS animation by changing the key the className
      // depends on. CSS keyframes only fire on element insertion or
      // class change — bumping the key is the smallest hammer.
      setFlashKey(`${fingerprint}::${Date.now()}`);
    }
  }, [fingerprint]);

  if (!headline) {
    return (
      <div className="mesh-event-ticker" aria-live="polite">
        <span className="mesh-event-ticker-dot" style={{ background: "var(--muted)", boxShadow: "none" }} />
        <span className="mesh-event-ticker-empty">Fleet quiet</span>
      </div>
    );
  }

  const service = headline.scenario_key ? humanize(headline.scenario_key) : headline.run_id.slice(0, 12);
  const updated = relativeTime(headline.updated_at);

  return (
    <div
      key={flashKey || fingerprint}
      className="mesh-event-ticker flash"
      aria-live="polite"
      title={`Run ${headline.run_id} — ${headline.stage}`}
    >
      <span className="mesh-event-ticker-dot" />
      <span className="mesh-event-ticker-stage">{humanize(headline.stage)}</span>
      <span className="mesh-event-ticker-text">
        {service} · {updated}
      </span>
    </div>
  );
}
