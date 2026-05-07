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
  buildRcaGraph,
  buildRethSignalGraph,
  buildRunGraph,
  toneForStage,
  type RcaGraphBlocker,
  type RcaGraphCandidate,
  type RcaGraphCitation,
  type RcaGraphInput,
  type RcaGraphToolCall,
  type RunGraphNode,
} from "./lib/runGraph";
import type {
  ApprovalQueueItem,
  ApprovalQueuePacket,
  BenchmarkRecord,
  ConnectorCertificationPacket,
  DarkharnessPilotPacket,
  HealthSnapshot,
  KillSwitchStatus,
  ConnectionStatus,
  EvidenceGraph,
  GoalRecord,
  InspectorTab,
  IntegrationReadiness,
  MerkleProof,
  PilotGoNoGoPacket,
  PolicySimulationResult,
  ResearchCorpusIntelligence,
  ResearchSessionDetail,
  ResearchSessionRecord,
  RunDetail,
  RunExportPackage,
  RunEventRecord,
  RunSessionRecord,
  AgentTask,
  ScenarioAnalysis,
  ScenarioRecord,
  ServiceAgentRecord,
  SimulationScenarioRecord,
  TrustLadderEntry,
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
type CanvasMode = "labyrinth" | "flow" | "evidence" | "rca" | "signal" | "merkle" | "artifacts";
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
  | "simulator"
  | "trust"
  | "packets"
  | "roadmap"
  | "settings";
type RunDetailTab = "timeline" | "evidence" | "rca" | "approvals" | "actions" | "darkharness" | "audit" | "agents" | "topology";
type ConnectorState =
  | "ready"
  | "degraded"
  | "config-only"
  | "unsafe"
  | "stub"
  | "disconnected"
  | "mock"
  | "read-only"
  | "staging-ready"
  | "pilot-ready"
  | "production-ready"
  | "unfinished"
  | "disabled"
  | "proposal-only";

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

interface ConfidencePoint {
  id: string;
  label: string;
  value: number;
  detail: string;
  tone: string;
}

interface RcaSnapshot extends RcaGraphInput {
  confidenceMovement: ConfidencePoint[];
  report: Record<string, any> | null;
}

const AUTHORITY_PIPELINE = [
  "Signal",
  "Trigger",
  "Evidence",
  "RCA",
  "Policy",
  "Model Review",
  "Evaluation",
  "Steering",
  "Execution",
  "Feedback",
  "Memory",
];

const ROADMAP_PHASES = [
  {
    id: "phase-1",
    title: "Local production-like E2E",
    gate: "Evidence graph, simulator, failure library, live actuator blocks",
    before: "local stack",
  },
  {
    id: "phase-2",
    title: "Private staging",
    gate: "Identity, RBAC, tiered readiness, connector certification, kill switch",
    before: "external operators",
  },
  {
    id: "phase-3",
    title: "Controlled pilot",
    gate: "Go/no-go packet, live proof, approval split, rollback and drills",
    before: "production pilot",
  },
  {
    id: "phase-4",
    title: "Expansion",
    gate: "Postgres default, load, procurement, SLO dashboards, release train",
    before: "repeatable production",
  },
];

const ROADMAP_PRIORITY_SURFACES = [
  ["Identity-first control plane", "Operator identity, roles, approvals, audit"],
  ["Evidence graph", "Default run inspection surface"],
  ["Policy simulator", "Mutation-free replay for fixtures and captured runs"],
  ["Pilot packet", "Evidence-generated go/no-go artifact"],
  ["Connector matrix", "Mock, read-only, staging, pilot, production states"],
  ["Failure library", "Replayable denied and degraded states"],
  ["Trust ladder", "Autonomy earned per service and action class"],
  ["Run export", "Postmortem, audit, Merkle, decision, evaluation records"],
  ["Kill switch", "Watcher, live execution, namespace, action gate controls"],
];

const EVIDENCE_PACKET_LINKS = [
  ["Evaluation kit", "docs/evaluation-kits.md"],
  ["Hardening records", "docs/production-hardening-records.md"],
  ["Design partner packet", "docs/design-partner-packet.md"],
  ["Community governance", "docs/community-governance.md"],
  ["Postgres restart proof", "docs/postgres-restart-proof.md"],
];

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
    case "rca":
      return "RCA";
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
    case "rca":
      return <AlertTriangle size={size} />;
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
  const [connectorCertification, setConnectorCertification] = useState<ConnectorCertificationPacket | null>(null);
  const [approvalPacket, setApprovalPacket] = useState<ApprovalQueuePacket | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioRecord[]>([]);
  const [goals, setGoals] = useState<GoalRecord[]>([]);
  const [runs, setRuns] = useState<RunSessionRecord[]>([]);
  const [researchSessions, setResearchSessions] = useState<ResearchSessionRecord[]>([]);
  const [researchCorpus, setResearchCorpus] = useState<ResearchCorpusIntelligence | null>(null);
  const [simulations, setSimulations] = useState<SimulationScenarioRecord[]>([]);
  const [benchmarks, setBenchmarks] = useState<BenchmarkRecord[]>([]);
  const [serviceAgents, setServiceAgents] = useState<ServiceAgentRecord[]>([]);
  const [trustLadder, setTrustLadder] = useState<TrustLadderEntry[]>([]);
  const [killSwitchStatus, setKillSwitchStatus] = useState<KillSwitchStatus | null>(null);
  const [pilotPacket, setPilotPacket] = useState<PilotGoNoGoPacket | null>(null);
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
  const [policySimulationDraft, setPolicySimulationDraft] = useState('{\n  "scenario_key": ""\n}');
  const [policySimulation, setPolicySimulation] = useState<PolicySimulationResult | null>(null);
  const [selectedSimulationId, setSelectedSimulationId] = useState("");
  const [showGoalForm, setShowGoalForm] = useState(false);
  const [showOverrides, setShowOverrides] = useState(false);
  const [leftRailOpen, setLeftRailOpen] = useState(true);
  const [rightRailOpen, setRightRailOpen] = useState(false);
  const [canvasMode, setCanvasMode] = useState<CanvasMode>("evidence");
  const [activeView, setActiveView] = useState<AppView>("overview");
  const [runDetailTab, setRunDetailTab] = useState<RunDetailTab>("evidence");

  const [rightRailTab, setRightRailTab] = useState<RightRailTab>("overview");
  const [selectedEventId, setSelectedEventId] = useState("");
  const [vaultDocument, setVaultDocument] = useState("");
  const [vaultTree, setVaultTree] = useState<VaultTreeEntry[] | null>(null);
  const [merkleProof, setMerkleProof] = useState<MerkleProof | null>(null);
  const [runExport, setRunExport] = useState<RunExportPackage | null>(null);
  const [darkharnessPacket, setDarkharnessPacket] = useState<DarkharnessPilotPacket | null>(null);

  const [systemConnection, setSystemConnection] = useState<ConnectionStatus>("reconnecting");
  const [runConnection, setRunConnection] = useState<ConnectionStatus>("reconnecting");

  const [booting, setBooting] = useState(true);
  const [launching, setLaunching] = useState(false);
  const [steering, setSteering] = useState("");
  const [creatingGoal, setCreatingGoal] = useState(false);
  const [killSwitching, setKillSwitching] = useState(false);
  const [simulatingPolicy, setSimulatingPolicy] = useState(false);
  const [runningSimulation, setRunningSimulation] = useState("");
  const [exportingRun, setExportingRun] = useState(false);
  const [exportingArchive, setExportingArchive] = useState(false);

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
        void api.getConnectorCertification(baseUrl).then(setConnectorCertification).catch(() => setConnectorCertification(null));
        void api.getApprovals(baseUrl).then(setApprovalPacket).catch(() => setApprovalPacket(null));
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
      setRunExport(null);
      setDarkharnessPacket(null);
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
      const [
        healthRes,
        readinessRes,
        goalsRes,
        runsRes,
        researchRes,
        researchCorpusRes,
        watchersRes,
        simulationsRes,
        benchmarksRes,
        serviceAgentsRes,
        trustLadderRes,
        killSwitchRes,
        connectorCertificationRes,
        approvalQueueRes,
        pilotPacketRes,
      ] = await Promise.all([
        boot(api.getHealth(baseUrl), null),
        boot(api.getReadiness(baseUrl), null),
        boot(api.getGoals(baseUrl), { goals: [] }),
        boot(api.getRuns(baseUrl), { runs: [] }),
        boot(api.getResearchSessions(baseUrl), { sessions: [] }),
        boot(api.getResearchCorpus(baseUrl), null),
        boot(api.getWatchers(baseUrl), null),
        boot(api.getSimulations(baseUrl), { simulations: [] }),
        boot(api.getBenchmarks(baseUrl), { benchmarks: [] }),
        boot(api.getServiceAgents(baseUrl), { service_agents: [] }),
        boot(api.getTrustLadder(baseUrl), { entries: [] }),
        boot(api.getKillSwitch(baseUrl), null),
        boot(api.getConnectorCertification(baseUrl), null),
        boot(api.getApprovals(baseUrl), null),
        boot(api.getPilotGoNoGo(baseUrl), null),
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
      setSimulations(simulationsRes.simulations);
      setBenchmarks(benchmarksRes.benchmarks);
      setServiceAgents(serviceAgentsRes.service_agents);
      setTrustLadder(trustLadderRes.entries);
      setKillSwitchStatus(killSwitchRes);
      setConnectorCertification(connectorCertificationRes);
      setApprovalPacket(approvalQueueRes);
      setPilotPacket(pilotPacketRes);
      if (!selectedGoalId && goalsRes.goals[0]) setSelectedGoalId(goalsRes.goals[0].goal_id);
      if (!activeRunId && runsRes.runs[0]) setActiveRunId(runsRes.runs[0].run_id);
      void withTimeout(api.getScenarios(baseUrl), 4_000).then((scenariosRes) => {
        setScenarios(scenariosRes.scenarios);
        if (scenariosRes.scenarios[0] && !launchDraft.scenarioKey) {
          setLaunchDraft((d) => ({ ...d, scenarioKey: scenariosRes.scenarios[0].key }));
          setPolicySimulationDraft(JSON.stringify({ scenario_key: scenariosRes.scenarios[0].key }, null, 2));
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
      const [run, taskResponse, analysisResponse, evidenceResponse, memoryResponse, darkharnessResponse] = await Promise.all([
        api.getRun(baseUrl, runId),
        api.getAgentTasks(baseUrl, runId).catch(() => ({ tasks: [] as AgentTask[] })),
        api.getScenarioAnalysis(baseUrl, runId).catch(() => null),
        api.getEvidenceGraph(baseUrl, runId).catch(() => null),
        api.getMemoryCrystallization(baseUrl, runId).catch(() => null),
        api.getRunDarkharnessPacket(baseUrl, runId).catch(() => null),
      ]);
      setActiveRun(run);
      setAgentTasks(taskResponse.tasks);
      setScenarioAnalysis(analysisResponse);
      setEvidenceGraph(evidenceResponse);
      setMemoryCrystallization(memoryResponse);
      setDarkharnessPacket(darkharnessResponse);
      setRunExport((current) => (current?.run_id === runId ? current : null));
    } catch (error) {
      addToast({ variant: "error", title: "Failed to load run", description: error instanceof Error ? error.message : "Unknown error" });
    }
  }

  async function handleBuildRunExport() {
    if (!activeRunId) {
      addToast({ variant: "warning", title: "No run selected" });
      return;
    }
    setExportingRun(true);
    try {
      const exported = await api.getRunExport(baseUrl, activeRunId);
      setRunExport(exported);
      await loadRun(activeRunId);
      addToast({
        variant: "success",
        title: "Run export generated",
        description: `${exported.timeline_json.length} events, ${exported.vault_documents.length} vault documents`,
      });
    } catch (error) {
      addToast({ variant: "error", title: "Run export failed", description: error instanceof Error ? error.message : "Unknown error" });
    } finally {
      setExportingRun(false);
    }
  }

  async function handleBuildRunArchive() {
    if (!activeRunId) {
      addToast({ variant: "warning", title: "No run selected" });
      return;
    }
    setExportingArchive(true);
    try {
      const { blob, filename } = await api.getRunExportArchive(baseUrl, activeRunId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      await loadRun(activeRunId);
      addToast({ variant: "success", title: "Run archive generated", description: filename });
    } catch (error) {
      addToast({ variant: "error", title: "Run archive failed", description: error instanceof Error ? error.message : "Unknown error" });
    } finally {
      setExportingArchive(false);
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

  async function handleApplyKillSwitch() {
    setKillSwitching(true);
    try {
      const status = await api.applyKillSwitch(baseUrl, {
        stop_watchers: true,
        disable_live_execution: true,
        force_approval_gate: true,
      });
      const [readinessRes, watchersRes, pilotPacketRes] = await Promise.all([
        api.getReadiness(baseUrl).catch(() => null),
        api.getWatchers(baseUrl).catch(() => null),
        api.getPilotGoNoGo(baseUrl).catch(() => null),
      ]);
      setReadiness(readinessRes);
      setWatchers(watchersRes);
      setKillSwitchStatus(status);
      setPilotPacket(pilotPacketRes);
      addToast({ variant: "warning", title: "Kill switch applied", description: "Watchers stopped, live execution disabled, approval gate forced." });
    } catch (error) {
      addToast({ variant: "error", title: "Kill switch failed", description: error instanceof Error ? error.message : "Unknown error" });
    } finally {
      setKillSwitching(false);
    }
  }

  async function handleSimulatePolicy(payloadOverride?: Record<string, unknown>) {
    setSimulatingPolicy(true);
    try {
      let payload = payloadOverride;
      if (!payload) {
        const parsed = safeJsonParse<Record<string, unknown>>(policySimulationDraft);
        if (!parsed.ok) {
          addToast({ variant: "error", title: "Invalid simulator JSON", description: parsed.error });
          return;
        }
        payload = parsed.data;
      }
      const fallbackScenario = launchDraft.scenarioKey || scenarios[0]?.key;
      if (!payload.signal_payload && !payload.scenario_key && !payload.run_id && !payload.captured_run_id && fallbackScenario) {
        payload = { ...payload, scenario_key: fallbackScenario };
      }
      const result = await api.simulatePolicy(baseUrl, payload);
      setPolicySimulation(result);
      addToast({
        variant: result.blockers.length > 0 ? "warning" : "success",
        title: "Policy simulation complete",
        description: result.mutates ? "Unexpected mutation flag returned." : "Mutation-free dry run recorded.",
      });
    } catch (error) {
      addToast({ variant: "error", title: "Policy simulation failed", description: error instanceof Error ? error.message : "Unknown error" });
    } finally {
      setSimulatingPolicy(false);
    }
  }

  async function handleRunSimulation(scenarioId: string) {
    if (!scenarioId) return;
    setRunningSimulation(scenarioId);
    try {
      const run = await api.runSimulation(baseUrl, scenarioId, {
        goal_id: selectedGoalId || goals[0]?.goal_id,
        evaluation_mode: launchDraft.evaluationMode,
        orchestration_mode: "native",
        steering_mode: "approval_gate",
        pause_points: ["evaluation_ready"],
      });
      setActiveRunId(run.run_id);
      setActiveResearchSessionId("");
      setResearchDetail(null);
      setActiveView("runs");
      setRunDetailTab("evidence");
      await refreshBootstrap();
      addToast({ variant: "success", title: "Simulation run launched", description: scenarioId });
    } catch (error) {
      addToast({ variant: "error", title: "Simulation launch failed", description: error instanceof Error ? error.message : "Unknown error" });
    } finally {
      setRunningSimulation("");
    }
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
  const rcaSnapshot = useMemo(
    () => buildRcaSnapshot(activeRun, scenarioAnalysis, agentTasks, approvalBlockingReasons),
    [activeRun, agentTasks, approvalBlockingReasons, scenarioAnalysis],
  );
  const rcaCanvas = useMemo(
    () => buildRcaGraph(rcaSnapshot),
    [rcaSnapshot],
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
      case "rca":
        return rcaCanvas;
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
  }, [artifactCanvas, canvasMode, evidenceCanvas, flowCanvas, labyrinthCanvas, merkleCanvas, rcaCanvas, signalCanvas]);
  const canvasAvailability = useMemo(
    () => ({
      labyrinth: labyrinthCanvas.nodes.length > 0,
      flow: flowCanvas.nodes.length > 0,
      evidence: evidenceCanvas.nodes.length > 0,
      rca: rcaCanvas.nodes.length > 0,
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
      rcaCanvas.nodes.length,
      signalCanvas.nodes.length,
    ],
  );
  const canvasEmptyMessage = useMemo(() => {
    switch (canvasMode) {
      case "labyrinth":
        return "Start or select a run to see the operation map.";
      case "evidence":
        return "This run has no scenario-analysis evidence graph yet.";
      case "rca":
        return "This run has no investigation report, tool trajectory, RCA candidates, blockers, or citations yet.";
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
  const readinessItems = readiness
    ? [
        readiness.promptfoo,
        readiness.hermes,
        readiness.goose,
        readiness.latentmas,
        readiness.deepagents,
      ]
    : [];
  const integrationsReady = readinessItems.filter((i) => i?.ready).length;
  const integrationsTotal = readinessItems.length || 5;
  const inferencePrimaryRoute = readiness?.goose.primary_route ?? "Booting";
  const inferenceFallbackRoute = readiness?.goose.fallback_route ?? null;
  const inferenceWarning = readiness?.goose.warnings?.[0] ?? null;
  const environmentLabel = health ? humanize(health.environment) : "Booting";
  const buildSubline = health ? `v${health.version} • ${health.commit.slice(0, 7)}` : undefined;
  const requiredChecks = Object.entries(readiness?.required_checks ?? {});
  const requiredChecksPassing = requiredChecks.filter(([, value]) => value === true || typeof value !== "boolean").length;
  const requiredChecksTotal = requiredChecks.length;
  const readinessBlockerCount = readiness?.blockers.length ?? 0;
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
    () => approvalPacket?.items ?? buildApprovalQueue(activeRun, approvalCurrentlyBlocked, approvalBlockingReasons),
    [activeRun, approvalBlockingReasons, approvalCurrentlyBlocked, approvalPacket?.items],
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
    if (canvasAvailability.evidence) {
      setCanvasMode("evidence");
      return;
    }
    if (canvasAvailability.labyrinth) {
      setCanvasMode("labyrinth");
      return;
    }
    if (canvasAvailability.flow) {
      setCanvasMode("flow");
      return;
    }
    if (canvasAvailability.rca) {
      setCanvasMode("rca");
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
              setRunDetailTab("evidence");
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

      <aside className={`mesh-sidebar mesh-session-rail ${leftRailOpen ? "" : "collapsed"}`} aria-label="orbital-mesh workspace sessions">
        <div className="mesh-sidebar-brand">
          <div className="brand-icon"><Codicon name="circuit-board" /></div>
          {leftRailOpen ? (
            <div>
              <p className="mesh-kicker">orbital-mesh</p>
              <h1>Operator Console</h1>
              <span className="mesh-brand-subtitle">Bounded production authority</span>
            </div>
          ) : null}
        </div>
        <nav className="mesh-nav" data-testid="mesh-primary-nav">
          {([
            ["overview", "Command", <Codicon name="home" />],
            ["runs", "Evidence Runs", <Codicon name="run-all" />],
            ["approvals", "Approvals", <Codicon name="pass" />],
            ["automation", "Launch", <Codicon name="play" />],
            ["simulator", "Simulator", <Codicon name="beaker" />],
            ["trust", "Trust Ladder", <Codicon name="shield" />],
            ["packets", "Pilot Packet", <Codicon name="package" />],
            ["control-plane", "Readiness", <Codicon name="server-environment" />],
            ["evidence", "Evidence", <Codicon name="references" />],
            ["integrations", "Connectors", <PlugIcon />],
            ["agents", "Proposal Lanes", <Codicon name="hubot" />],
            ["fleet", "Signals", <Codicon name="broadcast" />],
            ["hermes", "Hermes", <Codicon name="sparkle" />],
            ["audit", "Audit", <Codicon name="verified" />],
            ["roadmap", "Roadmap", <Codicon name="list-tree" />],
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
              aria-label={label}
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
              icon={<Codicon name="server-environment" />}
              title="Readiness gates"
              detail={readiness?.blockers.length ? readiness.blockers[0] : `${humanize(readiness?.profile ?? "local")} profile`}
              count={readiness?.status ?? "boot"}
              active={activeView === "control-plane"}
              tone={(readiness?.blockers.length ?? 0) > 0 ? "warn" : "good"}
              onClick={() => setActiveView("control-plane")}
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
              icon={<Codicon name="beaker" />}
              title="Policy simulator"
              detail={policySimulation ? (policySimulation.blockers.length ? "Denied path visible" : "Allowed path visible") : "Mutation-free replay"}
              count={String(simulations.length)}
              active={activeView === "simulator"}
              tone={policySimulation?.blockers.length ? "warn" : "neutral"}
              onClick={() => setActiveView("simulator")}
            />
            <RailWorkstreamButton
              icon={<Codicon name="references" />}
              title="Evidence graph"
              detail={`${recentEvidenceEvents.length} recent proof events`}
              count={String(recentEvidenceEvents.length)}
              active={activeView === "evidence" || activeView === "runs"}
              onClick={() => setActiveView("evidence")}
            />
            <RailWorkstreamButton
              icon={<Codicon name="package" />}
              title="Pilot packet"
              detail={pilotPacket ? humanize(pilotPacket.status) : "No packet"}
              count={pilotPacket?.missing_evidence.length ? String(pilotPacket.missing_evidence.length) : "0"}
              active={activeView === "packets"}
              tone={pilotPacket?.status === "go" ? "good" : "warn"}
              onClick={() => setActiveView("packets")}
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
            <p className="mesh-kicker">Production deployment control plane</p>
            <h2>{viewTitle(activeView)}</h2>
            <span>{activeGoal?.title ?? "No active goal"} / {activeRun ? activeRun.run_id.slice(0, 12) : "no run"}</span>
          </div>
          <div className="mesh-topbar-metrics">
            <HeaderMetric icon={<Codicon name="server-environment" />} label="Environment" value={environmentLabel} subline={buildSubline} />
            <HeaderMetric
              icon={<Codicon name="shield" />}
              label="Readiness"
              value={readiness ? humanize(readiness.profile) : "Unknown"}
              subline={requiredChecksTotal ? `${requiredChecksPassing}/${requiredChecksTotal} required gates` : undefined}
              warning={readinessBlockerCount ? `${readinessBlockerCount} blockers` : undefined}
              tone={readinessBlockerCount ? "danger" : "good"}
            />
            <HeaderMetric
              icon={<Codicon name="package" />}
              label="Pilot packet"
              value={pilotPacket ? humanize(pilotPacket.status) : "Unknown"}
              subline={pilotPacket ? `${pilotPacket.observed.run_count} evidence runs` : undefined}
              warning={pilotPacket?.missing_evidence.length ? `${pilotPacket.missing_evidence.length} missing proofs` : undefined}
              tone={pilotPacket?.status === "go" ? "good" : pilotPacket ? "warn" : "danger"}
            />
            <HeaderMetric
              icon={<Codicon name="git-branch" />}
              label="Authority"
              value={humanize(activeRun?.steering_mode ?? launchDraft.steeringMode)}
              subline={`${trustLadder.length} trust entries`}
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
              readiness={readiness}
              pilotPacket={pilotPacket}
              trustLadder={trustLadder}
              serviceAgents={serviceAgents}
              simulations={simulations}
              benchmarks={benchmarks}
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
              rcaSnapshot={rcaSnapshot}
              approvalQueue={approvalQueue}
              recentEvidenceEvents={recentEvidenceEvents}
              selectedEventInsights={selectedEventInsights}
              merkleProof={merkleProof}
              runExport={runExport}
              darkharnessPacket={darkharnessPacket}
              exportingRun={exportingRun}
              exportingArchive={exportingArchive}
              onSelectRun={(runId) => {
                setActiveRunId(runId);
                setActiveResearchSessionId("");
                setResearchDetail(null);
              }}
              onSelectEvent={setSelectedEventId}
              onRunDetailTabChange={setRunDetailTab}
              onCanvasModeChange={setCanvasMode}
              onToggleCanvasFullscreen={toggleCanvasFullscreen}
              onBuildRunExport={() => void handleBuildRunExport()}
              onBuildRunArchive={() => void handleBuildRunArchive()}
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
            <IntegrationsView
              connectors={integrationConnectors}
              readiness={readiness}
              connectorCertification={connectorCertification}
              watchers={watchers}
            />
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
              trustLadder={trustLadder}
              killSwitchStatus={killSwitchStatus}
              pilotPacket={pilotPacket}
              serviceAgents={serviceAgents}
              benchmarks={benchmarks}
              killSwitching={killSwitching}
              onApplyKillSwitch={handleApplyKillSwitch}
            />
          ) : activeView === "simulator" ? (
            <SimulatorView
              scenarios={scenarios}
              simulations={simulations}
              activeRun={activeRun}
              runs={runs}
              policySimulationDraft={policySimulationDraft}
              policySimulation={policySimulation}
              selectedSimulationId={selectedSimulationId}
              simulatingPolicy={simulatingPolicy}
              runningSimulation={runningSimulation}
              onPolicySimulationDraftChange={setPolicySimulationDraft}
              onSelectedSimulationIdChange={setSelectedSimulationId}
              onSimulatePolicy={(payload) => void handleSimulatePolicy(payload)}
              onRunSimulation={(scenarioId) => void handleRunSimulation(scenarioId)}
            />
          ) : activeView === "trust" ? (
            <TrustLadderView trustLadder={trustLadder} serviceAgents={serviceAgents} activeRun={activeRun} />
          ) : activeView === "packets" ? (
            <PilotPacketView
              packet={pilotPacket}
              darkharnessPacket={darkharnessPacket}
              readiness={readiness}
              benchmarks={benchmarks}
              activeRun={activeRun}
            />
          ) : activeView === "roadmap" ? (
            <RoadmapView readiness={readiness} pilotPacket={pilotPacket} simulations={simulations} trustLadder={trustLadder} />
          ) : activeView === "evidence" || activeView === "audit" ? (
            <EvidenceAuditView
              mode={activeView}
              activeRun={activeRun}
              events={recentEvidenceEvents}
              merkleProof={merkleProof}
              runExport={runExport}
              exportingRun={exportingRun}
              exportingArchive={exportingArchive}
              vaultDocument={vaultDocument}
              vaultTree={vaultTree}
              onBuildRunExport={() => void handleBuildRunExport()}
              onBuildRunArchive={() => void handleBuildRunArchive()}
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
            <AgentMeshPanel run={activeRun} tasks={agentTasks} />
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
      return "Readiness";
    case "simulator":
      return "Policy Simulator";
    case "packets":
      return "Pilot Packet";
    case "trust":
      return "Trust Ladder";
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
  readiness,
  pilotPacket,
  trustLadder,
  serviceAgents,
  simulations,
  benchmarks,
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
  readiness: IntegrationReadiness | null;
  pilotPacket: PilotGoNoGoPacket | null;
  trustLadder: TrustLadderEntry[];
  serviceAgents: ServiceAgentRecord[];
  simulations: SimulationScenarioRecord[];
  benchmarks: BenchmarkRecord[];
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
            <p className="mesh-kicker">Production readiness cockpit</p>
            <h2>{activeRun ? `Constrain ${humanize(activeRun.stage)}` : "Bounded authority before autonomy"}</h2>
            <p>
              {activeRun
                ? `${activeRun.run_id.slice(0, 12)} keeps signal, trigger, evidence, decision, evaluation, approval, execution, feedback, and audit proof in one thread.`
                : "The console is organized around proof, constraints, and bounded operator decisions required by the production deployment roadmap."}
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
            <button className="action-button compact" type="button" onClick={() => onView("simulator")}>
              <Codicon name="beaker" />
              Simulate
            </button>
            <button className="action-button compact" type="button" onClick={() => onView("packets")}>
              <Codicon name="package" />
              Packet
            </button>
          </div>
          <div className="mesh-command-dock-footer">
            <button type="button" onClick={() => onView("runs")}><Codicon name="git-branch" /> {activeRun ? activeRun.run_id.slice(0, 12) : `${runs.length} runs`}</button>
            <button type="button" onClick={() => onView("integrations")}><Codicon name="plug" /> {readyIntegrations}/{integrationConnectors.length} integrations</button>
            <button type="button" onClick={() => onView("agents")}><Codicon name="hubot" /> {readyAgents}/{agentConnectors.length} agents</button>
          </div>
        </div>
        <RoadmapProofStrip
          activeRun={activeRun}
          readiness={readiness}
          pilotPacket={pilotPacket}
          trustLadder={trustLadder}
          simulations={simulations}
          benchmarks={benchmarks}
          serviceAgents={serviceAgents}
        />
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
            <button key={approvalItemId(item)} className="mesh-list-row" type="button" onClick={() => onView("approvals")}>
              <span><strong>{approvalItemTitle(item)}</strong><small>{approvalItemDetail(item)}</small></span>
              <StatusPill state={approvalItemBlocked(item) ? "degraded" : "config-only"} label={humanize(item.pending_pause_stage ?? item.stage)} />
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
  rcaSnapshot,
  approvalQueue,
  recentEvidenceEvents,
  selectedEventInsights,
  merkleProof,
  runExport,
  darkharnessPacket,
  exportingRun,
  exportingArchive,
  onSelectRun,
  onSelectEvent,
  onRunDetailTabChange,
  onCanvasModeChange,
  onToggleCanvasFullscreen,
  onBuildRunExport,
  onBuildRunArchive,
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
  rcaSnapshot: RcaSnapshot;
  approvalQueue: ApprovalQueueItem[];
  recentEvidenceEvents: RunEventRecord[];
  selectedEventInsights: Array<{ label: string; value: string; tone?: string }>;
  merkleProof: MerkleProof | null;
  runExport: RunExportPackage | null;
  darkharnessPacket: DarkharnessPilotPacket | null;
  exportingRun: boolean;
  exportingArchive: boolean;
  onSelectRun: (runId: string) => void;
  onSelectEvent: (eventId: string) => void;
  onRunDetailTabChange: (tab: RunDetailTab) => void;
  onCanvasModeChange: (mode: CanvasMode) => void;
  onToggleCanvasFullscreen: () => void;
  onBuildRunExport: () => void;
  onBuildRunArchive: () => void;
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
          {(["timeline", "evidence", "rca", "approvals", "actions", "darkharness", "audit", "agents", "topology"] as RunDetailTab[]).map((tab) => (
            <button key={tab} className={runDetailTab === tab ? "tab active" : "tab"} type="button" onClick={() => onRunDetailTabChange(tab)}>
              {runDetailTabLabel(tab)}
            </button>
          ))}
        </div>
        {runDetailTab === "timeline" ? (
          <TimelineTable run={activeRun} selectedEventId={selectedEventId} timelineRef={timelineRef} onSelectEvent={onSelectEvent} />
        ) : runDetailTab === "evidence" ? (
          <EvidencePanel events={recentEvidenceEvents} selectedEvent={selectedEvent} insights={selectedEventInsights} onJumpContext={onJumpContext} />
        ) : runDetailTab === "rca" ? (
          <RcaPanel snapshot={rcaSnapshot} onJumpContext={onJumpContext} onOpenTopology={() => onRunDetailTabChange("topology")} />
        ) : runDetailTab === "approvals" ? (
          <RunApprovalPanel queue={approvalQueue} activeRun={activeRun} onJumpContext={onJumpContext} />
        ) : runDetailTab === "actions" ? (
          <RunActionPanel activeRun={activeRun} onJumpContext={onJumpContext} />
        ) : runDetailTab === "darkharness" ? (
          <DarkharnessPacketPanel packet={darkharnessPacket} activeRun={activeRun} />
        ) : runDetailTab === "audit" ? (
          <RunAuditPanel
            activeRun={activeRun}
            merkleProof={merkleProof}
            runExport={runExport}
            exportingRun={exportingRun}
            exportingArchive={exportingArchive}
            onBuildRunExport={onBuildRunExport}
            onBuildRunArchive={onBuildRunArchive}
            onJumpContext={onJumpContext}
          />
        ) : runDetailTab === "agents" ? (
          <AgentMeshPanel run={activeRun} tasks={agentTasks} />
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
        <AgentMeshPanel run={activeRun} tasks={agentTasks} />
      </section>
    </div>
  );
}

function IntegrationsView({
  connectors,
  readiness,
  connectorCertification,
  watchers,
}: {
  connectors: IntegrationConnectorSummary[];
  readiness: IntegrationReadiness | null;
  connectorCertification: ConnectorCertificationPacket | null;
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
        <SectionTitle icon={<ShieldCheck size={15} />} title="Connector Certification Matrix" />
        <ConnectorCertificationMatrix readiness={readiness} certification={connectorCertification} />
      </section>
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
  trustLadder,
  killSwitchStatus,
  pilotPacket,
  serviceAgents,
  benchmarks,
  killSwitching,
  onApplyKillSwitch,
}: {
  health: HealthSnapshot | null;
  readiness: IntegrationReadiness | null;
  readinessItems: IntegrationReadiness[keyof Pick<IntegrationReadiness, "promptfoo" | "hermes" | "goose" | "latentmas" | "deepagents">][];
  integrationsReady: number;
  integrationsTotal: number;
  systemConnection: ConnectionStatus;
  runConnection: ConnectionStatus;
  agentConnectors: AgentConnectorSummary[];
  integrationConnectors: IntegrationConnectorSummary[];
  trustLadder: TrustLadderEntry[];
  killSwitchStatus: KillSwitchStatus | null;
  pilotPacket: PilotGoNoGoPacket | null;
  serviceAgents: ServiceAgentRecord[];
  benchmarks: BenchmarkRecord[];
  killSwitching: boolean;
  onApplyKillSwitch: () => void;
}) {
  const requiredChecks = Object.entries(readiness?.required_checks ?? {});
  const optionalChecks = Object.entries(readiness?.optional_checks ?? {});
  return (
    <div className="mesh-dashboard-grid">
      <section className="mesh-card mesh-card-span">
        <div className="mesh-section-header">
          <div>
            <p className="mesh-kicker">Tiered readiness</p>
            <h3>{readiness ? `${humanize(readiness.profile)} profile` : "Readiness unavailable"}</h3>
          </div>
          <StatusPill state={systemConnection === "connected" ? "ready" : "degraded"} label={humanize(systemConnection)} />
        </div>
        <div className="mesh-metric-grid">
          <MetricCard metric={{ label: "Environment", value: health ? humanize(health.environment) : "Unknown", detail: health ? `${health.version} ${health.commit.slice(0, 7)}` : "Health unavailable", tone: health ? "good" : "danger" }} />
          <MetricCard metric={{ label: "Readiness", value: readiness ? humanize(readiness.status) : "Unknown", detail: readiness ? `${humanize(readiness.profile)} profile` : "Profile unavailable", tone: readiness?.status === "ready" ? "good" : "danger" }} />
          <MetricCard metric={{ label: "Required gates", value: `${requiredChecks.filter(([, value]) => value === true || typeof value !== "boolean").length}/${requiredChecks.length}`, detail: "profile checks", tone: readiness?.blockers.length ? "danger" : "good" }} />
          <MetricCard metric={{ label: "Topology", value: readiness?.orchestration_topology?.active_topology ? humanize(String(readiness.orchestration_topology.active_topology)) : "Unknown", detail: readiness?.orchestration_topology?.ready ? "profile configured" : "profile unavailable", tone: readiness?.orchestration_topology?.ready ? "good" : "warn" }} />
          <MetricCard metric={{ label: "Integrations", value: `${integrationsReady}/${integrationsTotal}`, detail: "optional connector probes", tone: integrationsReady === integrationsTotal ? "good" : "warn" }} />
          <MetricCard metric={{ label: "Agents", value: `${agentConnectors.filter((a) => a.state === "ready").length}/${agentConnectors.length}`, detail: "worker connectors", tone: "neutral" }} />
          <MetricCard metric={{ label: "Run stream", value: humanize(runConnection), detail: "active run SSE", tone: runConnection === "connected" ? "good" : "warn" }} />
          <MetricCard metric={{ label: "Pilot packet", value: pilotPacket ? humanize(pilotPacket.status) : "Unknown", detail: pilotPacket ? `${pilotPacket.missing_evidence.length} missing proofs` : "not generated", tone: pilotPacket?.status === "go" ? "good" : "warn" }} />
        </div>
      </section>
      <section className="mesh-card mesh-card-span">
        <SectionTitle icon={<ShieldCheck size={15} />} title="Required Gate Matrix" />
        <ReadinessGateList checks={requiredChecks} blockers={readiness?.blockers ?? []} />
      </section>
      <section className="mesh-card">
        <SectionTitle icon={<ShieldCheck size={15} />} title="Kill Switch" />
        <div className="mesh-stack">
          <ConnectorRow name="Live execution" detail={killSwitchStatus?.live_execution_enabled ? "Enabled" : "Disabled"} state={killSwitchStatus?.live_execution_enabled ? "degraded" : "ready"} />
          <ConnectorRow name="Watchers" detail={`${killSwitchStatus?.watchers.watchers.filter((w) => w.running).length ?? 0}/${killSwitchStatus?.watchers.watchers.length ?? 0} running`} state={killSwitchStatus?.watchers.watchers.some((w) => w.running) ? "config-only" : "ready"} />
          <ConnectorRow name="Approval gate" detail={killSwitchStatus?.force_approval_gate || readiness?.required_checks?.force_approval_gate ? "Forced or defaulted" : "Not forced"} state={killSwitchStatus?.force_approval_gate || readiness?.required_checks?.force_approval_gate ? "ready" : "config-only"} />
          <ConnectorRow name="Readiness blockers" detail={(readiness?.blockers ?? []).join(", ") || "None"} state={(readiness?.blockers ?? []).length ? "degraded" : "ready"} />
          <button className="action-button danger" type="button" onClick={onApplyKillSwitch} disabled={killSwitching}>
            <ShieldCheck size={15} />
            {killSwitching ? "Applying" : "Stop live authority"}
          </button>
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
        <SectionTitle icon={<ShieldCheck size={15} />} title="Optional Lanes" />
        <div className="readiness-grid">
          {readinessItems.map((item) => (
            <ReadinessCard key={item.name} label={humanize(item.name)} status={item} />
          ))}
        </div>
      </section>
      <section className="mesh-card">
        <SectionTitle icon={<Activity size={15} />} title="Evidence Capacity" />
        <div className="mesh-stack">
          <ConnectorRow name="Trust ladder" detail={`${trustLadder.length} service/action entries`} state={trustLadder.length > 0 ? "ready" : "config-only"} />
          <ConnectorRow name="Service agent scopes" detail={`${serviceAgents.length} services registered`} state={serviceAgents.length > 0 ? "ready" : "config-only"} />
          <ConnectorRow name="Benchmark records" detail={`${benchmarks.length} recorded`} state={benchmarks.length > 0 ? "ready" : "config-only"} />
        </div>
      </section>
      <section className="mesh-card mesh-card-span">
        <SectionTitle icon={<CircleDot size={15} />} title="Optional Gate Detail" />
        <ReadinessGateList checks={optionalChecks} blockers={[]} compact />
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

function RoadmapProofStrip({
  activeRun,
  readiness,
  pilotPacket,
  trustLadder,
  serviceAgents,
  simulations,
  benchmarks,
}: {
  activeRun: RunDetail | null;
  readiness: IntegrationReadiness | null;
  pilotPacket: PilotGoNoGoPacket | null;
  trustLadder: TrustLadderEntry[];
  serviceAgents: ServiceAgentRecord[];
  simulations: SimulationScenarioRecord[];
  benchmarks: BenchmarkRecord[];
}) {
  const requiredChecks = Object.entries(readiness?.required_checks ?? {});
  const requiredPassed = requiredChecks.filter(([, value]) => value === true || typeof value !== "boolean").length;
  const connectorStates = Object.values(readiness?.connector_certification ?? {}).map((item) => String(asRecord(item).state ?? ""));
  const certifiedCount = connectorStates.filter((state) => ["read-only", "staging-ready", "pilot-ready", "production-ready", "proposal-only"].includes(state)).length;
  const pipelineEvents = (activeRun?.events ?? []).map((event) => `${event.event_type} ${event.stage} ${event.artifact_key ?? ""}`).join(" ").toLowerCase();
  const stepReady = (step: string) => {
    const key = step.toLowerCase();
    if (key === "rca") return /investigation|rca|root/.test(pipelineEvents);
    if (key === "model review") return /hermes|goose|agent|latent|deepagents/.test(pipelineEvents);
    if (key === "memory") return /memory|vault|merkle|feedback/.test(pipelineEvents);
    return pipelineEvents.includes(key);
  };
  const proofCards = [
    {
      label: "Tiered readiness",
      value: readiness ? `${requiredPassed}/${requiredChecks.length}` : "0/0",
      detail: readiness ? `${humanize(readiness.profile)} profile` : "No readiness snapshot",
      state: readiness?.blockers.length ? "degraded" : "ready",
    },
    {
      label: "Connector maturity",
      value: `${certifiedCount}/${connectorStates.length}`,
      detail: "certification states visible",
      state: certifiedCount > 0 ? "ready" : "config-only",
    },
    {
      label: "Policy replay",
      value: String(simulations.length),
      detail: "failure-mode scenarios",
      state: simulations.length > 0 ? "ready" : "config-only",
    },
    {
      label: "Trust ladder",
      value: String(trustLadder.length),
      detail: `${serviceAgents.length} service scopes`,
      state: trustLadder.length > 0 ? "ready" : "config-only",
    },
    {
      label: "Pilot packet",
      value: pilotPacket ? humanize(pilotPacket.status) : "Missing",
      detail: pilotPacket ? `${pilotPacket.missing_evidence.length} missing proofs` : "Generate from observed evidence",
      state: pilotPacket?.status === "go" ? "ready" : pilotPacket ? "degraded" : "config-only",
    },
    {
      label: "Benchmarks",
      value: String(benchmarks.length),
      detail: "recorded gate outputs",
      state: benchmarks.length > 0 ? "ready" : "config-only",
    },
  ] as Array<{ label: string; value: string; detail: string; state: ConnectorState }>;

  return (
    <div className="mesh-proof-strip">
      <div className="mesh-proof-grid">
        {proofCards.map((card) => (
          <div key={card.label} className="mesh-proof-card">
            <span>{card.label}</span>
            <strong>{card.value}</strong>
            <small>{card.detail}</small>
            <StatusPill state={card.state} label={humanize(card.state)} />
          </div>
        ))}
      </div>
      <div className="authority-pipeline" aria-label="Production authority pipeline">
        {AUTHORITY_PIPELINE.map((step, index) => (
          <div key={step} className={`authority-step ${stepReady(step) ? "ready" : ""}`}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{step}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function ReadinessGateList({
  checks,
  blockers,
  compact,
}: {
  checks: Array<[string, any]>;
  blockers: string[];
  compact?: boolean;
}) {
  if (checks.length === 0) return <EmptyState text="No gate data returned by readiness." />;
  return (
    <div className={compact ? "gate-matrix compact" : "gate-matrix"}>
      {checks.map(([name, value]) => {
        const record = asRecord(value);
        const boolValue = typeof value === "boolean" ? value : typeof record.ready === "boolean" ? record.ready : true;
        const blocked = blockers.includes(name) || boolValue === false;
        const detail =
          typeof value === "boolean"
            ? (value ? "pass" : "fail")
            : [record.certification, record.detail].filter(Boolean).map(String).join(" / ") || summarizeRecord(record);
        return (
          <div key={name} className={`gate-matrix-row ${blocked ? "blocked" : ""}`}>
            <span>{humanize(name)}</span>
            <strong>{detail || "recorded"}</strong>
            <StatusPill state={blocked ? "degraded" : "ready"} label={blocked ? "blocked" : "pass"} />
          </div>
        );
      })}
    </div>
  );
}

function ConnectorCertificationMatrix({
  readiness,
  certification,
}: {
  readiness: IntegrationReadiness | null;
  certification: ConnectorCertificationPacket | null;
}) {
  const entries = Object.entries(certification?.connectors ?? readiness?.connector_certification ?? {});
  if (entries.length === 0) return <EmptyState text="No connector certification state returned by readiness." />;
  return (
    <div className="mesh-table-wrap">
      <table className="mesh-table">
        <thead><tr><th>Connector</th><th>State</th><th>Authority</th><th>Credential Boundary</th><th>Scopes / Blockers</th></tr></thead>
        <tbody>
          {entries.map(([name, raw]) => {
            const item = asRecord(raw);
            const state = toConnectorState(String(item.state ?? item.certified_state ?? item.observed_state ?? ""), "config-only");
            const connectorName = String(item.display_name ?? item.connector_id ?? name);
            const authority = String(item.authority_posture ?? item.detail ?? "");
            const credentialBoundary = connectorCredentialBoundarySummary(item.credential_boundary);
            const scopes = stringList(item.allowed_scopes);
            const blockers = stringList(item.blockers);
            return (
              <tr key={name}>
                <td>
                  <strong>{connectorName}</strong>
                  <small>{humanize(String(item.domain ?? name))}</small>
                </td>
                <td><StatusPill state={state} label={humanize(state)} /></td>
                <td>
                  <span>{authority || "Not recorded"}</span>
                  <small>Before {humanize(String(item.required_before ?? "unset"))}</small>
                </td>
                <td>{credentialBoundary}</td>
                <td>
                  <span>{scopes.length ? scopes.join(", ") : "No scopes"}</span>
                  <small>{blockers.length ? `Blocked: ${blockers.join(", ")}` : "No blockers"}</small>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function connectorCredentialBoundarySummary(value: unknown): string {
  const boundary = asRecord(value);
  if (Object.keys(boundary).length === 0) return "Not recorded";
  const flags = [
    boundary.production_actuator_credentials_allowed === true ? "actuator creds" : "no actuator creds",
    boundary.repo_write_credentials_allowed === true ? "repo write" : "no repo write",
    boundary.runtime_secret_mount_required === true ? "runtime mount" : null,
    boundary.break_glass_recording_required === true ? "break-glass recorded" : null,
  ].filter(Boolean);
  return [
    boundary.credential_mode,
    boundary.service_account_ref,
    flags.join(", "),
  ].filter(Boolean).join(" / ");
}

function SimulatorView({
  scenarios,
  simulations,
  activeRun,
  runs,
  policySimulationDraft,
  policySimulation,
  selectedSimulationId,
  simulatingPolicy,
  runningSimulation,
  onPolicySimulationDraftChange,
  onSelectedSimulationIdChange,
  onSimulatePolicy,
  onRunSimulation,
}: {
  scenarios: ScenarioRecord[];
  simulations: SimulationScenarioRecord[];
  activeRun: RunDetail | null;
  runs: RunSessionRecord[];
  policySimulationDraft: string;
  policySimulation: PolicySimulationResult | null;
  selectedSimulationId: string;
  simulatingPolicy: boolean;
  runningSimulation: string;
  onPolicySimulationDraftChange: (value: string) => void;
  onSelectedSimulationIdChange: (value: string) => void;
  onSimulatePolicy: (payload?: Record<string, unknown>) => void;
  onRunSimulation: (scenarioId: string) => void;
}) {
  const selectedScenario = selectedSimulationId || simulations[0]?.scenario_id || "";
  return (
    <div className="mesh-dashboard-grid">
      <section className="mesh-card mesh-card-span">
        <div className="mesh-section-header">
          <div>
            <p className="mesh-kicker">Mutation-free policy simulator</p>
            <h3>Replay a fixture, captured run, or inline signal before live authority</h3>
          </div>
          <StatusPill state={policySimulation?.mutates ? "unsafe" : "ready"} label={policySimulation?.mutates ? "mutating" : "dry run"} />
        </div>
        <div className="simulator-layout">
          <div className="mesh-stack">
            <textarea
              value={policySimulationDraft}
              onChange={(event) => onPolicySimulationDraftChange(event.target.value)}
              className="mono-textarea simulator-json"
              placeholder='{"scenario_key": "search_latency_regression"}'
            />
            <div className="context-action-row">
              <button className="action-button primary" type="button" disabled={simulatingPolicy} onClick={() => onSimulatePolicy()}>
                {simulatingPolicy ? <Loader2 size={14} className="spin" /> : <Codicon name="beaker" />}
                Simulate policy
              </button>
              <button
                className="action-button"
                type="button"
                disabled={!activeRun || simulatingPolicy}
                onClick={() => onSimulatePolicy(activeRun ? { captured_run_id: activeRun.run_id } : undefined)}
              >
                Captured run
              </button>
              {scenarios.slice(0, 3).map((scenario) => (
                <button
                  key={scenario.key}
                  className="action-button"
                  type="button"
                  disabled={simulatingPolicy}
                  onClick={() => {
                    onPolicySimulationDraftChange(JSON.stringify({ scenario_key: scenario.key }, null, 2));
                    onSimulatePolicy({ scenario_key: scenario.key });
                  }}
                >
                  {scenario.title}
                </button>
              ))}
            </div>
          </div>
          <PolicySimulationResultPanel result={policySimulation} runCount={runs.length} />
        </div>
      </section>

      <section className="mesh-card mesh-card-span">
        <div className="mesh-section-header">
          <div>
            <p className="mesh-kicker">Failure-mode library</p>
            <h3>Replay denied, degraded, and dependency-failure scenarios</h3>
          </div>
          <div className="context-action-row">
            <div className="select-wrap compact-select">
              <select value={selectedScenario} onChange={(event) => onSelectedSimulationIdChange(event.target.value)}>
                {simulations.map((scenario) => (
                  <option key={scenario.scenario_id} value={scenario.scenario_id}>{scenario.title}</option>
                ))}
              </select>
              <ChevronDown size={14} className="select-icon" />
            </div>
            <button className="action-button primary" type="button" disabled={!selectedScenario || !!runningSimulation} onClick={() => onRunSimulation(selectedScenario)}>
              {runningSimulation ? <Loader2 size={14} className="spin" /> : <Play size={14} />}
              Run sandbox
            </button>
          </div>
        </div>
        <div className="simulation-card-grid">
          {simulations.map((scenario) => (
            <article key={scenario.scenario_id} className={`simulation-card ${scenario.scenario_id === selectedScenario ? "selected" : ""}`}>
              <div className="mesh-section-header">
                <div>
                  <strong>{scenario.title}</strong>
                  <p>{humanize(scenario.fault_type)}</p>
                </div>
                <StatusPill state="config-only" label={humanize(scenario.expected_decision_type ?? "unscored")} />
              </div>
              <div className="context-link-list compact">
                <ContextLink label="Scenario" value={scenario.scenario_id} mono />
                <ContextLink label="Expected" value={scenario.expected_outcome ?? "not set"} />
                <ContextLink label="Sandbox" value={summarizeRecord(scenario.sandbox)} />
              </div>
              <div className="tag-row">
                {scenario.tags.slice(0, 5).map((tag) => <span key={tag}>{tag}</span>)}
              </div>
            </article>
          ))}
          {simulations.length === 0 ? <EmptyState text="No simulation scenarios are available from the control plane." /> : null}
        </div>
      </section>
    </div>
  );
}

function PolicySimulationResultPanel({ result, runCount }: { result: PolicySimulationResult | null; runCount: number }) {
  if (!result) {
    return (
      <div className="context-panel">
        <SectionTitle icon={<ShieldCheck size={14} />} title="Simulation Result" />
        <div className="context-stat-grid">
          <ContextStat label="Mutation" value="false by contract" />
          <ContextStat label="Captured runs" value={String(runCount)} />
          <ContextStat label="Allowed action" value="pending replay" />
          <ContextStat label="Denied action" value="pending replay" />
        </div>
      </div>
    );
  }
  const recommendation = stringField(asRecord(result.evaluation), "final_recommendation") ?? "unscored";
  const decision = stringField(asRecord(result.decision), "decision_type") ?? stringField(asRecord(result.decision), "action") ?? "none";
  return (
    <div className="context-panel">
      <SectionTitle icon={<ShieldCheck size={14} />} title="Simulation Result" />
      <div className="context-stat-grid">
        <ContextStat label="Mutation" value={String(result.mutates)} />
        <ContextStat label="Source" value={summarizeRecord(result.source)} />
        <ContextStat label="Decision" value={humanize(decision)} />
        <ContextStat label="Recommendation" value={humanize(recommendation)} />
      </div>
      <ConnectorRow name="Allowed action" detail={result.allowed_action ? summarizeRecord(result.allowed_action) : "None"} state={result.allowed_action ? "ready" : "config-only"} />
      <ConnectorRow name="Denied action" detail={result.denied_action ? summarizeRecord(result.denied_action) : "None"} state={result.denied_action ? "degraded" : "ready"} />
      <ConnectorRow name="Rollback path" detail={result.rollback_path ?? "Not available"} state={result.rollback_path ? "ready" : "config-only"} />
      {result.blockers.length > 0 ? (
        <div className="mesh-stack">
          {result.blockers.map((blocker) => (
            <div key={blocker} className="inspector-alert danger"><AlertTriangle size={14} /><span>{blocker}</span></div>
          ))}
        </div>
      ) : null}
      <pre className="timeline-summary">{JSON.stringify({ trigger: result.trigger, evaluation: result.evaluation }, null, 2)}</pre>
    </div>
  );
}

function TrustLadderView({
  trustLadder,
  serviceAgents,
  activeRun,
}: {
  trustLadder: TrustLadderEntry[];
  serviceAgents: ServiceAgentRecord[];
  activeRun: RunDetail | null;
}) {
  return (
    <div className="mesh-dashboard-grid">
      <section className="mesh-card mesh-card-span">
        <div className="mesh-section-header">
          <div>
            <p className="mesh-kicker">Operator trust ladder</p>
            <h3>Autonomy ceiling per service and action class</h3>
          </div>
          <StatusPill state={activeRun?.auto_mode ? "degraded" : "ready"} label={activeRun?.auto_mode ? "auto requested" : "approval default"} />
        </div>
        <div className="trust-ladder-grid">
          {trustLadder.map((entry) => (
            <TrustLadderCard key={`${entry.action_class}-${entry.service}`} entry={entry} />
          ))}
          {trustLadder.length === 0 ? <EmptyState text="No trust ladder entries yet. Outcomes appear after feedback records are written." /> : null}
        </div>
      </section>
      <section className="mesh-card mesh-card-span">
        <SectionTitle icon={<Bot size={15} />} title="Service Agent Scopes" />
        <div className="mesh-connector-grid">
          {serviceAgents.map((agent) => (
            <article key={agent.service} className="mesh-connector-card">
              <div className="mesh-section-header">
                <div>
                  <strong>{agent.service}</strong>
                  <p>{agent.runbook_path ?? "No runbook path"}</p>
                </div>
                <StatusPill state={agent.preferred_lanes.length > 0 ? "ready" : "config-only"} label={`${agent.preferred_lanes.length} lanes`} />
              </div>
              <div className="context-link-list compact">
                <ContextLink label="Preferred" value={agent.preferred_lanes.join(", ") || "none"} />
                <ContextLink label="Scope" value={summarizeRecord(agent.scope)} />
                <ContextLink label="Overrides" value={summarizeRecord(agent.autonomy_overrides)} />
              </div>
            </article>
          ))}
          {serviceAgents.length === 0 ? <EmptyState text="No service agent records are available." /> : null}
        </div>
      </section>
    </div>
  );
}

function TrustLadderCard({ entry }: { entry: TrustLadderEntry }) {
  const levels = ["suggest", "draft", "approve", "auto"];
  const levelIndex = Math.max(0, levels.indexOf(entry.level));
  const nextLevel = entry.next_level ? humanize(entry.next_level) : "Max";
  const requiredRuns = entry.promotion_requirements?.min_runs ?? 0;
  const requiredRate = entry.promotion_requirements?.min_success_rate ?? 0;
  const blockers = entry.promotion_blockers ?? [];
  return (
    <article className="trust-card">
      <div className="mesh-section-header">
        <div>
          <strong>{entry.service}</strong>
          <p>{humanize(entry.action_class)}</p>
        </div>
        <StatusPill state={entry.level === "auto" ? "degraded" : entry.level === "approve" ? "config-only" : "ready"} label={humanize(entry.level)} />
      </div>
      <div className="trust-track">
        {levels.map((level, index) => (
          <span key={level} className={index <= levelIndex ? "active" : ""}>{humanize(level)}</span>
        ))}
      </div>
      <div className="context-stat-grid">
        <ContextStat label="Runs" value={String(entry.total_runs)} />
        <ContextStat label="Success" value={`${Math.round(clamp01(entry.success_rate) * 100)}%`} />
        <ContextStat label="Failures" value={String(entry.consecutive_failures)} />
        <ContextStat label="Overrides" value={String(entry.override_count)} />
      </div>
      <div className="trust-rationale">
        <ContextLink
          label="Next"
          value={entry.next_level ? `${nextLevel}: ${requiredRuns} runs / ${Math.round(clamp01(requiredRate) * 100)}% success` : "Max ceiling reached"}
        />
        <ContextLink label="Ceiling" value={entry.autonomy_ceiling_reason ?? "No autonomy rationale reported."} />
      </div>
      {blockers.length > 0 ? (
        <div className="trust-blocker-list">
          {blockers.map((blocker) => (
            <span key={blocker}>{blocker}</span>
          ))}
        </div>
      ) : null}
      <p className="mesh-muted">{entry.last_outcome ? `Last outcome: ${humanize(entry.last_outcome)}` : "No outcome recorded."}</p>
    </article>
  );
}

function PilotPacketView({
  packet,
  darkharnessPacket,
  readiness,
  benchmarks,
  activeRun,
}: {
  packet: PilotGoNoGoPacket | null;
  darkharnessPacket: DarkharnessPilotPacket | null;
  readiness: IntegrationReadiness | null;
  benchmarks: BenchmarkRecord[];
  activeRun: RunDetail | null;
}) {
  const checks = Object.entries(packet?.checks ?? {});
  return (
    <div className="mesh-dashboard-grid">
      <section className="mesh-card mesh-card-span">
        <div className="mesh-section-header">
          <div>
            <p className="mesh-kicker">Evidence-generated pilot packet</p>
            <h3>{packet ? humanize(packet.status) : "Packet unavailable"}</h3>
          </div>
          <StatusPill state={packet?.status === "go" ? "ready" : "degraded"} label={packet?.packet_version ?? "not generated"} />
        </div>
        <div className="mesh-metric-grid">
          <MetricCard metric={{ label: "Run evidence", value: String(packet?.observed.run_count ?? 0), detail: "observed sessions", tone: (packet?.observed.run_count ?? 0) > 0 ? "good" : "warn" }} />
          <MetricCard metric={{ label: "Missing proofs", value: String(packet?.missing_evidence.length ?? 0), detail: "go/no-go blockers", tone: packet?.missing_evidence.length ? "danger" : "good" }} />
          <MetricCard metric={{ label: "Readiness", value: readiness ? humanize(readiness.status) : "Unknown", detail: readiness ? `${humanize(readiness.profile)} profile` : "unavailable", tone: readiness?.status === "ready" ? "good" : "warn" }} />
          <MetricCard metric={{ label: "Benchmarks", value: String(benchmarks.length), detail: "recorded gate rows", tone: benchmarks.length ? "good" : "neutral" }} />
          <MetricCard metric={{ label: "Current run", value: activeRun ? activeRun.run_id.slice(0, 10) : "None", detail: activeRun ? humanize(activeRun.stage) : "select a run", tone: activeRun ? "good" : "neutral" }} />
        </div>
      </section>
      <section className="mesh-card">
        <SectionTitle icon={<ShieldCheck size={15} />} title="Go/No-Go Checks" />
        <div className="gate-matrix compact">
          {checks.map(([name, passed]) => (
            <div key={name} className={`gate-matrix-row ${passed ? "" : "blocked"}`}>
              <span>{humanize(name)}</span>
              <strong>{passed ? "observed" : "missing"}</strong>
              <StatusPill state={passed ? "ready" : "degraded"} label={passed ? "pass" : "block"} />
            </div>
          ))}
          {checks.length === 0 ? <EmptyState text="No packet checks returned." /> : null}
        </div>
      </section>
      <section className="mesh-card">
        <SectionTitle icon={<AlertTriangle size={15} />} title="Missing Evidence" />
        <div className="mesh-stack">
          {(packet?.missing_evidence ?? []).map((item) => (
            <ConnectorRow key={item} name={humanize(item)} detail="Required before production pilot" state="degraded" />
          ))}
          {packet?.missing_evidence.length === 0 ? <EmptyState text="No missing evidence in the current packet." /> : null}
        </div>
      </section>
      <section className="mesh-card">
        <SectionTitle icon={<FolderGit2 size={15} />} title="Observed Proofs" />
        <div className="mesh-stack">
          <ContextStat label="Approved" value={(packet?.observed.approved_run_ids ?? []).slice(0, 3).join(", ") || "none"} />
          <ContextStat label="Live action" value={(packet?.observed.live_action_run_ids ?? []).slice(0, 3).join(", ") || "none"} />
          <ContextStat label="Denied action" value={(packet?.observed.denied_action_run_ids ?? []).slice(0, 3).join(", ") || "none"} />
          <ContextStat label="Merkle" value={(packet?.observed.merkle_run_ids ?? []).slice(0, 3).join(", ") || "none"} />
        </div>
      </section>
      <section className="mesh-card">
        <SectionTitle icon={<BookOpen size={15} />} title="Packet Artifacts" />
        <div className="mesh-stack">
          {EVIDENCE_PACKET_LINKS.map(([label, path]) => (
            <ConnectorRow key={path} name={label} detail={path} state="config-only" />
          ))}
        </div>
      </section>
      <section className="mesh-card mesh-card-span">
        <DarkharnessPacketPanel packet={darkharnessPacket} activeRun={activeRun} compact />
      </section>
      <section className="mesh-card mesh-card-span">
        <SectionTitle icon={<Activity size={15} />} title="Benchmark Records" />
        <BenchmarkTable benchmarks={benchmarks} />
      </section>
    </div>
  );
}

function BenchmarkTable({ benchmarks }: { benchmarks: BenchmarkRecord[] }) {
  if (benchmarks.length === 0) return <EmptyState text="No benchmark records are available." />;
  return (
    <div className="mesh-table-wrap">
      <table className="mesh-table">
        <thead><tr><th>Benchmark</th><th>Scenario</th><th>Run</th><th>Score</th><th>Status</th><th>Recorded</th></tr></thead>
        <tbody>
          {benchmarks.slice(0, 12).map((benchmark) => (
            <tr key={benchmark.benchmark_id}>
              <td><code>{benchmark.benchmark_id.slice(0, 14)}</code></td>
              <td>{benchmark.scenario_id}</td>
              <td><code>{benchmark.run_id.slice(0, 12)}</code></td>
              <td>{benchmark.score}</td>
              <td><StatusText status={benchmark.passed ? "ready" : "failed"} /></td>
              <td>{relativeTime(benchmark.recorded_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RoadmapView({
  readiness,
  pilotPacket,
  simulations,
  trustLadder,
}: {
  readiness: IntegrationReadiness | null;
  pilotPacket: PilotGoNoGoPacket | null;
  simulations: SimulationScenarioRecord[];
  trustLadder: TrustLadderEntry[];
}) {
  return (
    <div className="mesh-dashboard-grid">
      <section className="mesh-card mesh-card-span">
        <div className="mesh-section-header">
          <div>
            <p className="mesh-kicker">Production deployment roadmap</p>
            <h3>UI surfaces mapped to the release gates</h3>
          </div>
          <StatusPill state={readiness?.blockers.length ? "degraded" : "ready"} label={readiness ? humanize(readiness.profile) : "unknown"} />
        </div>
        <div className="roadmap-phase-grid">
          {ROADMAP_PHASES.map((phase) => (
            <article key={phase.id} className="roadmap-phase-card">
              <span>{phase.before}</span>
              <strong>{phase.title}</strong>
              <p>{phase.gate}</p>
            </article>
          ))}
        </div>
      </section>
      <section className="mesh-card mesh-card-span">
        <SectionTitle icon={<ShieldCheck size={15} />} title="Product Quality Surfaces" />
        <div className="roadmap-surface-grid">
          {ROADMAP_PRIORITY_SURFACES.map(([title, detail], index) => (
            <article key={title} className="roadmap-surface-card">
              <span>{index + 1}</span>
              <strong>{title}</strong>
              <p>{detail}</p>
            </article>
          ))}
        </div>
      </section>
      <section className="mesh-card">
        <SectionTitle icon={<Activity size={15} />} title="Current Coverage" />
        <div className="mesh-stack">
          <ConnectorRow name="Readiness blockers" detail={(readiness?.blockers ?? []).join(", ") || "None"} state={readiness?.blockers.length ? "degraded" : "ready"} />
          <ConnectorRow name="Failure library" detail={`${simulations.length} replay scenarios`} state={simulations.length ? "ready" : "config-only"} />
          <ConnectorRow name="Trust ladder" detail={`${trustLadder.length} entries`} state={trustLadder.length ? "ready" : "config-only"} />
          <ConnectorRow name="Pilot packet" detail={pilotPacket ? `${humanize(pilotPacket.status)} with ${pilotPacket.missing_evidence.length} missing proofs` : "Unavailable"} state={pilotPacket?.status === "go" ? "ready" : "degraded"} />
        </div>
      </section>
      <section className="mesh-card">
        <SectionTitle icon={<AlertTriangle size={15} />} title="Non-Negotiable Rules" />
        <div className="mesh-stack">
          <ConnectorRow name="Authenticated TLS" detail="No public exposure without identity enforcement" state="config-only" />
          <ConnectorRow name="Proposal lanes" detail="Deep Agents, Goose, Hermes, and Mesh Brain do not own actuation" state="ready" />
          <ConnectorRow name="Autonomy" detail="No action without allowlist, policy, evaluation, approval, rollback, and trust evidence" state="ready" />
          <ConnectorRow name="Adapter claims" detail="Unfinished adapters stay visibly unfinished" state="ready" />
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
  runExport,
  exportingRun,
  exportingArchive,
  vaultDocument,
  vaultTree,
  onBuildRunExport,
  onBuildRunArchive,
  onVaultSelect,
  onJumpRun,
}: {
  mode: "evidence" | "audit";
  activeRun: RunDetail | null;
  events: RunEventRecord[];
  merkleProof: MerkleProof | null;
  runExport: RunExportPackage | null;
  exportingRun: boolean;
  exportingArchive: boolean;
  vaultDocument: string;
  vaultTree: VaultTreeEntry[] | null;
  onBuildRunExport: () => void;
  onBuildRunArchive: () => void;
  onVaultSelect: (path: string) => void;
  onJumpRun: () => void;
}) {
  const activeExport = runExport?.run_id === activeRun?.run_id ? runExport : null;
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
          <ContextStat label="Export" value={activeExport ? activeExport.package_sha256.slice(0, 16) : "Not generated"} />
        </div>
        <div className="context-action-row">
          <button className="action-button compact primary" type="button" disabled={!activeRun || exportingRun} onClick={onBuildRunExport}>
            {exportingRun ? "Building export" : "Build export"}
          </button>
          <button className="action-button compact" type="button" disabled={!activeRun || exportingArchive} onClick={onBuildRunArchive}>
            {exportingArchive ? "Building archive" : "Archive"}
          </button>
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
            <div key={approvalItemId(item)} className="mesh-list-row static">
              <span><strong>{approvalItemTitle(item)}</strong><small>{approvalItemDetail(item)}</small></span>
              <StatusPill state={approvalItemBlocked(item) ? "degraded" : "config-only"} label={humanize(item.pending_pause_stage ?? item.stage)} />
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
            <ConnectorRow key={watcher.name} name={watcher.name} detail={watcherOwnerDetail(watcher)} state={watcher.running ? "ready" : "degraded"} />
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

function watcherOwnerDetail(watcher: WatcherStatus["watchers"][number]): string {
  const owner = watcher.ownership?.owner?.display_name ?? watcher.ownership?.owner?.owner_id;
  const resolved = watcher.ownership?.resolved_target_count ?? 0;
  const total = watcher.ownership?.target_count ?? 0;
  const target = watcher.ownership?.targets?.[0];
  const escalation = typeof target?.escalation_route === "string" && target.escalation_route ? target.escalation_route : null;
  const blockers = watcher.ownership?.blockers ?? [];
  if (owner && escalation) return `${owner} / ${resolved}/${total} targets / ${escalation}`;
  if (owner) return `${owner} / ${resolved}/${total} targets`;
  if (blockers.length > 0) return `${watcher.signal_source} / ${blockers.join(", ")}`;
  return `${watcher.signal_source} / ${watcher.interval_seconds}s`;
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
          <button className="action-button compact" type="button" onClick={onUseResearchSafe}>Proposal Safe</button>
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
    status === "completed" || status === "ready" || status === "pilot-ready" || status === "production-ready" || status === "staging-ready" ? "ready" :
    status === "failed" || status === "danger" || status === "disconnected" || status === "unfinished" || status === "disabled" ? "degraded" :
    status === "unsafe" ? "unsafe" :
    status === "stub" ? "stub" :
    status === "config-only" || status === "mock" || status === "read-only" || status === "proposal-only" ? "config-only" :
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

function RcaPanel({
  snapshot,
  onJumpContext,
  onOpenTopology,
}: {
  snapshot: RcaSnapshot;
  onJumpContext: (tab: RightRailTab) => void;
  onOpenTopology: () => void;
}) {
  const topCandidate = snapshot.candidates[0];
  return (
    <div className="mesh-detail-grid">
      <section className="context-panel rca-summary-panel">
        <div className="context-panel-header">
          <div>
            <p className="eyebrow">Root Cause Analysis</p>
            <h4>{topCandidate ? topCandidate.cause : "No ranked candidate"}</h4>
          </div>
          <StatusChip
            label={snapshot.stopReason ? humanize(snapshot.stopReason) : "No report"}
            tone={snapshot.blockers.some((blocker) => blocker.severity === "danger") ? "#f75464" : "#2aacb8"}
          />
        </div>
        <div className="context-stat-grid">
          <ContextStat label="Tools" value={String(snapshot.tools.length)} />
          <ContextStat label="Candidates" value={String(snapshot.candidates.length)} />
          <ContextStat label="Blockers" value={String(snapshot.blockers.length)} />
          <ContextStat label="Citations" value={String(snapshot.citations.length)} />
        </div>
        <div className="context-action-row">
          <button className="action-button compact" type="button" onClick={onOpenTopology}>RCA graph</button>
          <button className="action-button compact" type="button" onClick={() => onJumpContext("evidence")}>Evidence inspector</button>
          <button className="action-button compact" type="button" onClick={() => onJumpContext("merkle")}>Audit proof</button>
        </div>
      </section>

      <section className="context-panel">
        <SectionTitle icon={<Activity size={14} />} title="Tool Trajectory" />
        <div className="rca-tool-list">
          {snapshot.tools.map((tool, index) => (
            <article key={tool.id} className={`rca-tool-row ${tool.valid ? "valid" : "invalid"}`}>
              <span className="rca-rank">{index + 1}</span>
              <div>
                <strong>{tool.name}</strong>
                <small>{tool.summary || humanize(tool.status)}</small>
                {tool.citationIds.length > 0 ? <code>{tool.citationIds.slice(0, 3).join(" / ")}</code> : null}
              </div>
              <StatusPill state={tool.valid ? "ready" : "degraded"} label={humanize(tool.status || "recorded")} />
            </article>
          ))}
          {snapshot.tools.length === 0 ? <EmptyState text="No read-only RCA tool calls are recorded." /> : null}
        </div>
      </section>

      <section className="context-panel">
        <SectionTitle icon={<AlertTriangle size={14} />} title="Ranked Candidates" />
        <div className="rca-candidate-grid">
          {snapshot.candidates.map((candidate) => (
            <article key={candidate.id} className="rca-candidate-card">
              <div className="agent-attempt-header">
                <strong>#{candidate.rank} {candidate.cause}</strong>
                <span>{formatPercent(candidate.confidence)}</span>
              </div>
              {candidate.support.length > 0 ? <p>{candidate.support.slice(0, 4).join(", ")}</p> : null}
              {candidate.citationIds.length > 0 ? <code>{candidate.citationIds.slice(0, 4).join(" / ")}</code> : null}
            </article>
          ))}
          {snapshot.candidates.length === 0 ? <EmptyState text="No root-cause candidates are ranked yet." /> : null}
        </div>
      </section>

      <section className="context-panel">
        <SectionTitle icon={<CircleDot size={14} />} title="Confidence Movement" />
        <div className="confidence-movement">
          {snapshot.confidenceMovement.map((point) => (
            <div key={point.id} className="confidence-step">
              <span>{point.label}</span>
              <div className="confidence-track"><i style={{ width: `${Math.round(point.value * 100)}%`, background: point.tone }} /></div>
              <strong>{Math.round(point.value * 100)}%</strong>
              <small>{point.detail}</small>
            </div>
          ))}
          {snapshot.confidenceMovement.length === 0 ? <EmptyState text="No confidence-bearing artifacts are recorded." /> : null}
        </div>
      </section>

      <section className="context-panel">
        <SectionTitle icon={<ShieldCheck size={14} />} title="Blockers And Audit Citations" />
        <div className="rca-two-column">
          <div className="mesh-stack">
            {snapshot.blockers.map((blocker) => (
              <div key={blocker.id} className={`inspector-alert ${blocker.severity === "danger" ? "danger" : ""}`}>
                <AlertTriangle size={14} />
                <span><strong>{blocker.label}</strong><br />{blocker.detail}</span>
              </div>
            ))}
            {snapshot.blockers.length === 0 ? <EmptyState text="No RCA or evaluation blockers are attached." /> : null}
          </div>
          <div className="mesh-stack">
            {snapshot.citations.map((citation) => (
              <ContextLink key={citation.id} label={citation.label} value={citation.detail || citation.id} mono />
            ))}
            {snapshot.citations.length === 0 ? <EmptyState text="No RCA citations are attached." /> : null}
          </div>
        </div>
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
          {queue.map((item) => (
            <ConnectorRow
              key={approvalItemId(item)}
              name={approvalItemTitle(item)}
              detail={approvalItemDetail(item)}
              state={approvalItemBlocked(item) ? "degraded" : "config-only"}
            />
          ))}
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
        <p className="mesh-muted">Approvals, notes, overrides, and execution context remain behind Mesh steering controls.</p>
        <div className="context-action-row">
          <button className="action-button compact primary" type="button" disabled={!activeRun} onClick={() => onJumpContext("steering")}>Steering</button>
          <button className="action-button compact" type="button" disabled={!activeRun} onClick={() => onJumpContext("execution")}>Execution</button>
          <button className="action-button compact" type="button" disabled={!activeRun} onClick={() => onJumpContext("policy")}>Policy</button>
        </div>
      </section>
    </div>
  );
}

function DarkharnessPacketPanel({
  packet,
  activeRun,
  compact,
}: {
  packet: DarkharnessPilotPacket | null;
  activeRun: RunDetail | null;
  compact?: boolean;
}) {
  const missingEvidence = packet?.missing_evidence ?? [];
  const checks = Object.entries(packet?.checks ?? {});
  const evidence = packet?.implemented_evidence;
  const records = packet?.perennial_records;
  const allowedProofs = evidence?.allowed_action_proofs ?? [];
  const deniedProofs = evidence?.denied_action_proofs ?? [];
  const merkleProofs = evidence?.merkle_proofs ?? [];
  const governanceCommits = records?.governance_commits ?? [];
  const agentRecords = records?.agent_action_records ?? [];
  const reservoirs = records?.sensitive_reservoirs ?? [];
  const runExports = evidence?.run_exports ?? [];
  const proofEnvelopes = records?.proof_envelopes ?? [];
  const implementedClaims = packet?.claim_boundary.implemented ?? [];
  const proposedClaims = packet?.claim_boundary.proposed ?? [];
  const notImplementedClaims = packet?.claim_boundary.not_implemented ?? [];
  const state: ConnectorState = !packet ? "disconnected" : packet.status === "blocked" ? "degraded" : "ready";
  const statusLabel = !packet ? "Unavailable" : packet.status === "blocked" ? "Blocked" : "Packet ready";
  const boundaryPasses =
    packet?.boundaries.raw_reservoir_egress === "deny" &&
    packet.boundaries.external_model_calls === "deny" &&
    packet.boundaries.production_actions_approval_required === true;
  const checkedValues = Object.values(packet?.checks ?? {});
  const capabilityRows: Array<{ name: string; detail: string; state: ConnectorState }> = [
    {
      name: "Evidence capture",
      detail: `${runExports.length} run exports, ${merkleProofs.length} Merkle proofs, ${missingEvidence.length} blockers`,
      state: !packet ? "disconnected" : runExports.length > 0 && merkleProofs.length > 0 && missingEvidence.length === 0 ? "ready" : "degraded",
    },
    {
      name: "Action gate exercise",
      detail: `${allowedProofs.length} allowed proofs, ${deniedProofs.length} denied proofs, ${governanceCommits.length} governance commits`,
      state: !packet ? "disconnected" : allowedProofs.length > 0 && governanceCommits.length > 0 ? "ready" : "degraded",
    },
    {
      name: "Boundary enforcement",
      detail: `Raw egress ${packet?.boundaries.raw_reservoir_egress ?? "unavailable"}, external models ${packet?.boundaries.external_model_calls ?? "unavailable"}, approval ${packet ? String(packet.boundaries.production_actions_approval_required) : "unavailable"}`,
      state: !packet ? "disconnected" : boundaryPasses ? "ready" : "degraded",
    },
    {
      name: "Perennial record materialization",
      detail: `${reservoirs.length} reservoirs, ${agentRecords.length} agent actions, ${proofEnvelopes.length} proof envelopes`,
      state: !packet ? "disconnected" : reservoirs.length > 0 && agentRecords.length > 0 && proofEnvelopes.length > 0 ? "ready" : "config-only",
    },
    {
      name: "Claim separation",
      detail: `${implementedClaims.length} implemented, ${proposedClaims.length} proposed, ${notImplementedClaims.length} not implemented`,
      state: !packet ? "disconnected" : implementedClaims.length > 0 ? "ready" : "degraded",
    },
    {
      name: "Policy checks",
      detail: `${checkedValues.filter(Boolean).length} observed, ${checkedValues.filter((passed) => !passed).length} missing`,
      state: !packet ? "disconnected" : checkedValues.length === 0 || checkedValues.every(Boolean) ? "ready" : "degraded",
    },
  ];
  return (
    <div className={compact ? "darkharness-panel compact" : "mesh-detail-grid darkharness-panel"} data-testid="darkharness-packet-panel">
      <section className="context-panel">
        <div className="mesh-section-header">
          <SectionTitle icon={<ShieldCheck size={14} />} title="Dark Harness Packet" />
          <StatusPill state={state} label={statusLabel} />
        </div>
        <div className="context-stat-grid">
          <ContextStat label="Run" value={activeRun?.run_id ?? packet?.run_id ?? "No run"} />
          <ContextStat label="Packet" value={packet?.packet_id?.slice(0, 18) ?? packet?.packet ?? "Unavailable"} />
          <ContextStat label="Allowed proof" value={String(allowedProofs.length)} />
          <ContextStat label="Denied proof" value={String(deniedProofs.length)} />
          <ContextStat label="Merkle proofs" value={String(merkleProofs.length)} />
          <ContextStat label="Missing evidence" value={String(missingEvidence.length)} />
        </div>
      </section>
      <section className="context-panel">
        <SectionTitle icon={<SlidersHorizontal size={14} />} title="Harness Capabilities" />
        <div className="mesh-stack">
          {capabilityRows.map((row) => (
            <ConnectorRow key={row.name} name={row.name} detail={row.detail} state={row.state} />
          ))}
        </div>
      </section>
      <section className="context-panel">
        <SectionTitle icon={<Binary size={14} />} title="Boundary Status" />
        <div className="gate-matrix compact">
          <DarkharnessBoundaryRow
            label="Raw reservoir egress"
            value={packet?.boundaries.raw_reservoir_egress}
            passed={packet?.boundaries.raw_reservoir_egress === "deny"}
          />
          <DarkharnessBoundaryRow
            label="External model calls"
            value={packet?.boundaries.external_model_calls}
            passed={packet?.boundaries.external_model_calls === "deny"}
          />
          <DarkharnessBoundaryRow
            label="Production approval"
            value={packet ? String(packet.boundaries.production_actions_approval_required) : undefined}
            passed={packet?.boundaries.production_actions_approval_required === true}
          />
          {checks.map(([name, passed]) => (
            <div key={name} className={`gate-matrix-row ${passed ? "" : "blocked"}`}>
              <span>{humanize(name)}</span>
              <strong>{passed ? "observed" : "missing"}</strong>
              <StatusPill state={passed ? "ready" : "degraded"} label={passed ? "pass" : "block"} />
            </div>
          ))}
        </div>
      </section>
      <section className="context-panel">
        <SectionTitle icon={<AlertTriangle size={14} />} title="Missing Evidence" />
        <div className="mesh-stack">
          {missingEvidence.map((item) => (
            <ConnectorRow key={item} name={humanize(item)} detail="Packet eligibility blocker" state="degraded" />
          ))}
          {packet && missingEvidence.length === 0 ? <EmptyState text="No missing evidence in the Dark Harness packet." /> : null}
          {!packet ? <EmptyState text="No Dark Harness packet is available for the selected run." /> : null}
        </div>
      </section>
      <section className="context-panel">
        <SectionTitle icon={<Activity size={14} />} title="Implemented Evidence" />
        <div className="context-stat-grid">
          <ContextStat label="Run exports" value={String(evidence?.run_exports?.length ?? 0)} />
          <ContextStat label="Agent records" value={String(agentRecords.length)} />
          <ContextStat label="Governance commits" value={String(governanceCommits.length)} />
          <ContextStat label="Reservoirs" value={String(reservoirs.length)} />
          <ContextStat label="Readiness" value={humanize(String(evidence?.readiness?.status ?? "unavailable"))} />
          <ContextStat label="Go/no-go" value={humanize(String(evidence?.go_no_go?.status ?? evidence?.go_no_go?.final_release_decision ?? "unavailable"))} />
        </div>
      </section>
      <section className="context-panel">
        <SectionTitle icon={<FolderGit2 size={14} />} title="Claim Boundary" />
        <ClaimBoundaryList title="Implemented" items={implementedClaims} state="ready" />
        <ClaimBoundaryList title="Proposed" items={proposedClaims} state="config-only" />
        <ClaimBoundaryList title="Not implemented" items={notImplementedClaims} state="degraded" />
      </section>
      <section className="context-panel">
        <SectionTitle icon={<BookOpen size={14} />} title="Perennial Records" />
        <div className="mesh-table-wrap">
          <table className="mesh-table">
            <thead><tr><th>Record</th><th>Count</th><th>Status</th></tr></thead>
            <tbody>
              <DarkharnessRecordRow label="Sensitive reservoirs" count={reservoirs.length} />
              <DarkharnessRecordRow label="Agent actions" count={agentRecords.length} />
              <DarkharnessRecordRow label="Governance commits" count={governanceCommits.length} />
              <DarkharnessRecordRow label="Epistemic states" count={records?.epistemic_states?.length ?? 0} />
              <DarkharnessRecordRow label="Ontological states" count={records?.ontological_states?.length ?? 0} />
              <DarkharnessRecordRow label="Proof envelopes" count={records?.proof_envelopes?.length ?? 0} />
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function DarkharnessBoundaryRow({ label, value, passed }: { label: string; value?: string; passed: boolean }) {
  return (
    <div className={`gate-matrix-row ${passed ? "" : "blocked"}`}>
      <span>{label}</span>
      <strong>{value ?? "unavailable"}</strong>
      <StatusPill state={passed ? "ready" : "degraded"} label={passed ? "pass" : "block"} />
    </div>
  );
}

function ClaimBoundaryList({ title, items, state }: { title: string; items: string[]; state: ConnectorState }) {
  return (
    <div className="darkharness-claim-group">
      <div className="mesh-section-header compact">
        <strong>{title}</strong>
        <StatusPill state={state} label={String(items.length)} />
      </div>
      <div className="darkharness-claim-list">
        {items.map((item) => (
          <span key={`${title}-${item}`}>{humanize(item)}</span>
        ))}
        {items.length === 0 ? <small>None</small> : null}
      </div>
    </div>
  );
}

function DarkharnessRecordRow({ label, count }: { label: string; count: number }) {
  return (
    <tr>
      <td>{label}</td>
      <td>{count}</td>
      <td><StatusPill state={count > 0 ? "ready" : "config-only"} label={count > 0 ? "present" : "empty"} /></td>
    </tr>
  );
}

function RunAuditPanel({
  activeRun,
  merkleProof,
  runExport,
  exportingRun,
  exportingArchive,
  onBuildRunExport,
  onBuildRunArchive,
  onJumpContext,
}: {
  activeRun: RunDetail | null;
  merkleProof: MerkleProof | null;
  runExport: RunExportPackage | null;
  exportingRun: boolean;
  exportingArchive: boolean;
  onBuildRunExport: () => void;
  onBuildRunArchive: () => void;
  onJumpContext: (tab: RightRailTab) => void;
}) {
  const activeExport = runExport?.run_id === activeRun?.run_id ? runExport : null;
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
        <div className="context-action-row">
          <button className="action-button compact" type="button" onClick={() => onJumpContext("merkle")}>Open Merkle inspector</button>
          <button className="action-button compact primary" type="button" disabled={!activeRun || exportingRun} onClick={onBuildRunExport}>
            {exportingRun ? "Building export" : "Build export"}
          </button>
          <button className="action-button compact" type="button" disabled={!activeRun || exportingArchive} onClick={onBuildRunArchive}>
            {exportingArchive ? "Building archive" : "Archive"}
          </button>
        </div>
      </section>
      <section className="context-panel">
        <SectionTitle icon={<FolderGit2 size={14} />} title="Run Export Package" />
        <div className="context-stat-grid">
          <ContextStat label="Status" value={activeExport ? "Generated" : "Not generated"} />
          <ContextStat label="Events" value={activeExport ? String(activeExport.timeline_json.length) : "0"} />
          <ContextStat label="Vault docs" value={activeExport ? String(activeExport.vault_documents.length) : "0"} />
          <ContextStat label="Checksum" value={activeExport?.package_sha256.slice(0, 18) ?? "Unavailable"} />
          <ContextStat label="Compacted" value={activeExport ? String(activeExport.size_control.truncated) : "Unavailable"} />
          <ContextStat label="Retention" value={activeExport ? `${activeExport.retention.retention_days}d${activeExport.retention.reviewed ? "" : " review"}` : "Unavailable"} />
        </div>
        {activeExport ? <pre className="timeline-summary">{activeExport.postmortem_markdown}</pre> : null}
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
          {(["labyrinth", "flow", "evidence", "rca", "signal", "merkle", "artifacts"] as CanvasMode[]).map((mode) => (
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
            <Background color="#25262a" gap={24} />
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
    queue_id: `approval://${run.run_id}`,
    run_id: run.run_id,
    created_at: run.created_at,
    updated_at: run.updated_at,
    scenario_key: run.scenario_key,
    service: asRecord(run.artifacts?.input_signal).service ?? asRecord(run.artifacts?.ownership_boundary).service ?? null,
    namespace: asRecord(run.artifacts?.input_signal).namespace ?? asRecord(run.artifacts?.ownership_boundary).namespace ?? null,
    environment: asRecord(run.artifacts?.input_signal).environment ?? "local",
    stage: run.stage,
    pending_pause_stage: run.pending_pause_stage,
    steering_mode: run.steering_mode,
    decision_type: asRecord(run.artifacts?.decision).decision_type ?? null,
    risk_level: asRecord(run.artifacts?.decision).risk_level ?? null,
    final_recommendation: asRecord(run.artifacts?.evaluation).final_recommendation ?? null,
    approval_state: blocked ? "blocked" : "pending",
    blockers: reasons,
    requested_by: asRecord(run.artifacts?.operator),
    owner: asRecord(run.artifacts?.ownership_boundary).owner ?? null,
    approver_roles: firstArray(asRecord(run.artifacts?.ownership_boundary).approver_roles),
    allowed_commands: blocked ? ["explain_blockers", "override_decision", "cancel", "handoff"] : ["approve", "resume", "cancel", "handoff"],
    evidence_refs: [`run://${run.run_id}`, ...(run.latest_event_id ? [`event://${run.latest_event_id}`] : [])],
    latest_event_id: run.latest_event_id,
  }];
}

function approvalItemId(item: ApprovalQueueItem): string {
  return item.queue_id || `approval://${item.run_id}`;
}

function approvalItemBlocked(item: ApprovalQueueItem): boolean {
  return item.approval_state === "blocked";
}

function approvalItemTitle(item: ApprovalQueueItem): string {
  return approvalItemBlocked(item) ? "Approval blocked" : "Awaiting operator approval";
}

function approvalItemDetail(item: ApprovalQueueItem): string {
  return item.blockers[0] ?? item.decision_type ?? item.service ?? "Run is paused at the operator gate.";
}

function buildRcaSnapshot(
  run: RunDetail | null,
  analysis: ScenarioAnalysis | null,
  tasks: AgentTask[],
  approvalBlockingReasons: string[],
): RcaSnapshot {
  const artifacts = asRecord(run?.artifacts);
  const report = firstRecord(
    artifacts.investigation_report,
    artifacts.rca_report,
    artifacts.root_cause_analysis,
  );
  const tools = buildRcaTools(artifacts, report, tasks);
  const candidates = buildRcaCandidates(report, analysis);
  const blockers = buildRcaBlockers(report, artifacts, tools, approvalBlockingReasons);
  const citations = buildRcaCitations(report, tools, candidates, run);
  const confidenceMovement = buildConfidenceMovement(report, candidates, artifacts, analysis, tasks);

  return {
    tools,
    candidates,
    blockers,
    citations,
    confidenceMovement,
    report,
    stopReason: stringField(report, "stop_reason") ?? stringField(report, "status"),
  };
}

function buildRcaTools(artifacts: Record<string, any>, report: Record<string, any> | null, tasks: AgentTask[]): RcaGraphToolCall[] {
  const rawToolCalls = firstArray(
    artifacts.tool_trajectory,
    artifacts.tool_calls,
    artifacts.investigation_tool_trajectory,
    report?.tool_trajectory,
  );
  const source = rawToolCalls.length > 0 ? rawToolCalls : firstArray(report?.probe_results, report?.probes);
  const tools = source
    .map((item, index) => {
      const record = asRecord(item);
      const name = stringField(record, "tool_name") ?? stringField(record, "probe_name") ?? stringField(record, "name") ?? stringField(record, "tool") ?? `tool-${index + 1}`;
      const status = stringField(record, "status") ?? (record.error ? "failed" : "recorded");
      const valid = typeof record.valid === "boolean" ? record.valid : !["failed", "invalid", "error"].includes(status.toLowerCase());
      const summary =
        stringField(record, "summary") ??
        stringField(record, "output_excerpt") ??
        stringField(record, "error") ??
        summarizeRecord(record.args ?? record.arguments ?? record.input ?? record.output);
      return {
        id: stableId(name, index),
        name,
        status,
        valid,
        summary,
        citationIds: stringList(record.citation_ids ?? record.citations ?? record.citation_refs),
      };
    })
    .filter((tool) => tool.name.trim().length > 0);

  if (tools.length > 0) return tools;

  return tasks.flatMap((task, taskIndex) =>
    (task.attempts ?? []).map((attempt, attemptIndex) => ({
      id: stableId(`${task.kind}-${attempt.agent}`, taskIndex + attemptIndex),
      name: `agent_mesh:${attempt.agent}`,
      status: attempt.status,
      valid: attempt.status === "completed" && attempt.risk_flags.length === 0,
      summary: attempt.summary,
      citationIds: stringList(attempt.citations),
    })),
  );
}

function buildRcaCandidates(report: Record<string, any> | null, analysis: ScenarioAnalysis | null): RcaGraphCandidate[] {
  const findings = firstArray(report?.findings);
  const rankedFromFinding = findings.flatMap((finding) => firstArray(asRecord(finding).details?.ranked));
  const rawCandidates = firstArray(
    report?.root_cause_candidates,
    report?.ranked_root_cause_candidates,
    report?.candidates,
    rankedFromFinding,
  );
  const source = rawCandidates.length > 0
    ? rawCandidates
    : findings.filter((finding) => {
        const kind = String(asRecord(finding).kind ?? "").toLowerCase();
        return kind.includes("root_cause") || kind.includes("ranked");
      });

  const candidates = source
    .map((item, index) => {
      const record = asRecord(item);
      const cause =
        stringField(record, "root_cause") ??
        stringField(record, "candidate_cause") ??
        stringField(record, "cause") ??
        stringField(record, "summary") ??
        stringField(record, "name") ??
        `candidate-${index + 1}`;
      const confidence = numericField(record, "confidence");
      return {
        id: stableId(cause, index),
        rank: Math.max(1, Math.trunc(numericField(record, "rank") ?? index + 1)),
        cause,
        confidence,
        support: stringList(record.supporting_tools ?? record.matched_patterns ?? record.supporting_evidence ?? record.evidence),
        citationIds: stringList(record.citation_ids ?? record.citations ?? record.citation_refs),
      };
    })
    .filter((candidate) => candidate.cause.trim().length > 0)
    .sort((left, right) => left.rank - right.rank);

  if (candidates.length > 0) return candidates;

  return (analysis?.subdecisions ?? [])
    .filter((item) => String(item.kind ?? item.analyzer ?? "").toLowerCase().includes("investigation"))
    .map((item, index) => {
      const record = asRecord(item);
      const cause = stringField(record, "recommendation") ?? stringField(record, "summary") ?? `analysis-${index + 1}`;
      return {
        id: stableId(cause, index),
        rank: index + 1,
        cause,
        confidence: numericField(record, "confidence"),
        support: stringList(record.reasons),
        citationIds: stringList(record.evidence_refs),
      };
    });
}

function buildRcaBlockers(
  report: Record<string, any> | null,
  artifacts: Record<string, any>,
  tools: RcaGraphToolCall[],
  approvalBlockingReasons: string[],
): RcaGraphBlocker[] {
  const blockers: RcaGraphBlocker[] = approvalBlockingReasons.map((reason, index) => ({
    id: `evaluation-${index}`,
    label: "Evaluation blocker",
    detail: reason,
    source: "evaluation",
    severity: "danger",
  }));
  const uncertainty = numericField(report, "uncertainty");
  if (typeof uncertainty === "number" && uncertainty >= 0.35) {
    blockers.push({
      id: "investigation-uncertainty",
      label: "High uncertainty",
      detail: `${Math.round(uncertainty * 100)}% uncertainty in investigation report`,
      source: "investigation",
      severity: "warning",
    });
  }
  const stopReason = stringField(report, "stop_reason") ?? stringField(report, "status");
  if (stopReason && /fail|blocked|unknown|insufficient/i.test(stopReason)) {
    blockers.push({
      id: "investigation-stop",
      label: "Investigation stop reason",
      detail: humanize(stopReason),
      source: "investigation",
      severity: /fail|blocked/i.test(stopReason) ? "danger" : "warning",
    });
  }
  tools
    .filter((tool) => !tool.valid)
    .slice(0, 4)
    .forEach((tool) => {
      blockers.push({
        id: `tool-${tool.id}`,
        label: `${tool.name} not valid`,
        detail: tool.summary || humanize(tool.status),
        source: "tool",
        severity: tool.status.toLowerCase() === "failed" ? "danger" : "warning",
      });
    });
  const evaluation = asRecord(artifacts.evaluation);
  stringList(evaluation.blocking_reasons).forEach((reason, index) => {
    if (blockers.some((blocker) => blocker.detail === reason)) return;
    blockers.push({
      id: `evaluation-artifact-${index}`,
      label: "Evaluation blocker",
      detail: reason,
      source: "evaluation",
      severity: "danger",
    });
  });
  return blockers;
}

function buildRcaCitations(
  report: Record<string, any> | null,
  tools: RcaGraphToolCall[],
  candidates: RcaGraphCandidate[],
  run: RunDetail | null,
): RcaGraphCitation[] {
  const citations = new Map<string, RcaGraphCitation>();
  const add = (id: string, label: string, detail = "") => {
    if (!id || citations.has(id)) return;
    citations.set(id, { id, label, detail: detail || id });
  };

  firstArray(report?.citations).forEach((item, index) => {
    if (typeof item === "string") {
      add(item, "Report citation", item);
      return;
    }
    const record = asRecord(item);
    const id = stringField(record, "id") ?? stringField(record, "claim_id") ?? stringField(record, "source_ref") ?? stringField(record, "source") ?? `report-citation-${index}`;
    const label = stringField(record, "source_type") ?? stringField(record, "source") ?? "Report citation";
    const detail = stringField(record, "summary") ?? stringField(record, "source_ref") ?? summarizeRecord(record);
    add(id, humanize(label), detail);
  });
  tools.forEach((tool) => tool.citationIds.forEach((id) => add(id, `${tool.name} citation`, id)));
  candidates.forEach((candidate) => candidate.citationIds.forEach((id) => add(id, `Candidate #${candidate.rank}`, candidate.cause)));
  (run?.events ?? []).forEach((event) => {
    if (event.merkle_leaf_hash && event.artifact_key === "investigation_report") {
      add(event.merkle_leaf_hash, "Merkle leaf", `${event.sequence}: ${humanize(event.event_type)}`);
    }
  });
  return Array.from(citations.values()).slice(0, 14);
}

function buildConfidenceMovement(
  report: Record<string, any> | null,
  candidates: RcaGraphCandidate[],
  artifacts: Record<string, any>,
  analysis: ScenarioAnalysis | null,
  tasks: AgentTask[],
): ConfidencePoint[] {
  const points: ConfidencePoint[] = [];
  const topConfidence = candidates.find((candidate) => typeof candidate.confidence === "number")?.confidence;
  if (typeof topConfidence === "number") {
    points.push({ id: "rca-top", label: "Top RCA", value: clamp01(topConfidence), detail: candidates[0]?.cause ?? "candidate", tone: "#2aacb8" });
  }
  const uncertainty = numericField(report, "uncertainty");
  if (typeof uncertainty === "number") {
    points.push({ id: "investigation", label: "Investigation", value: clamp01(1 - uncertainty), detail: "1 - uncertainty", tone: "#548af7" });
  }
  const decisionConfidence = numericField(asRecord(artifacts.decision), "confidence");
  if (typeof decisionConfidence === "number") {
    points.push({ id: "decision", label: "Decision", value: clamp01(decisionConfidence), detail: stringField(asRecord(artifacts.decision), "decision_type") ?? "decision", tone: "#c77dbb" });
  }
  if (typeof analysis?.confidence === "number") {
    points.push({ id: "scenario-analysis", label: "Scenario", value: clamp01(analysis.confidence), detail: humanize(analysis.suggested_decision_type), tone: "#e8a33e" });
  }
  tasks.flatMap((task) => task.attempts).forEach((attempt, index) => {
    const confidence = numericField(asRecord(attempt.output), "confidence");
    if (typeof confidence !== "number") return;
    points.push({ id: `agent-${index}`, label: humanize(attempt.agent), value: clamp01(confidence), detail: humanize(attempt.recommended_action), tone: "#73b00a" });
  });
  return points.slice(0, 8);
}

export function buildAgentConnectors(readiness: IntegrationReadiness | null, tasks: AgentTask[]): AgentConnectorSummary[] {
  const attempts = tasks.flatMap((task) => task.attempts ?? []);
  const lastAttempt = (agent: string) => attempts.slice().reverse().find((attempt) => attempt.agent === agent);
  const readinessFor = (key: "hermes" | "goose" | "latentmas" | "deepagents") => readiness?.[key] ?? null;
  const certification = readiness?.connector_certification ?? {};
  const certFor = (id: string): Record<string, any> => asRecord(certification[id]);
  const fromReadiness = (status: IntegrationReadiness["hermes"] | null): ConnectorState => {
    if (!status) return "disconnected";
    if (status.ready) return "ready";
    if (status.warnings?.length) return "degraded";
    if (status.command || status.url || status.detail) return "config-only";
    return "disconnected";
  };
  const specs: Array<{
    id: string;
    name: string;
    role: string;
    adapter: string;
    status: IntegrationReadiness["hermes"] | null;
    primary: boolean;
    platform?: boolean;
  }> = [
    { id: "hermes", name: "Hermes", role: "Default root-cause and blocker interaction", adapter: "hermes bridge", status: readinessFor("hermes"), primary: true },
    { id: "goose", name: "Goose", role: "Operational coordination and review", adapter: "goose bridge", status: readinessFor("goose"), primary: false },
    { id: "codex", name: "Codex", role: "Patch proposal lane", adapter: "deepagents/native contract", status: readinessFor("deepagents"), primary: false },
    { id: "claudecode", name: "Claude Code", role: "Review and risk lane", adapter: "deepagents/native contract", status: readinessFor("deepagents"), primary: false },
    { id: "openclaw", name: "OpenClaw", role: "Staging validation lane", adapter: "deepagents/native contract", status: readinessFor("deepagents"), primary: false },
    { id: "latentmas", name: "LatentMAS", role: "Advisory full-inference worker", adapter: "latentmas sidecar", status: readinessFor("latentmas"), primary: false },
    { id: "deepagents", name: "Deep Agents", role: "Sandboxed multi-agent proposal fabric", adapter: "deepagents", status: readinessFor("deepagents"), primary: false },
    { id: "airflow", name: "Apache Airflow", role: "DAG state and scheduled workflow evidence lane", adapter: "native orchestration contract", status: null, primary: false, platform: true },
    { id: "temporal", name: "Temporal", role: "Durable workflow history and supervisor lane", adapter: "native orchestration contract", status: null, primary: false, platform: true },
    { id: "dagster", name: "Dagster", role: "Asset lineage and materialization evidence lane", adapter: "native orchestration contract", status: null, primary: false, platform: true },
    { id: "prefect", name: "Prefect", role: "Flow run state and work-pool evidence lane", adapter: "native orchestration contract", status: null, primary: false, platform: true },
    { id: "flyte", name: "Flyte", role: "ML workflow reproducibility evidence lane", adapter: "native orchestration contract", status: null, primary: false, platform: true },
    { id: "luigi", name: "Luigi", role: "Pipeline dependency proposal lane", adapter: "native orchestration contract", status: null, primary: false, platform: true },
    { id: "oozie", name: "Apache Oozie", role: "Hadoop workflow status evidence lane", adapter: "native orchestration contract", status: null, primary: false, platform: true },
    { id: "kubernetes", name: "Kubernetes", role: "Controller reconciliation and bounded actuator lane", adapter: "native orchestration contract", status: null, primary: false, platform: true },
    { id: "n8n", name: "n8n", role: "Low-code workflow trace proposal lane", adapter: "native orchestration contract", status: null, primary: false, platform: true },
    { id: "custom-http", name: "Custom HTTP Agent", role: "Future external worker connector", adapter: "http connector", status: null, primary: false },
  ];
  return specs.map(({ id, name, role, adapter, status, primary, platform }) => {
    const attempt = lastAttempt(id);
    const cert = certFor(id);
    const certState = String(cert.state ?? "");
    return {
      id,
      name,
      role,
      adapter,
      state: platform ? toConnectorState(certState, "config-only") : id === "custom-http" ? "disconnected" : fromReadiness(status),
      scope: platform ? "Topology routed orchestration lane" : primary ? "Default Mesh run context" : "Domain/service scoped",
      profile: platform
        ? `${humanize(certState || "mock")} before ${humanize(String(cert.required_before ?? "expansion"))}`
        : status?.primary_route ?? status?.url ?? status?.command ?? "Not configured",
      readinessDetail: platform ? String(cert.detail ?? cert.authority_posture ?? "Connector certification governs authority") : status?.detail ?? "Connector registry placeholder",
      lastAttempt: attempt ? `${humanize(attempt.status)}: ${attempt.summary}` : undefined,
      riskFlags: attempt?.risk_flags ?? stringList(cert.blockers ?? status?.warnings ?? []),
      boundary: platform
        ? String(cert.authority_posture ?? "Mesh governs topology, approval, audit, and execution authority.")
        : "Proposal-only. Mesh owns policy, approval, audit, and execution.",
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
  const certification = readiness?.connector_certification ?? {};
  const certState = (id: string, fallback: ConnectorState): ConnectorState => {
    const state = String((certification[id] as Record<string, any> | undefined)?.state ?? "");
    return toConnectorState(state, fallback);
  };
  const certDetail = (id: string, fallback: string): string => {
    const item = certification[id] as Record<string, any> | undefined;
    const state = item?.state ? `${humanize(String(item.state))}: ` : "";
    return `${state}${item?.detail ?? fallback}`;
  };
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
    { id: "kubernetes", name: "Kubernetes", domain: "Web2 Production", state: watcherReady("kubernetes") || watcherReady("live_kubernetes") ? "ready" : certState("kubernetes", "config-only"), authType: "Service account", scopes: ["deployments", "pods", "events"], detail: certDetail("kubernetes", "Live execution requires explicit allowlists") },
    { id: "argocd", name: "ArgoCD", domain: "Web2 Production", state: "config-only", authType: "API key", scopes: ["applications", "sync", "health"], detail: "Runtime config supports ArgoCD URL/token" },
    { id: "otel", name: "Prometheus / OpenTelemetry", domain: "Web2 Production", state: watcherReady("otel") || watcherReady("prometheus") ? "ready" : certState("otel", "config-only"), authType: "API key", scopes: ["metrics", "slo", "feedback"], detail: certDetail("otel", "OTLP receiver and Prometheus feedback are opt-in") },
    { id: "logs", name: "Logs", domain: "Web2 Production", state: "disconnected", authType: "OAuth/OIDC", scopes: ["errors", "patterns", "trace"], detail: "Loki/Elastic connector track" },
    { id: "github", name: "GitHub / GitLab", domain: "Development", state: "disconnected", authType: "OAuth/OIDC", scopes: ["repos", "prs", "checks"], detail: "Reserved for repo and release management" },
    { id: "promptfoo", name: "Promptfoo", domain: "Development", state: statusState(readiness?.promptfoo), authType: "Local config", scopes: ["evaluation", "gates"], detail: readiness?.promptfoo.detail ?? "Evaluation bridge" },
    { id: "ci", name: "CI and build gates", domain: "Development", state: "config-only", authType: "OAuth/OIDC", scopes: ["checks", "artifacts", "logs"], detail: "Release-readiness connector track" },
    { id: "pagerduty", name: "PagerDuty / Opsgenie", domain: "Operations", state: certState("incident_adapter", "stub"), authType: "API key", scopes: ["incidents", "escalations"], detail: certDetail("incident_adapter", "Incident adapter is not production-complete yet") },
    { id: "linear", name: "Linear / Jira", domain: "Operations", state: "disconnected", authType: "OAuth/OIDC", scopes: ["issues", "projects", "comments"], detail: "Work tracking connector track" },
    { id: "audit-sink", name: "Audit sinks", domain: "Operations", state: certState("audit_sink", "stub"), authType: "Service account", scopes: ["append-only", "exports"], detail: certDetail("audit_sink", "Local audit adapter must be mirrored before compliance reliance") },
  ];
}

function toConnectorState(raw: string, fallback: ConnectorState): ConnectorState {
  const allowed: ConnectorState[] = [
    "ready",
    "degraded",
    "config-only",
    "unsafe",
    "stub",
    "disconnected",
    "mock",
    "read-only",
    "staging-ready",
    "pilot-ready",
    "production-ready",
    "unfinished",
    "disabled",
    "proposal-only",
  ];
  return allowed.includes(raw as ConnectorState) ? raw as ConnectorState : fallback;
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
                <StatusChip label="Hermes" tone="#56a8f5" />
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

export function AgentMeshPanel({
  run,
  tasks,
}: {
  run: RunDetail | null;
  tasks: AgentTask[];
}) {
  const fallbackTasks = Array.isArray(run?.artifacts?.agent_tasks)
    ? (run?.artifacts?.agent_tasks as AgentTask[])
    : [];
  const resolvedTasks = tasks.length > 0 ? tasks : fallbackTasks;

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
          <StatusChip label="Read Only" tone="#2aacb8" />
        </div>
        <p className="inspector-muted">
          Workers produce proposals and risk signals. Mesh keeps policy, tests, audit, Kubernetes actuation, and production promotion gates.
        </p>
      </section>

      {resolvedTasks.map((task) => (
        <section key={task.task_id} className="context-panel">
          <div className="context-panel-header">
            <div>
              <p className="eyebrow">{humanize(task.kind)}</p>
              <h4>{task.task_id}</h4>
            </div>
            <StatusChip label={humanize(task.status)} tone={task.status === "completed" ? "#2aacb8" : "#e8a33e"} />
          </div>
          <div className="context-stat-grid">
            <ContextStat label="Workers" value={String(task.attempts.length)} />
            <ContextStat label="Selected" value={task.selected_attempt_id ? task.selected_attempt_id.split("_").slice(-2, -1)[0] ?? "set" : "none"} />
            <ContextStat label="Paths" value={String(task.allowed_paths.length)} />
            <ContextStat label="Tests" value={String(task.test_commands.length)} />
          </div>
          <AgentTopologyPanel task={task} />
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

function AgentTopologyPanel({ task }: { task: AgentTask }) {
  const topology = asRecord(task.orchestration_topology || task.lane_routing);
  if (Object.keys(topology).length === 0) return null;
  const lanes = firstArray(topology.selected_lanes);
  const blockers = stringList(topology.blockers);
  const sourceEvidence = asRecord(topology.source_evidence);
  const ownership = asRecord(sourceEvidence.ownership_boundary);
  return (
    <section className="agent-topology-panel" data-testid="agent-topology-panel">
      <div className="context-panel-header">
        <div>
          <p className="eyebrow">Topology</p>
          <h4>{humanize(String(topology.active_topology ?? "centralized"))}</h4>
        </div>
        <StatusChip label={blockers.length ? "Blocked" : "Mesh Governed"} tone={blockers.length ? "#e8a33e" : "#2aacb8"} />
      </div>
      <div className="context-stat-grid">
        <ContextStat label="Rule" value={String(topology.rule_id ?? "default")} />
        <ContextStat label="Lanes" value={String(lanes.length || task.agents.length)} />
        <ContextStat label="Reconciliation" value={humanize(String(topology.reconciliation ?? "mesh_reconciles"))} />
        <ContextStat label="Authority" value="Mesh" />
      </div>
      <div className="context-link-list compact">
        <ContextLink label="Reason" value={String(topology.routing_reason ?? "default profile topology")} />
        {ownership.record_id ? <ContextLink label="Ownership" value={String(ownership.record_id)} /> : null}
        {ownership.tenant_id ? <ContextLink label="Tenant" value={String(ownership.tenant_id)} /> : null}
      </div>
      {lanes.length > 0 ? (
        <div className="mesh-table-wrap compact-table">
          <table className="mesh-table">
            <thead>
              <tr><th>Lane</th><th>Role</th><th>Authority</th><th>State</th></tr>
            </thead>
            <tbody>
              {lanes.map((lane, index) => {
                const record = asRecord(lane);
                return (
                  <tr key={`${record.lane_id ?? index}`}>
                    <td>{humanize(String(record.lane_id ?? "lane"))}</td>
                    <td>{humanize(String(record.role ?? "worker"))}</td>
                    <td>{humanize(String(record.authority ?? "proposal_only"))}</td>
                    <td>{humanize(String(record.certified_state ?? "unknown"))}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      {blockers.length > 0 && (
        <div className="readiness-warning">
          {blockers.map((blocker) => humanize(blocker)).join(", ")}
        </div>
      )}
    </section>
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

function asRecord(value: unknown): Record<string, any> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, any>) : {};
}

function firstRecord(...values: unknown[]): Record<string, any> | null {
  for (const value of values) {
    const record = asRecord(value);
    if (Object.keys(record).length > 0) return record;
  }
  return null;
}

function firstArray(...values: unknown[]): any[] {
  for (const value of values) {
    if (Array.isArray(value)) return value;
  }
  return [];
}

function stringField(record: Record<string, any> | null | undefined, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function numericField(record: Record<string, any> | null | undefined, key: string): number | null {
  const value = record?.[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) return Number(value);
  return null;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .flatMap((item) => {
      if (typeof item === "string" || typeof item === "number") return [String(item)];
      const record = asRecord(item);
      const id = record.claim_id ?? record.id ?? record.source_ref ?? record.source ?? record.summary ?? record.name;
      return id == null ? [] : [String(id)];
    })
    .filter((item) => item.trim().length > 0);
}

function summarizeRecord(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value.length > 180 ? `${value.slice(0, 179)}…` : value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return `${value.length} items`;
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).slice(0, 3);
    return entries.map(([key, item]) => `${key}:${formatInsightValue(item) || typeof item}`).join(" / ");
  }
  return "";
}

function stableId(value: string, index: number): string {
  const slug = value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 42);
  return `${slug || "item"}-${index + 1}`;
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function formatPercent(value: number | null): string {
  return typeof value === "number" ? `${Math.round(clamp01(value) * 100)}%` : "unscored";
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
    case "darkharness":
      return "Dark Harness";
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
