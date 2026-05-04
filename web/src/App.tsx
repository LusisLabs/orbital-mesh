import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Binary,
  BookOpen,
  Bot,
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
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Background, Handle, Position, ReactFlow, type NodeProps } from "@xyflow/react";

import { api, connectRunStream, connectSystemStream, resolveBaseUrl } from "./api";
import { AmbientAsciiSignal } from "./components/AmbientAsciiSignal";
import { Inspector } from "./components/Inspector";
import { Toaster, useToast } from "./components/Toaster";
import { formatTimestamp, humanize, relativeTime, safeJsonParse } from "./lib/format";
import {
  buildLabyrinthCrossings,
  buildLabyrinthGuideposts,
  buildLabyrinthJourneys,
} from "./lib/labyrinth";
import {
  buildArtifactGraph,
  buildEvidenceGraph,
  buildKubernetesGraph,
  buildLabyrinthGraph,
  buildMerkleGraph,
  buildRethSignalGraph,
  buildRunGraph,
  toneForStage,
  type RunGraphNode,
} from "./lib/runGraph";
import type {
  HealthSnapshot,
  ConnectionStatus,
  EvidenceGraph,
  GoalRecord,
  InspectorTab,
  IntegrationReadiness,
  MerkleProof,
  ResearchCorpusIntelligence,
  ResearchSessionDetail,
  ResearchSessionRecord,
  RunDetail,
  RunEventRecord,
  RunSessionRecord,
  AgentTask,
  EvoLaunchRecord,
  ScenarioAnalysis,
  ScenarioRecord,
  VaultTreeEntry,
  WatcherStatus,
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
type CanvasMode = "labyrinth" | "flow" | "evidence" | "signal" | "merkle" | "artifacts";
type AppView =
  | "overview"
  | "incidents"
  | "fleet"
  | "runs"
  | "approvals"
  | "agents"
  | "integrations"
  | "evidence"
  | "audit"
  | "automation"
  | "hermes"
  | "control-plane"
  | "settings";
type RunDetailTab = "timeline" | "evidence" | "approvals" | "actions" | "audit" | "agents" | "topology";
type ConnectorState = "ready" | "degraded" | "config-only" | "unsafe" | "stub" | "disconnected";

interface AgentConnectorSummary {
  id: string;
  name: string;
  role: string;
  adapter: string;
  state: ConnectorState;
  scope: string;
  profile: string;
  readinessDetail: string;
  lastAttempt?: string;
  riskFlags: string[];
  boundary: string;
  primary?: boolean;
}

interface IntegrationConnectorSummary {
  id: string;
  name: string;
  domain: "Web3" | "Web2 Production" | "Development" | "Operations";
  state: ConnectorState;
  authType: "OAuth/OIDC" | "API key" | "Service account" | "Local config" | "Manual";
  scopes: string[];
  detail: string;
}

interface DashboardMetric {
  label: string;
  value: string;
  detail: string;
  tone: "good" | "warn" | "danger" | "neutral";
}

interface ApprovalQueueItem {
  id: string;
  title: string;
  detail: string;
  stage: string;
  blocked: boolean;
}

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
    case "agents":
      return <Bot size={15} />;
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
    case "labyrinth":
      return "Overview";
    case "flow":
      return "Run Flow";
    case "evidence":
      return "Evidence";
    case "signal":
      return "Signal";
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
    case "labyrinth":
      return <CircleDot size={size} />;
    case "flow":
      return <GitBranch size={size} />;
    case "evidence":
      return <Activity size={size} />;
    case "signal":
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
    case "task_trace":
    case "trajectory_score":
    case "verifier_output":
    case "phoenix_spans":
    case "hermes_explanation":
      return "policy";
    case "execution":
    case "goose_review":
    case "hermes_review":
      return "execution";
    case "agent_tasks":
    case "agents":
      return "agents";
    case "feedback":
      return "feedback";
    default:
      return "overview";
  }
}

export default function App() {
  const [baseUrl] = useState(resolveBaseUrl);

  const [health, setHealth] = useState<HealthSnapshot | null>(null);
  const [readiness, setReadiness] = useState<IntegrationReadiness | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioRecord[]>([]);
  const [goals, setGoals] = useState<GoalRecord[]>([]);
  const [runs, setRuns] = useState<RunSessionRecord[]>([]);
  const [researchSessions, setResearchSessions] = useState<ResearchSessionRecord[]>([]);
  const [researchCorpus, setResearchCorpus] = useState<ResearchCorpusIntelligence | null>(null);
  const [activeResearchSessionId, setActiveResearchSessionId] = useState("");
  const [researchDetail, setResearchDetail] = useState<ResearchSessionDetail | null>(null);
  const [activeRun, setActiveRun] = useState<RunDetail | null>(null);
  const [scenarioAnalysis, setScenarioAnalysis] = useState<ScenarioAnalysis | null>(null);
  const [evidenceGraph, setEvidenceGraph] = useState<EvidenceGraph | null>(null);
  const [memoryCrystallization, setMemoryCrystallization] = useState<Record<string, unknown> | null>(null);
  const [watchers, setWatchers] = useState<WatcherStatus | null>(null);
  const [agentTasks, setAgentTasks] = useState<AgentTask[]>([]);
  const [activeRunId, setActiveRunId] = useState(
    () => new URLSearchParams(window.location.search).get("run") ?? "",
  );
  const [selectedGoalId, setSelectedGoalId] = useState("");

  const [goalDraft, setGoalDraft] = useState(DEFAULT_GOAL_DRAFT);
  const [launchDraft, setLaunchDraft] = useState(DEFAULT_LAUNCH_DRAFT);
  const [noteDraft, setNoteDraft] = useState("");
  const [hermesChatDraft, setHermesChatDraft] = useState("");
  const [overrideDecisionDraft, setOverrideDecisionDraft] = useState('{\n  "decision_type": "reduce_rollout"\n}');
  const [overrideParamsDraft, setOverrideParamsDraft] = useState('{\n  "rollout_pct": 5\n}');
  const [showGoalForm, setShowGoalForm] = useState(false);
  const [showOverrides, setShowOverrides] = useState(false);
  const [leftRailOpen, setLeftRailOpen] = useState(true);
  const [rightRailOpen, setRightRailOpen] = useState(false);
  const [canvasMode, setCanvasMode] = useState<CanvasMode>("labyrinth");
  const [activeView, setActiveView] = useState<AppView>("overview");
  const [runDetailTab, setRunDetailTab] = useState<RunDetailTab>("timeline");

  const [rightRailTab, setRightRailTab] = useState<RightRailTab>("overview");
  const [selectedEventId, setSelectedEventId] = useState("");
  const [vaultDocument, setVaultDocument] = useState("");
  const [vaultTree, setVaultTree] = useState<VaultTreeEntry[] | null>(null);
  const [merkleProof, setMerkleProof] = useState<MerkleProof | null>(null);

  const [systemConnection, setSystemConnection] = useState<ConnectionStatus>("reconnecting");
  const [runConnection, setRunConnection] = useState<ConnectionStatus>("reconnecting");

  const [booting, setBooting] = useState(true);
  const [launching, setLaunching] = useState(false);
  const [steering, setSteering] = useState("");
  const [creatingGoal, setCreatingGoal] = useState(false);

  const { toasts, addToast, dismissToast } = useToast();

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
        void api.getWatchers(baseUrl).then(setWatchers).catch(() => setWatchers(null));
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
      setAgentTasks([]);
      setScenarioAnalysis(null);
      setEvidenceGraph(null);
      setMemoryCrystallization(null);
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
        ["investigation_ready", "decision_ready", "evaluation_ready", "execution_recorded", "feedback_recorded"].includes(e.event_type),
      )?.event_id;
    if (proofEventId) {
      void api.getMerkleProof(baseUrl, activeRun.run_id, proofEventId).then(setMerkleProof).catch(() => setMerkleProof(null));
    } else {
      setMerkleProof(null);
    }
  }, [activeRun, baseUrl, selectedEventId]);

  useEffect(() => {
    void api.getVaultTree(baseUrl).then((r) => setVaultTree(r.tree)).catch(() => setVaultTree(null));
  }, [baseUrl]);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      void api.getWatchers(baseUrl).then((status) => {
        if (!cancelled) setWatchers(status);
      }).catch(() => {
        if (!cancelled) setWatchers(null);
      });
    };
    load();
    const timer = window.setInterval(load, 10_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
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

  async function refreshBootstrap() {
    const boot = <T,>(request: Promise<T>, fallback: T, timeoutMs = 8_000) =>
      withTimeout(request, timeoutMs).catch(() => fallback);
    try {
      const [healthRes, readinessRes, goalsRes, runsRes, researchRes, researchCorpusRes, watchersRes] = await Promise.all([
        boot(api.getHealth(baseUrl), null),
        boot(api.getReadiness(baseUrl), null),
        boot(api.getGoals(baseUrl), { goals: [] }),
        boot(api.getRuns(baseUrl), { runs: [] }),
        boot(api.getResearchSessions(baseUrl), { sessions: [] }),
        boot(api.getResearchCorpus(baseUrl), null),
        boot(api.getWatchers(baseUrl), null),
      ]);
      if (!healthRes) {
        throw new Error("Could not reach control plane health endpoint.");
      }
      setHealth(healthRes);
      setReadiness(readinessRes);
      setGoals(goalsRes.goals);
      setRuns(runsRes.runs);
      setResearchSessions(researchRes.sessions);
      setResearchCorpus(researchCorpusRes);
      setWatchers(watchersRes);
      if (!selectedGoalId && goalsRes.goals[0]) setSelectedGoalId(goalsRes.goals[0].goal_id);
      if (!activeRunId && runsRes.runs[0]) setActiveRunId(runsRes.runs[0].run_id);
      void withTimeout(api.getScenarios(baseUrl), 4_000).then((scenariosRes) => {
        setScenarios(scenariosRes.scenarios);
        if (scenariosRes.scenarios[0] && !launchDraft.scenarioKey) {
          setLaunchDraft((d) => ({ ...d, scenarioKey: scenariosRes.scenarios[0].key }));
        }
      }).catch(() => setScenarios([]));
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
      const [run, taskResponse, analysisResponse, evidenceResponse, memoryResponse] = await Promise.all([
        api.getRun(baseUrl, runId),
        api.getAgentTasks(baseUrl, runId).catch(() => ({ tasks: [] as AgentTask[] })),
        api.getScenarioAnalysis(baseUrl, runId).catch(() => null),
        api.getEvidenceGraph(baseUrl, runId).catch(() => null),
        api.getMemoryCrystallization(baseUrl, runId).catch(() => null),
      ]);
      setActiveRun(run);
      setAgentTasks(taskResponse.tasks);
      setScenarioAnalysis(analysisResponse);
      setEvidenceGraph(evidenceResponse);
      setMemoryCrystallization(memoryResponse);
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
        addToast({
          variant: "success",
          title: command === "launch_evo" ? "Evo launch requested" : `Run ${humanize(command).toLowerCase()}d`,
        });
      } catch (error) {
        addToast({ variant: "error", title: `Steer failed`, description: error instanceof Error ? error.message : "Unknown error" });
      } finally {
        setSteering("");
      }
    },
    [activeRunId, baseUrl, addToast], // eslint-disable-line react-hooks/exhaustive-deps
  );

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

  function handleHermesChat() {
    const message = hermesChatDraft.trim();
    if (!message) {
      addToast({ variant: "warning", title: "Hermes message required" });
      return;
    }
    void handleSteer("chat_with_hermes", { message });
    setHermesChatDraft("");
  }

  function handleAcceptHermesAction() {
    if (!hermesExplanation) {
      return;
    }
    const command = String(hermesExplanation.proposed_command ?? "").trim();
    const payload =
      hermesExplanation.proposed_payload && typeof hermesExplanation.proposed_payload === "object"
        ? (hermesExplanation.proposed_payload as Record<string, unknown>)
        : {};
    if (!command) {
      addToast({ variant: "warning", title: "No Hermes action to accept" });
      return;
    }
    void handleSteer(command, payload);
  }

  const flowCanvas = useMemo(
    () => buildRunGraph(activeRun?.events ?? [], selectedEventId),
    [activeRun?.events, selectedEventId],
  );
  const activeSignal = useMemo(
    () => (activeRun?.artifacts?.input_signal ?? activeRun?.artifacts?.trigger ?? null) as Record<string, any> | null,
    [activeRun?.artifacts],
  );
  const labyrinthCrossings = useMemo(
    () =>
      buildLabyrinthCrossings({
        run: activeRun,
        scenarioAnalysis,
        evidenceGraph,
        memoryCrystallization,
        watchers,
      }),
    [activeRun, evidenceGraph, memoryCrystallization, scenarioAnalysis, watchers],
  );
  const labyrinthGuideposts = useMemo(
    () => buildLabyrinthGuideposts({ run: activeRun, scenarioAnalysis, evidenceGraph, watchers }),
    [activeRun, evidenceGraph, scenarioAnalysis, watchers],
  );
  const labyrinthJourneys = useMemo(
    () =>
      buildLabyrinthJourneys({
        runs,
        researchSessions,
        watchers,
        activeRunId,
        activeResearchSessionId,
      }),
    [activeResearchSessionId, activeRunId, researchSessions, runs, watchers],
  );
  const labyrinthCanvas = useMemo(
    () => buildLabyrinthGraph(labyrinthCrossings, selectedEventId),
    [labyrinthCrossings, selectedEventId],
  );
  const evidenceCanvas = useMemo(
    () => buildEvidenceGraph(evidenceGraph),
    [evidenceGraph],
  );
  const signalCanvas = useMemo(() => {
    const reth = buildRethSignalGraph(activeSignal);
    return reth.nodes.length > 0 ? reth : buildKubernetesGraph(activeSignal);
  }, [activeSignal]);
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
  const canvasGraph = useMemo(() => {
    switch (canvasMode) {
      case "labyrinth":
        return labyrinthCanvas;
      case "evidence":
        return evidenceCanvas;
      case "signal":
        return signalCanvas;
      case "merkle":
        return merkleCanvas;
      case "artifacts":
        return artifactCanvas;
      case "flow":
      default:
        return flowCanvas;
    }
  }, [artifactCanvas, canvasMode, evidenceCanvas, flowCanvas, labyrinthCanvas, merkleCanvas, signalCanvas]);
  const canvasAvailability = useMemo(
    () => ({
      labyrinth: labyrinthCanvas.nodes.length > 0,
      flow: flowCanvas.nodes.length > 0,
      evidence: evidenceCanvas.nodes.length > 0,
      signal: signalCanvas.nodes.length > 0,
      merkle: merkleCanvas.nodes.length > 0,
      artifacts: artifactCanvas.nodes.length > 0,
    }),
    [
      artifactCanvas.nodes.length,
      evidenceCanvas.nodes.length,
      flowCanvas.nodes.length,
      labyrinthCanvas.nodes.length,
      merkleCanvas.nodes.length,
      signalCanvas.nodes.length,
    ],
  );
  const canvasEmptyMessage = useMemo(() => {
    switch (canvasMode) {
      case "labyrinth":
        return "Start or select a run to see the operation map.";
      case "evidence":
        return "This run has no scenario-analysis evidence graph yet.";
      case "signal":
        return "This run does not include a Reth or Kubernetes signal.";
      case "merkle":
        return "This run has no Merkle snapshot available yet.";
      case "artifacts":
        return "This run has not produced artifact snapshots yet.";
      case "flow":
      default:
        return "Launch a run to see the execution graph.";
    }
  }, [canvasMode]);
  const canvasFitPadding = canvasMode === "labyrinth" ? 0.08 : canvasMode === "flow" ? 0.12 : canvasMode === "artifacts" ? 0.16 : 0.2;

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
  const hermesExplanation = (activeRun?.artifacts?.hermes_explanation ?? null) as Record<string, any> | null;

  const readinessItems = readiness
    ? [
        readiness.promptfoo,
        readiness.hermes,
        readiness.goose,
        readiness.evo,
        readiness.latentmas,
        readiness.deepagents,
      ]
    : [];
  const integrationsReady = readinessItems.filter((i) => i?.ready).length;
  const integrationsTotal = readinessItems.length || 6;
  const inferencePrimaryRoute = readiness?.goose.primary_route ?? "Booting";
  const inferenceFallbackRoute = readiness?.goose.fallback_route ?? null;
  const inferenceWarning = readiness?.goose.warnings?.[0] ?? null;
  const environmentLabel = health ? humanize(health.environment) : "Booting";
  const buildSubline = health ? `v${health.version} • ${health.commit.slice(0, 7)}` : undefined;
  const researchSessionsAnalyzed = researchCorpus?.sessions_analyzed ?? researchSessions.length;
  const agentConnectors = useMemo(
    () => buildAgentConnectors(readiness, agentTasks),
    [agentTasks, readiness],
  );
  const integrationConnectors = useMemo(
    () => buildIntegrationConnectors(readiness, watchers, activeSignal),
    [activeSignal, readiness, watchers],
  );
  const approvalQueue = useMemo(
    () => buildApprovalQueue(activeRun, approvalCurrentlyBlocked, approvalBlockingReasons),
    [activeRun, approvalBlockingReasons, approvalCurrentlyBlocked],
  );
  const incidentRuns = useMemo(
    () =>
      runs.filter((run) =>
        run.status === "failed" ||
        run.stage === "awaiting_operator" ||
        run.stage === "executing" ||
        run.error,
      ),
    [runs],
  );
  const dashboardMetrics = useMemo(
    () =>
      buildDashboardMetrics({
        runs,
        incidentCount: incidentRuns.length,
        approvalCount: approvalQueue.length,
        integrationsReady,
        integrationsTotal,
        agentConnectors,
        watchers,
      }),
    [agentConnectors, approvalQueue.length, incidentRuns.length, integrationsReady, integrationsTotal, runs, watchers],
  );
  const recentEvidenceEvents = useMemo(
    () =>
      (activeRun?.events ?? [])
        .filter((event) => event.artifact_key || event.integration_name || event.merkle_leaf_hash)
        .slice(-6)
        .reverse(),
    [activeRun?.events],
  );

  useEffect(() => {
    if (!activeRun) return;
    if (canvasAvailability[canvasMode]) return;
    if (canvasAvailability.labyrinth) {
      setCanvasMode("labyrinth");
      return;
    }
    if (canvasAvailability.flow) {
      setCanvasMode("flow");
      return;
    }
    if (canvasAvailability.evidence) {
      setCanvasMode("evidence");
      return;
    }
    if (canvasAvailability.signal) {
      setCanvasMode("signal");
      return;
    }
    if (canvasAvailability.artifacts) {
      setCanvasMode("artifacts");
      return;
    }
    if (canvasAvailability.merkle) {
      setCanvasMode("merkle");
    }
  }, [activeRun, canvasAvailability, canvasMode]);

  if (booting) {
    return (
      <div className="boot-screen">
        <Loader2 className="spin" size={32} />
        <p>Connecting to control plane…</p>
      </div>
    );
  }

  const headerPrimaryAction =
    approvalQueue.length > 0
      ? {
          icon: "diff",
          label: "Review gate",
          onClick: () => setActiveView("approvals"),
        }
      : activeRun
        ? {
            icon: "run-all",
            label: "Continue run",
            onClick: () => {
              setActiveView("runs");
              setRunDetailTab("timeline");
            },
          }
        : {
            icon: "play",
            label: "Launch run",
            onClick: () => setActiveView("automation"),
          };

  return (
    <div className={`mesh-console-shell mesh-agent-console ${rightRailOpen ? "drawer-open" : ""}`}>
      <Toaster toasts={toasts} onDismiss={dismissToast} />

      <aside className={`mesh-sidebar mesh-session-rail ${leftRailOpen ? "" : "collapsed"}`} aria-label="Purna Labs workspace sessions">
        <div className="mesh-sidebar-brand">
          <div className="brand-icon"><Codicon name="circuit-board" /></div>
          {leftRailOpen ? (
            <div>
              <p className="mesh-kicker">Purna Labs OS</p>
              <h1>Purna Console</h1>
              <span className="mesh-brand-subtitle">Bounded operations</span>
            </div>
          ) : null}
        </div>
        <nav className="mesh-nav" data-testid="mesh-primary-nav">
          {([
            ["overview", "Overview", <Codicon name="home" />],
            ["runs", "Runs", <Codicon name="run-all" />],
            ["approvals", "Approvals", <Codicon name="pass" />],
            ["hermes", "Hermes", <Codicon name="sparkle" />],
            ["automation", "Launch", <Codicon name="play" />],
            ["evidence", "Evidence", <Codicon name="references" />],
            ["agents", "Agents", <Codicon name="hubot" />],
            ["integrations", "Integrations", <PlugIcon />],
            ["incidents", "Incidents", <Codicon name="warning" />],
            ["fleet", "Fleet", <Codicon name="broadcast" />],
            ["audit", "Audit", <Codicon name="verified" />],
            ["control-plane", "Control Plane", <Codicon name="settings-gear" />],
            ["settings", "Settings", <Codicon name="tools" />],
          ] as Array<[AppView, string, React.ReactNode]>).map(([view, label, icon]) => (
            <button
              key={view}
              className={`mesh-nav-item ${activeView === view ? "active" : ""}`}
              type="button"
              onClick={() => {
                setActiveView(view);
                setRightRailOpen(false);
              }}
              title={label}
              aria-label={view === "automation" ? "Automation" : label}
            >
              {icon}
              {leftRailOpen ? <span>{label}</span> : null}
            </button>
          ))}
        </nav>
        {leftRailOpen ? (
          <div className="mesh-rail-workspaces" aria-label="Mesh workstreams">
            <div className="mesh-rail-section-title">
              <span>Workstreams</span>
              <Codicon name="filter" />
            </div>
            <RailWorkstreamButton
              icon={<Codicon name="run-all" />}
              title="Active run"
              detail={activeRun ? humanize(activeRun.stage) : "No run selected"}
              count={activeRun ? activeRun.run_id.slice(0, 8) : String(runs.length)}
              active={activeView === "runs"}
              onClick={() => {
                setActiveView("runs");
                setRunDetailTab("timeline");
              }}
            />
            <RailWorkstreamButton
              icon={<Codicon name="diff" />}
              title="Review queue"
              detail={approvalQueue.length > 0 ? "Operator action required" : "No pending approval"}
              count={String(approvalQueue.length)}
              active={activeView === "approvals"}
              tone={approvalQueue.length > 0 ? "warn" : "good"}
              onClick={() => setActiveView("approvals")}
            />
            <RailWorkstreamButton
              icon={<Codicon name="sparkle" />}
              title="Hermes"
              detail={readiness?.hermes.ready ? "Run-scoped agent ready" : "Agent degraded"}
              count={readiness?.hermes.ready ? "ready" : "check"}
              active={activeView === "hermes"}
              tone={readiness?.hermes.ready ? "good" : "warn"}
              onClick={() => setActiveView("hermes")}
            />
            <RailWorkstreamButton
              icon={<Codicon name="references" />}
              title="Evidence"
              detail={`${recentEvidenceEvents.length} recent events`}
              count={String(recentEvidenceEvents.length)}
              active={activeView === "evidence"}
              onClick={() => setActiveView("evidence")}
            />
            <RailWorkstreamButton
              icon={<Codicon name="hubot" />}
              title="Agent mesh"
              detail={`${agentTasks.length} task packets`}
              count={`${agentConnectors.filter((agent) => agent.state === "ready").length}/${agentConnectors.length}`}
              active={activeView === "agents"}
              tone={agentTasks.length > 0 ? "good" : "neutral"}
              onClick={() => setActiveView("agents")}
            />
          </div>
        ) : null}
        <button className="mesh-sidebar-toggle" type="button" onClick={() => setLeftRailOpen((open) => !open)}>
          <Codicon name={leftRailOpen ? "chevron-left" : "chevron-right"} />
          {leftRailOpen ? "Collapse rail" : "Expand rail"}
        </button>
      </aside>

      <div className="mesh-console-main">
        <header className="mesh-console-topbar">
          <div className="mesh-task-title">
            <p className="mesh-kicker">Purna Labs desktop</p>
            <h2>{viewTitle(activeView)}</h2>
            <span>{activeGoal?.title ?? "No active goal"} / {activeRun ? activeRun.run_id.slice(0, 12) : "no run"}</span>
          </div>
          <div className="mesh-topbar-metrics">
            <HeaderMetric icon={<Codicon name="server-environment" />} label="Environment" value={environmentLabel} subline={buildSubline} />
            <HeaderMetric
              icon={<Codicon name="shield" />}
              label="Integrations"
              value={`${integrationsReady}/${integrationsTotal} ready`}
              tone={integrationsReady === integrationsTotal ? "good" : integrationsReady > 0 ? "warn" : "danger"}
            />
            <HeaderMetric icon={<Codicon name="git-branch" />} label="Mode" value={humanize(activeRun?.steering_mode ?? launchDraft.steeringMode)} />
            <InferenceMetric
              icon={<Codicon name="sparkle" />}
              primaryRoute={inferencePrimaryRoute}
              fallbackRoute={inferenceFallbackRoute}
              warning={inferenceWarning}
              ready={Boolean(readiness?.goose.ready)}
            />
          </div>
          <div className="mesh-topbar-actions">
            <ConnectionDot status={systemConnection} label="System" />
            <ConnectionDot status={runConnection} label="Run" />
            <button className="action-button compact primary" type="button" onClick={headerPrimaryAction.onClick}>
              <Codicon name={headerPrimaryAction.icon} />
              {headerPrimaryAction.label}
            </button>
            <button className="action-button compact" type="button" onClick={() => setRightRailOpen((open) => !open)}>
              <Codicon name="layout-sidebar-right" />
              Context
            </button>
          </div>
        </header>

        <main className="mesh-page" data-testid={`mesh-view-${activeView}`}>
          {activeView === "overview" ? (
            <OverviewDashboard
              metrics={dashboardMetrics}
              runs={runs}
              activeRun={activeRun}
              incidents={incidentRuns}
              approvalQueue={approvalQueue}
              agentConnectors={agentConnectors}
              integrationConnectors={integrationConnectors}
              evidenceEvents={recentEvidenceEvents}
              watchers={watchers}
              researchSessionsAnalyzed={researchSessionsAnalyzed}
              onSelectRun={(runId) => {
                setActiveRunId(runId);
                setActiveResearchSessionId("");
                setResearchDetail(null);
                setActiveView("runs");
                setRunDetailTab("timeline");
              }}
              onView={(view) => setActiveView(view)}
              onOpenContext={(tab) => {
                setRightRailTab(tab);
                setRightRailOpen(true);
              }}
            />
          ) : activeView === "runs" ? (
            <RunsView
              runs={runs}
              activeRun={activeRun}
              activeRunId={activeRunId}
              selectedEvent={selectedEvent}
              runDetailTab={runDetailTab}
              canvasMode={canvasMode}
              canvasAvailability={canvasAvailability}
              canvasGraph={canvasGraph}
              canvasEmptyMessage={canvasEmptyMessage}
              canvasFitPadding={canvasFitPadding}
              canvasFullscreen={canvasFullscreen}
              canvasPanelRef={canvasPanelRef}
              timelineRef={timelineRef}
              selectedEventId={selectedEventId}
              agentTasks={agentTasks}
              approvalQueue={approvalQueue}
              recentEvidenceEvents={recentEvidenceEvents}
              selectedEventInsights={selectedEventInsights}
              merkleProof={merkleProof}
              onSelectRun={(runId) => {
                setActiveRunId(runId);
                setActiveResearchSessionId("");
                setResearchDetail(null);
              }}
              onSelectEvent={setSelectedEventId}
              onRunDetailTabChange={setRunDetailTab}
              onCanvasModeChange={setCanvasMode}
              onToggleCanvasFullscreen={toggleCanvasFullscreen}
              onJumpContext={(tab) => {
                setRightRailTab(tab);
                setRightRailOpen(true);
              }}
            />
          ) : activeView === "hermes" ? (
            <HermesView
              readiness={readiness}
              activeRun={activeRun}
              activeRunId={activeRunId}
              activeEvent={selectedEvent}
              approvalCurrentlyBlocked={approvalCurrentlyBlocked}
              approvalBlockingReasons={approvalBlockingReasons}
              hermesExplanation={hermesExplanation}
              hermesChatDraft={hermesChatDraft}
              onHermesChatDraftChange={setHermesChatDraft}
              onHermesChat={handleHermesChat}
              onAcceptHermesAction={handleAcceptHermesAction}
              onExplainBlockers={() => void handleSteer("explain_blockers")}
              steering={steering}
            />
          ) : activeView === "agents" ? (
            <AgentsView
              agentConnectors={agentConnectors}
              activeRun={activeRun}
              agentTasks={agentTasks}
              steering={steering}
              onSteer={handleSteer}
            />
          ) : activeView === "integrations" ? (
            <IntegrationsView connectors={integrationConnectors} readiness={readiness} watchers={watchers} />
          ) : activeView === "control-plane" ? (
            <ControlPlaneView
              health={health}
              readiness={readiness}
              readinessItems={readinessItems}
              integrationsReady={integrationsReady}
              integrationsTotal={integrationsTotal}
              systemConnection={systemConnection}
              runConnection={runConnection}
              agentConnectors={agentConnectors}
              integrationConnectors={integrationConnectors}
            />
          ) : activeView === "evidence" || activeView === "audit" ? (
            <EvidenceAuditView
              mode={activeView}
              activeRun={activeRun}
              events={recentEvidenceEvents}
              merkleProof={merkleProof}
              vaultDocument={vaultDocument}
              vaultTree={vaultTree}
              onVaultSelect={handleVaultSelect}
              onJumpRun={() => {
                setActiveView("runs");
                setRunDetailTab(activeView === "audit" ? "audit" : "evidence");
              }}
            />
          ) : activeView === "approvals" ? (
            <ApprovalsView
              approvalQueue={approvalQueue}
              activeRun={activeRun}
              approvalCurrentlyBlocked={approvalCurrentlyBlocked}
              active={steering}
              onSteer={handleSteer}
              onOpenHermes={() => setActiveView("hermes")}
            />
          ) : activeView === "incidents" ? (
            <IncidentView
              incidents={incidentRuns}
              activeRunId={activeRunId}
              onSelectRun={(runId) => {
                setActiveRunId(runId);
                setActiveView("runs");
              }}
            />
          ) : activeView === "fleet" ? (
            <FleetView watchers={watchers} activeSignal={activeSignal} integrationConnectors={integrationConnectors} />
          ) : activeView === "automation" ? (
            <AutomationView
              launchDraft={launchDraft}
              scenarios={scenarios}
              launching={launching}
              onLaunchDraftChange={setLaunchDraft}
              onUseResearchSafe={() => setLaunchDraft((draft) => ({ ...draft, ...RESEARCH_SAFE_LAUNCH_OVERRIDES }))}
              onLaunchRun={() => void handleLaunchRun()}
              goals={goals}
              selectedGoalId={selectedGoalId}
              goalDraft={goalDraft}
              showGoalForm={showGoalForm}
              creatingGoal={creatingGoal}
              onGoalDraftChange={setGoalDraft}
              onSelectedGoalChange={setSelectedGoalId}
              onShowGoalFormChange={setShowGoalForm}
              onCreateGoal={() => void handleCreateGoal()}
            />
          ) : (
            <SettingsView
              baseUrl={baseUrl}
              readiness={readiness}
              integrationConnectors={integrationConnectors}
              agentConnectors={agentConnectors}
            />
          )}
        </main>
      </div>

      {rightRailOpen ? (
        <aside className="mesh-context-drawer mesh-review-drawer" data-testid="mesh-context-drawer">
          <div className="mesh-context-header">
            <SectionTitle icon={rightRailTabIcon(rightRailTab)} title={rightRailTabLabel(rightRailTab)} />
            <button className="icon-btn" type="button" onClick={() => setRightRailOpen(false)} title="Hide context">
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
                "agents",
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
              guideposts={labyrinthGuideposts}
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
              hermesExplanation={hermesExplanation}
              hermesChatDraft={hermesChatDraft}
              onHermesChatDraftChange={setHermesChatDraft}
              onHermesChat={handleHermesChat}
              onAcceptHermesAction={handleAcceptHermesAction}
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
          ) : rightRailTab === "agents" ? (
            <AgentMeshPanel run={activeRun} tasks={agentTasks} active={steering} onSteer={handleSteer} />
          ) : (
            <Inspector
              tab={rightRailTab}
              run={activeRun}
              researchCorpus={researchCorpus}
              researchDetail={researchDetail}
              vaultDocument={vaultDocument}
              vaultTree={vaultTree}
              merkleProof={merkleProof}
              onVaultSelect={handleVaultSelect}
            />
          )}
        </aside>
      ) : null}
      <footer className="mesh-terminal-strip" aria-label="Mesh runtime status">
        <button className="mesh-terminal-owner" type="button" onClick={() => setActiveView("control-plane")}>
          <Codicon name="terminal" />
          <strong>mesh</strong>
          <span>{baseUrl || "same-origin"}</span>
        </button>
        <div className="mesh-terminal-segments">
          <button type="button" onClick={() => setActiveView("runs")}><Codicon name="git-branch" /> {activeRun ? activeRun.run_id.slice(0, 12) : "no-run"}</button>
          <button type="button" className={systemConnection === "connected" ? "good" : "warn"} onClick={() => setActiveView("control-plane")}>system:{systemConnection}</button>
          <button type="button" className={runConnection === "connected" ? "good" : "warn"} onClick={() => setActiveView("runs")}>run:{runConnection}</button>
          <button type="button" onClick={() => setActiveView("integrations")}>{integrationsReady}/{integrationsTotal} integrations</button>
          <button type="button" onClick={() => setActiveView("agents")}>{agentConnectors.filter((agent) => agent.state === "ready").length}/{agentConnectors.length} agents</button>
          <button type="button" onClick={() => setRightRailOpen((open) => !open)}><Codicon name="layout-sidebar-right" /> context</button>
        </div>
      </footer>
    </div>
  );

}

function Codicon({ name, className = "" }: { name: string; className?: string }) {
  return <span aria-hidden="true" className={`codicon codicon-${name} ${className}`} />;
}

function PlugIcon() {
  return <Codicon name="plug" />;
}

function RailWorkstreamButton({
  icon,
  title,
  detail,
  count,
  active,
  tone = "neutral",
  onClick,
}: {
  icon: React.ReactNode;
  title: string;
  detail: string;
  count: string;
  active: boolean;
  tone?: "good" | "warn" | "neutral";
  onClick: () => void;
}) {
  return (
    <button className={`mesh-rail-workstream ${active ? "active" : ""} ${tone}`} type="button" onClick={onClick}>
      <span className="mesh-rail-workstream-icon">{icon}</span>
      <span className="mesh-rail-workstream-copy">
        <strong>{title}</strong>
        <small>{detail}</small>
      </span>
      <span className="mesh-rail-workstream-count">{count}</span>
    </button>
  );
}

function viewTitle(view: AppView): string {
  switch (view) {
    case "control-plane":
      return "Control Plane";
    default:
      return humanize(view);
  }
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error("request timed out")), timeoutMs);
    promise.then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        window.clearTimeout(timer);
        reject(error);
      },
    );
  });
}

function OverviewDashboard({
  metrics,
  runs,
  activeRun,
  incidents,
  approvalQueue,
  agentConnectors,
  integrationConnectors,
  evidenceEvents,
  watchers,
  researchSessionsAnalyzed,
  onSelectRun,
  onView,
  onOpenContext,
}: {
  metrics: DashboardMetric[];
  runs: RunSessionRecord[];
  activeRun: RunDetail | null;
  incidents: RunSessionRecord[];
  approvalQueue: ApprovalQueueItem[];
  agentConnectors: AgentConnectorSummary[];
  integrationConnectors: IntegrationConnectorSummary[];
  evidenceEvents: RunEventRecord[];
  watchers: WatcherStatus | null;
  researchSessionsAnalyzed: number;
  onSelectRun: (runId: string) => void;
  onView: (view: AppView) => void;
  onOpenContext: (tab: RightRailTab) => void;
}) {
  const readyAgents = agentConnectors.filter((agent) => agent.state === "ready").length;
  const readyIntegrations = integrationConnectors.filter((integration) => integration.state === "ready").length;
  return (
    <div className="mesh-dashboard-grid mesh-command-center">
      <section className="mesh-card mesh-card-span mesh-command-hero">
        <div className="mesh-command-dock" aria-label="Mesh primary actions">
          <div className="mesh-command-dock-copy">
            <p className="mesh-kicker">Current objective</p>
            <h2>{activeRun ? `Operate ${humanize(activeRun.stage)}` : "What should Mesh operate on?"}</h2>
            <p>
              {activeRun
                ? `${activeRun.run_id.slice(0, 12)} keeps timeline, evidence, agents, approvals, and audit state in one thread.`
                : "Start with a bounded signal, then use the run thread for evidence, steering, and audit review."}
            </p>
          </div>
          <div className="mesh-command-dock-actions">
            {approvalQueue.length > 0 ? (
              <button className="action-button compact primary" type="button" onClick={() => onView("approvals")}>
                <Codicon name="diff" />
                Review gate
              </button>
            ) : activeRun ? (
              <button className="action-button compact primary" type="button" onClick={() => onView("runs")}>
                <Codicon name="run-all" />
                Continue run
              </button>
            ) : (
              <button className="action-button compact primary" type="button" onClick={() => onView("automation")}>
                <Codicon name="play" />
                Launch run
              </button>
            )}
            <button className="action-button compact" type="button" onClick={() => onView("hermes")} disabled={!activeRun}>
              <Codicon name="sparkle" />
              Hermes
            </button>
            <button className="action-button compact" type="button" onClick={() => onOpenContext("steering")} disabled={!activeRun}>
              <Codicon name="layout-sidebar-right" />
              Steering
            </button>
          </div>
          <div className="mesh-command-dock-footer">
            <button type="button" onClick={() => onView("runs")}><Codicon name="git-branch" /> {activeRun ? activeRun.run_id.slice(0, 12) : `${runs.length} runs`}</button>
            <button type="button" onClick={() => onView("integrations")}><Codicon name="plug" /> {readyIntegrations}/{integrationConnectors.length} integrations</button>
            <button type="button" onClick={() => onView("agents")}><Codicon name="hubot" /> {readyAgents}/{agentConnectors.length} agents</button>
          </div>
        </div>
        <div className="mesh-section-header">
          <div>
            <p className="mesh-kicker">Operating picture</p>
            <h3>{activeRun ? humanize(activeRun.stage) : "Ready for a bounded run"}</h3>
            <p className="mesh-muted">
              {activeRun
                ? `${activeRun.run_id} is the current investigation. Review evidence, agent attempts, approvals, and audit state from this thread.`
                : "Launch or select a run to bind agents, evidence, approvals, and audit output to one operator thread."}
            </p>
          </div>
        </div>
        <div className="mesh-metric-grid">
          {metrics.map((metric) => (
            <MetricCard key={metric.label} metric={metric} />
          ))}
        </div>
      </section>

      <section className="mesh-card mesh-transcript-card">
        <div className="mesh-section-header">
          <SectionTitle icon={<Codicon name="warning" />} title="Incident Queue" />
          <button className="mesh-link-button" type="button" onClick={() => onView("incidents")}>Open incidents</button>
        </div>
        <div className="mesh-table-wrap">
          <table className="mesh-table">
            <thead><tr><th>Run</th><th>Stage</th><th>Status</th></tr></thead>
            <tbody>
              {incidents.slice(0, 5).map((run) => (
                <tr key={run.run_id} onClick={() => onSelectRun(run.run_id)}>
                  <td><code>{run.run_id.slice(0, 10)}</code></td>
                  <td>{humanize(run.stage)}</td>
                  <td><StatusText status={run.status} /></td>
                </tr>
              ))}
              {incidents.length === 0 ? <tr><td colSpan={3}>No active incidents.</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mesh-card mesh-review-card">
        <div className="mesh-section-header">
          <SectionTitle icon={<Codicon name="diff" />} title="Review Queue" />
          <button className="mesh-link-button" type="button" onClick={() => onView("approvals")}>Review gates</button>
        </div>
        <div className="mesh-stack">
          {approvalQueue.slice(0, 4).map((item) => (
            <button key={item.id} className="mesh-list-row" type="button" onClick={() => onView("approvals")}>
              <span><strong>{item.title}</strong><small>{item.detail}</small></span>
              <StatusPill state={item.blocked ? "degraded" : "config-only"} label={humanize(item.stage)} />
            </button>
          ))}
          {approvalQueue.length === 0 ? <EmptyState text="No operator approvals are pending." /> : null}
        </div>
      </section>

      <section className="mesh-card mesh-agent-card">
        <div className="mesh-section-header">
          <SectionTitle icon={<Codicon name="hubot" />} title="Agents" />
          <button className="mesh-link-button" type="button" onClick={() => onView("agents")}>Agent registry</button>
        </div>
        <div className="mesh-compact-stats">
          <strong>{readyAgents}/{agentConnectors.length}</strong>
          <span>ready or connected</span>
        </div>
        <div className="mesh-stack">
          {agentConnectors.slice(0, 4).map((agent) => (
            <ConnectorRow key={agent.id} name={agent.name} detail={agent.role} state={agent.state} />
          ))}
        </div>
      </section>

      <section className="mesh-card mesh-tool-card">
        <div className="mesh-section-header">
          <SectionTitle icon={<Codicon name="plug" />} title="Integrations" />
          <button className="mesh-link-button" type="button" onClick={() => onView("integrations")}>Integration registry</button>
        </div>
        <div className="mesh-compact-stats">
          <strong>{readyIntegrations}/{integrationConnectors.length}</strong>
          <span>production surfaces ready</span>
        </div>
        <div className="mesh-stack">
          {integrationConnectors.slice(0, 4).map((connector) => (
            <ConnectorRow key={connector.id} name={connector.name} detail={connector.domain} state={connector.state} />
          ))}
        </div>
      </section>

      <section className="mesh-card mesh-card-span mesh-transcript-card">
        <div className="mesh-section-header">
          <SectionTitle icon={<Codicon name="run-all" />} title="Run Threads" />
          <button className="mesh-link-button" type="button" onClick={() => onView("runs")}>Open threads</button>
        </div>
        <div className="mesh-table-wrap">
          <table className="mesh-table">
            <thead><tr><th>Run</th><th>Scenario</th><th>Stage</th><th>Updated</th><th>Events</th></tr></thead>
            <tbody>
              {runs.slice(0, 7).map((run) => (
                <tr key={run.run_id} className={activeRun?.run_id === run.run_id ? "selected" : ""} onClick={() => onSelectRun(run.run_id)}>
                  <td><code>{run.run_id.slice(0, 12)}</code></td>
                  <td>{run.scenario_key ? humanize(run.scenario_key) : "Manual"}</td>
                  <td>{humanize(run.stage)}</td>
                  <td>{relativeTime(run.updated_at)}</td>
                  <td>{run.latest_event_sequence}</td>
                </tr>
              ))}
              {runs.length === 0 ? <tr><td colSpan={5}>No runs recorded.</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mesh-card mesh-evidence-card">
        <div className="mesh-section-header">
          <SectionTitle icon={<Codicon name="references" />} title="Recent Evidence" />
          <button className="mesh-link-button" type="button" onClick={() => onView("evidence")}>Evidence log</button>
        </div>
        <EvidenceEventList events={evidenceEvents} />
      </section>

      <section className="mesh-card mesh-tool-card">
        <div className="mesh-section-header">
          <SectionTitle icon={<Codicon name="broadcast" />} title="Fleet Signals" />
          <button className="mesh-link-button" type="button" onClick={() => onView("fleet")}>Fleet signals</button>
        </div>
        <div className="mesh-stack">
          <ConnectorRow name="Typed watchers" detail={`${watchers?.watchers.filter((w) => w.running).length ?? 0}/${watchers?.watchers.length ?? 0} live`} state={watchers?.watchers.some((w) => w.running) ? "ready" : "config-only"} />
          <ConnectorRow name="Research memory" detail={`${researchSessionsAnalyzed} sessions analyzed`} state={researchSessionsAnalyzed > 0 ? "ready" : "config-only"} />
          <ConnectorRow name="Audit continuity" detail={activeRun?.latest_merkle_root ? activeRun.latest_merkle_root.slice(0, 14) : "No active root"} state={activeRun?.latest_merkle_root ? "ready" : "config-only"} />
        </div>
      </section>
    </div>
  );
}

function RunsView({
  runs,
  activeRun,
  activeRunId,
  selectedEvent,
  runDetailTab,
  canvasMode,
  canvasAvailability,
  canvasGraph,
  canvasEmptyMessage,
  canvasFitPadding,
  canvasFullscreen,
  canvasPanelRef,
  timelineRef,
  selectedEventId,
  agentTasks,
  approvalQueue,
  recentEvidenceEvents,
  selectedEventInsights,
  merkleProof,
  onSelectRun,
  onSelectEvent,
  onRunDetailTabChange,
  onCanvasModeChange,
  onToggleCanvasFullscreen,
  onJumpContext,
}: {
  runs: RunSessionRecord[];
  activeRun: RunDetail | null;
  activeRunId: string;
  selectedEvent: RunEventRecord | null;
  runDetailTab: RunDetailTab;
  canvasMode: CanvasMode;
  canvasAvailability: Record<CanvasMode, boolean>;
  canvasGraph: { nodes: any[]; edges: any[] };
  canvasEmptyMessage: string;
  canvasFitPadding: number;
  canvasFullscreen: boolean;
  canvasPanelRef: React.RefObject<HTMLDivElement>;
  timelineRef: React.RefObject<HTMLDivElement>;
  selectedEventId: string;
  agentTasks: AgentTask[];
  approvalQueue: ApprovalQueueItem[];
  recentEvidenceEvents: RunEventRecord[];
  selectedEventInsights: Array<{ label: string; value: string; tone?: string }>;
  merkleProof: MerkleProof | null;
  onSelectRun: (runId: string) => void;
  onSelectEvent: (eventId: string) => void;
  onRunDetailTabChange: (tab: RunDetailTab) => void;
  onCanvasModeChange: (mode: CanvasMode) => void;
  onToggleCanvasFullscreen: () => void;
  onJumpContext: (tab: RightRailTab) => void;
}) {
  return (
    <div className="mesh-split-page mesh-run-workspace">
      <section className="mesh-card mesh-session-list">
        <div className="mesh-section-header">
          <SectionTitle icon={<Codicon name="run-all" />} title="Run Threads" />
          <span className="mesh-muted">{runs.length} sessions</span>
        </div>
        <div className="mesh-table-wrap">
          <table className="mesh-table">
            <thead><tr><th>Run</th><th>Stage</th><th>Status</th><th>Updated</th></tr></thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id} className={activeRunId === run.run_id ? "selected" : ""} onClick={() => onSelectRun(run.run_id)}>
                  <td><code>{run.run_id.slice(0, 12)}</code></td>
                  <td>{humanize(run.stage)}</td>
                  <td><StatusText status={run.status} /></td>
                  <td>{relativeTime(run.updated_at)}</td>
                </tr>
              ))}
              {runs.length === 0 ? <tr><td colSpan={4}>No runs recorded.</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mesh-card mesh-run-detail mesh-transcript-card" data-testid="run-detail-view">
        <div className="mesh-section-header">
          <div>
            <p className="mesh-kicker">Agent thread</p>
            <h3>{activeRun ? activeRun.run_id : "No run selected"}</h3>
          </div>
          {activeRun ? <StatusChip label={humanize(activeRun.stage)} tone={toneForStage(activeRun.stage)} /> : null}
        </div>
        <div className="mesh-tab-list" role="tablist" aria-label="Run detail">
          {(["timeline", "evidence", "approvals", "actions", "audit", "agents", "topology"] as RunDetailTab[]).map((tab) => (
            <button key={tab} className={runDetailTab === tab ? "tab active" : "tab"} type="button" onClick={() => onRunDetailTabChange(tab)}>
              {runDetailTabLabel(tab)}
            </button>
          ))}
        </div>
        {runDetailTab === "timeline" ? (
          <TimelineTable run={activeRun} selectedEventId={selectedEventId} timelineRef={timelineRef} onSelectEvent={onSelectEvent} />
        ) : runDetailTab === "evidence" ? (
          <EvidencePanel events={recentEvidenceEvents} selectedEvent={selectedEvent} insights={selectedEventInsights} onJumpContext={onJumpContext} />
        ) : runDetailTab === "approvals" ? (
          <RunApprovalPanel queue={approvalQueue} activeRun={activeRun} onJumpContext={onJumpContext} />
        ) : runDetailTab === "actions" ? (
          <RunActionPanel activeRun={activeRun} onJumpContext={onJumpContext} />
        ) : runDetailTab === "audit" ? (
          <RunAuditPanel activeRun={activeRun} merkleProof={merkleProof} onJumpContext={onJumpContext} />
        ) : runDetailTab === "agents" ? (
          <AgentMeshPanel run={activeRun} tasks={agentTasks} active="" onSteer={() => undefined} />
        ) : (
          <TopologyPanel
            activeRun={activeRun}
            canvasMode={canvasMode}
            canvasAvailability={canvasAvailability}
            canvasGraph={canvasGraph}
            canvasEmptyMessage={canvasEmptyMessage}
            canvasFitPadding={canvasFitPadding}
            canvasFullscreen={canvasFullscreen}
            canvasPanelRef={canvasPanelRef}
            onCanvasModeChange={onCanvasModeChange}
            onToggleCanvasFullscreen={onToggleCanvasFullscreen}
            onSelectEvent={onSelectEvent}
            onJumpContext={onJumpContext}
          />
        )}
      </section>
    </div>
  );
}

function HermesView({
  readiness,
  activeRun,
  activeRunId,
  activeEvent,
  approvalCurrentlyBlocked,
  approvalBlockingReasons,
  hermesExplanation,
  hermesChatDraft,
  onHermesChatDraftChange,
  onHermesChat,
  onAcceptHermesAction,
  onExplainBlockers,
  steering,
}: {
  readiness: IntegrationReadiness | null;
  activeRun: RunDetail | null;
  activeRunId: string;
  activeEvent: RunEventRecord | null;
  approvalCurrentlyBlocked: boolean;
  approvalBlockingReasons: string[];
  hermesExplanation: Record<string, any> | null;
  hermesChatDraft: string;
  onHermesChatDraftChange: (value: string) => void;
  onHermesChat: () => void;
  onAcceptHermesAction: () => void;
  onExplainBlockers: () => void;
  steering: string;
}) {
  const proposedCommand = String(hermesExplanation?.proposed_command ?? "").trim();
  const messages = Array.isArray(hermesExplanation?.messages) ? hermesExplanation.messages : [];
  return (
    <div className="mesh-dashboard-grid mesh-agent-chat">
      <section className="mesh-card mesh-agent-card">
        <div className="mesh-section-header">
          <SectionTitle icon={<Bot size={15} />} title="Hermes Status" />
          <StatusPill state={readiness?.hermes.ready ? "ready" : "degraded"} label={readiness?.hermes.ready ? "Connected" : "Unavailable"} />
        </div>
        <ReadinessCard label="Hermes" status={readiness?.hermes} />
        <p className="mesh-muted">Hermes explains blockers and proposes operator actions. Mesh keeps policy, approval, audit, and execution authority.</p>
      </section>

      <section className="mesh-card mesh-card-span mesh-transcript-card">
        <div className="mesh-section-header">
          <SectionTitle icon={<SlidersHorizontal size={15} />} title="Conversation" />
          <StatusPill state={activeRunId ? "ready" : "config-only"} label={activeRunId ? "Run scoped" : "No run"} />
        </div>
        <div className="mesh-chat-log">
          {messages.slice(-6).map((message, index) => (
            <div key={`${String(message.role)}-${index}`} className="mesh-chat-message">
              <strong>{humanize(String(message.role ?? "assistant"))}</strong>
              <p>{String(message.content ?? "")}</p>
            </div>
          ))}
          {messages.length === 0 ? <EmptyState text="Hermes responses will appear after a blocker explanation or chat message." /> : null}
        </div>
        <div className="note-row">
          <input
            value={hermesChatDraft}
            onChange={(event) => onHermesChatDraftChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && hermesChatDraft.trim()) onHermesChat();
            }}
            placeholder={activeRun ? "Ask Hermes about the selected run..." : "Select a run before chatting with Hermes"}
            disabled={!activeRunId}
          />
          <button className="action-button compact primary" type="button" disabled={!activeRunId || !hermesChatDraft.trim() || !!steering} onClick={onHermesChat}>
            {steering === "chat_with_hermes" ? <Loader2 size={14} className="spin" /> : null}
            Send
          </button>
        </div>
      </section>

      <section className="mesh-card mesh-review-card">
        <div className="mesh-section-header">
          <SectionTitle icon={<AlertTriangle size={15} />} title="Blockers" />
          <button className="action-button compact" type="button" disabled={!activeRunId || !!steering} onClick={onExplainBlockers}>
            Explain
          </button>
        </div>
        <div className="mesh-stack">
          <ConnectorRow name="Approval state" detail={approvalCurrentlyBlocked ? "Blocked by evaluation policy" : "No active blocker"} state={approvalCurrentlyBlocked ? "degraded" : "ready"} />
          {approvalBlockingReasons.slice(0, 5).map((reason) => (
            <div key={reason} className="mesh-list-row static"><span><strong>{reason}</strong><small>Evaluation blocker</small></span></div>
          ))}
          {approvalBlockingReasons.length === 0 ? <p className="mesh-muted">No blocker reasons are attached to the active run.</p> : null}
        </div>
      </section>

      <section className="mesh-card mesh-tool-card">
        <div className="mesh-section-header">
          <SectionTitle icon={<ArrowRight size={15} />} title="Proposed Action" />
          <StatusPill state={proposedCommand ? "config-only" : "disconnected"} label={proposedCommand ? "Proposal ready" : "No proposal"} />
        </div>
        <div className="mesh-stack">
          <ContextStat label="Recommendation" value={humanize(String(hermesExplanation?.recommendation ?? "human_review"))} />
          <ContextStat label="Command" value={proposedCommand || "None"} />
          <p className="mesh-muted">{String(hermesExplanation?.summary ?? "No Hermes explanation has been recorded for this run.")}</p>
          <button className="action-button compact primary" type="button" disabled={!proposedCommand || !!steering} onClick={onAcceptHermesAction}>
            Accept Hermes Action
          </button>
        </div>
      </section>

      <section className="mesh-card mesh-evidence-card">
        <div className="mesh-section-header">
          <SectionTitle icon={<Activity size={15} />} title="Context" />
        </div>
        <div className="mesh-stack">
          <ContextStat label="Run" value={activeRun?.run_id ?? "No run selected"} />
          <ContextStat label="Stage" value={activeRun ? humanize(activeRun.stage) : "Idle"} />
          <ContextStat label="Event" value={activeEvent ? humanize(activeEvent.event_type) : "No event selected"} />
          <ContextStat label="Audit root" value={activeRun?.latest_merkle_root?.slice(0, 18) ?? "Unavailable"} />
        </div>
      </section>
    </div>
  );
}

function AgentsView({
  agentConnectors,
  activeRun,
  agentTasks,
  steering,
  onSteer,
}: {
  agentConnectors: AgentConnectorSummary[];
  activeRun: RunDetail | null;
  agentTasks: AgentTask[];
  steering: string;
  onSteer: (command: string, payload?: Record<string, unknown>) => void;
}) {
  return (
    <div className="mesh-dashboard-grid">
      <section className="mesh-card mesh-card-span">
        <div className="mesh-section-header">
          <div>
            <p className="mesh-kicker">Agent connector registry</p>
            <h3>Connected and connectable workers</h3>
          </div>
          <StatusPill state="config-only" label="Proposal-only" />
        </div>
        <div className="mesh-connector-grid" data-testid="agents-grid">
          {agentConnectors.map((agent) => (
            <article key={agent.id} className={`mesh-connector-card ${agent.primary ? "primary" : ""}`}>
              <div className="mesh-section-header">
                <div>
                  <strong>{agent.name}</strong>
                  <p>{agent.role}</p>
                </div>
                <StatusPill state={agent.state} label={humanize(agent.state)} />
              </div>
              <div className="mesh-connector-meta">
                <ContextStat label="Adapter" value={agent.adapter} />
                <ContextStat label="Scope" value={agent.scope} />
                <ContextStat label="Profile" value={agent.profile} />
                <ContextStat label="Last attempt" value={agent.lastAttempt ?? "No attempts"} />
              </div>
              <p className="mesh-muted">{agent.boundary}</p>
              {agent.riskFlags.length > 0 ? <code>{agent.riskFlags.slice(0, 3).join(" / ")}</code> : null}
            </article>
          ))}
        </div>
      </section>
      <section className="mesh-card mesh-card-span">
        <SectionTitle icon={<Bot size={15} />} title="Active Run Agent Attempts" />
        <AgentMeshPanel run={activeRun} tasks={agentTasks} active={steering} onSteer={onSteer} />
      </section>
    </div>
  );
}

function IntegrationsView({
  connectors,
  readiness,
  watchers,
}: {
  connectors: IntegrationConnectorSummary[];
  readiness: IntegrationReadiness | null;
  watchers: WatcherStatus | null;
}) {
  const groups = ["Web3", "Web2 Production", "Development", "Operations"] as const;
  return (
    <div className="mesh-dashboard-grid" data-testid="integrations-grid">
      {groups.map((domain) => (
        <section key={domain} className="mesh-card">
          <div className="mesh-section-header">
            <SectionTitle icon={<FolderGit2 size={15} />} title={domain} />
            <StatusPill state={connectors.some((connector) => connector.domain === domain && connector.state === "ready") ? "ready" : "config-only"} label="Domain pack" />
          </div>
          <div className="mesh-stack">
            {connectors.filter((connector) => connector.domain === domain).map((connector) => (
              <div key={connector.id} className="mesh-integration-row">
                <div>
                  <strong>{connector.name}</strong>
                  <span>{connector.detail}</span>
                  <small>{connector.authType} · {connector.scopes.join(", ")}</small>
                </div>
                <StatusPill state={connector.state} label={humanize(connector.state)} />
              </div>
            ))}
          </div>
        </section>
      ))}
      <section className="mesh-card mesh-card-span">
        <SectionTitle icon={<ShieldCheck size={15} />} title="Connection Boundary" />
        <p className="mesh-muted">
          OAuth/OIDC, service-account, and API-key connections must store raw secrets outside run artifacts. Runs record connection ids, scopes, readiness state, and audit references only.
        </p>
        <div className="mesh-stack">
          <ConnectorRow name="Readiness path" detail={readiness?.integrations_config_path ?? "Unavailable"} state={readiness ? "ready" : "disconnected"} />
          <ConnectorRow name="Watchers" detail={`${watchers?.watchers.length ?? 0} registered`} state={(watchers?.watchers.length ?? 0) > 0 ? "ready" : "config-only"} />
        </div>
      </section>
    </div>
  );
}

function ControlPlaneView({
  health,
  readiness,
  readinessItems,
  integrationsReady,
  integrationsTotal,
  systemConnection,
  runConnection,
  agentConnectors,
  integrationConnectors,
}: {
  health: HealthSnapshot | null;
  readiness: IntegrationReadiness | null;
  readinessItems: IntegrationReadiness[keyof Pick<IntegrationReadiness, "promptfoo" | "hermes" | "goose" | "evo" | "latentmas" | "deepagents">][];
  integrationsReady: number;
  integrationsTotal: number;
  systemConnection: ConnectionStatus;
  runConnection: ConnectionStatus;
  agentConnectors: AgentConnectorSummary[];
  integrationConnectors: IntegrationConnectorSummary[];
}) {
  return (
    <div className="mesh-dashboard-grid">
      <section className="mesh-card mesh-card-span">
        <div className="mesh-section-header">
          <div>
            <p className="mesh-kicker">Runtime internals</p>
            <h3>Control plane diagnostics</h3>
          </div>
          <StatusPill state={systemConnection === "connected" ? "ready" : "degraded"} label={humanize(systemConnection)} />
        </div>
        <div className="mesh-metric-grid">
          <MetricCard metric={{ label: "Environment", value: health ? humanize(health.environment) : "Unknown", detail: health ? `${health.version} ${health.commit.slice(0, 7)}` : "Health unavailable", tone: health ? "good" : "danger" }} />
          <MetricCard metric={{ label: "Integrations", value: `${integrationsReady}/${integrationsTotal}`, detail: "hardcoded readiness keys", tone: integrationsReady === integrationsTotal ? "good" : "warn" }} />
          <MetricCard metric={{ label: "Agents", value: `${agentConnectors.filter((a) => a.state === "ready").length}/${agentConnectors.length}`, detail: "worker connectors", tone: "neutral" }} />
          <MetricCard metric={{ label: "Run stream", value: humanize(runConnection), detail: "active run SSE", tone: runConnection === "connected" ? "good" : "warn" }} />
        </div>
      </section>
      <section className="mesh-card">
        <SectionTitle icon={<FolderGit2 size={15} />} title="Storage" />
        <div className="mesh-stack">
          <ContextStat label="State path" value={readiness?.state_path ?? "Unavailable"} />
          <ContextStat label="Vault path" value={readiness?.vault_path ?? "Unavailable"} />
          <ContextStat label="Integrations config" value={readiness?.integrations_config_path ?? "Unavailable"} />
        </div>
      </section>
      <section className="mesh-card">
        <SectionTitle icon={<ShieldCheck size={15} />} title="Readiness" />
        <div className="readiness-grid">
          {readinessItems.map((item) => (
            <ReadinessCard key={item.name} label={humanize(item.name)} status={item} />
          ))}
        </div>
      </section>
      <section className="mesh-card mesh-card-span">
        <SectionTitle icon={<Activity size={15} />} title="Connector Inventory" />
        <div className="mesh-table-wrap">
          <table className="mesh-table">
            <thead><tr><th>Name</th><th>Kind</th><th>State</th><th>Detail</th></tr></thead>
            <tbody>
              {agentConnectors.map((agent) => (
                <tr key={`agent-${agent.id}`}><td>{agent.name}</td><td>Agent</td><td><StatusText status={agent.state} /></td><td>{agent.readinessDetail}</td></tr>
              ))}
              {integrationConnectors.map((connector) => (
                <tr key={`integration-${connector.id}`}><td>{connector.name}</td><td>{connector.domain}</td><td><StatusText status={connector.state} /></td><td>{connector.detail}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function EvidenceAuditView({
  mode,
  activeRun,
  events,
  merkleProof,
  vaultDocument,
  vaultTree,
  onVaultSelect,
  onJumpRun,
}: {
  mode: "evidence" | "audit";
  activeRun: RunDetail | null;
  events: RunEventRecord[];
  merkleProof: MerkleProof | null;
  vaultDocument: string;
  vaultTree: VaultTreeEntry[] | null;
  onVaultSelect: (path: string) => void;
  onJumpRun: () => void;
}) {
  return (
    <div className="mesh-dashboard-grid">
      <section className="mesh-card">
        <div className="mesh-section-header">
          <SectionTitle icon={mode === "audit" ? <Binary size={15} /> : <Activity size={15} />} title={mode === "audit" ? "Audit State" : "Evidence State"} />
          <button className="mesh-link-button" type="button" onClick={onJumpRun}>Open run detail</button>
        </div>
        <div className="mesh-stack">
          <ContextStat label="Run" value={activeRun?.run_id ?? "No run selected"} />
          <ContextStat label="Merkle root" value={activeRun?.latest_merkle_root ?? "Unavailable"} />
          <ContextStat label="Proof" value={merkleProof?.valid ? "Valid" : merkleProof ? "Invalid" : "Unavailable"} />
        </div>
      </section>
      <section className="mesh-card">
        <SectionTitle icon={<Activity size={15} />} title="Evidence Events" />
        <EvidenceEventList events={events} />
      </section>
      <section className="mesh-card mesh-card-span">
        <Inspector
          tab={mode === "audit" ? "vault" : "evidence"}
          run={activeRun}
          researchCorpus={null}
          researchDetail={null}
          vaultDocument={vaultDocument}
          vaultTree={vaultTree}
          merkleProof={merkleProof}
          onVaultSelect={onVaultSelect}
        />
      </section>
    </div>
  );
}

function ApprovalsView({
  approvalQueue,
  activeRun,
  approvalCurrentlyBlocked,
  active,
  onSteer,
  onOpenHermes,
}: {
  approvalQueue: ApprovalQueueItem[];
  activeRun: RunDetail | null;
  approvalCurrentlyBlocked: boolean;
  active: string;
  onSteer: (command: string, payload?: Record<string, unknown>) => void;
  onOpenHermes: () => void;
}) {
  return (
    <div className="mesh-dashboard-grid">
      <section className="mesh-card">
        <SectionTitle icon={<ShieldCheck size={15} />} title="Approval Queue" />
        <div className="mesh-stack">
          {approvalQueue.map((item) => (
            <div key={item.id} className="mesh-list-row static">
              <span><strong>{item.title}</strong><small>{item.detail}</small></span>
              <StatusPill state={item.blocked ? "degraded" : "config-only"} label={humanize(item.stage)} />
            </div>
          ))}
          {approvalQueue.length === 0 ? <EmptyState text="No pending approvals." /> : null}
        </div>
      </section>
      <section className="mesh-card">
        <SectionTitle icon={<SlidersHorizontal size={15} />} title="Actions" />
        <div className="steering-grid">
          <SteerButton label="Approve" command="approve" active={active} disabled={!activeRun || activeRun.stage !== "awaiting_operator" || approvalCurrentlyBlocked} primary onClick={onSteer} />
          <SteerButton label="Resume" command="resume" active={active} disabled={!activeRun} onClick={onSteer} />
          <SteerButton label="Cancel" command="cancel" active={active} disabled={!activeRun} onClick={onSteer} />
          <button className="action-button" type="button" onClick={onOpenHermes}>Ask Hermes</button>
        </div>
      </section>
    </div>
  );
}

function IncidentView({
  incidents,
  activeRunId,
  onSelectRun,
}: {
  incidents: RunSessionRecord[];
  activeRunId: string;
  onSelectRun: (runId: string) => void;
}) {
  return (
    <section className="mesh-card">
      <SectionTitle icon={<AlertTriangle size={15} />} title="Incidents" />
      <div className="mesh-table-wrap">
        <table className="mesh-table">
          <thead><tr><th>Run</th><th>Scenario</th><th>Stage</th><th>Status</th><th>Updated</th></tr></thead>
          <tbody>
            {incidents.map((run) => (
              <tr key={run.run_id} className={activeRunId === run.run_id ? "selected" : ""} onClick={() => onSelectRun(run.run_id)}>
                <td><code>{run.run_id}</code></td>
                <td>{run.scenario_key ? humanize(run.scenario_key) : "Manual"}</td>
                <td>{humanize(run.stage)}</td>
                <td><StatusText status={run.status} /></td>
                <td>{relativeTime(run.updated_at)}</td>
              </tr>
            ))}
            {incidents.length === 0 ? <tr><td colSpan={5}>No active incidents.</td></tr> : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function FleetView({
  watchers,
  activeSignal,
  integrationConnectors,
}: {
  watchers: WatcherStatus | null;
  activeSignal: Record<string, any> | null;
  integrationConnectors: IntegrationConnectorSummary[];
}) {
  return (
    <div className="mesh-dashboard-grid">
      <section className="mesh-card">
        <SectionTitle icon={<Waves size={15} />} title="Watchers" />
        <div className="mesh-stack">
          {(watchers?.watchers ?? []).map((watcher) => (
            <ConnectorRow key={watcher.name} name={watcher.name} detail={`${watcher.signal_source} / ${watcher.interval_seconds}s`} state={watcher.running ? "ready" : "degraded"} />
          ))}
          {(!watchers || watchers.watchers.length === 0) ? <EmptyState text="No typed watchers registered." /> : null}
        </div>
      </section>
      <section className="mesh-card">
        <SectionTitle icon={<Activity size={15} />} title="Active Signal" />
        <pre className="timeline-summary">{JSON.stringify(activeSignal ?? { status: "no active signal" }, null, 2)}</pre>
      </section>
      <section className="mesh-card mesh-card-span">
        <SectionTitle icon={<FolderGit2 size={15} />} title="Fleet Integrations" />
        <div className="mesh-connector-grid">
          {integrationConnectors.filter((connector) => connector.domain === "Web3" || connector.domain === "Web2 Production").map((connector) => (
            <ConnectorRow key={connector.id} name={connector.name} detail={connector.detail} state={connector.state} />
          ))}
        </div>
      </section>
    </div>
  );
}

function AutomationView({
  launchDraft,
  scenarios,
  launching,
  onLaunchDraftChange,
  onUseResearchSafe,
  onLaunchRun,
  goals,
  selectedGoalId,
  goalDraft,
  showGoalForm,
  creatingGoal,
  onGoalDraftChange,
  onSelectedGoalChange,
  onShowGoalFormChange,
  onCreateGoal,
}: {
  launchDraft: typeof DEFAULT_LAUNCH_DRAFT;
  scenarios: ScenarioRecord[];
  launching: boolean;
  onLaunchDraftChange: React.Dispatch<React.SetStateAction<typeof DEFAULT_LAUNCH_DRAFT>>;
  onUseResearchSafe: () => void;
  onLaunchRun: () => void;
  goals: GoalRecord[];
  selectedGoalId: string;
  goalDraft: typeof DEFAULT_GOAL_DRAFT;
  showGoalForm: boolean;
  creatingGoal: boolean;
  onGoalDraftChange: React.Dispatch<React.SetStateAction<typeof DEFAULT_GOAL_DRAFT>>;
  onSelectedGoalChange: (goalId: string) => void;
  onShowGoalFormChange: (show: boolean) => void;
  onCreateGoal: () => void;
}) {
  return (
    <div className="mesh-dashboard-grid">
      <section className="mesh-card">
        <div className="mesh-section-header">
          <SectionTitle icon={<Play size={15} />} title="Launch Run" />
          <button className="action-button compact" type="button" onClick={onUseResearchSafe}>Research Safe</button>
        </div>
        <div className="mesh-stack">
          <div className="select-wrap">
            <select value={launchDraft.signalSource} onChange={(event) => onLaunchDraftChange((draft) => ({ ...draft, signalSource: event.target.value }))}>
              <option value="scenario">Signal: Fixture Scenario</option>
              <option value="live_kubernetes">Signal: Live Kubernetes Deployment</option>
              <option value="custom">Signal: Custom JSON</option>
            </select>
            <ChevronDown size={14} className="select-icon" />
          </div>
          {launchDraft.signalSource === "scenario" ? (
            <div className="select-wrap">
              <select value={launchDraft.scenarioKey} onChange={(event) => onLaunchDraftChange((draft) => ({ ...draft, scenarioKey: event.target.value }))}>
                {scenarios.map((scenario) => <option key={scenario.key} value={scenario.key}>{scenario.title}</option>)}
              </select>
              <ChevronDown size={14} className="select-icon" />
            </div>
          ) : null}
          {launchDraft.signalSource === "live_kubernetes" ? (
            <>
              <div className="two-col">
                <input value={launchDraft.liveDeploymentName} onChange={(event) => onLaunchDraftChange((draft) => ({ ...draft, liveDeploymentName: event.target.value }))} placeholder="Deployment name" />
                <input value={launchDraft.liveNamespace} onChange={(event) => onLaunchDraftChange((draft) => ({ ...draft, liveNamespace: event.target.value }))} placeholder="Namespace" />
              </div>
              <div className="two-col">
                <input value={launchDraft.liveKubeContext} onChange={(event) => onLaunchDraftChange((draft) => ({ ...draft, liveKubeContext: event.target.value }))} placeholder="Kube context" />
                <input value={launchDraft.liveEnvironment} onChange={(event) => onLaunchDraftChange((draft) => ({ ...draft, liveEnvironment: event.target.value }))} placeholder="Environment" />
              </div>
            </>
          ) : null}
          {launchDraft.signalSource === "custom" ? (
            <textarea value={launchDraft.customSignal} onChange={(event) => onLaunchDraftChange((draft) => ({ ...draft, customSignal: event.target.value }))} placeholder="Raw signal JSON" className="small-textarea mono-textarea" />
          ) : null}
          <div className="two-col">
            <select value={launchDraft.evaluationMode} onChange={(event) => onLaunchDraftChange((draft) => ({ ...draft, evaluationMode: event.target.value }))}>
              <option value="native">Eval: Native</option>
              <option value="promptfoo">Eval: Promptfoo</option>
            </select>
            <select value={launchDraft.orchestrationMode} onChange={(event) => onLaunchDraftChange((draft) => ({ ...draft, orchestrationMode: event.target.value }))}>
              <option value="native">Orch: Native</option>
              <option value="hermes">Orch: Hermes</option>
              <option value="goose">Orch: Goose</option>
            </select>
          </div>
          <select value={launchDraft.steeringMode} onChange={(event) => onLaunchDraftChange((draft) => ({ ...draft, steeringMode: event.target.value }))}>
            <option value="approval_gate">Approval Gate</option>
            <option value="interruptible_auto">Interruptible Auto</option>
          </select>
          <button className="action-button primary" type="button" disabled={launching} onClick={onLaunchRun}>
            {launching ? <Loader2 size={15} className="spin" /> : <Play size={15} />}
            {launching ? "Launching..." : "Launch Run"}
          </button>
        </div>
      </section>
      <section className="mesh-card">
        <div className="mesh-section-header">
          <SectionTitle icon={<CircleDot size={15} />} title="Goals" />
          <button className="icon-btn" type="button" onClick={() => onShowGoalFormChange(!showGoalForm)} title="Add goal"><Plus size={14} /></button>
        </div>
        <div className="mesh-stack">
          {goals.map((goal) => (
            <button key={goal.goal_id} className={`mesh-list-row ${selectedGoalId === goal.goal_id ? "selected" : ""}`} type="button" onClick={() => onSelectedGoalChange(goal.goal_id)}>
              <span><strong>{goal.title}</strong><small>{goal.objective}</small></span>
            </button>
          ))}
          {showGoalForm ? (
            <div className="composer animate-in">
              <input value={goalDraft.title} onChange={(event) => onGoalDraftChange((draft) => ({ ...draft, title: event.target.value }))} placeholder="Goal title" />
              <textarea value={goalDraft.objective} onChange={(event) => onGoalDraftChange((draft) => ({ ...draft, objective: event.target.value }))} placeholder="Objective" className="small-textarea" />
              <input value={goalDraft.successCriteria} onChange={(event) => onGoalDraftChange((draft) => ({ ...draft, successCriteria: event.target.value }))} placeholder="Success criteria, comma-separated" />
              <button className="action-button" type="button" disabled={creatingGoal} onClick={onCreateGoal}>{creatingGoal ? "Creating..." : "Create Goal"}</button>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function SettingsView({
  baseUrl,
  readiness,
  integrationConnectors,
  agentConnectors,
}: {
  baseUrl: string;
  readiness: IntegrationReadiness | null;
  integrationConnectors: IntegrationConnectorSummary[];
  agentConnectors: AgentConnectorSummary[];
}) {
  return (
    <div className="mesh-dashboard-grid">
      <section className="mesh-card">
        <SectionTitle icon={<TimerReset size={15} />} title="Settings" />
        <div className="mesh-stack">
          <ContextStat label="API base URL" value={baseUrl || "same origin"} />
          <ContextStat label="State path" value={readiness?.state_path ?? "Unavailable"} />
          <ContextStat label="Connector count" value={`${integrationConnectors.length + agentConnectors.length}`} />
        </div>
      </section>
      <section className="mesh-card mesh-card-span">
        <SectionTitle icon={<ShieldCheck size={15} />} title="Production Auth Track" />
        <p className="mesh-muted">
          OAuth/OIDC, RBAC, and connector secret storage are backend expansion work. This UI reserves the connection model without storing raw credentials in run artifacts.
        </p>
      </section>
    </div>
  );
}

function MetricCard({ metric }: { metric: DashboardMetric }) {
  return (
    <div className={`mesh-metric-card ${metric.tone}`}>
      <span>{metric.label}</span>
      <strong>{metric.value}</strong>
      <small>{metric.detail}</small>
    </div>
  );
}

function StatusPill({ state, label }: { state: ConnectorState; label: string }) {
  return <span className={`mesh-status-pill ${state}`}>{label}</span>;
}

function StatusText({ status }: { status: string }) {
  const state: ConnectorState =
    status === "completed" || status === "ready" ? "ready" :
    status === "failed" || status === "danger" || status === "disconnected" ? "degraded" :
    status === "unsafe" ? "unsafe" :
    status === "stub" ? "stub" :
    status === "config-only" ? "config-only" :
    "config-only";
  return <StatusPill state={state} label={humanize(status)} />;
}

function ConnectorRow({ name, detail, state }: { name: string; detail: string; state: ConnectorState }) {
  return (
    <div className="mesh-list-row static">
      <span>
        <strong>{name}</strong>
        <small>{detail}</small>
      </span>
      <StatusPill state={state} label={humanize(state)} />
    </div>
  );
}

function EvidenceEventList({ events }: { events: RunEventRecord[] }) {
  if (events.length === 0) return <EmptyState text="No evidence or audit events are attached to the active run." />;
  return (
    <div className="mesh-stack">
      {events.map((event) => (
        <div key={event.event_id} className="mesh-list-row static">
          <span>
            <strong>{humanize(event.event_type)}</strong>
            <small>{event.artifact_key ?? event.integration_name ?? event.merkle_leaf_hash?.slice(0, 16) ?? "event"}</small>
          </span>
          <StatusPill state={event.status === "failed" ? "degraded" : "ready"} label={`#${event.sequence}`} />
        </div>
      ))}
    </div>
  );
}

function TimelineTable({
  run,
  selectedEventId,
  timelineRef,
  onSelectEvent,
}: {
  run: RunDetail | null;
  selectedEventId: string;
  timelineRef: React.RefObject<HTMLDivElement>;
  onSelectEvent: (eventId: string) => void;
}) {
  if (!run) return <EmptyState text="Select a run to inspect its timeline." />;
  return (
    <div className="mesh-table-wrap timeline-table-wrap" ref={timelineRef}>
      <table className="mesh-table">
        <thead><tr><th>#</th><th>Event</th><th>Stage</th><th>Integration</th><th>Recorded</th></tr></thead>
        <tbody>
          {run.events.map((event) => (
            <tr key={event.event_id} className={selectedEventId === event.event_id ? "selected" : ""} onClick={() => onSelectEvent(event.event_id)}>
              <td>{event.sequence}</td>
              <td>{humanize(event.event_type)}</td>
              <td>{humanize(event.stage)}</td>
              <td>{event.integration_name ?? event.artifact_key ?? "mesh"}</td>
              <td>{formatTimestamp(event.recorded_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EvidencePanel({
  events,
  selectedEvent,
  insights,
  onJumpContext,
}: {
  events: RunEventRecord[];
  selectedEvent: RunEventRecord | null;
  insights: Array<{ label: string; value: string; tone?: string }>;
  onJumpContext: (tab: RightRailTab) => void;
}) {
  return (
    <div className="mesh-detail-grid">
      <section className="context-panel">
        <SectionTitle icon={<Activity size={14} />} title="Evidence Summary" />
        <EvidenceEventList events={events} />
      </section>
      <section className="context-panel">
        <SectionTitle icon={<CircleDot size={14} />} title="Selected Event" />
        {selectedEvent ? (
          <>
            <div className="context-stat-grid">
              <ContextStat label="Event" value={humanize(selectedEvent.event_type)} />
              <ContextStat label="Stage" value={humanize(selectedEvent.stage)} />
              <ContextStat label="Artifact" value={selectedEvent.artifact_key ?? "None"} />
              <ContextStat label="Integration" value={selectedEvent.integration_name ?? "Mesh"} />
            </div>
            {insights.length > 0 ? (
              <div className="context-insight-grid">
                {insights.map((insight) => (
                  <div key={`${insight.label}-${insight.value}`} className="context-insight-card">
                    <span>{insight.label}</span>
                    <strong style={insight.tone ? { color: insight.tone } : undefined}>{insight.value}</strong>
                  </div>
                ))}
              </div>
            ) : null}
            <button className="action-button compact" type="button" onClick={() => onJumpContext("evidence")}>Open inspector</button>
          </>
        ) : <EmptyState text="Select a timeline event to inspect evidence." />}
      </section>
    </div>
  );
}

function RunApprovalPanel({
  queue,
  activeRun,
  onJumpContext,
}: {
  queue: ApprovalQueueItem[];
  activeRun: RunDetail | null;
  onJumpContext: (tab: RightRailTab) => void;
}) {
  return (
    <div className="mesh-detail-grid">
      <section className="context-panel">
        <SectionTitle icon={<ShieldCheck size={14} />} title="Approval State" />
        <div className="mesh-stack">
          <ContextStat label="Run" value={activeRun?.run_id ?? "No run"} />
          <ContextStat label="Stage" value={activeRun ? humanize(activeRun.stage) : "Idle"} />
          {queue.map((item) => <ConnectorRow key={item.id} name={item.title} detail={item.detail} state={item.blocked ? "degraded" : "config-only"} />)}
          {queue.length === 0 ? <EmptyState text="No pending approval for this run." /> : null}
          <button className="action-button compact" type="button" onClick={() => onJumpContext("steering")}>Open steering</button>
        </div>
      </section>
    </div>
  );
}

function RunActionPanel({ activeRun, onJumpContext }: { activeRun: RunDetail | null; onJumpContext: (tab: RightRailTab) => void }) {
  return (
    <div className="mesh-detail-grid">
      <section className="context-panel">
        <SectionTitle icon={<Play size={14} />} title="Action Surface" />
        <p className="mesh-muted">Approvals, notes, overrides, Evo launch, and execution context remain behind Mesh steering controls.</p>
        <div className="context-action-row">
          <button className="action-button compact primary" type="button" disabled={!activeRun} onClick={() => onJumpContext("steering")}>Steering</button>
          <button className="action-button compact" type="button" disabled={!activeRun} onClick={() => onJumpContext("execution")}>Execution</button>
          <button className="action-button compact" type="button" disabled={!activeRun} onClick={() => onJumpContext("policy")}>Policy</button>
        </div>
      </section>
    </div>
  );
}

function RunAuditPanel({
  activeRun,
  merkleProof,
  onJumpContext,
}: {
  activeRun: RunDetail | null;
  merkleProof: MerkleProof | null;
  onJumpContext: (tab: RightRailTab) => void;
}) {
  return (
    <div className="mesh-detail-grid">
      <section className="context-panel">
        <SectionTitle icon={<Binary size={14} />} title="Audit Continuity" />
        <div className="context-stat-grid">
          <ContextStat label="Merkle root" value={activeRun?.latest_merkle_root ?? "Unavailable"} />
          <ContextStat label="Leaf count" value={activeRun?.merkle?.leaf_count ? String(activeRun.merkle.leaf_count) : "0"} />
          <ContextStat label="Proof event" value={merkleProof?.event_id ?? "Unavailable"} />
          <ContextStat label="Proof valid" value={merkleProof ? String(merkleProof.valid) : "Unavailable"} />
        </div>
        <button className="action-button compact" type="button" onClick={() => onJumpContext("merkle")}>Open Merkle inspector</button>
      </section>
    </div>
  );
}

function TopologyPanel({
  activeRun,
  canvasMode,
  canvasAvailability,
  canvasGraph,
  canvasEmptyMessage,
  canvasFitPadding,
  canvasFullscreen,
  canvasPanelRef,
  onCanvasModeChange,
  onToggleCanvasFullscreen,
  onSelectEvent,
  onJumpContext,
}: {
  activeRun: RunDetail | null;
  canvasMode: CanvasMode;
  canvasAvailability: Record<CanvasMode, boolean>;
  canvasGraph: { nodes: any[]; edges: any[] };
  canvasEmptyMessage: string;
  canvasFitPadding: number;
  canvasFullscreen: boolean;
  canvasPanelRef: React.RefObject<HTMLDivElement>;
  onCanvasModeChange: (mode: CanvasMode) => void;
  onToggleCanvasFullscreen: () => void;
  onSelectEvent: (eventId: string) => void;
  onJumpContext: (tab: RightRailTab) => void;
}) {
  return (
    <div className="mesh-topology-shell">
      <div className="mesh-section-header">
        <div className="tab-strip canvas-mode-strip" role="tablist" aria-label="Canvas mode">
          {(["labyrinth", "flow", "evidence", "signal", "merkle", "artifacts"] as CanvasMode[]).map((mode) => (
            <button
              key={mode}
              className={canvasMode === mode ? "tab active" : "tab"}
              type="button"
              disabled={!canvasAvailability[mode]}
              onClick={() => onCanvasModeChange(mode)}
              title={canvasAvailability[mode] ? `${canvasModeLabel(mode)} canvas` : `${canvasModeLabel(mode)} unavailable for this run`}
            >
              {canvasModeIcon(mode)}
              {canvasModeLabel(mode)}
            </button>
          ))}
        </div>
      </div>
      <div ref={canvasPanelRef} className="panel graph-panel mesh-topology-panel">
        <div className="graph-panel-fs-toolbar">
          <button
            type="button"
            className="icon-btn graph-panel-fs-btn"
            onClick={onToggleCanvasFullscreen}
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
            minZoom={canvasMode === "labyrinth" ? 0.08 : canvasMode === "flow" ? 0.3 : 0.22}
            nodes={canvasGraph.nodes}
            edges={canvasGraph.edges}
            nodeTypes={nodeTypes}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            onNodeClick={(_, node) => {
              const eventId = String(node.data?.eventId ?? "");
              if (eventId) onSelectEvent(eventId);
              if (node.data?.nodeKind === "merkle") onJumpContext("merkle");
              else if (node.data?.nodeKind === "kubernetes" || canvasMode === "signal") onJumpContext("evidence");
              else if (node.data?.nodeKind === "artifact") onJumpContext(inspectorTabForArtifact(String(node.data?.artifactKey ?? "")));
            }}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#d9dee7" gap={24} />
          </ReactFlow>
        ) : (
          <EmptyState text={canvasEmptyMessage} icon={canvasModeIcon(canvasMode, 28)} />
        )}
      </div>
    </div>
  );
}

function buildDashboardMetrics({
  runs,
  incidentCount,
  approvalCount,
  integrationsReady,
  integrationsTotal,
  agentConnectors,
  watchers,
}: {
  runs: RunSessionRecord[];
  incidentCount: number;
  approvalCount: number;
  integrationsReady: number;
  integrationsTotal: number;
  agentConnectors: AgentConnectorSummary[];
  watchers: WatcherStatus | null;
}): DashboardMetric[] {
  const liveWatchers = watchers?.watchers.filter((watcher) => watcher.running).length ?? 0;
  const readyAgents = agentConnectors.filter((agent) => agent.state === "ready").length;
  return [
    { label: "Runs", value: String(runs.length), detail: "tracked sessions", tone: "neutral" },
    { label: "Incidents", value: String(incidentCount), detail: "active or blocked", tone: incidentCount > 0 ? "warn" : "good" },
    { label: "Approvals", value: String(approvalCount), detail: "operator queue", tone: approvalCount > 0 ? "warn" : "good" },
    { label: "Agents", value: `${readyAgents}/${agentConnectors.length}`, detail: "connected workers", tone: readyAgents > 0 ? "good" : "warn" },
    { label: "Integrations", value: `${integrationsReady}/${integrationsTotal}`, detail: "readiness keys", tone: integrationsReady === integrationsTotal ? "good" : "warn" },
    { label: "Watchers", value: String(liveWatchers), detail: "live signal loops", tone: liveWatchers > 0 ? "good" : "neutral" },
  ];
}

function buildApprovalQueue(run: RunDetail | null, blocked: boolean, reasons: string[]): ApprovalQueueItem[] {
  if (!run || run.stage !== "awaiting_operator") return [];
  return [{
    id: `${run.run_id}-approval`,
    title: blocked ? "Approval blocked" : "Awaiting operator approval",
    detail: reasons[0] ?? "Run is paused at the operator gate.",
    stage: run.pending_pause_stage ?? run.stage,
    blocked,
  }];
}

function buildAgentConnectors(readiness: IntegrationReadiness | null, tasks: AgentTask[]): AgentConnectorSummary[] {
  const attempts = tasks.flatMap((task) => task.attempts ?? []);
  const lastAttempt = (agent: string) => attempts.slice().reverse().find((attempt) => attempt.agent === agent);
  const readinessFor = (key: "hermes" | "goose" | "evo" | "latentmas" | "deepagents") => readiness?.[key] ?? null;
  const fromReadiness = (status: IntegrationReadiness["hermes"] | null): ConnectorState => {
    if (!status) return "disconnected";
    if (status.ready) return "ready";
    if (status.warnings?.length) return "degraded";
    if (status.command || status.url || status.detail) return "config-only";
    return "disconnected";
  };
  const specs = [
    ["hermes", "Hermes", "Default root-cause and blocker interaction", "hermes bridge", readinessFor("hermes"), true],
    ["goose", "Goose", "Operational coordination and review", "goose bridge", readinessFor("goose"), false],
    ["codex", "Codex", "Patch proposal lane", "deepagents/native contract", readinessFor("deepagents"), false],
    ["claudecode", "Claude Code", "Review and risk lane", "deepagents/native contract", readinessFor("deepagents"), false],
    ["openclaw", "OpenClaw", "Staging validation lane", "deepagents/native contract", readinessFor("deepagents"), false],
    ["evo", "Evo", "Benchmark and discovery lane", "evo cli", readinessFor("evo"), false],
    ["latentmas", "LatentMAS", "Advisory full-inference worker", "latentmas sidecar", readinessFor("latentmas"), false],
    ["deepagents", "Deep Agents", "Sandboxed multi-agent proposal fabric", "deepagents", readinessFor("deepagents"), false],
    ["custom-http", "Custom HTTP Agent", "Future external worker connector", "http connector", null, false],
  ] as const;
  return specs.map(([id, name, role, adapter, status, primary]) => {
    const attempt = lastAttempt(id);
    return {
      id,
      name,
      role,
      adapter,
      state: id === "custom-http" ? "disconnected" : fromReadiness(status),
      scope: primary ? "Default Mesh run context" : "Domain/service scoped",
      profile: status?.primary_route ?? status?.url ?? status?.command ?? "Not configured",
      readinessDetail: status?.detail ?? "Connector registry placeholder",
      lastAttempt: attempt ? `${humanize(attempt.status)}: ${attempt.summary}` : undefined,
      riskFlags: attempt?.risk_flags ?? status?.warnings ?? [],
      boundary: "Proposal-only. Mesh owns policy, approval, audit, and execution.",
      primary,
    };
  });
}

function buildIntegrationConnectors(
  readiness: IntegrationReadiness | null,
  watchers: WatcherStatus | null,
  activeSignal: Record<string, any> | null,
): IntegrationConnectorSummary[] {
  const watcherReady = (source: string) => Boolean(watchers?.watchers.some((watcher) => watcher.signal_source === source && watcher.running));
  const statusState = (status?: { ready: boolean; warnings?: string[] } | null): ConnectorState => {
    if (!status) return "disconnected";
    if (status.ready) return "ready";
    if (status.warnings?.length) return "degraded";
    return "config-only";
  };
  const hasRethSignal = String(activeSignal?.signal_type ?? activeSignal?.node?.kind ?? "").toLowerCase().includes("reth");
  return [
    { id: "reth", name: "Reth / geth nodes", domain: "Web3", state: hasRethSignal ? "ready" : "config-only", authType: "Local config", scopes: ["rpc", "sync", "disk", "peers"], detail: hasRethSignal ? "Active node signal loaded" : "Configured through node targets or signal fixtures" },
    { id: "validators", name: "Validators", domain: "Web3", state: "config-only", authType: "Service account", scopes: ["validator", "slashing-safe", "telemetry"], detail: "Domain pack reserved for validator operations" },
    { id: "kurtosis", name: "Kurtosis devnets", domain: "Web3", state: hasRethSignal ? "ready" : "config-only", authType: "Local config", scopes: ["enclave", "service", "restart"], detail: "Bounded devnet actuation behind allowlists" },
    { id: "kubernetes", name: "Kubernetes", domain: "Web2 Production", state: watcherReady("kubernetes") || watcherReady("live_kubernetes") ? "ready" : "config-only", authType: "Service account", scopes: ["deployments", "pods", "events"], detail: "Live execution requires explicit allowlists" },
    { id: "argocd", name: "ArgoCD", domain: "Web2 Production", state: "config-only", authType: "API key", scopes: ["applications", "sync", "health"], detail: "Runtime config supports ArgoCD URL/token" },
    { id: "otel", name: "Prometheus / OpenTelemetry", domain: "Web2 Production", state: watcherReady("otel") || watcherReady("prometheus") ? "ready" : "config-only", authType: "API key", scopes: ["metrics", "slo", "feedback"], detail: "OTLP receiver and Prometheus feedback are opt-in" },
    { id: "logs", name: "Logs", domain: "Web2 Production", state: "disconnected", authType: "OAuth/OIDC", scopes: ["errors", "patterns", "trace"], detail: "Loki/Elastic connector track" },
    { id: "github", name: "GitHub / GitLab", domain: "Development", state: "disconnected", authType: "OAuth/OIDC", scopes: ["repos", "prs", "checks"], detail: "Reserved for repo and release management" },
    { id: "promptfoo", name: "Promptfoo", domain: "Development", state: statusState(readiness?.promptfoo), authType: "Local config", scopes: ["evaluation", "gates"], detail: readiness?.promptfoo.detail ?? "Evaluation bridge" },
    { id: "ci", name: "CI and build gates", domain: "Development", state: "config-only", authType: "OAuth/OIDC", scopes: ["checks", "artifacts", "logs"], detail: "Release-readiness connector track" },
    { id: "pagerduty", name: "PagerDuty / Opsgenie", domain: "Operations", state: "stub", authType: "API key", scopes: ["incidents", "escalations"], detail: "Incident adapter is not production-complete yet" },
    { id: "linear", name: "Linear / Jira", domain: "Operations", state: "disconnected", authType: "OAuth/OIDC", scopes: ["issues", "projects", "comments"], detail: "Work tracking connector track" },
    { id: "audit-sink", name: "Audit sinks", domain: "Operations", state: "stub", authType: "Service account", scopes: ["append-only", "exports"], detail: "Local audit adapter must be mirrored before compliance reliance" },
  ];
}

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
  guideposts,
  eventIndex,
  eventCount,
  onJumpTab,
}: {
  run: RunDetail | null;
  event: RunEventRecord | null;
  insights: Array<{ label: string; value: string; tone?: string }>;
  guideposts: ReturnType<typeof buildLabyrinthGuideposts>;
  eventIndex: number;
  eventCount: number;
  onJumpTab: (tab: RightRailTab) => void;
}) {
  if (!run || !event) {
    return <EmptyState text="Select an event to inspect payload, evidence, and controls." />;
  }

  return (
    <div className="inspector-scroll">
      <section className="context-panel">
        <div className="context-panel-header">
          <div>
            <p className="eyebrow">Event Overview</p>
            <h4>{humanize(event.event_type)}</h4>
          </div>
          <StatusChip label={humanize(event.stage)} tone={toneForStage(event.stage)} />
        </div>
        <div className="context-stat-grid">
          <ContextStat label="Event" value={`${eventIndex + 1}/${eventCount}`} />
          <ContextStat label="Sequence" value={`#${event.sequence}`} />
          <ContextStat label="Recorded" value={formatTimestamp(event.recorded_at)} />
          <ContextStat label="Status" value={event.status ? humanize(event.status) : "Captured"} />
        </div>
      </section>

      {insights.length > 0 && (
        <section className="context-panel">
          <SectionTitle icon={<CircleDot size={14} />} title="Signals" />
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

      {guideposts.length > 0 && (
        <section className="context-panel">
          <SectionTitle icon={<AlertTriangle size={14} />} title="Attention" />
          <div className="guidepost-list">
            {guideposts.map((guidepost) => (
              <article key={guidepost.id} className={`guidepost-card guidepost-${guidepost.severity}`}>
                <strong>{guidepost.title}</strong>
                <p>{guidepost.detail}</p>
                {guidepost.evidence_refs.length > 0 ? <code>{guidepost.evidence_refs.slice(0, 3).join(" / ")}</code> : null}
              </article>
            ))}
          </div>
        </section>
      )}

      <section className="context-panel">
        <SectionTitle icon={<ArrowRight size={14} />} title="Next Actions" />
        <div className="context-action-row">
          <button className="action-button compact" type="button" onClick={() => onJumpTab("steering")}>Steering</button>
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
  hermesExplanation,
  hermesChatDraft,
  onHermesChatDraftChange,
  onHermesChat,
  onAcceptHermesAction,
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
  hermesExplanation: Record<string, any> | null;
  hermesChatDraft: string;
  onHermesChatDraftChange: (value: string) => void;
  onHermesChat: () => void;
  onAcceptHermesAction: () => void;
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
            label="Ask Hermes"
            command="explain_blockers"
            active={active}
            disabled={!activeRunId || !approvalCurrentlyBlocked}
            onClick={onSteer}
          />
          <SteerButton
            label={activeRun?.auto_mode ? "Set Gate" : "Set Auto"}
            command="set_auto_mode"
            active={active}
            disabled={!activeRunId}
            onClick={(cmd) => onSteer(cmd, { enabled: !(activeRun?.auto_mode ?? false) })}
          />
        </div>
        <div className="stack">
          {approvalCurrentlyBlocked && hermesExplanation && (
            <section className="context-panel">
              <div className="context-panel-header">
                <div>
                  <p className="eyebrow">Hermes Explanation</p>
                  <h4>{humanize(String(hermesExplanation.recommendation ?? "human_review"))}</h4>
                </div>
                <StatusChip label="Hermes" tone="#4aa8ff" />
              </div>
              <p className="inspector-muted">{String(hermesExplanation.summary ?? "No explanation available.")}</p>
              {Array.isArray(hermesExplanation.operator_actions) && hermesExplanation.operator_actions.length > 0 && (
                <div className="context-link-list">
                  {hermesExplanation.operator_actions.slice(0, 3).map((action) => (
                    <ContextLink key={String(action)} label="Action" value={String(action)} />
                  ))}
                </div>
              )}
              {Array.isArray(hermesExplanation.messages) && hermesExplanation.messages.length > 0 && (
                <div className="stack">
                  {hermesExplanation.messages.slice(-6).map((message, index) => (
                    <pre key={`${String(message.role)}-${index}`} className="timeline-summary">
                      {`${humanize(String(message.role ?? "assistant"))}: ${String(message.content ?? "")}`}
                    </pre>
                  ))}
                </div>
              )}
              <div className="note-row">
                <input
                  value={hermesChatDraft}
                  onChange={(e) => onHermesChatDraftChange(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && hermesChatDraft.trim()) {
                      onHermesChat();
                    }
                  }}
                  placeholder="Ask Hermes a follow-up…"
                  disabled={!approvalCurrentlyBlocked}
                />
                <button
                  className="action-button compact"
                  disabled={!approvalCurrentlyBlocked || !hermesChatDraft.trim()}
                  onClick={onHermesChat}
                >
                  Send
                </button>
              </div>
              <button
                className="action-button compact"
                disabled={!hermesExplanation.proposed_command}
                onClick={onAcceptHermesAction}
              >
                Accept Hermes Action
              </button>
            </section>
          )}
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

function AgentMeshPanel({
  run,
  tasks,
  active,
  onSteer,
}: {
  run: RunDetail | null;
  tasks: AgentTask[];
  active: string;
  onSteer: (command: string, payload?: Record<string, unknown>) => void;
}) {
  const fallbackTasks = Array.isArray(run?.artifacts?.agent_tasks)
    ? (run?.artifacts?.agent_tasks as AgentTask[])
    : [];
  const resolvedTasks = tasks.length > 0 ? tasks : fallbackTasks;
  const evoLaunches = Array.isArray((run?.artifacts?.evo_launches as { launches?: EvoLaunchRecord[] } | undefined)?.launches)
    ? (((run?.artifacts?.evo_launches as { launches?: EvoLaunchRecord[] }).launches ?? []) as EvoLaunchRecord[])
    : [];
  const defaultTargetPath = resolvedTasks.flatMap((task) => task.allowed_paths)[0] ?? "";
  const defaultGateCommand = resolvedTasks.flatMap((task) => task.test_commands)[0] ?? "";
  const [targetPath, setTargetPath] = useState(defaultTargetPath);
  const [benchmarkCommand, setBenchmarkCommand] = useState("");
  const [metric, setMetric] = useState("max");
  const [instrumentationMode, setInstrumentationMode] = useState("inline");
  const [gateCommand, setGateCommand] = useState(defaultGateCommand);

  useEffect(() => {
    setTargetPath(defaultTargetPath);
    setGateCommand(defaultGateCommand);
    setBenchmarkCommand("");
    setMetric("max");
    setInstrumentationMode("inline");
  }, [run?.run_id, defaultTargetPath, defaultGateCommand]);

  if (!run) {
    return <EmptyState text="Agent worker tasks will appear after a run reaches evaluation." />;
  }
  if (resolvedTasks.length === 0) {
    return (
      <div className="inspector-scroll">
        <section className="context-panel">
          <SectionTitle icon={<Bot size={14} />} title="Agent Mesh" />
          <p className="inspector-muted">
            No agent tasks recorded yet. Launch a run that reaches decision and evaluation.
          </p>
        </section>
      </div>
    );
  }

  return (
    <div className="inspector-scroll">
      <section className="context-panel">
        <div className="context-panel-header">
          <div>
            <p className="eyebrow">Agent Mesh</p>
            <h4>{resolvedTasks.length} task{resolvedTasks.length === 1 ? "" : "s"} recorded</h4>
          </div>
          <StatusChip label="Read Only" tone="#41d6b1" />
        </div>
        <p className="inspector-muted">
          Workers produce proposals and risk signals. Mesh keeps policy, tests, audit, Kubernetes actuation, and production promotion gates.
        </p>
      </section>

      <section className="context-panel">
        <div className="context-panel-header">
          <div>
            <p className="eyebrow">Evo Launch</p>
            <h4>Operator-triggered discovery bootstrap</h4>
          </div>
          <StatusChip label={active === "launch_evo" ? "Launching" : "Manual"} tone={active === "launch_evo" ? "#f2b84b" : "#41d6b1"} />
        </div>
        <div className="stack">
          <input
            value={targetPath}
            onChange={(e) => setTargetPath(e.target.value)}
            placeholder="Target path"
            disabled={!defaultTargetPath || active === "launch_evo"}
          />
          <textarea
            value={benchmarkCommand}
            onChange={(e) => setBenchmarkCommand(e.target.value)}
            placeholder="Benchmark command (required unless the repo already contains .evo/meta.json)"
            className="small-textarea mono-textarea"
            disabled={active === "launch_evo"}
          />
          <div className="steering-grid">
            <select value={metric} onChange={(e) => setMetric(e.target.value)} disabled={active === "launch_evo"}>
              <option value="max">Metric: max</option>
              <option value="min">Metric: min</option>
            </select>
            <select
              value={instrumentationMode}
              onChange={(e) => setInstrumentationMode(e.target.value)}
              disabled={active === "launch_evo"}
            >
              <option value="inline">Instrumentation: inline</option>
              <option value="sdk">Instrumentation: sdk</option>
            </select>
          </div>
          <input
            value={gateCommand}
            onChange={(e) => setGateCommand(e.target.value)}
            placeholder="Gate command"
            disabled={active === "launch_evo"}
          />
          <button
            className="action-button compact"
            disabled={!targetPath.trim() || !gateCommand.trim() || active === "launch_evo"}
            onClick={() =>
              onSteer("launch_evo", {
                target_path: targetPath.trim(),
                benchmark_command: benchmarkCommand.trim() || undefined,
                metric,
                instrumentation_mode: instrumentationMode,
                gate_command: gateCommand.trim(),
              })
            }
          >
            Launch Evo
          </button>
          {evoLaunches.length > 0 && (
            <div className="stack">
              {evoLaunches.map((launch) => (
                <article key={launch.launch_id} className="agent-attempt-card">
                  <div className="agent-attempt-header">
                    <strong>{humanize(launch.action)}</strong>
                    <span className={launch.status === "completed" ? "agent-risk-badge good" : launch.status === "failed" ? "agent-risk-badge warn" : "agent-risk-badge"}>
                      {humanize(launch.status)}
                    </span>
                  </div>
                  <div className="context-link-list compact">
                    <ContextLink label="Target" value={launch.target_path} mono />
                    {launch.experiment_id ? <ContextLink label="Experiment" value={launch.experiment_id} mono /> : null}
                    {launch.dashboard_url ? <ContextLink label="Dashboard" value={launch.dashboard_url} mono /> : null}
                  </div>
                  {launch.error ? <div className="readiness-warning">{launch.error}</div> : null}
                </article>
              ))}
            </div>
          )}
        </div>
      </section>

      {resolvedTasks.map((task) => (
        <section key={task.task_id} className="context-panel">
          <div className="context-panel-header">
            <div>
              <p className="eyebrow">{humanize(task.kind)}</p>
              <h4>{task.task_id}</h4>
            </div>
            <StatusChip label={humanize(task.status)} tone={task.status === "completed" ? "#41d6b1" : "#f2b84b"} />
          </div>
          <div className="context-stat-grid">
            <ContextStat label="Workers" value={String(task.attempts.length)} />
            <ContextStat label="Selected" value={task.selected_attempt_id ? task.selected_attempt_id.split("_").slice(-2, -1)[0] ?? "set" : "none"} />
            <ContextStat label="Paths" value={String(task.allowed_paths.length)} />
            <ContextStat label="Tests" value={String(task.test_commands.length)} />
          </div>
          {Object.keys(task.kubernetes_scope ?? {}).length > 0 && (
            <div className="context-link-list">
              {Object.entries(task.kubernetes_scope).map(([key, value]) => (
                value ? <ContextLink key={key} label={humanize(key)} value={String(value)} /> : null
              ))}
            </div>
          )}
          <div className="agent-attempt-grid">
            {task.attempts.map((attempt) => {
              const selected = attempt.attempt_id === task.selected_attempt_id;
              const blocked = attempt.risk_flags.length > 0;
              const metrics =
                attempt.output && typeof attempt.output.metrics === "object" && attempt.output.metrics !== null
                  ? (attempt.output.metrics as Record<string, unknown>)
                  : null;
              return (
                <article key={attempt.attempt_id} className={`agent-attempt-card ${selected ? "selected" : ""}`}>
                  <div className="agent-attempt-header">
                    <strong>{humanize(attempt.agent)}</strong>
                    <span className={blocked ? "agent-risk-badge warn" : "agent-risk-badge good"}>
                      {blocked ? "gated" : humanize(attempt.status)}
                    </span>
                  </div>
                  <p>{attempt.summary}</p>
                  <div className="context-link-list compact">
                    <ContextLink label="Action" value={humanize(attempt.recommended_action)} />
                    <ContextLink label="Adapter" value={attempt.adapter} />
                    {typeof attempt.output?.confidence === "number" && (
                      <ContextLink label="Confidence" value={`${Math.round(attempt.output.confidence * 100)}%`} />
                    )}
                    {metrics?.model_name != null && <ContextLink label="Model" value={String(metrics.model_name)} />}
                    {typeof metrics?.elapsed_time_sec === "number" && (
                      <ContextLink label="Latency" value={`${metrics.elapsed_time_sec}s`} />
                    )}
                  </div>
                  {attempt.risk_flags.length > 0 && (
                    <div className="readiness-warning">
                      {attempt.risk_flags.map((flag) => humanize(flag)).join(", ")}
                    </div>
                  )}
                  {attempt.changed_files.length > 0 && (
                    <pre className="timeline-summary">{attempt.changed_files.join("\n")}</pre>
                  )}
                  {attempt.test_results.length > 0 && (
                    <pre className="timeline-summary">{JSON.stringify(attempt.test_results, null, 2)}</pre>
                  )}
                  {typeof attempt.output?.workspace_path === "string" && attempt.output.workspace_path ? (
                    <ContextLink label="Workspace" value={String(attempt.output.workspace_path)} />
                  ) : null}
                  {typeof attempt.output?.diff === "string" && attempt.output.diff.trim() !== "" ? (
                    <pre className="timeline-summary">{String(attempt.output.diff)}</pre>
                  ) : null}
                </article>
              );
            })}
          </div>
        </section>
      ))}
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
  subline,
  warning,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone?: "good" | "warn" | "danger";
  subline?: string;
  warning?: string;
}) {
  return (
    <div className={`header-metric ${tone ?? ""}`}>
      <span className="header-metric-icon">{icon}</span>
      <div>
        <p>{label}</p>
        <strong>{value}</strong>
        {subline ? <span className="header-metric-subline">{subline}</span> : null}
        {warning ? <span className="header-metric-warning">{warning}</span> : null}
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

function runDetailTabLabel(tab: RunDetailTab) {
  switch (tab) {
    case "timeline":
      return "Transcript";
    case "approvals":
      return "Review gates";
    case "actions":
      return "Steering";
    default:
      return humanize(tab);
  }
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
