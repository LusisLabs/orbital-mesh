import { useEffect, useMemo, useState } from "react";

import { buildAsciiSignalFrame } from "../lib/asciiSignal";
import type { LabyrinthCrossing, LabyrinthGuidepost, WatcherStatus } from "../types";

export function AmbientAsciiSignal({
  stage,
  status,
  signal,
  crossings,
  guideposts,
  watchers,
}: {
  stage?: string | null;
  status?: string | null;
  signal?: Record<string, any> | null;
  crossings: LabyrinthCrossing[];
  guideposts: LabyrinthGuidepost[];
  watchers: WatcherStatus | null;
}) {
  const [frame, setFrame] = useState(0);
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReducedMotion(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    if (reducedMotion) return;
    const timer = window.setInterval(() => setFrame((value) => (value + 1) % 60), 600);
    return () => window.clearInterval(timer);
  }, [reducedMotion]);

  const ascii = useMemo(
    () =>
      buildAsciiSignalFrame({
        stage,
        status,
        signal,
        crossings,
        guideposts,
        watchers,
        frame: reducedMotion ? 0 : frame,
      }),
    [crossings, frame, guideposts, reducedMotion, signal, stage, status, watchers],
  );

  return (
    <section className={`ambient-ascii ambient-ascii-${ascii.tone}`} aria-label="Ambient ASCII signal">
      <div className="ambient-ascii-header">
        <span>Signal Monitor</span>
        <strong>{ascii.title}</strong>
      </div>
      <pre>{ascii.lines.join("\n")}</pre>
    </section>
  );
}
