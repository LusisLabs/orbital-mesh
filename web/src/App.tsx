import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Binary,
  Bot,
  Check,
  ChevronDown,
  CircleDot,
  FolderGit2,
  GitBranch,
  Loader2,
  Play,
  Plus,
  ShieldCheck,
  TimerReset,
  Waves,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Background, Controls, MiniMap, ReactFlow } from "@xyflow/react";

import { api, connectRunStream, connectSystemStream, resolveBaseUrl } from "./api";
import { Inspector } from "./components/Inspector";
import { Toaster, useToast } from "./components/Toaster";
import { formatTimestamp, humanize, relativeTime, safeJsonParse, stageIcon } from "./lib/format";
import { buildRunGraph, toneForStage } from "./lib/runGraph";
import type {
  ConnectionStatus,
  GoalRecord,
  InspectorTab,
  IntegrationReadiness,
  MerkleProof,
  RunDetail,
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
  evaluationMode: "native",
  orchestrationMode: "native",
  steeringMode: "approval_gate",
  scenarioKey: "",
  customSignal: "",
};

const RESEARCH_SAFE_LAUNCH_OVERRIDES = {
  evaluationMode: "promptfoo",
  orchestrationMode: "goose",
  steeringMode: "interruptible_auto",
} as const;

export default function App() {
  const [baseUrl] = useState(resolveBaseUrl);

  /* ── Core data ── */
  const [readiness, setReadiness] = useState<IntegrationReadiness | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioRecord[]>([]);
  const [goals, setGoals] = useState<GoalRecord[]>([]);
  const [runs, setRuns] = useState<RunSessionRecord[]>([]);
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

  /* ── Inspector ── */
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("overview");
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

  /* ──────────── Effects ──────────── */

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

    const proofEvent = activeRun.events.find((e) =>
      ["decision_ready", "evaluation_ready", "execution_recorded", "feedback_recorded"].includes(e.event_type),
    );
    if (proofEvent) {
      void api.getMerkleProof(baseUrl, activeRun.run_id, proofEvent.event_id).then(setMerkleProof).catch(() => setMerkleProof(null));
    } else {
      setMerkleProof(null);
    }
  }, [activeRun, baseUrl]);

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

  /* ──────────── Actions ──────────── */

  async function refreshBootstrap() {
    try {
      const [readinessRes, scenariosRes, goalsRes, runsRes] = await Promise.all([
        api.getReadiness(baseUrl),
        api.getScenarios(baseUrl),
        api.getGoals(baseUrl),
        api.getRuns(baseUrl),
      ]);
      setReadiness(readinessRes);
      setScenarios(scenariosRes.scenarios);
      setGoals(goalsRes.goals);
      setRuns(runsRes.runs);
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
      if (launchDraft.customSignal.trim()) {
        const parsed = safeJsonParse(launchDraft.customSignal);
        if (!parsed.ok) {
          addToast({ variant: "error", title: "Invalid signal JSON", description: parsed.error });
          setLaunching(false);
          return;
        }
        payload.signal_payload = parsed.data;
      } else {
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

  const graph = useMemo(
    () => buildRunGraph(activeRun?.events ?? []),
    [activeRun?.events],
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
          <div className="brand-icon"><Zap size={20} /></div>
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
      </header>

      {/* ─── Workspace ─── */}
      <main className="workspace">

        {/* ── Left Rail ── */}
        <aside className="left-rail panel">
          <SectionTitle icon={<Activity size={15} />} title="Integrations" />
          <div className="readiness-grid">
            <ReadinessCard label="Promptfoo" status={readiness?.promptfoo} />
            <ReadinessCard label="Goose" status={readiness?.goose} />
            <ReadinessCard label="GitNexus" status={readiness?.gitnexus} />
          </div>

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
              <p className="helper-text">Promptfoo + Goose + interruptible auto with no default pause points.</p>
            </div>
            {scenarios.length > 0 && (
              <div className="select-wrap">
                <select value={launchDraft.scenarioKey} onChange={(e) => setLaunchDraft({ ...launchDraft, scenarioKey: e.target.value })}>
                  {scenarios.map((s) => (
                    <option key={s.key} value={s.key}>{s.title}</option>
                  ))}
                </select>
                <ChevronDown size={14} className="select-icon" />
              </div>
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
            <textarea
              value={launchDraft.customSignal}
              onChange={(e) => setLaunchDraft({ ...launchDraft, customSignal: e.target.value })}
              placeholder="Optional raw signal JSON…"
              className="small-textarea mono-textarea"
            />
            <button className="action-button primary" onClick={() => void handleLaunchRun()} disabled={launching}>
              {launching ? <Loader2 size={15} className="spin" /> : <Play size={15} />}
              {launching ? "Launching…" : "Launch Run"}
            </button>
          </div>

          <SectionTitle icon={<GitBranch size={15} />} title="Run Queue" />
          <div className="stack">
            {runs.map((run) => (
              <button
                key={run.run_id}
                className={`list-card run-card ${activeRunId === run.run_id ? "selected" : ""}`}
                onClick={() => setActiveRunId(run.run_id)}
              >
                <div className="run-card-header">
                  <strong>{run.scenario_key ?? "manual"}</strong>
                  <span className="run-stage-badge" data-stage={run.stage}>
                    {stageIcon(run.stage)}
                  </span>
                </div>
                <div className="run-card-meta">
                  <span>{humanize(run.stage)}</span>
                  <span>{relativeTime(run.updated_at)}</span>
                </div>
              </button>
            ))}
            {runs.length === 0 && <EmptyState text="No runs yet" />}
          </div>
        </aside>

        {/* ── Center Stage ── */}
        <section className="center-stage">
          <div className="panel center-header">
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
            <div className="status-row">
              <StatusChip label={activeRun ? humanize(activeRun.stage) : "Idle"} tone={toneForStage(activeRun?.stage ?? "queued")} />
              {activeRun?.latest_merkle_root && (
                <StatusChip label={`⧫ ${activeRun.latest_merkle_root.slice(0, 10)}`} tone="#64c7d0" />
              )}
              <ConnectionDot status={systemConnection} label="System" />
              <ConnectionDot status={runConnection} label="Run" />
            </div>
          </div>

          <div className="center-grid">
            <div className="panel graph-panel">
              <SectionTitle icon={<ArrowRight size={15} />} title="Run Graph" />
              {activeRun && graph.nodes.length > 0 ? (
                <ReactFlow
                  fitView
                  nodes={graph.nodes}
                  edges={graph.edges}
                  nodesDraggable={false}
                  nodesConnectable={false}
                  elementsSelectable={false}
                  proOptions={{ hideAttribution: true }}
                >
                  <MiniMap pannable zoomable style={{ background: "rgba(8,14,23,0.9)" }} />
                  <Controls showInteractive={false} />
                  <Background color="#1a2a38" gap={24} />
                </ReactFlow>
              ) : (
                <EmptyState text="Launch a run to see the execution graph." icon={<GitBranch size={28} strokeWidth={1.2} />} />
              )}
            </div>

            <div className="panel timeline-panel">
              <SectionTitle icon={<AlertTriangle size={15} />} title="Steering Console" />
              <div className="steering-grid">
                <SteerButton
                  label="Approve"
                  command="approve"
                  active={steering}
                  disabled={!activeRunId || activeRun?.stage !== "awaiting_operator" || approvalCurrentlyBlocked}
                  primary
                  onClick={handleSteer}
                />
                <SteerButton label="Resume" command="resume" active={steering} disabled={!activeRunId} onClick={handleSteer} />
                <SteerButton label="Cancel" command="cancel" active={steering} disabled={!activeRunId} onClick={handleSteer} />
                <SteerButton
                  label={activeRun?.auto_mode ? "Set Gate" : "Set Auto"}
                  command="set_auto_mode"
                  active={steering}
                  disabled={!activeRunId}
                  onClick={(cmd) => handleSteer(cmd, { enabled: !(activeRun?.auto_mode ?? false) })}
                />
              </div>
              <div className="stack">
                <div className="note-row">
                  <input
                    value={noteDraft}
                    onChange={(e) => setNoteDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && noteDraft.trim()) {
                        void handleSteer("attach_note", { note: noteDraft.trim() });
                        setNoteDraft("");
                      }
                    }}
                    placeholder="Operator note…"
                    disabled={!activeRunId}
                  />
                  <button
                    className="action-button compact"
                    disabled={!activeRunId || !noteDraft.trim()}
                    onClick={() => {
                      void handleSteer("attach_note", { note: noteDraft.trim() });
                      setNoteDraft("");
                    }}
                  >
                    Attach
                  </button>
                </div>
                <button
                  className="toggle-btn"
                  onClick={() => setShowOverrides((v) => !v)}
                >
                  <ChevronDown size={14} className={showOverrides ? "rotate-180" : ""} />
                  Advanced Overrides
                </button>
                {showOverrides && (
                  <div className="stack animate-in">
                    <textarea
                      value={overrideDecisionDraft}
                      onChange={(e) => setOverrideDecisionDraft(e.target.value)}
                      placeholder="Decision override JSON"
                      className="small-textarea mono-textarea"
                    />
                    <button className="action-button compact" disabled={!activeRunId} onClick={handleOverrideDecision}>
                      Override Decision
                    </button>
                    <textarea
                      value={overrideParamsDraft}
                      onChange={(e) => setOverrideParamsDraft(e.target.value)}
                      placeholder="Execution parameter override JSON"
                      className="small-textarea mono-textarea"
                    />
                    <button className="action-button compact" disabled={!activeRunId} onClick={handleOverrideParams}>
                      Override Params
                    </button>
                  </div>
                )}
              </div>

              <SectionTitle icon={<Activity size={15} />} title="Live Timeline" />
              <div className="timeline" ref={timelineRef}>
                {(activeRun?.events ?? []).map((event, i) => (
                  <div
                    key={event.event_id}
                    className="timeline-card"
                    style={{ animationDelay: `${i * 40}ms` }}
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
                  </div>
                ))}
                {(!activeRun || activeRun.events.length === 0) && (
                  <EmptyState text="Events will appear here as the run progresses." />
                )}
              </div>
            </div>
          </div>
        </section>

        {/* ── Right Rail ── */}
        <aside className="right-rail panel">
          <div className="tab-strip">
            {(
              ["overview", "evidence", "policy", "execution", "feedback", "vault", "merkle", "code"] as InspectorTab[]
            ).map((tab) => (
              <button
                key={tab}
                className={inspectorTab === tab ? "tab active" : "tab"}
                onClick={() => setInspectorTab(tab)}
              >
                {tab === "code" ? <FolderGit2 size={12} /> : null}
                {humanize(tab)}
              </button>
            ))}
          </div>
          <Inspector
            tab={inspectorTab}
            run={activeRun}
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
        </aside>
      </main>
    </div>
  );
}

/* ──────────── Inline components ──────────── */

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
  return (
    <div className={`header-metric header-inference ${warning ? "danger" : ready ? "good" : "warn"}`}>
      <span className="header-metric-icon">{icon}</span>
      <div>
        <p>Inference Routing</p>
        <strong>{primaryRoute}</strong>
        {fallbackRoute && <span className="header-metric-subline">Fallback: {fallbackRoute}</span>}
        {warning && <span className="header-metric-warning">{warning}</span>}
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
