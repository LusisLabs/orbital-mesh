import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Binary,
  BookOpen,
  Bot,
  Check,
  ChevronDown,
  CircleDot,
  FolderGit2,
  GitBranch,
  Loader2,
  Maximize2,
  Minimize2,
  Play,
  Plus,
  ShieldCheck,
  SlidersHorizontal,
  TimerReset,
  Waves,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Background, Handle, Position, ReactFlow, type NodeProps } from "@xyflow/react";

import { api, connectRunStream, connectSystemStream, resolveBaseUrl } from "./api";
import { Inspector } from "./components/Inspector";
import { Toaster, useToast } from "./components/Toaster";
import { formatTimestamp, humanize, relativeTime, safeJsonParse, stageIcon } from "./lib/format";
import {
  buildArtifactGraph,
  buildKubernetesGraph,
  buildMerkleGraph,
  buildRunGraph,
  buildUnifiedGraph,
  toneForStage,
  type RunGraphNode,
} from "./lib/runGraph";
import type {
  ConnectionStatus,
  GoalRecord,
  InspectorTab,
  IntegrationReadiness,
  MerkleProof,
  ResearchSessionDetail,
  ResearchSessionRecord,
  RunDetail,
  RunEventRecord,
  RunSessionRecord,
  ScenarioRecord,
  VaultTreeEntry,
} from "./types";

const DEFAULT_GOAL_DRAFT = {
  title: "",
  objective: "",
  successCriteria: "",
};

const DEFAULT_LAUNCH_DRAFT = {
  signalSource: "scenario",
  evaluationMode: "native",
  orchestrationMode: "native",
  steeringMode: "approval_gate",
  scenarioKey: "",
  customSignal: "",
  liveDeploymentName: "semantic-search",
  liveNamespace: "search",
  liveKubeContext: "k3d-mesh-e2e",
  liveEnvironment: "local",
  liveService: "",
};

const RESEARCH_SAFE_LAUNCH_OVERRIDES = {
  evaluationMode: "promptfoo",
  orchestrationMode: "goose",
  steeringMode: "interruptible_auto",
} as const;

type RightRailTab = "steering" | InspectorTab;
type CanvasMode = "unified" | "flow" | "kubernetes" | "merkle" | "artifacts";

const nodeTypes = {
  runEvent: RunEventNode,
};

function rightRailTabLabel(tab: RightRailTab): string {
  if (tab === "steering") return "Controls";
  return humanize(tab);
}

function rightRailTabIcon(tab: RightRailTab): React.ReactNode {
  switch (tab) {
    case "overview":
      return <CircleDot size={15} />;
    case "steering":
      return <SlidersHorizontal size={15} />;
    case "evidence":
      return <Activity size={15} />;
    case "policy":
      return <ShieldCheck size={15} />;
    case "execution":
      return <Play size={15} />;
    case "feedback":
      return <Waves size={15} />;
    case "vault":
      return <BookOpen size={15} />;
    case "merkle":
      return <Binary size={15} />;
    case "code":
      return <FolderGit2 size={15} />;
    case "research":
      return <Bot size={15} />;
    default:
      return <CircleDot size={15} />;
  }
}

function canvasModeLabel(mode: CanvasMode): string {
  switch (mode) {
    case "unified":
      return "Unified";
    case "flow":
      return "Run Flow";
    case "kubernetes":
      return "Kubernetes";
    case "merkle":
      return "Merkle";
    case "artifacts":
      return "Artifacts";
    default:
      return "Canvas";
  }
}

function canvasModeIcon(mode: CanvasMode, size = 14): React.ReactNode {
  switch (mode) {
    case "unified":
      return <CircleDot size={size} />;
    case "flow":
      return <GitBranch size={size} />;
    case "kubernetes":
      return <Waves size={size} />;
    case "merkle":
      return <Binary size={size} />;
    case "artifacts":
      return <FolderGit2 size={size} />;
    default:
      return <CircleDot size={size} />;
  }
}

function inspectorTabForArtifact(artifactKey?: string | null): RightRailTab {
  switch (artifactKey) {
    case "input_signal":
    case "integration_readiness":
    case "normalized_event":
    case "trigger":
      return "evidence";
    case "decision":
    case "evaluation":
    case "promptfoo_artifact":
      return "policy";
    case "execution":
    case "goose_review":
      return "execution";
    case "feedback":
      return "feedback";
    default:
      return "overview";
  }
}

export default function App() {
  const [baseUrl] = useState(resolveBaseUrl);

  /* ── Core data ── */
  const [readiness, setReadiness] = useState<IntegrationReadiness | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioRecord[]>([]);
  const [goals, setGoals] = useState<GoalRecord[]>([]);
  const [runs, setRuns] = useState<RunSessionRecord[]>([]);
  const [researchSessions, setResearchSessions] = useState<ResearchSessionRecord[]>([]);
  const [activeResearchSessionId, setActiveResearchSessionId] = useState("");
  const [researchDetail, setResearchDetail] = useState<ResearchSessionDetail | null>(null);
  const [activeRun, setActiveRun] = useState<RunDetail | null>(null);
  const [activeRunId, setActiveRunId] = useState(
    () => new URLSearchParams(window.location.search).get("run") ?? "",
  );
  const [selectedGoalId, setSelectedGoalId] = useState("");

  /* ── Forms ── */
  const [goalDraft, setGoalDraft] = useState(DEFAULT_GOAL_DRAFT);
  const [launchDraft, setLaunchDraft] = useState(DEFAULT_LAUNCH_DRAFT);
  const [noteDraft, setNoteDraft] = useState("");
  const [overrideDecisionDraft, setOverrideDecisionDraft] = useState('{\n  "decision_type": "reduce_rollout"\n}');
  const [overrideParamsDraft, setOverrideParamsDraft] = useState('{\n  "rollout_pct": 5\n}');
  const [showGoalForm, setShowGoalForm] = useState(false);
  const [showOverrides, setShowOverrides] = useState(false);
  const [leftRailOpen, setLeftRailOpen] = useState(true);
  const [rightRailOpen, setRightRailOpen] = useState(true);
  const [canvasMode, setCanvasMode] = useState<CanvasMode>("unified");

  /* ── Inspector ── */
  const [rightRailTab, setRightRailTab] = useState<RightRailTab>("overview");
  const [selectedEventId, setSelectedEventId] = useState("");
  const [vaultDocument, setVaultDocument] = useState("");
  const [vaultTree, setVaultTree] = useState<VaultTreeEntry[] | null>(null);
  const [merkleProof, setMerkleProof] = useState<MerkleProof | null>(null);
  const [gitnexusInfo, setGitnexusInfo] = useState<Record<string, unknown> | null>(null);
  const [gitnexusProcesses, setGitnexusProcesses] = useState<Record<string, unknown> | null>(null);
  const [gitnexusSearch, setGitnexusSearch] = useState("feature flag remediation");
  const [gitnexusSearchResult, setGitnexusSearchResult] = useState<Record<string, unknown> | null>(null);

  /* ── Connection ── */
  const [systemConnection, setSystemConnection] = useState<ConnectionStatus>("reconnecting");
  const [runConnection, setRunConnection] = useState<ConnectionStatus>("reconnecting");

  /* ── Loading ── */
  const [booting, setBooting] = useState(true);
  const [launching, setLaunching] = useState(false);
  const [steering, setSteering] = useState("");
  const [creatingGoal, setCreatingGoal] = useState(false);

  /* ── Toast ── */
  const { toasts, addToast, dismissToast } = useToast();

  /* ── Refs ── */
  const timelineRef = useRef<HTMLDivElement>(null);
  const canvasPanelRef = useRef<HTMLDivElement>(null);
  const [canvasFullscreen, setCanvasFullscreen] = useState(false);

  const toggleCanvasFullscreen = useCallback(async () => {
    const el = canvasPanelRef.current;
    if (!el) return;
    const doc = document as Document & {
      webkitFullscreenElement?: Element | null;
      webkitExitFullscreen?: () => Promise<void>;
    };
    const fsNow = document.fullscreenElement ?? doc.webkitFullscreenElement ?? null;
    try {
      if (fsNow === el) {
        if (document.exitFullscreen) await document.exitFullscreen();
        else await doc.webkitExitFullscreen?.();
      } else {
        const anyEl = el as HTMLElement & { webkitRequestFullscreen?: () => Promise<void> };
        if (anyEl.requestFullscreen) await anyEl.requestFullscreen();
        else await anyEl.webkitRequestFullscreen?.();
      }
    } catch {
      addToast({ variant: "warning", title: "Fullscreen unavailable", description: "Your browser blocked or does not support fullscreen for this panel." });
    }
  }, [addToast]);

  /* ──────────── Effects ──────────── */

  useEffect(() => {
    const sync = () => {
      const panel = canvasPanelRef.current;
      const doc = document as Document & { webkitFullscreenElement?: Element | null };
      const fs = document.fullscreenElement ?? doc.webkitFullscreenElement ?? null;
      setCanvasFullscreen(panel ? fs === panel : false);
    };
    document.addEventListener("fullscreenchange", sync);
    document.addEventListener("webkitfullscreenchange", sync);
    return () => {
      document.removeEventListener("fullscreenchange", sync);
      document.removeEventListener("webkitfullscreenchange", sync);
    };
  }, []);

  useEffect(() => {
    void refreshBootstrap();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const close = connectSystemStream(baseUrl, {
      onSnapshot: (snapshot) => {
        setSystemConnection("connected");
        setRuns(snapshot.runs);
        setReadiness(snapshot.readiness);
        if (!activeRunId && snapshot.runs.length > 0) {
          setActiveRunId(snapshot.runs[0].run_id);
        }
      },
      onOpen: () => setSystemConnection("connected"),
      onError: () => setSystemConnection("reconnecting"),
    });
    return close;
  }, [baseUrl, activeRunId]);

  useEffect(() => {
    if (!activeRunId) {
      setActiveRun(null);
      setRunConnection("disconnected");
      return;
    }
    void loadRun(activeRunId);
    const close = connectRunStream(baseUrl, activeRunId, {
      onEvent: () => {
        setRunConnection("connected");
        void loadRun(activeRunId);
      },
      onOpen: () => setRunConnection("connected"),
      onError: () => setRunConnection("reconnecting"),
    });
    return close;
  }, [activeRunId, baseUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const url = new URL(window.location.href);
    if (activeRunId) url.searchParams.set("run", activeRunId);
    else url.searchParams.delete("run");
    window.history.replaceState(null, "", url.toString());
  }, [activeRunId]);

  useEffect(() => {
    if (!activeRun) {
      setVaultDocument("");
      setMerkleProof(null);
      return;
    }
    void api
      .getVaultDocument(baseUrl, `Runs/${activeRun.run_id}.md`)
      .then((doc) => setVaultDocument(doc.content))
      .catch(() => setVaultDocument(""));

    const proofEventId =
      selectedEventId ||
      activeRun.events.find((e) =>
        ["decision_ready", "evaluation_ready", "execution_recorded", "feedback_recorded"].includes(e.event_type),
      )?.event_id;
    if (proofEventId) {
      void api.getMerkleProof(baseUrl, activeRun.run_id, proofEventId).then(setMerkleProof).catch(() => setMerkleProof(null));
    } else {
      setMerkleProof(null);
    }
  }, [activeRun, baseUrl, selectedEventId]);

  useEffect(() => {
    if (!readiness?.gitnexus.ready || !readiness.gitnexus.url) return;
    void api.getGitNexusInfo(readiness.gitnexus.url).then(setGitnexusInfo).catch(() => setGitnexusInfo(null));
    void api.getGitNexusProcesses(readiness.gitnexus.url).then(setGitnexusProcesses).catch(() => setGitnexusProcesses(null));
  }, [readiness?.gitnexus.ready, readiness?.gitnexus.url]);

  useEffect(() => {
    void api.getVaultTree(baseUrl).then((r) => setVaultTree(r.tree)).catch(() => setVaultTree(null));
  }, [baseUrl]);

  useEffect(() => {
    if (timelineRef.current) {
      timelineRef.current.scrollTop = timelineRef.current.scrollHeight;
    }
  }, [activeRun?.events.length]);

  useEffect(() => {
    if (!activeRun?.events?.length) {
      setSelectedEventId("");
      return;
    }
    setSelectedEventId((current) => {
      if (current && activeRun.events.some((event) => event.event_id === current)) {
        return current;
      }
      return activeRun.latest_event_id ?? activeRun.events[activeRun.events.length - 1].event_id;
    });
  }, [activeRun]);

  /* ──────────── Actions ──────────── */

  async function refreshBootstrap() {
    try {
      const [readinessRes, scenariosRes, goalsRes, runsRes, researchRes] = await Promise.all([
        api.getReadiness(baseUrl),
        api.getScenarios(baseUrl),
        api.getGoals(baseUrl),
        api.getRuns(baseUrl),
        api.getResearchSessions(baseUrl),
      ]);
      setReadiness(readinessRes);
      setScenarios(scenariosRes.scenarios);
      setGoals(goalsRes.goals);
      setRuns(runsRes.runs);
      setResearchSessions(researchRes.sessions);
      if (!selectedGoalId && goalsRes.goals[0]) setSelectedGoalId(goalsRes.goals[0].goal_id);
      if (!activeRunId && runsRes.runs[0]) setActiveRunId(runsRes.runs[0].run_id);
      if (scenariosRes.scenarios[0] && !launchDraft.scenarioKey) {
        setLaunchDraft((d) => ({ ...d, scenarioKey: scenariosRes.scenarios[0].key }));
      }
    } catch (error) {
      addToast({
        variant: "error",
        title: "Connection Failed",
        description: error instanceof Error ? error.message : "Could not reach control plane.",
      });
    } finally {
      setBooting(false);
    }
  }

  async function loadRun(runId: string) {
    try {
      const run = await api.getRun(baseUrl, runId);
      setActiveRun(run);
    } catch (error) {
      addToast({ variant: "error", title: "Failed to load run", description: error instanceof Error ? error.message : "Unknown error" });
    }
  }

  async function handleSelectResearchSession(sessionId: string) {
    setActiveRunId("");
    setActiveResearchSessionId(sessionId);
    setRightRailTab("research");
    try {
      const detail = await api.getResearchSession(baseUrl, sessionId);
      setResearchDetail(detail);
    } catch (error) {
      setResearchDetail(null);
      addToast({
        variant: "error",
        title: "Failed to load research session",
        description: error instanceof Error ? error.message : "Unknown error",
      });
    }
  }

  async function handleCreateGoal() {
    if (!goalDraft.title.trim()) {
      addToast({ variant: "warning", title: "Goal title required" });
      return;
    }
    setCreatingGoal(true);
    try {
      const goal = await api.createGoal(baseUrl, {
        title: goalDraft.title.trim(),
        objective: goalDraft.objective.trim(),
        success_criteria: goalDraft.successCriteria
          .split(",")
          .map((c) => c.trim())
          .filter(Boolean),
      });
      setGoals((prev) => [goal, ...prev]);
      setSelectedGoalId(goal.goal_id);
      setGoalDraft(DEFAULT_GOAL_DRAFT);
      setShowGoalForm(false);
      addToast({ variant: "success", title: "Goal created", description: goal.title });
    } catch (error) {
      addToast({ variant: "error", title: "Failed to create goal", description: error instanceof Error ? error.message : "Unknown error" });
    } finally {
      setCreatingGoal(false);
    }
  }

  async function handleLaunchRun() {
    setLaunching(true);
    try {
      const payload: Record<string, unknown> = {
        goal_id: selectedGoalId || goals[0]?.goal_id,
        evaluation_mode: launchDraft.evaluationMode,
        orchestration_mode: launchDraft.orchestrationMode,
        steering_mode: launchDraft.steeringMode,
      };
      if (launchDraft.signalSource === "custom") {
        const parsed = safeJsonParse(launchDraft.customSignal);
        if (!parsed.ok) {
          addToast({ variant: "error", title: "Invalid signal JSON", description: parsed.error });
          setLaunching(false);
          return;
        }
        payload.signal_payload = parsed.data;
      } else if (launchDraft.signalSource === "live_kubernetes") {
        if (!launchDraft.liveDeploymentName.trim()) {
          addToast({ variant: "warning", title: "Deployment name required", description: "Enter a Kubernetes deployment to harvest." });
          setLaunching(false);
          return;
        }
        payload.live_signal = {
          source: "kubernetes",
          deployment_name: launchDraft.liveDeploymentName.trim(),
          namespace: launchDraft.liveNamespace.trim() || "default",
          kube_context: launchDraft.liveKubeContext.trim() || undefined,
          environment: launchDraft.liveEnvironment.trim() || "local",
          service: launchDraft.liveService.trim() || undefined,
        };
      } else {
        if (!launchDraft.scenarioKey) {
          addToast({ variant: "warning", title: "Scenario required", description: "Choose a fixture scenario or switch signal source." });
          setLaunching(false);
          return;
        }
        payload.scenario_key = launchDraft.scenarioKey;
      }
      if (launchDraft.steeringMode === "interruptible_auto") {
        payload.pause_points = [];
      }
      const run = await api.createRun(baseUrl, payload);
      setActiveRunId(run.run_id);
      addToast({ variant: "success", title: "Run launched", description: `${run.scenario_key ?? "manual"} started` });
      await refreshBootstrap();
    } catch (error) {
      addToast({ variant: "error", title: "Failed to launch run", description: error instanceof Error ? error.message : "Unknown error" });
    } finally {
      setLaunching(false);
    }
  }

  const handleSteer = useCallback(
    async (command: string, payload: Record<string, unknown> = {}) => {
      if (!activeRunId) return;
      setSteering(command);
      try {
        await api.steerRun(baseUrl, activeRunId, { command, ...payload });
        await loadRun(activeRunId);
        addToast({ variant: "success", title: `Run ${humanize(command).toLowerCase()}d` });
      } catch (error) {
        addToast({ variant: "error", title: `Steer failed`, description: error instanceof Error ? error.message : "Unknown error" });
      } finally {
        setSteering("");
      }
    },
    [activeRunId, baseUrl, addToast], // eslint-disable-line react-hooks/exhaustive-deps
  );

  async function handleGitNexusSearch() {
    if (!readiness?.gitnexus.url) return;
    try {
      const result = await api.searchGitNexus(readiness.gitnexus.url, gitnexusSearch);
      setGitnexusSearchResult(result);
    } catch (error) {
      setGitnexusSearchResult({ error: error instanceof Error ? error.message : "Search failed" });
    }
  }

  function handleVaultSelect(path: string) {
    void api
      .getVaultDocument(baseUrl, path)
      .then((doc) => setVaultDocument(doc.content))
      .catch(() => setVaultDocument("Document unavailable."));
  }

  function handleOverrideDecision() {
    const parsed = safeJsonParse(overrideDecisionDraft);
    if (!parsed.ok) {
      addToast({ variant: "error", title: "Invalid JSON", description: parsed.error });
      return;
    }
    void handleSteer("override_decision", parsed.data);
  }

  function handleOverrideParams() {
    const parsed = safeJsonParse(overrideParamsDraft);
    if (!parsed.ok) {
      addToast({ variant: "error", title: "Invalid JSON", description: parsed.error });
      return;
    }
    void handleSteer("override_execution_parameters", { parameters: parsed.data });
  }

  /* ──────────── Derived ──────────── */

  const flowCanvas = useMemo(
    () => buildRunGraph(activeRun?.events ?? [], selectedEventId),
    [activeRun?.events, selectedEventId],
  );
  const kubernetesCanvas = useMemo(
    () =>
      buildKubernetesGraph(
        (activeRun?.artifacts?.input_signal ?? activeRun?.artifacts?.trigger ?? null) as Record<string, unknown> | null,
      ),
    [activeRun?.artifacts],
  );
  const merkleCanvas = useMemo(
    () => buildMerkleGraph(activeRun?.merkle ?? null, merkleProof),
    [activeRun?.merkle, merkleProof],
  );
  const artifactCanvas = useMemo(
    () =>
      buildArtifactGraph(
        activeRun
          ? {
              artifacts: activeRun.artifacts,
              stage: activeRun.stage,
              status: activeRun.status,
            }
          : null,
      ),
    [activeRun],
  );
  const unifiedCanvas = useMemo(
    () =>
      buildUnifiedGraph({
        flow: flowCanvas,
        kubernetes: kubernetesCanvas,
        merkle: merkleCanvas,
        artifacts: artifactCanvas,
      }),
    [artifactCanvas, flowCanvas, kubernetesCanvas, merkleCanvas],
  );
  const canvasGraph = useMemo(() => {
    switch (canvasMode) {
      case "unified":
        return unifiedCanvas;
      case "kubernetes":
        return kubernetesCanvas;
      case "merkle":
        return merkleCanvas;
      case "artifacts":
        return artifactCanvas;
      case "flow":
      default:
        return flowCanvas;
    }
  }, [artifactCanvas, canvasMode, flowCanvas, kubernetesCanvas, merkleCanvas, unifiedCanvas]);
  const canvasAvailability = useMemo(
    () => ({
      unified: unifiedCanvas.nodes.length > 0,
      flow: flowCanvas.nodes.length > 0,
      kubernetes: kubernetesCanvas.nodes.length > 0,
      merkle: merkleCanvas.nodes.length > 0,
      artifacts: artifactCanvas.nodes.length > 0,
    }),
    [
      artifactCanvas.nodes.length,
      flowCanvas.nodes.length,
      kubernetesCanvas.nodes.length,
      merkleCanvas.nodes.length,
      unifiedCanvas.nodes.length,
    ],
  );
  const canvasEmptyMessage = useMemo(() => {
    switch (canvasMode) {
      case "unified":
        return "Launch a run to see the unified execution canvas.";
      case "kubernetes":
        return "This run does not include a Kubernetes deployment signal.";
      case "merkle":
        return "This run has no Merkle snapshot available yet.";
      case "artifacts":
        return "This run has not produced artifact snapshots yet.";
      case "flow":
      default:
        return "Launch a run to see the execution graph.";
    }
  }, [canvasMode]);
  const canvasFitPadding = canvasMode === "unified" ? 0.08 : canvasMode === "flow" ? 0.12 : canvasMode === "artifacts" ? 0.16 : 0.2;

  const selectedEvent = useMemo(() => {
    if (!activeRun?.events?.length) return null;
    return activeRun.events.find((event) => event.event_id === selectedEventId) ?? activeRun.events[activeRun.events.length - 1];
  }, [activeRun?.events, selectedEventId]);
  const selectedEventInsights = useMemo(
    () => (selectedEvent ? buildEventInsights(selectedEvent) : []),
    [selectedEvent],
  );
  const selectedEventIndex = useMemo(
    () => (selectedEvent && activeRun ? activeRun.events.findIndex((event) => event.event_id === selectedEvent.event_id) : -1),
    [activeRun, selectedEvent],
  );

  const activeGoal = goals.find(
    (g) => g.goal_id === (activeRun?.goal_id ?? selectedGoalId),
  ) ?? goals[0] ?? null;
  const activeEvaluation = activeRun?.artifacts.evaluation as Record<string, any> | undefined;
  const approvalBlockedEvent = activeRun?.events
    ?.slice()
    .reverse()
    .find((event) => event.event_type === "approval_blocked");
  const approvalBlockingReasons = (
    approvalBlockedEvent?.payload?.blocking_reasons ??
    activeEvaluation?.blocking_reasons ??
    []
  ) as string[];
  const approvalRecommendation = String(
    approvalBlockedEvent?.payload?.final_recommendation ??
    activeEvaluation?.final_recommendation ??
    "",
  );
  const approvalCurrentlyBlocked =
    activeRun?.stage === "awaiting_operator" &&
    activeRun?.pending_pause_stage === "evaluation_ready" &&
    approvalRecommendation !== "" &&
    approvalRecommendation !== "execute";

  const integrationsReady = readiness
    ? [readiness.promptfoo, readiness.goose, readiness.gitnexus].filter((i) => i.ready).length
    : 0;
  const inferencePrimaryRoute = readiness?.goose.primary_route ?? "Booting";
  const inferenceFallbackRoute = readiness?.goose.fallback_route ?? null;
  const inferenceWarning = readiness?.goose.warnings?.[0] ?? null;

  useEffect(() => {
    if (!activeRun) return;
    if (canvasAvailability[canvasMode]) return;
    if (canvasAvailability.unified) {
      setCanvasMode("unified");
      return;
    }
    if (canvasAvailability.flow) {
      setCanvasMode("flow");
      return;
    }
    if (canvasAvailability.artifacts) {
      setCanvasMode("artifacts");
      return;
    }
    if (canvasAvailability.kubernetes) {
      setCanvasMode("kubernetes");
      return;
    }
    if (canvasAvailability.merkle) {
      setCanvasMode("merkle");
    }
  }, [activeRun, canvasAvailability, canvasMode]);

  /* ──────────── Render ──────────── */

  if (booting) {
    return (
      <div className="boot-screen">
        <Loader2 className="spin" size={32} />
        <p>Connecting to control plane…</p>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <Toaster toasts={toasts} onDismiss={dismissToast} />

      {/* ─── Top Bar ─── */}
      <header className="topbar">
        <div className="topbar-brand">
          <div className="brand-icon"><Zap size={16} /></div>
          <div>
            <p className="eyebrow">Mesh Intelligence</p>
            <h1>Operator Control Plane</h1>
          </div>
        </div>
        <div className="topbar-grid">
          <HeaderMetric icon={<Bot size={16} />} label="Environment" value={readiness ? "Local" : "Booting"} />
          <HeaderMetric
            icon={<ShieldCheck size={16} />}
            label="Integrations"
            value={`${integrationsReady}/3 ready`}
            tone={integrationsReady === 3 ? "good" : integrationsReady > 0 ? "warn" : "danger"}
          />
          <HeaderMetric
            icon={<CircleDot size={16} />}
            label="Operator Mode"
            value={humanize(activeRun?.steering_mode ?? launchDraft.steeringMode)}
          />
          <InferenceMetric
            icon={<Zap size={16} />}
            primaryRoute={inferencePrimaryRoute}
            fallbackRoute={inferenceFallbackRoute}
            warning={inferenceWarning}
            ready={Boolean(readiness?.goose.ready)}
          />
          <HeaderMetric
            icon={<Waves size={16} />}
            label="System"
            value={systemConnection === "connected" ? "Connected" : "Reconnecting…"}
            tone={systemConnection === "connected" ? "good" : "warn"}
          />
        </div>
        <div className="topbar-actions">
          <button className="action-button compact" type="button" onClick={() => setLeftRailOpen((open) => !open)}>
            {leftRailOpen ? "Hide Sessions" : "Show Sessions"}
          </button>
          <button className="action-button compact primary" type="button" onClick={() => setRightRailOpen((open) => !open)}>
            <SlidersHorizontal size={13} />
            Controls
          </button>
        </div>
      </header>

      {/* ─── Workspace ─── */}
      <main className={`workspace ${leftRailOpen ? "" : "workspace-left-collapsed"} ${rightRailOpen ? "" : "workspace-right-collapsed"}`}>
        {!leftRailOpen && (
          <button className="drawer-peek left" type="button" onClick={() => setLeftRailOpen(true)}>
            Sessions
          </button>
        )}

        {/* ── Left Rail ── */}
        {leftRailOpen && (
        <aside className="left-rail panel">
          <div className="rail-heading">
            <SectionTitle icon={<GitBranch size={15} />} title="Sessions" />
            <button className="icon-btn" type="button" onClick={() => setLeftRailOpen(false)} title="Hide sessions">
              <ChevronDown size={14} className="rotate-90" />
            </button>
          </div>
          <div className="session-summary">
            <div>
              <strong>{runs.length}</strong>
              <span>Runs</span>
            </div>
            <div>
              <strong>{researchSessions.length}</strong>
              <span>Research</span>
            </div>
            <div>
              <strong>{integrationsReady}/3</strong>
              <span>Ready</span>
            </div>
          </div>

          <details className="rail-disclosure">
            <summary>
              <span>Integrations</span>
              <span>{integrationsReady}/3 ready</span>
            </summary>
          <div className="readiness-grid">
            <ReadinessCard label="Promptfoo" status={readiness?.promptfoo} />
            <ReadinessCard label="Goose" status={readiness?.goose} />
            <ReadinessCard label="GitNexus" status={readiness?.gitnexus} />
          </div>
          </details>

          <div className="section-header">
            <SectionTitle icon={<Binary size={15} />} title="Goals" />
            <button
              className="icon-btn"
              onClick={() => setShowGoalForm((v) => !v)}
              title="Add goal"
            >
              <Plus size={14} />
            </button>
          </div>
          <div className="stack">
            {goals.map((goal) => (
              <button
                key={goal.goal_id}
                className={`list-card ${selectedGoalId === goal.goal_id ? "selected" : ""}`}
                onClick={() => setSelectedGoalId(goal.goal_id)}
              >
                <strong>{goal.title}</strong>
                <span className="list-card-sub">{goal.objective}</span>
              </button>
            ))}
            {goals.length === 0 && <EmptyState text="No goals yet" />}
          </div>

          {showGoalForm && (
            <div className="composer animate-in">
              <input
                value={goalDraft.title}
                onChange={(e) => setGoalDraft({ ...goalDraft, title: e.target.value })}
                placeholder="Goal title"
                autoFocus
              />
              <textarea
                value={goalDraft.objective}
                onChange={(e) => setGoalDraft({ ...goalDraft, objective: e.target.value })}
                placeholder="Objective"
                className="small-textarea"
              />
              <input
                value={goalDraft.successCriteria}
                onChange={(e) => setGoalDraft({ ...goalDraft, successCriteria: e.target.value })}
                placeholder="Success criteria (comma-separated)"
              />
              <button className="action-button" onClick={() => void handleCreateGoal()} disabled={creatingGoal}>
                {creatingGoal ? <Loader2 size={14} className="spin" /> : <Check size={14} />}
                {creatingGoal ? "Creating…" : "Create Goal"}
              </button>
            </div>
          )}

          <SectionTitle icon={<TimerReset size={15} />} title="Launch Run" />
          <div className="stack">
            <div className="launch-preset-row">
              <button
                className="action-button compact"
                onClick={() => setLaunchDraft((draft) => ({ ...draft, ...RESEARCH_SAFE_LAUNCH_OVERRIDES }))}
                type="button"
              >
                <ShieldCheck size={14} />
                Research Safe
              </button>
              <p className="helper-text">Evaluation + Orchestration + Interruptible Auto with no default pause points.</p>
            </div>
            <div className="select-wrap">
              <select
                value={launchDraft.signalSource}
                onChange={(e) => setLaunchDraft({ ...launchDraft, signalSource: e.target.value })}
              >
                <option value="scenario">Signal: Fixture Scenario</option>
                <option value="live_kubernetes">Signal: Live Kubernetes Deployment</option>
                <option value="custom">Signal: Custom JSON</option>
              </select>
              <ChevronDown size={14} className="select-icon" />
            </div>
            {launchDraft.signalSource === "scenario" && scenarios.length > 0 && (
              <div className="select-wrap">
                <select value={launchDraft.scenarioKey} onChange={(e) => setLaunchDraft({ ...launchDraft, scenarioKey: e.target.value })}>
                  {scenarios.map((s) => (
                    <option key={s.key} value={s.key}>{s.title}</option>
                  ))}
                </select>
                <ChevronDown size={14} className="select-icon" />
              </div>
            )}
            {launchDraft.signalSource === "live_kubernetes" && (
              <>
                <div className="two-col">
                  <input
                    value={launchDraft.liveDeploymentName}
                    onChange={(e) => setLaunchDraft({ ...launchDraft, liveDeploymentName: e.target.value })}
                    placeholder="Deployment name"
                  />
                  <input
                    value={launchDraft.liveNamespace}
                    onChange={(e) => setLaunchDraft({ ...launchDraft, liveNamespace: e.target.value })}
                    placeholder="Namespace"
                  />
                </div>
                <div className="two-col">
                  <input
                    value={launchDraft.liveKubeContext}
                    onChange={(e) => setLaunchDraft({ ...launchDraft, liveKubeContext: e.target.value })}
                    placeholder="Kube context"
                  />
                  <input
                    value={launchDraft.liveEnvironment}
                    onChange={(e) => setLaunchDraft({ ...launchDraft, liveEnvironment: e.target.value })}
                    placeholder="Mesh environment"
                  />
                </div>
                <input
                  value={launchDraft.liveService}
                  onChange={(e) => setLaunchDraft({ ...launchDraft, liveService: e.target.value })}
                  placeholder="Optional service label override"
                />
                <p className="helper-text">
                  The control plane will harvest the live deployment state with backend <code>kubectl</code> access and launch the run directly from that snapshot.
                </p>
              </>
            )}
            <div className="two-col">
              <div className="select-wrap">
                <select value={launchDraft.evaluationMode} onChange={(e) => setLaunchDraft({ ...launchDraft, evaluationMode: e.target.value })}>
                  <option value="native">Eval: Native</option>
                  <option value="promptfoo">Eval: Promptfoo</option>
                </select>
                <ChevronDown size={14} className="select-icon" />
              </div>
              <div className="select-wrap">
                <select value={launchDraft.orchestrationMode} onChange={(e) => setLaunchDraft({ ...launchDraft, orchestrationMode: e.target.value })}>
                  <option value="native">Orch: Native</option>
                  <option value="hermes">Orch: Hermes</option>
                  <option value="goose">Orch: Goose</option>
                </select>
                <ChevronDown size={14} className="select-icon" />
              </div>
            </div>
            <div className="select-wrap">
              <select value={launchDraft.steeringMode} onChange={(e) => setLaunchDraft({ ...launchDraft, steeringMode: e.target.value })}>
                <option value="approval_gate">Approval Gate</option>
                <option value="interruptible_auto">Interruptible Auto</option>
              </select>
              <ChevronDown size={14} className="select-icon" />
            </div>
            {launchDraft.signalSource === "custom" && (
              <textarea
                value={launchDraft.customSignal}
                onChange={(e) => setLaunchDraft({ ...launchDraft, customSignal: e.target.value })}
                placeholder="Raw signal JSON…"
                className="small-textarea mono-textarea"
              />
            )}
            <button className="action-button primary" onClick={() => void handleLaunchRun()} disabled={launching}>
              {launching ? <Loader2 size={15} className="spin" /> : <Play size={15} />}
              {launching ? "Launching…" : "Launch Run"}
            </button>
          </div>

          <SectionTitle icon={<GitBranch size={15} />} title="Run Sessions" />
          <div className="stack">
            {runs.map((run) => (
              <button
                key={run.run_id}
                className={`list-card run-card ${activeRunId === run.run_id ? "selected" : ""}`}
                onClick={() => {
                  setActiveResearchSessionId("");
                  setResearchDetail(null);
                  setActiveRunId(run.run_id);
                  setRightRailTab("overview");
                }}
              >
                <div className="run-card-header">
                  <strong>{run.scenario_key ?? "manual"}</strong>
                  <span className="run-stage-badge" data-stage={run.stage}>
                    {stageIcon(run.stage)}
                  </span>
                </div>
                <div className="run-card-meta">
                  <span>{humanize(run.stage)}</span>
                  <span>{run.latest_event_sequence} threads</span>
                  <span>{relativeTime(run.updated_at)}</span>
                </div>
              </button>
            ))}
            {runs.length === 0 && <EmptyState text="No runs yet" />}
          </div>

          <SectionTitle icon={<BookOpen size={15} />} title="Autonomous Research" />
          <p className="helper-text" style={{ margin: "0 0 0.5rem" }}>
            Autoresearch from <code>run_minimax_research.py</code> (file-backed sessions). Refresh the page after a CLI run
            to list new sessions.
          </p>
          <div className="stack">
            {researchSessions.map((s) => (
              <button
                key={s.session_id}
                className={`list-card run-card ${activeResearchSessionId === s.session_id ? "selected" : ""}`}
                type="button"
                onClick={() => void handleSelectResearchSession(s.session_id)}
              >
                <div className="run-card-header">
                  <strong>{s.directory.slice(0, 36)}{s.directory.length > 36 ? "…" : ""}</strong>
                  <span className="run-stage-badge" data-stage="completed">
                    {s.has_final_report ? "◆" : "○"}
                  </span>
                </div>
                <div className="run-card-meta">
                  <span>{s.research_intelligence ? humanize(s.research_intelligence.classification) : s.minimax_route ?? "—"}</span>
                  <span>{relativeTime(s.updated_at)}</span>
                </div>
              </button>
            ))}
            {researchSessions.length === 0 && <EmptyState text="No research sessions yet" />}
          </div>
        </aside>
        )}

        {/* ── Center Stage ── */}
        <section className="center-stage auto-canvas-stage">
          <div className="panel center-header canvas-command-bar">
            <div className="center-header-main">
              <div className="center-header-text">
                <p className="eyebrow">Active Goal</p>
                <h2>{activeGoal?.title ?? "No goal selected"}</h2>
                <p className="muted">{activeGoal?.objective ?? "Create a goal or select the default goal to begin."}</p>
                {activeRun?.stage === "awaiting_operator" && (
                  <div className={`run-gate-banner ${approvalCurrentlyBlocked ? "danger" : "warn"}`}>
                    <AlertTriangle size={14} />
                    <div>
                      <strong>
                        {approvalCurrentlyBlocked
                          ? `Approval blocked: ${humanize(approvalRecommendation)}`
                          : "Awaiting operator approval"}
                      </strong>
                      <p>
                        {approvalCurrentlyBlocked
                          ? "Execution is paused until you resolve the blocking evaluation issues or override the decision."
                          : "This run is paused at the operator gate and can continue when approved."}
                      </p>
                      {approvalBlockingReasons.length > 0 && (
                        <ul className="banner-reason-list">
                          {approvalBlockingReasons.slice(0, 3).map((reason, index) => (
                            <li key={`${reason}-${index}`}>{reason}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                )}
              </div>
              <div className="tab-strip canvas-mode-strip" role="tablist" aria-label="Canvas mode">
                {(["unified", "flow", "kubernetes", "merkle", "artifacts"] as CanvasMode[]).map((mode) => (
                  <button
                    key={mode}
                    className={canvasMode === mode ? "tab active" : "tab"}
                    type="button"
                    disabled={!canvasAvailability[mode]}
                    onClick={() => setCanvasMode(mode)}
                    title={
                      canvasAvailability[mode]
                        ? `${canvasModeLabel(mode)} canvas`
                        : `${canvasModeLabel(mode)} unavailable for this run`
                    }
                  >
                    {canvasModeIcon(mode)}
                    {canvasModeLabel(mode)}
                  </button>
                ))}
              </div>
            </div>
            <div className="status-row">
              <StatusChip label={activeRun ? humanize(activeRun.stage) : "Idle"} tone={toneForStage(activeRun?.stage ?? "queued")} />
              {activeRun?.latest_merkle_root && (
                <StatusChip label={`⧫ ${activeRun.latest_merkle_root.slice(0, 10)}`} tone="#41d6b1" />
              )}
              <ConnectionDot status={systemConnection} label="System" />
              <ConnectionDot status={runConnection} label="Run" />
            </div>
          </div>

          <div className="center-grid auto-canvas-grid">
            <div ref={canvasPanelRef} className="panel graph-panel">
              <div className="graph-panel-fs-toolbar">
                <button
                  type="button"
                  className="icon-btn graph-panel-fs-btn"
                  onClick={() => void toggleCanvasFullscreen()}
                  title={canvasFullscreen ? "Exit canvas fullscreen (Esc)" : "Fullscreen canvas"}
                  aria-pressed={canvasFullscreen}
                >
                  {canvasFullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
                </button>
              </div>
              {activeRun && canvasGraph.nodes.length > 0 ? (
                <ReactFlow
                  fitView
                  fitViewOptions={{ padding: canvasFitPadding }}
                  minZoom={canvasMode === "unified" ? 0.08 : canvasMode === "flow" ? 0.3 : 0.22}
                  nodes={canvasGraph.nodes}
                  edges={canvasGraph.edges}
                  nodeTypes={nodeTypes}
                  nodesDraggable={false}
                  nodesConnectable={false}
                  elementsSelectable={false}
                  onNodeClick={(_, node) => {
                    const eventId = String(node.data?.eventId ?? "");
                    if (eventId) setSelectedEventId(eventId);
                    if (node.data?.nodeKind === "merkle") {
                      setRightRailTab("merkle");
                      return;
                    }
                    if (node.data?.nodeKind === "kubernetes") {
                      setRightRailTab("evidence");
                      return;
                    }
                    if (node.data?.nodeKind === "artifact") {
                      setRightRailTab(inspectorTabForArtifact(String(node.data?.artifactKey ?? "")));
                      return;
                    }
                    if (rightRailTab === "research") setRightRailTab("overview");
                  }}
                  proOptions={{ hideAttribution: true }}
                >
                  <Background color="#1a2a38" gap={24} />
                </ReactFlow>
              ) : (
                <EmptyState text={canvasEmptyMessage} icon={canvasModeIcon(canvasMode, 28)} />
              )}
            </div>

            <div className="panel timeline-panel">
              <SectionTitle icon={<Activity size={15} />} title="Live Timeline" />
              <div className="timeline" ref={timelineRef}>
                {(activeRun?.events ?? []).map((event, i) => (
                  <button
                    key={event.event_id}
                    className={`timeline-card timeline-card-button ${selectedEvent?.event_id === event.event_id ? "selected" : ""}`}
                    style={{ animationDelay: `${i * 40}ms` }}
                    onClick={() => {
                      setSelectedEventId(event.event_id);
                      if (rightRailTab === "research") setRightRailTab("overview");
                    }}
                  >
                    <div className="timeline-heading">
                      <div className="timeline-heading-left">
                        <span className="timeline-seq">{event.sequence}</span>
                        <strong>{humanize(event.event_type)}</strong>
                      </div>
                      <span className="timeline-stage" data-stage={event.stage}>
                        {humanize(event.stage)}
                      </span>
                    </div>
                    <span className="timeline-time">{formatTimestamp(event.recorded_at)}</span>
                    {event.summary && Object.keys(event.summary).length > 0 && (
                      <pre className="timeline-summary">{JSON.stringify(event.summary, null, 2)}</pre>
                    )}
                  </button>
                ))}
                {(!activeRun || activeRun.events.length === 0) && (
                  <EmptyState text="Events will appear here as the run progresses." />
                )}
              </div>
            </div>
          </div>
        </section>

        {/* ── Right Rail ── */}
        {!rightRailOpen && (
          <button className="drawer-peek right" type="button" onClick={() => setRightRailOpen(true)}>
            Controls
          </button>
        )}
        {rightRailOpen && (
        <aside className="right-rail panel">
          <div className="rail-heading">
            <SectionTitle
              icon={rightRailTabIcon(rightRailTab)}
              title={rightRailTabLabel(rightRailTab)}
            />
            <button className="icon-btn" type="button" onClick={() => setRightRailOpen(false)} title="Hide controls">
              <ChevronDown size={14} className="rotate-270" />
            </button>
          </div>
          <div className="tab-strip">
            {(
              [
                "overview",
                "steering",
                "evidence",
                "policy",
                "execution",
                "feedback",
                "vault",
                "merkle",
                "code",
                "research",
              ] as RightRailTab[]
            ).map((tab) => (
              <button
                key={tab}
                className={rightRailTab === tab ? "tab active" : "tab"}
                onClick={() => setRightRailTab(tab)}
              >
                {rightRailTabIcon(tab)}
                {rightRailTabLabel(tab)}
              </button>
            ))}
          </div>
          {rightRailTab === "overview" ? (
            <CanvasOverviewPanel
              run={activeRun}
              event={selectedEvent}
              insights={selectedEventInsights}
              eventIndex={selectedEventIndex}
              eventCount={activeRun?.events.length ?? 0}
              onJumpTab={(tab) => setRightRailTab(tab)}
            />
          ) : rightRailTab === "steering" ? (
            <SteeringConsolePanel
              activeRun={activeRun}
              activeRunId={activeRunId}
              activeEvent={selectedEvent}
              active={steering}
              approvalCurrentlyBlocked={approvalCurrentlyBlocked}
              noteDraft={noteDraft}
              onNoteDraftChange={setNoteDraft}
              onSteer={handleSteer}
              showOverrides={showOverrides}
              onToggleOverrides={() => setShowOverrides((v) => !v)}
              overrideDecisionDraft={overrideDecisionDraft}
              onOverrideDecisionDraftChange={setOverrideDecisionDraft}
              onOverrideDecision={handleOverrideDecision}
              overrideParamsDraft={overrideParamsDraft}
              onOverrideParamsDraftChange={setOverrideParamsDraft}
              onOverrideParams={handleOverrideParams}
            />
          ) : (
            <Inspector
              tab={rightRailTab}
              run={activeRun}
              researchDetail={researchDetail}
              vaultDocument={vaultDocument}
              vaultTree={vaultTree}
              merkleProof={merkleProof}
              gitnexusInfo={gitnexusInfo}
              gitnexusProcesses={gitnexusProcesses}
              gitnexusSearch={gitnexusSearch}
              gitnexusSearchResult={gitnexusSearchResult}
              onGitnexusSearchChange={setGitnexusSearch}
              onGitnexusSearch={handleGitNexusSearch}
              onVaultSelect={handleVaultSelect}
            />
          )}
        </aside>
        )}
      </main>
    </div>
  );
}

/* ──────────── Inline components ──────────── */

function RunEventNode({ data, selected }: NodeProps<RunGraphNode>) {
  const tone = typeof data.accent === "string" ? data.accent : toneForStage(String(data.stage));
  const badgeLabel =
    data.nodeKind === "run" && Number(data.sequence) > 0
      ? String(data.sequence)
      : data.nodeKind === "kubernetes"
        ? "K8s"
      : data.nodeKind === "merkle"
        ? "Hash"
        : data.nodeKind === "section"
          ? "View"
          : "Data";
  const meta = Array.isArray(data.meta)
    ? data.meta.filter((value): value is string => typeof value === "string" && value.trim().length > 0).slice(0, 2)
    : [];
  const nodeTitle = typeof data.title === "string" ? data.title : String(data.eventType);
  const statusLabel = typeof data.statusLabel === "string" ? data.statusLabel : humanize(String(data.stage));
  const preview = typeof data.preview === "string" && data.preview.trim().length > 0 ? data.preview : "No additional detail";
  const tooltipBits = [nodeTitle, statusLabel];
  if (data.recordedAt) tooltipBits.push(formatTimestamp(String(data.recordedAt)));

  return (
    <div
      className={`run-event-node ${selected ? "selected" : ""}`}
      style={{ borderColor: tone, boxShadow: selected ? `0 0 0 1px ${tone}, 0 12px 28px ${tone}33` : undefined }}
      title={tooltipBits.join(" • ")}
    >
      <Handle className="run-event-handle" type="target" position={Position.Left} isConnectable={false} />
      <div className="run-event-node-header">
        <span className="run-event-node-seq">{badgeLabel}</span>
        <span className="run-event-node-stage" style={{ color: tone }}>
          {statusLabel}
        </span>
      </div>
      <strong className="run-event-node-title">{nodeTitle}</strong>
      <span className="run-event-node-preview">{preview}</span>
      {meta.length > 0 && (
        <div className="run-event-node-meta">
          {meta.map((entry) => (
            <span key={entry}>{entry}</span>
          ))}
        </div>
      )}
      <Handle className="run-event-handle" type="source" position={Position.Right} isConnectable={false} />
    </div>
  );
}

function CanvasOverviewPanel({
  run,
  event,
  insights,
  eventIndex,
  eventCount,
  onJumpTab,
}: {
  run: RunDetail | null;
  event: RunEventRecord | null;
  insights: Array<{ label: string; value: string; tone?: string }>;
  eventIndex: number;
  eventCount: number;
  onJumpTab: (tab: RightRailTab) => void;
}) {
  if (!run || !event) {
    return <EmptyState text="Select a node to inspect its path, payload, and controls." />;
  }

  return (
    <div className="inspector-scroll">
      <section className="context-panel">
        <div className="context-panel-header">
          <div>
            <p className="eyebrow">Canvas Overview</p>
            <h4>{humanize(event.event_type)}</h4>
          </div>
          <StatusChip label={humanize(event.stage)} tone={toneForStage(event.stage)} />
        </div>
        <div className="context-stat-grid">
          <ContextStat label="Thread" value={`${eventIndex + 1}/${eventCount}`} />
          <ContextStat label="Sequence" value={`#${event.sequence}`} />
          <ContextStat label="Recorded" value={formatTimestamp(event.recorded_at)} />
          <ContextStat label="Status" value={event.status ? humanize(event.status) : "Captured"} />
        </div>
      </section>

      {insights.length > 0 && (
        <section className="context-panel">
          <SectionTitle icon={<CircleDot size={14} />} title="Salient Insights" />
          <div className="context-insight-grid">
            {insights.map((insight) => (
              <div key={`${insight.label}-${insight.value}`} className="context-insight-card">
                <span>{insight.label}</span>
                <strong style={insight.tone ? { color: insight.tone } : undefined}>{insight.value}</strong>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="context-panel">
        <SectionTitle icon={<ArrowRight size={14} />} title="Drill Down" />
        <div className="context-action-row">
          <button className="action-button compact" type="button" onClick={() => onJumpTab("steering")}>Open Steering</button>
          <button className="action-button compact" type="button" onClick={() => onJumpTab("evidence")}>Evidence</button>
          <button className="action-button compact" type="button" onClick={() => onJumpTab("policy")}>Policy</button>
          <button className="action-button compact" type="button" onClick={() => onJumpTab("execution")}>Execution</button>
        </div>
      </section>

      {event.summary && Object.keys(event.summary).length > 0 && (
        <section className="context-panel">
          <SectionTitle icon={<Activity size={14} />} title="Summary" />
          <pre className="timeline-summary">{JSON.stringify(event.summary, null, 2)}</pre>
        </section>
      )}

      <section className="context-panel">
        <SectionTitle icon={<Binary size={14} />} title="Payload" />
        <pre className="timeline-summary">{JSON.stringify(event.payload, null, 2)}</pre>
      </section>

      {(event.artifact_key || event.integration_name || event.merkle_leaf_hash) && (
        <section className="context-panel">
          <SectionTitle icon={<FolderGit2 size={14} />} title="Links" />
          <div className="context-link-list">
            {event.artifact_key ? <ContextLink label="Artifact" value={event.artifact_key} /> : null}
            {event.integration_name ? <ContextLink label="Integration" value={event.integration_name} /> : null}
            {event.merkle_leaf_hash ? <ContextLink label="Merkle Leaf" value={event.merkle_leaf_hash} mono /> : null}
          </div>
        </section>
      )}
    </div>
  );
}

function SteeringConsolePanel({
  activeRun,
  activeRunId,
  activeEvent,
  active,
  approvalCurrentlyBlocked,
  noteDraft,
  onNoteDraftChange,
  onSteer,
  showOverrides,
  onToggleOverrides,
  overrideDecisionDraft,
  onOverrideDecisionDraftChange,
  onOverrideDecision,
  overrideParamsDraft,
  onOverrideParamsDraftChange,
  onOverrideParams,
}: {
  activeRun: RunDetail | null;
  activeRunId: string;
  activeEvent: RunEventRecord | null;
  active: string;
  approvalCurrentlyBlocked: boolean;
  noteDraft: string;
  onNoteDraftChange: (value: string) => void;
  onSteer: (command: string, payload?: Record<string, unknown>) => void;
  showOverrides: boolean;
  onToggleOverrides: () => void;
  overrideDecisionDraft: string;
  onOverrideDecisionDraftChange: (value: string) => void;
  onOverrideDecision: () => void;
  overrideParamsDraft: string;
  onOverrideParamsDraftChange: (value: string) => void;
  onOverrideParams: () => void;
}) {
  return (
    <div className="inspector-scroll">
      {activeEvent && (
        <section className="context-panel">
          <div className="context-panel-header">
            <div>
              <p className="eyebrow">Steering Context</p>
              <h4>{humanize(activeEvent.event_type)}</h4>
            </div>
            <StatusChip label={humanize(activeEvent.stage)} tone={toneForStage(activeEvent.stage)} />
          </div>
          <p className="inspector-muted">
            Targeting node #{activeEvent.sequence}. Commands act on the run while keeping this node as the active context anchor.
          </p>
        </section>
      )}

      <div className="steering-console">
        <div className="steering-grid">
          <SteerButton
            label="Approve"
            command="approve"
            active={active}
            disabled={!activeRunId || activeRun?.stage !== "awaiting_operator" || approvalCurrentlyBlocked}
            primary
            onClick={onSteer}
          />
          <SteerButton label="Resume" command="resume" active={active} disabled={!activeRunId} onClick={onSteer} />
          <SteerButton label="Cancel" command="cancel" active={active} disabled={!activeRunId} onClick={onSteer} />
          <SteerButton
            label={activeRun?.auto_mode ? "Set Gate" : "Set Auto"}
            command="set_auto_mode"
            active={active}
            disabled={!activeRunId}
            onClick={(cmd) => onSteer(cmd, { enabled: !(activeRun?.auto_mode ?? false) })}
          />
        </div>
        <div className="stack">
          <div className="note-row">
            <input
              value={noteDraft}
              onChange={(e) => onNoteDraftChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && noteDraft.trim()) {
                  onSteer("attach_note", { note: noteDraft.trim() });
                  onNoteDraftChange("");
                }
              }}
              placeholder={activeEvent ? `Note for ${humanize(activeEvent.event_type)}…` : "Operator note…"}
              disabled={!activeRunId}
            />
            <button
              className="action-button compact"
              disabled={!activeRunId || !noteDraft.trim()}
              onClick={() => {
                onSteer("attach_note", { note: noteDraft.trim() });
                onNoteDraftChange("");
              }}
            >
              Attach
            </button>
          </div>
          <button className="toggle-btn" onClick={onToggleOverrides}>
            <ChevronDown size={14} className={showOverrides ? "rotate-180" : ""} />
            Advanced Overrides
          </button>
          {showOverrides && (
            <div className="stack animate-in">
              <textarea
                value={overrideDecisionDraft}
                onChange={(e) => onOverrideDecisionDraftChange(e.target.value)}
                placeholder="Decision override JSON"
                className="small-textarea mono-textarea"
              />
              <button className="action-button compact" disabled={!activeRunId} onClick={onOverrideDecision}>
                Override Decision
              </button>
              <textarea
                value={overrideParamsDraft}
                onChange={(e) => onOverrideParamsDraftChange(e.target.value)}
                placeholder="Execution parameter override JSON"
                className="small-textarea mono-textarea"
              />
              <button className="action-button compact" disabled={!activeRunId} onClick={onOverrideParams}>
                Override Params
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ContextStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="context-stat-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ContextLink({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="context-link-row">
      <span>{label}</span>
      <strong className={mono ? "context-link-value mono" : "context-link-value"}>{value}</strong>
    </div>
  );
}

function buildEventInsights(event: RunEventRecord): Array<{ label: string; value: string; tone?: string }> {
  const insights: Array<{ label: string; value: string; tone?: string }> = [];
  const summaryEntries = event.summary ? Object.entries(event.summary) : [];
  const payloadEntries = Object.entries(event.payload ?? {});

  for (const [key, value] of summaryEntries) {
    const preview = formatInsightValue(value);
    if (preview) insights.push({ label: humanize(key), value: preview, tone: key.toLowerCase().includes("risk") ? "var(--accent-warm)" : undefined });
  }

  if (event.integration_name) insights.push({ label: "Integration", value: event.integration_name, tone: "var(--accent)" });
  if (event.artifact_key) insights.push({ label: "Artifact", value: event.artifact_key });
  if (event.status) insights.push({ label: "Status", value: humanize(event.status), tone: toneForStage(event.stage) });

  for (const [key, value] of payloadEntries) {
    if (summaryEntries.some(([summaryKey]) => summaryKey === key)) continue;
    const preview = formatInsightValue(value);
    if (preview) insights.push({ label: humanize(key), value: preview });
  }

  return insights.slice(0, 8);
}

function formatInsightValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    if (value.length === 0) return "0 items";
    if (value.every((entry) => typeof entry === "string" || typeof entry === "number")) {
      return value.slice(0, 3).join(", ") + (value.length > 3 ? ` +${value.length - 3}` : "");
    }
    return `${value.length} items`;
  }
  if (typeof value === "object") {
    return `${Object.keys(value as Record<string, unknown>).length} fields`;
  }
  return "";
}

function HeaderMetric({
  icon,
  label,
  value,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone?: "good" | "warn" | "danger";
}) {
  return (
    <div className={`header-metric ${tone ?? ""}`}>
      <span className="header-metric-icon">{icon}</span>
      <div>
        <p>{label}</p>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

function SectionTitle({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="section-title">
      <span>{icon}</span>
      <h3>{title}</h3>
    </div>
  );
}

function ReadinessCard({
  label,
  status,
}: {
  label: string;
  status?: {
    ready: boolean;
    detail: string;
    primary_route?: string | null;
    fallback_route?: string | null;
    warnings?: string[];
  } | null;
}) {
  return (
    <div className={`readiness-card ${status?.ready ? "good" : "warn"}`}>
      <div className="readiness-dot" data-ready={String(status?.ready ?? false)} />
      <strong>{label}</strong>
      {status?.primary_route && (
        <span className="readiness-route">
          Primary: <code>{status.primary_route}</code>
        </span>
      )}
      {status?.fallback_route && (
        <span className="readiness-route">
          Fallback: <code>{status.fallback_route}</code>
        </span>
      )}
      {status?.warnings?.map((warning) => (
        <span key={warning} className="readiness-warning">
          <AlertTriangle size={12} />
          {warning}
        </span>
      ))}
      <span className="readiness-detail">{status?.detail ?? "Checking…"}</span>
    </div>
  );
}

function InferenceMetric({
  icon,
  primaryRoute,
  fallbackRoute,
  warning,
  ready,
}: {
  icon: React.ReactNode;
  primaryRoute: string;
  fallbackRoute: string | null;
  warning: string | null;
  ready: boolean;
}) {
  const detail = [fallbackRoute ? `Fallback: ${fallbackRoute}` : null, warning].filter(Boolean).join(" | ");
  return (
    <div
      className={`header-metric header-inference ${warning ? "danger" : ready ? "good" : "warn"}`}
      title={detail || primaryRoute}
    >
      <span className="header-metric-icon">{icon}</span>
      <div>
        <p>Inference Routing</p>
        <strong>{primaryRoute}</strong>
      </div>
    </div>
  );
}

function StatusChip({ label, tone }: { label: string; tone: string }) {
  return (
    <span className="status-chip" style={{ borderColor: tone, color: tone }}>
      {label}
    </span>
  );
}

function ConnectionDot({ status, label }: { status: ConnectionStatus; label: string }) {
  return (
    <span className={`connection-dot ${status}`} title={`${label}: ${status}`}>
      <span className="dot-indicator" />
      {label}
    </span>
  );
}

function EmptyState({ text, icon }: { text: string; icon?: React.ReactNode }) {
  return (
    <div className="empty-state">
      {icon}
      <p>{text}</p>
    </div>
  );
}

function SteerButton({
  label,
  command,
  active,
  disabled,
  primary,
  onClick,
}: {
  label: string;
  command: string;
  active: string;
  disabled: boolean;
  primary?: boolean;
  onClick: (command: string, payload?: Record<string, unknown>) => void;
}) {
  const loading = active === command;
  return (
    <button
      className={`action-button ${primary ? "primary" : ""}`}
      disabled={disabled || !!active}
      onClick={() => onClick(command)}
    >
      {loading ? <Loader2 size={14} className="spin" /> : null}
      {label}
    </button>
  );
}
