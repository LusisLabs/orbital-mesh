import { useEffect, useRef, useState } from "react";

import { humanize, relativeTime } from "../../lib/format";
import type { RunSessionRecord } from "../../types";

const TERMINAL_STAGES = new Set(["completed", "failed", "cancelled", "no_trigger", "recovery_spawned"]);

interface LiveEventTickerProps {
  activeRuns: readonly RunSessionRecord[];
}

function pickHeadline(activeRuns: readonly RunSessionRecord[]): RunSessionRecord | null {
  const liveRuns = activeRuns.filter((run) => !TERMINAL_STAGES.has(run.stage));
  if (liveRuns.length === 0) return null;
  return liveRuns.reduce((latest, run) => (run.updated_at > latest.updated_at ? run : latest), liveRuns[0]);
}

export function LiveEventTicker({ activeRuns }: LiveEventTickerProps) {
  const headline = pickHeadline(activeRuns);
  const fingerprint = headline ? `${headline.run_id}:${headline.stage}` : "";
  const [flashKey, setFlashKey] = useState("");
  const lastFingerprintRef = useRef("");

  useEffect(() => {
    if (!fingerprint) {
      lastFingerprintRef.current = "";
      return;
    }
    if (fingerprint !== lastFingerprintRef.current) {
      lastFingerprintRef.current = fingerprint;
      setFlashKey(`${fingerprint}:${Date.now()}`);
    }
  }, [fingerprint]);

  if (!headline) {
    return (
      <div className="mesh-event-ticker" aria-live="polite">
        <span className="mesh-event-ticker-dot quiet" />
        <span className="mesh-event-ticker-empty">Fleet quiet</span>
      </div>
    );
  }

  const service = headline.scenario_key ? humanize(headline.scenario_key) : headline.run_id.slice(0, 12);

  return (
    <div
      key={flashKey || fingerprint}
      className="mesh-event-ticker flash"
      aria-live="polite"
      title={`Run ${headline.run_id} - ${headline.stage}`}
    >
      <span className="mesh-event-ticker-dot" />
      <span className="mesh-event-ticker-stage">{humanize(headline.stage)}</span>
      <span className="mesh-event-ticker-text">
        {service} / {relativeTime(headline.updated_at)}
      </span>
    </div>
  );
}
