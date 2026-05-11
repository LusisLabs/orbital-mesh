import type { LabyrinthCrossing, LabyrinthGuidepost, WatcherStatus } from "../types";

export type AsciiSignalTone = "stable" | "warning" | "danger" | "active";

export interface AsciiSignalFrame {
  tone: AsciiSignalTone;
  title: string;
  lines: string[];
}

const STABLE_WAVE = [
  "    .--.      .--.      .--.",
  "---'    '----'    '----'    '--",
  "  signal steady / evidence locked",
  "---.    .----.    .----.    .--",
  "    '--'      '--'      '--'",
];

const ACTIVE_WAVE = [
  "  /\\        /\\        /\\",
  " /  \\  /\\  /  \\  /\\  /  \\",
  "<    \\/  \\/    \\/  \\/    >",
  " \\      threshold current     /",
  "  \\__/\\__/\\__/\\__/\\__/\\__/",
];

const WARNING_WAVE = [
  "::::::..    ..::::::..",
  "::  REVIEW THRESHOLD ::",
  "::::..    evidence    ..::::",
  "  ..:: route requires operator ::..",
  "::::::..    ..::::::..",
];

const DANGER_WAVE = [
  "########  FAILURE  ########",
  "##   blocked path detected ##",
  "#### evidence before action ####",
  "##   review attention      ##",
  "########  FAILURE  ########",
];

export function buildAsciiSignalFrame({
  stage,
  status,
  signal,
  crossings,
  guideposts,
  watchers,
  frame = 0,
}: {
  stage?: string | null;
  status?: string | null;
  signal?: Record<string, any> | null;
  crossings: LabyrinthCrossing[];
  guideposts: LabyrinthGuidepost[];
  watchers: WatcherStatus | null;
  frame?: number;
}): AsciiSignalFrame {
  const danger = status === "failed" || stage === "failed" || guideposts.some((guidepost) => guidepost.severity === "danger");
  const warning =
    stage === "awaiting_operator" ||
    guideposts.some((guidepost) => guidepost.severity === "warning") ||
    (watchers?.watchers ?? []).some((watcher) => !watcher.running);
  const active = stage === "executing" || stage === "scenario_analysis_ready" || crossings.some((crossing) => crossing.status === "running");
  const tone: AsciiSignalTone = danger ? "danger" : warning ? "warning" : active ? "active" : "stable";
  const base = tone === "danger" ? DANGER_WAVE : tone === "warning" ? WARNING_WAVE : tone === "active" ? ACTIVE_WAVE : STABLE_WAVE;
  const shifted = shouldAnimate(tone) ? rotateLine(base[frame % base.length], frame % 6) : base[0];
  const service = String(signal?.service ?? signal?.node?.name ?? signal?.deployment?.name ?? "mesh");
  const nodeKind = String(signal?.signal_type ?? signal?.node?.network ?? "control-plane");
  const metricLine = buildMetricLine(signal);
  const watcherLine = `${(watchers?.watchers ?? []).filter((watcher) => watcher.running).length}/${watchers?.watchers.length ?? 0} watchers live`;

  return {
    tone,
    title: `${service} / ${nodeKind}`,
    lines: [
      shifted,
      base[1],
      metricLine,
      watcherLine,
      `${crossings.length} events / ${guideposts.length} attention`,
    ],
  };
}

function shouldAnimate(tone: AsciiSignalTone): boolean {
  return tone === "active" || tone === "stable";
}

function rotateLine(line: string, offset: number): string {
  if (line.length === 0) return line;
  const safeOffset = offset % line.length;
  return `${line.slice(safeOffset)}${line.slice(0, safeOffset)}`;
}

function buildMetricLine(signal?: Record<string, any> | null): string {
  if (!signal) return "no live signal selected";
  if (signal.signal_type === "reth_node") {
    const peers = signal.execution?.peer_count ?? "?";
    const lag = signal.execution?.block_lag ?? "?";
    const disk = signal.storage?.disk_used_pct ?? "?";
    return `reth peers:${peers} lag:${lag} disk:${disk}`;
  }
  if (signal.signal_type === "kubernetes_deployment_issue" || signal.deployment) {
    const ready = signal.deployment?.available_replicas ?? "?";
    const desired = signal.deployment?.desired_replicas ?? "?";
    return `k8s replicas:${ready}/${desired} status:${signal.deployment?.rollout_status ?? "unknown"}`;
  }
  return `${String(signal.signal_type ?? "signal")} evidence loaded`;
}
