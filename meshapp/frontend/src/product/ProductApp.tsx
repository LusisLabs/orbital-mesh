"use client";

import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  BookOpen,
  Boxes,
  Calendar,
  CheckCircle2,
  ChevronDown,
  CircleDot,
  Cpu,
  Database,
  FileCheck,
  Github,
  Globe,
  Home,
  KeyRound,
  Layers,
  Lock,
  LogOut,
  Mail,
  Network,
  Play,
  Plus,
  Search,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Users,
  Zap,
} from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useState } from "react";

import AsciiFlowCanvas from "../landing/AsciiFlowCanvas";
import OperatorConsole, { type AppView } from "../App";
import {
  type AuthConfig,
  type ApprovalCommand,
  type DashboardPayload,
  type LoadState,
  type PraxisSourceInput,
  type RunAdmissionPacket,
  type RunDetailResponse,
  type RunLaunchResponse,
  type SessionPayload,
  backendUnavailableMessage,
  loadStateFromError,
  productApi,
} from "./api";

export type ViewKey =
  | "home"
  | "console"
  | "console-runs"
  | "console-approvals"
  | "console-launch"
  | "console-simulator"
  | "console-trust"
  | "console-packets"
  | "console-readiness"
  | "console-evidence"
  | "console-connectors"
  | "console-agents"
  | "console-signals"
  | "console-hermes"
  | "console-audit"
  | "console-roadmap"
  | "praxis"
  | "environments"
  | "evaluations"
  | "training"
  | "inference"
  | "gpu"
  | "clusters"
  | "instances"
  | "team"
  | "members"
  | "keys"
  | "settings";

const NAV_GROUPS: { label: string; items: { key: ViewKey; label: string; icon: any }[] }[] = [
  {
    label: "Product",
    items: [
      { key: "home", label: "Home", icon: Home },
      { key: "praxis", label: "Praxis", icon: Sparkles },
      { key: "evaluations", label: "Evaluations", icon: BarChart3 },
      { key: "environments", label: "Connectors", icon: Boxes },
      { key: "gpu", label: "Readiness", icon: Cpu },
      { key: "instances", label: "Policy State", icon: Layers },
    ],
  },
  {
    label: "Runtime",
    items: [
      { key: "training", label: "Topology", icon: Network },
      { key: "inference", label: "Memory Projection", icon: Database },
      { key: "clusters", label: "Kill Switch", icon: Calendar },
    ],
  },
  {
    label: "Team",
    items: [
      { key: "team", label: "Team Settings", icon: Settings },
      { key: "members", label: "Members", icon: Users },
      { key: "keys", label: "Keys & Secrets", icon: KeyRound },
      { key: "settings", label: "Settings", icon: SlidersHorizontal },
    ],
  },
  {
    label: "Advanced Console",
    items: [
      { key: "console", label: "Command", icon: Home },
      { key: "console-runs", label: "Evidence Runs", icon: Activity },
      { key: "console-approvals", label: "Approvals", icon: Lock },
      { key: "console-launch", label: "Launch", icon: Play },
      { key: "console-readiness", label: "Control Plane", icon: Cpu },
      { key: "console-evidence", label: "Evidence", icon: ShieldCheck },
      { key: "console-connectors", label: "Connector Matrix", icon: Boxes },
      { key: "console-packets", label: "Pilot Packet", icon: BookOpen },
      { key: "console-hermes", label: "Hermes", icon: Sparkles },
      { key: "console-agents", label: "Proposal Lanes", icon: Network },
      { key: "console-signals", label: "Signals", icon: Zap },
      { key: "console-simulator", label: "Simulator", icon: Layers },
      { key: "console-trust", label: "Trust Ladder", icon: ShieldCheck },
      { key: "console-audit", label: "Audit", icon: Search },
      { key: "console-roadmap", label: "Roadmap", icon: Calendar },
    ],
  },
];

type OperatorWorkflowKey = "launch" | "approval" | "evidence" | "readiness" | "connector" | "settings";
type ConsoleTone = "good" | "warn" | "neutral";
type MemberRole = "viewer" | "launcher" | "approver" | "admin";
export type DashboardSurfaceState = "ready" | "empty" | "degraded" | "blocked" | "unauthorized" | "backend-unavailable";
type AuthProviderKey = "google" | "github";
export type ConsoleWorkflow = {
  productView: ViewKey;
  consoleView: AppView;
  productFallback: ViewKey;
  label: string;
  description: string;
};
type ControlSummary = {
  value: string;
  detail: string;
  tone: ConsoleTone;
};
type ControlRow = {
  id: string;
  label: string;
  value: string;
  detail: string;
};
type DashboardControlModel = {
  readiness: ControlSummary;
  runs: ControlSummary;
  approvals: ControlSummary;
  evidence: ControlSummary;
  recentRuns: ControlRow[];
  connectors: ControlRow[];
  systemRows: Array<ControlRow & { view: ViewKey }>;
};
type DashboardTileModel = {
  title: string;
  detail: string;
  icon: any;
  view: ViewKey;
  apiSection: string;
  state: DashboardSurfaceState;
  stateReason: string;
};
type PartnerHomeModel = {
  readiness: { label: "Go" | "Blocked" | "Demo-only"; detail: string; tone: ConsoleTone };
  nextStep: { label: string; detail: string; view: ViewKey; action: string };
  recentActivity: ControlRow[];
  blockedEvidence: ControlRow[];
};
export type SettingsParityRow = {
  key: string;
  label: string;
  value: string;
  description: string;
  mutable: boolean;
  values?: string[];
  uiMutationPath?: string;
  cliPath?: string;
  readOnlyReason?: string;
};
type PraxisProductModel = {
  requestId: string;
  runCount: string;
  status: string;
  proofStatus: string;
  sourcePackets: string;
  toolCandidates: string;
  certifiedTools: string;
  deniedTools: string;
  mcpEndpoint: string;
  runtimeStatus: string;
  managedRuntime: boolean;
  blockerCount: number;
  tools: Array<ControlRow & { method: string; path: string; tone: ConsoleTone }>;
  controls: Array<ControlRow & { state: string; requiresMeshApproval: boolean }>;
};

const CONSOLE_WORKFLOW_MATRIX: ConsoleWorkflow[] = [
  { productView: "console", consoleView: "overview", productFallback: "home", label: "Command", description: "Production readiness cockpit, live system stream, launch prompts, and active run context." },
  { productView: "console-runs", consoleView: "runs", productFallback: "evaluations", label: "Evidence Runs", description: "Run timeline, delivery context, evidence graph, RCA, approvals, actions, Darkharness, audit, agents, and topology." },
  { productView: "console-approvals", consoleView: "approvals", productFallback: "evaluations", label: "Approvals", description: "Approval queue, steering commands, operator notes, and Hermes escalation hooks." },
  { productView: "console-launch", consoleView: "automation", productFallback: "evaluations", label: "Launch", description: "Goal creation, scenario launch, evaluation mode, orchestration mode, steering mode, and target lock controls." },
  { productView: "console-simulator", consoleView: "simulator", productFallback: "evaluations", label: "Simulator", description: "Scenario simulator and policy dry-run controls backed by Mesh admission and evaluation state." },
  { productView: "console-trust", consoleView: "trust", productFallback: "instances", label: "Trust Ladder", description: "Trust ladder entries, autonomy tiers, service authority, and promotion posture." },
  { productView: "console-packets", consoleView: "packets", productFallback: "evaluations", label: "Pilot Packet", description: "Pilot go/no-go, Darkharness packet, evidence packet, release proof, and boundary status." },
  { productView: "console-readiness", consoleView: "control-plane", productFallback: "gpu", label: "Readiness", description: "Control-plane readiness, connector certification, watcher state, kill switch, and deployment blockers." },
  { productView: "console-evidence", consoleView: "evidence", productFallback: "evaluations", label: "Evidence", description: "Evidence graph, proof drill-ins, selected event context, Merkle continuity, and export path." },
  { productView: "console-connectors", consoleView: "integrations", productFallback: "environments", label: "Connectors", description: "Connector certification matrix, credential boundaries, authority posture, and integration groups." },
  { productView: "console-agents", consoleView: "agents", productFallback: "training", label: "Proposal Lanes", description: "Hermes, Goose, native, custom HTTP agent lanes, certification, and bounded proposal posture." },
  { productView: "console-signals", consoleView: "fleet", productFallback: "gpu", label: "Signals", description: "Fleet health, watcher signals, live events, and system stream status." },
  { productView: "console-hermes", consoleView: "hermes", productFallback: "evaluations", label: "Hermes", description: "Hermes chat, explanation, advisory context, and steering-bound operator interaction." },
  { productView: "console-audit", consoleView: "audit", productFallback: "evaluations", label: "Audit", description: "Timeline proof, Merkle proof, evidence continuity, operator audit, and export validation." },
  { productView: "console-roadmap", consoleView: "roadmap", productFallback: "home", label: "Roadmap", description: "Operator roadmap, release gates, readiness milestones, and migration status." },
];

export function consoleParityMatrix(): ConsoleWorkflow[] {
  return CONSOLE_WORKFLOW_MATRIX;
}

export function isConsoleProductView(view: ViewKey): boolean {
  return CONSOLE_WORKFLOW_MATRIX.some((workflow) => workflow.productView === view);
}

export function consoleWorkflowForView(view: ViewKey): ConsoleWorkflow {
  return CONSOLE_WORKFLOW_MATRIX.find((workflow) => workflow.productView === view) ?? CONSOLE_WORKFLOW_MATRIX[0];
}

export function operatorWorkflowPosture(workflow: OperatorWorkflowKey): { callPath: string; posture: "native" | "delegated" | "read_only"; reason: string } {
  const postures: Record<OperatorWorkflowKey, { callPath: string; posture: "native" | "delegated" | "read_only"; reason: string }> = {
    launch: {
      callPath: "/api/operator/dashboard mesh.runs and Mesh-owned POST /api/runs admission",
      posture: "native",
      reason: "Run launch is product-native, but mutation still goes through Mesh-owned /api/runs admission, role checks, policy, and audit context.",
    },
    approval: {
      callPath: "/api/operator/dashboard mesh.approvals and Mesh-owned /api/runs/{run_id}/steer",
      posture: "read_only",
      reason: "Approval state is embedded in the dashboard. Steering remains Mesh-controlled and is not bypassed by this product shell.",
    },
    evidence: {
      callPath: "/api/runs/{run_id}/evidence-graph and export endpoints",
      posture: "read_only",
      reason: "Evidence is inspectable here as a read model; Mesh remains the evidence and export authority.",
    },
    readiness: {
      callPath: "/api/readiness through /api/operator/dashboard",
      posture: "read_only",
      reason: "Readiness is a Mesh-owned read model in the product shell; remediation and actuation stay in Mesh.",
    },
    connector: {
      callPath: "/api/connectors/certification through /api/operator/dashboard",
      posture: "read_only",
      reason: "Connector certification is read-only here until Mesh exposes a product-native mutation endpoint.",
    },
    settings: {
      callPath: "/api/operator/settings and scripts/operator_config.py",
      posture: "native",
      reason: "Settings mutate the shared validated settings slice used by the UI and CLI.",
    },
  };
  return postures[workflow];
}

export default function ProductApp() {
  const [authConfig, setAuthConfig] = useState<AuthConfig | null>(null);
  const [session, setSession] = useState<SessionPayload | null>(null);
  const [sessionState, setSessionState] = useState<LoadState<SessionPayload>>({ state: "loading" });
  const [dashboardState, setDashboardState] = useState<LoadState<DashboardPayload>>({ state: "loading" });
  const [view, setView] = useState<ViewKey>("home");
  const [onboardingComplete, setOnboardingComplete] = useState(false);
  const [logoutError, setLogoutError] = useState("");
  const [loggingOut, setLoggingOut] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  function soloOnboardingKey(userId: string): string {
    return `mesh.product.solo.${userId}`;
  }

  function acceptSession(payload: SessionPayload) {
    setSession(payload);
    setSessionState({ state: "ready", data: payload });
    setOnboardingComplete(Boolean(payload.active_team || window.localStorage.getItem(soloOnboardingKey(payload.user.id)) === "1"));
  }

  function clearSession(state: LoadState<SessionPayload>) {
    setSession(null);
    setSessionState(state);
    setOnboardingComplete(false);
    setDashboardState({ state: "empty", message: "Sign in to load the dashboard." });
  }

  async function refreshDashboard() {
    if (!session || (!session.active_team && !onboardingComplete)) return;
    setDashboardState((current) => (current.state === "ready" ? current : { state: "loading" }));
    try {
      const payload = await productApi.dashboard(session.active_team?.id ?? null);
      setDashboardState({ state: "ready", data: payload });
    } catch (error) {
      const nextState = loadStateFromError<DashboardPayload>(error);
      setDashboardState(nextState);
      if (nextState.state === "unauthorized") {
        clearSession({ state: "unauthorized", message: "Session expired or missing. Sign in again." });
      }
    }
  }

  useEffect(() => {
    let mounted = true;
    async function boot() {
      try {
        const config = await productApi.authConfig();
        if (!mounted) return;
        setAuthConfig(config);
      } catch {
        if (!mounted) return;
        setAuthConfig(null);
      }
      try {
        const payload = await productApi.me();
        if (!mounted) return;
        acceptSession(payload);
      } catch (error) {
        if (!mounted) return;
        clearSession(loadStateFromError(error));
      }
    }
    boot();
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!session || (!session.active_team && !onboardingComplete)) return;
    let mounted = true;
    setDashboardState((current) => (current.state === "ready" ? current : { state: "loading" }));
    productApi.dashboard(session.active_team?.id ?? null)
      .then((payload) => {
        if (!mounted) return;
        setDashboardState({ state: "ready", data: payload });
      })
      .catch((error) => {
        if (!mounted) return;
        const nextState = loadStateFromError<DashboardPayload>(error);
        setDashboardState(nextState);
        if (nextState.state === "unauthorized") {
          clearSession({ state: "unauthorized", message: "Session expired or missing. Sign in again." });
        }
      });
    return () => {
      mounted = false;
    };
  }, [session, onboardingComplete]);

  async function refreshSession() {
    const payload = await productApi.me();
    acceptSession(payload);
    return payload;
  }

  async function logout() {
    if (loggingOut) return;
    setLoggingOut(true);
    setLogoutError("");
    try {
      if (session) window.localStorage.removeItem(soloOnboardingKey(session.user.id));
      await productApi.logout();
      setSession(null);
      setOnboardingComplete(false);
      setSessionState({ state: "unauthorized", message: "Logged out" });
      setDashboardState({ state: "empty", message: "Sign in to load the dashboard." });
    } catch (err) {
      setLogoutError(err instanceof Error ? err.message : "Logout failed. Session was not cleared.");
    } finally {
      setLoggingOut(false);
    }
  }

  if (sessionState.state === "loading") {
    return <BootScreen />;
  }

  if (!session) {
    return <AuthScreen config={authConfig} sessionState={sessionState} onSession={acceptSession} />;
  }

  if (!session.active_team && !onboardingComplete) {
    return (
      <TeamSetupScreen
        session={session}
        onSolo={() => {
          window.localStorage.setItem(soloOnboardingKey(session.user.id), "1");
          setOnboardingComplete(true);
        }}
        onTeam={(payload) => {
          acceptSession(payload);
          setOnboardingComplete(true);
        }}
      />
    );
  }

  const dashboard = dashboardState.state === "ready" ? dashboardState.data : null;
  const consoleMode = isConsoleProductView(view);
  const activePage = pageMetaForView(view);
  const openView = (nextView: ViewKey) => {
    setView(nextView);
    if (typeof window !== "undefined") window.scrollTo({ top: 0, left: 0 });
  };

  return (
    <div className={`product-shell ${consoleMode ? "console-mode" : ""} ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <Sidebar
        session={session}
        activeView={view}
        onView={openView}
        onLogout={logout}
        loggingOut={loggingOut}
        collapsed={sidebarCollapsed}
        onCollapsedChange={setSidebarCollapsed}
      />
      <main className="product-main">
        <Header session={session} dashboard={dashboard} refreshSession={refreshSession} consoleMode={consoleMode} activePage={activePage} />
        {logoutError ? (
          <div className="product-alert" role="alert">
            <AlertTriangle size={16} />
            <span>{logoutError}</span>
          </div>
        ) : null}
        <ContentRouter
          view={view}
          authConfig={authConfig}
          session={session}
          dashboardState={dashboardState}
          setView={openView}
          onDashboardRefresh={refreshDashboard}
          onSession={acceptSession}
          onLogout={logout}
          loggingOut={loggingOut}
        />
      </main>
    </div>
  );
}

function BootScreen() {
  return (
    <div className="product-boot">
      <BrandLogo compact />
      <span>Loading operator surface</span>
    </div>
  );
}

function BrandLogo({ compact = false }: { compact?: boolean }) {
  return (
    <span className={compact ? "mesh-logo compact" : "mesh-logo"}>
      <img src="/orbital-mesh-logo.svg" alt="Mesh" />
      {compact ? null : <strong>Mesh</strong>}
    </span>
  );
}

function AsciiFlowBackground() {
  return (
    <div className="auth-ascii-flow" aria-hidden="true">
      <AsciiFlowCanvas progress={0} />
    </div>
  );
}

export function AuthScreen({
  config,
  sessionState,
  onSession,
}: {
  config: AuthConfig | null;
  sessionState?: LoadState<SessionPayload>;
  onSession: (session: SessionPayload) => void;
}) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [captchaToken, setCaptchaToken] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const backendUnavailable = !config;
  const sessionIssueMessage = sessionLoadIssueMessage(sessionState);
  const authUnavailable = backendUnavailable || sessionState?.state === "backend-unavailable";
  const signupMode = mode === "signup";
  const passwordMatches = !signupMode || password === passwordConfirm;
  const signupEnabled = !signupMode || Boolean(config?.signup_enabled && config?.password_auth_enabled);
  const inviteRequired = signupMode && Boolean(config?.invite?.required);
  const inviteSatisfied = !inviteRequired || Boolean(inviteCode.trim());
  const captchaSatisfied =
    !signupMode ||
    Boolean(config?.captcha.dev_bypass_enabled) ||
    (Boolean(config?.captcha.configured) && Boolean(captchaToken));
  const submitDisabled = busy || authUnavailable || !email.trim() || !password || !passwordMatches || !signupEnabled || !captchaSatisfied || !inviteSatisfied || (signupMode && !acceptedTerms);
  const enabledOauthProviders = (["google", "github"] as AuthProviderKey[]).filter((provider) => config?.oauth[provider].configured);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const authError = params.get("auth_error");
    if (authError) {
      setError(authCallbackErrorMessage(authError));
    }
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitDisabled) return;
    setBusy(true);
    setError("");
    try {
      const payload = mode === "signup"
        ? await productApi.signup({
          email,
          password,
          display_name: displayName,
          captcha_token: captchaToken || (config?.captcha.dev_bypass_enabled ? "dev-captcha-ok" : ""),
          invite_code: inviteCode.trim() || undefined,
          accepted_terms: acceptedTerms,
        })
        : await productApi.login({ email, password });
      onSession(payload);
    } catch (err) {
      setError(authFailureMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function oauth(provider: AuthProviderKey) {
    if (!config || authUnavailable) {
      setError(backendUnavailable ? backendUnavailableMessage() : sessionIssueMessage || "Authentication is unavailable.");
      return;
    }
    if (!config.oauth[provider].configured) {
      setError(`${providerLabel(provider)} sign-in is not available for this environment.`);
      return;
    }
    setError("");
    try {
      const payload = await productApi.oauthStart(provider);
      window.location.assign(payload.authorize_url);
    } catch (err) {
      setError(authFailureMessage(err));
    }
  }

  return (
    <div className="auth-scene">
      <AsciiFlowBackground />
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-brand">
          <BrandLogo compact />
          <span>Mesh</span>
        </div>
        <h1>{mode === "login" ? "Welcome" : "Create your account"}</h1>
        <p>Sign in to operate Mesh without changing its control-plane authority.</p>
        {backendUnavailable || sessionIssueMessage ? (
          <div className="auth-backend-banner">
            <AlertTriangle size={16} />
            <span>{backendUnavailable ? backendUnavailableMessage() : sessionIssueMessage}</span>
          </div>
        ) : null}
        {enabledOauthProviders.length ? (
          <div className="oauth-stack">
            {enabledOauthProviders.map((provider) => {
              const Icon = provider === "google" ? Globe : Github;
              return (
                <button key={provider} type="button" onClick={() => oauth(provider)} disabled={authUnavailable}>
                  <Icon size={18} /> Continue with {providerLabel(provider)}
                </button>
              );
            })}
          </div>
        ) : (
          <p className="auth-provider-note neutral">Use your invited email and password for this environment.</p>
        )}
        <div className="divider"><span>OR</span></div>
        {mode === "signup" ? (
          <label>
            Display name
            <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Shaan Patel" />
          </label>
        ) : null}
        <label>
          Email address
          <input value={email} onChange={(event) => setEmail(event.target.value)} placeholder="operator@company.com" autoComplete="email" />
        </label>
        <label>
          Password
          <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} />
        </label>
        {mode === "signup" ? (
          <>
            <label>
              Confirm password
              <input value={passwordConfirm} onChange={(event) => setPasswordConfirm(event.target.value)} type="password" autoComplete="new-password" />
            </label>
            {inviteRequired ? (
              <label>
                Invite code
                <input value={inviteCode} onChange={(event) => setInviteCode(event.target.value)} placeholder="from your Mesh invite" autoComplete="one-time-code" />
              </label>
            ) : null}
            <label className="consent-row">
              <input type="checkbox" checked={acceptedTerms} onChange={(event) => setAcceptedTerms(event.target.checked)} />
              <span>I agree to use only redacted sources and understand Mesh keeps policy, approvals, run state, evidence, and actuation authority.</span>
            </label>
            {!passwordMatches ? <div className="auth-error compact">Passwords must match.</div> : null}
            {!signupEnabled ? <div className="auth-error compact">Signup is invite-only for this environment.</div> : null}
          </>
        ) : null}
        {mode === "signup" ? <CaptchaWidget config={config} onToken={setCaptchaToken} /> : null}
        {error ? <div className="auth-error">{error}</div> : null}
        <button className="primary-button" type="submit" disabled={submitDisabled}>
          {busy ? "Working" : mode === "login" ? "Continue" : "Sign up"}
        </button>
        <button
          className="link-button"
          type="button"
          onClick={() => {
            setMode(mode === "login" ? "signup" : "login");
            setCaptchaToken("");
            setPasswordConfirm("");
            setInviteCode("");
            setAcceptedTerms(false);
            setError("");
          }}
        >
          {mode === "login" ? "Need an account? Sign up" : "Have an account? Log in"}
        </button>
      </form>
    </div>
  );
}

function providerLabel(provider: AuthProviderKey): string {
  return provider === "google" ? "Google" : "GitHub";
}

export function authFailureMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : "Authentication failed";
  const normalized = message.toLowerCase();
  if (normalized.includes("captcha")) return "Complete the verification challenge, then try again.";
  if (normalized.includes("invite") || normalized.includes("allowlist") || normalized.includes("not allowed")) return "This email is not invited for this Mesh environment.";
  if (normalized.includes("user already exists")) return "An account already exists for this email. Log in instead.";
  if (normalized.includes("invalid email or password")) return "Email or password is incorrect.";
  if (normalized.includes("password signup is disabled")) return "Signup is invite-only for this environment.";
  if (normalized.includes("oauth is not configured")) return "That sign-in provider is not available for this environment.";
  if (normalized.includes("terms consent")) return "Accept the data-handling and authority boundary terms before creating an account.";
  return message;
}

export function authCallbackErrorMessage(code: string): string {
  const normalized = code.trim().toLowerCase();
  if (normalized === "missing_oauth_code") {
    return "OAuth callback did not include a provider code. Provider setup or redirect state is incomplete.";
  }
  if (normalized === "google_oauth_failed") {
    return "Google OAuth callback failed. Provider redirect URL, code exchange, or client credentials did not validate on the Mesh API server.";
  }
  if (normalized === "github_oauth_failed") {
    return "GitHub OAuth callback failed. Provider redirect URL, code exchange, or client credentials did not validate on the Mesh API server.";
  }
  return normalized.replaceAll("_", " ");
}

function sessionLoadIssueMessage(state?: LoadState<SessionPayload>): string {
  if (!state || state.state === "loading" || state.state === "ready" || state.state === "unauthorized") {
    return "";
  }
  return state.message;
}

function CaptchaWidget({ config, onToken }: { config: AuthConfig | null; onToken: (token: string) => void }) {
  const [state, setState] = useState<"idle" | "loading" | "ready" | "verified" | "error">("idle");

  useEffect(() => {
    onToken("");
    if (!config?.captcha.configured || !config.captcha.site_key || config.captcha.dev_bypass_enabled) return;
    let mounted = true;
    const provider = config.captcha.provider;
    const scriptId = `mesh-captcha-script-${provider}`;
    const existingScript = document.getElementById(scriptId) as HTMLScriptElement | null;
    const script = document.createElement("script");
    script.async = true;
    script.defer = true;
    script.id = scriptId;
    script.src = provider === "turnstile"
      ? "https://challenges.cloudflare.com/turnstile/v0/api.js"
      : provider === "hcaptcha"
        ? "https://js.hcaptcha.com/1/api.js"
        : "https://www.google.com/recaptcha/api.js?render=explicit";
    const render = () => {
      if (!mounted) return;
      const target = document.getElementById("mesh-captcha");
      if (!target) return;
      target.innerHTML = "";
      const callback = (token: string) => {
        onToken(token);
        setState("verified");
      };
      const expiredCallback = () => {
        onToken("");
        setState("ready");
      };
      setState("ready");
      if (provider === "turnstile" && (window as any).turnstile) {
        (window as any).turnstile.render(target, { sitekey: config.captcha.site_key, callback, "expired-callback": expiredCallback });
      } else if (provider === "hcaptcha" && (window as any).hcaptcha) {
        (window as any).hcaptcha.render(target, { sitekey: config.captcha.site_key, callback, "expired-callback": expiredCallback });
      } else if ((window as any).grecaptcha) {
        (window as any).grecaptcha.ready(() => {
          (window as any).grecaptcha.render(target, { sitekey: config.captcha.site_key, callback, "expired-callback": expiredCallback });
        });
      } else {
        setState("error");
      }
    };
    setState("loading");
    if (existingScript) {
      render();
    } else {
      script.onload = render;
      script.onerror = () => setState("error");
      document.body.appendChild(script);
    }
    return () => {
      mounted = false;
      document.getElementById("mesh-captcha")?.replaceChildren();
    };
  }, [config, onToken]);

  if (config?.captcha.dev_bypass_enabled) {
    return <div className="captcha-box"><ShieldCheck size={18} /> Local captcha bypass is active for development only.</div>;
  }
  if (!config?.captcha.configured) {
    return <div className="captcha-box blocked"><AlertTriangle size={18} /> Signup blocked: captcha provider, site key, and secret must be configured on the Mesh API server.</div>;
  }
  return (
    <div className={`captcha-box captcha-widget ${state === "error" ? "blocked" : ""}`}>
      <div id="mesh-captcha" className="captcha-render-target" />
      {state === "loading" ? <span>Loading captcha challenge...</span> : null}
      {state === "verified" ? <span>Captcha verified.</span> : null}
      {state === "error" ? <span>Captcha failed to load. Check provider keys and browser network access.</span> : null}
    </div>
  );
}

function TeamSetupScreen({
  session,
  onSolo,
  onTeam,
}: {
  session: SessionPayload;
  onSolo: () => void;
  onTeam: (payload: SessionPayload) => void;
}) {
  const [name, setName] = useState("");
  const [invite, setInvite] = useState("");
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);

  async function createTeam() {
    const teamName = name.trim();
    if (!teamName) {
      setError("Team name is required.");
      return;
    }
    setCreating(true);
    setError("");
    try {
      const members = invite.split(",").map((email) => email.trim()).filter(Boolean).map((email) => ({ email, role: "viewer" }));
      const payload = await productApi.createTeam({ name: teamName, members });
      onTeam(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Team creation failed");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="setup-scene">
      <section className="setup-card">
        <BrandLogo compact />
        <h1>Create a team</h1>
        <p>Teams scope the dashboard and roles. Mesh still owns approvals, run state, evidence, policy, and actuation.</p>
        <label>
          Team name
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder={`${session.user.display_name}'s team`} />
        </label>
        <label>
          Invite members
          <input value={invite} onChange={(event) => setInvite(event.target.value)} placeholder="colleague@company.com, sre@company.com" />
        </label>
        {error ? <div className="auth-error">{error}</div> : null}
        <button className="primary-button" type="button" onClick={createTeam} disabled={creating}>{creating ? "Creating" : "Create team"}</button>
        <button className="link-button" type="button" onClick={onSolo}>Continue solo</button>
      </section>
    </div>
  );
}

function Sidebar({
  session,
  activeView,
  onView,
  onLogout,
  loggingOut,
  collapsed,
  onCollapsedChange,
}: {
  session: SessionPayload;
  activeView: ViewKey;
  onView: (view: ViewKey) => void;
  onLogout: () => void;
  loggingOut: boolean;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
}) {
  function openDocs() {
    window.open("https://github.com/LusisLabs/orbital-mesh/tree/master/docs", "_blank", "noopener,noreferrer");
  }

  return (
    <aside className="product-sidebar">
      <div className="brand-row">
        <BrandLogo />
        <button
          type="button"
          aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
          title={collapsed ? "Expand navigation" : "Collapse navigation"}
          onClick={() => onCollapsedChange(!collapsed)}
        >
          <ChevronDown size={14} />
        </button>
      </div>
      <nav>
        {NAV_GROUPS.map((group) => (
          <div className="nav-group" key={group.label || "home"}>
            {group.label ? <p>{group.label}</p> : null}
            {group.items.map((item) => {
              const Icon = item.icon;
              return (
                <button key={item.key} className={activeView === item.key ? "active" : ""} type="button" onClick={() => onView(item.key)} title={item.label} aria-label={item.label}>
                  <Icon size={16} /> <span className="nav-label">{item.label}</span>
                </button>
              );
            })}
          </div>
        ))}
        <div className="nav-group">
          <p>Support</p>
          <button type="button" onClick={() => onView("evaluations")} title="Run Review" aria-label="Run Review"><Mail size={16} /> <span className="nav-label">Run Review</span></button>
          <button type="button" onClick={openDocs} title="Documentation" aria-label="Documentation"><BookOpen size={16} /> <span className="nav-label">Documentation</span></button>
          <button type="button" onClick={() => onView("settings")} title="Config" aria-label="Config"><Database size={16} /> <span className="nav-label">Config</span></button>
        </div>
      </nav>
      <div className="sidebar-footer">
        <div>
          <strong>{session.active_team?.name || "Solo"}</strong>
          <span>{session.user.email}</span>
        </div>
        <button type="button" onClick={onLogout} disabled={loggingOut} title={loggingOut ? "Logging out" : "Log out"}><LogOut size={15} /></button>
      </div>
    </aside>
  );
}

function Header({
  session,
  dashboard,
  refreshSession,
  consoleMode,
  activePage,
}: {
  session: SessionPayload;
  dashboard: DashboardPayload | null;
  refreshSession: () => Promise<SessionPayload>;
  consoleMode?: boolean;
  activePage: { title: string; group: string; detail: string };
}) {
  const scope = dashboard?.scope.kind === "team" ? dashboard.scope.team?.display_name : "Solo dashboard";
  return (
    <header className="product-header">
      <div>
        <div className="breadcrumb-row">
          <span>{scope}</span>
          <ArrowRight size={13} />
          <span>{activePage.group}</span>
        </div>
        <h1>{activePage.title}</h1>
        <p>{consoleMode ? activePage.detail : activePage.detail || dashboard?.authority_boundary || "Mesh controls policy, approvals, run state, readiness, evidence, and actuation."}</p>
      </div>
      <div className="header-actions">
        <TeamSwitcher session={session} refreshSession={refreshSession} />
      </div>
    </header>
  );
}

function pageMetaForView(view: ViewKey): { title: string; group: string; detail: string } {
  if (isConsoleProductView(view)) {
    const workflow = consoleWorkflowForView(view);
    return { title: workflow.label, group: "Advanced Console", detail: workflow.description };
  }
  const match = NAV_GROUPS.flatMap((group) => group.items.map((item) => ({ ...item, group: group.label || "Product" }))).find((item) => item.key === view);
  const title = match?.label || humanize(view);
  const details: Partial<Record<ViewKey, string>> = {
    home: "Readiness, next action, recent activity, and blockers before the console.",
    praxis: "Upload sources, certify generated tools, start dry-run, and export proof.",
    evaluations: "Choose a scenario, launch through Mesh admission, and inspect proof.",
    environments: "Filter connector status by domain, state, and blocker evidence.",
    settings: "Choose safe defaults for new runs; deployment and CLI parity stay in Advanced.",
    team: "Create or review the active team scope for partner-safe access.",
    members: "Review team roles that map into Mesh operator permissions.",
    keys: "Review deployment-owned auth and secret posture without exposing raw values.",
  };
  return { title, group: match?.group || "Product", detail: details[view] || "Mesh-owned read model with product-safe controls." };
}

function TeamSwitcher({ session, refreshSession }: { session: SessionPayload; refreshSession: () => Promise<SessionPayload> }) {
  async function switchTeam(teamId: string | null) {
    await productApi.switchTeam(teamId);
    await refreshSession();
  }

  return (
    <select value={session.active_team?.id || "solo"} onChange={(event) => switchTeam(event.target.value === "solo" ? null : event.target.value)}>
      <option value="solo">Solo dashboard</option>
      {session.teams.map((team) => <option key={team.id} value={team.id}>{team.name}</option>)}
    </select>
  );
}

function ContentRouter({
  view,
  authConfig,
  session,
  dashboardState,
  setView,
  onDashboardRefresh,
  onSession,
  onLogout,
  loggingOut,
}: {
  view: ViewKey;
  authConfig: AuthConfig | null;
  session: SessionPayload;
  dashboardState: LoadState<DashboardPayload>;
  setView: (view: ViewKey) => void;
  onDashboardRefresh: () => Promise<void>;
  onSession: (session: SessionPayload) => void;
  onLogout: () => void;
  loggingOut: boolean;
}) {
  if (isConsoleProductView(view)) {
    return <ConsoleWorkspace view={view} setView={setView} />;
  }
  if (dashboardState.state !== "ready") {
    return <LoadStatePanel state={dashboardState} />;
  }
  const dashboard = dashboardState.data;
  if (view === "home") return <HomeView dashboard={dashboard} setView={setView} />;
  if (view === "praxis") return <PraxisView dashboard={dashboard} setView={setView} onDashboardRefresh={onDashboardRefresh} />;
  if (view === "environments") return <EnvironmentView dashboard={dashboard} setView={setView} />;
  if (view === "evaluations") return <EvaluationsView dashboard={dashboard} setView={setView} onDashboardRefresh={onDashboardRefresh} />;
  if (view === "team") return <TeamSettingsView session={session} dashboard={dashboard} onDashboardRefresh={onDashboardRefresh} onSession={onSession} onLogout={onLogout} loggingOut={loggingOut} />;
  if (view === "members") return <MembersView session={session} setView={setView} onSession={onSession} onDashboardRefresh={onDashboardRefresh} />;
  if (view === "keys") return <KeysView authConfig={authConfig} dashboard={dashboard} setView={setView} />;
  if (view === "settings") return <div className="content-stack"><SettingsView dashboard={dashboard} onDashboardRefresh={onDashboardRefresh} /></div>;
  return <CapabilityView view={view} dashboard={dashboard} setView={setView} />;
}

function ConsoleWorkspace({ view, setView }: { view: ViewKey; setView: (view: ViewKey) => void }) {
  const workflow = consoleWorkflowForView(view);
  return (
    <section className="console-workspace" aria-label="Full Mesh control console">
      <div className="console-workspace-toolbar">
        <div>
          <span>{workflow.label}</span>
          <strong>{workflow.description}</strong>
        </div>
        <div className="console-workspace-actions">
          <button type="button" onClick={() => setView("home")}>Product Home</button>
          <button type="button" onClick={() => setView(workflow.productFallback)}>Product View</button>
        </div>
      </div>
      <OperatorConsole initialView={workflow.consoleView} />
    </section>
  );
}

function LoadStatePanel<T>({ state }: { state: LoadState<T> }) {
  if (state.state === "loading") return <div className="skeleton-panel"><span /><span /><span /></div>;
  if (state.state === "ready") return null;
  return <div className={`state-panel ${state.state}`}><AlertTriangle size={18} /> {state.message}</div>;
}

function HomeView({ dashboard, setView }: { dashboard: DashboardPayload; setView: (view: ViewKey) => void }) {
  const praxis = buildPraxisProductModel(dashboard);
  const capabilityCards = buildDashboardTiles(dashboard);
  const partnerHome = buildPartnerHomeModel(dashboard);

  return (
    <div className="content-stack">
      <section className={`partner-home-hero ${partnerHome.readiness.tone}`}>
        <div>
          <span>Readiness</span>
          <h2>{partnerHome.readiness.label}</h2>
          <p>{partnerHome.readiness.detail}</p>
        </div>
        <button type="button" onClick={() => setView(partnerHome.nextStep.view)}>
          {partnerHome.nextStep.action} <ArrowRight size={16} />
        </button>
      </section>
      <section className="partner-home-grid">
        <article className="partner-card next">
          <div className="panel-title"><CheckCircle2 size={15} /><span>Next step</span></div>
          <strong>{partnerHome.nextStep.label}</strong>
          <p>{partnerHome.nextStep.detail}</p>
          <button type="button" onClick={() => setView(partnerHome.nextStep.view)}>{partnerHome.nextStep.action}</button>
        </article>
        <article className="partner-card">
          <div className="panel-title"><Activity size={15} /><span>Recent activity</span></div>
          {partnerHome.recentActivity.length ? partnerHome.recentActivity.map((item) => (
            <button className="console-row" key={item.id} type="button" onClick={() => setView("evaluations")}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
              <small>{item.detail}</small>
            </button>
          )) : <EmptyInline text="No recent Mesh activity for this scope." />}
        </article>
        <article className="partner-card">
          <div className="panel-title"><FileCheck size={15} /><span>Blocked evidence</span></div>
          {partnerHome.blockedEvidence.length ? partnerHome.blockedEvidence.map((item) => (
            <button className="console-row" key={item.id} type="button" onClick={() => setView("evaluations")}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
              <small>{item.detail}</small>
            </button>
          )) : <EmptyInline text="No missing proof reported by Mesh." />}
        </article>
      </section>
      <PraxisHomeModule model={praxis} setView={setView} />
      <section className="advanced-console-band">
        <div>
          <span>Advanced operator console</span>
          <strong>Full Mesh console workflows are still available, but product tasks come first.</strong>
        </div>
        <button type="button" onClick={() => setView("console")}>Open Advanced Console</button>
      </section>
      <SectionLabel label="Product paths" />
      <div className="capability-grid">
        {capabilityCards.filter((card) => card.view !== "console").slice(0, 6).map((card) => {
          const Icon = card.icon;
          return (
            <button className="capability-card" key={card.title} type="button" onClick={() => setView(card.view)}>
              <Icon size={18} />
              <strong>{card.title}</strong>
              <span className={`tile-state ${card.state}`}>{card.state}</span>
              <span>{card.detail}</span>
              <small>{card.apiSection}</small>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function buildPartnerHomeModel(dashboard: DashboardPayload): PartnerHomeModel {
  const mesh = dashboard.mesh || {};
  const control = buildDashboardControlModel(dashboard);
  const pilot = mesh.pilot_go_no_go || {};
  const readiness = mesh.readiness || {};
  const missing = Array.isArray(pilot.missing_evidence) ? pilot.missing_evidence : [];
  const readinessStatus = String(readiness.status || pilot.final_release_decision || pilot.status || "").toLowerCase();
  const demoOnly = readiness.profile === "local" || readinessStatus.includes("demo");
  const blocked = missing.length > 0 || readiness.ready === false || readinessStatus.includes("blocked") || readinessStatus.includes("denied");
  const readinessLabel = blocked ? "Blocked" : demoOnly ? "Demo-only" : "Go";
  const praxis = buildPraxisProductModel(dashboard);
  const nextStep = !dashboard.scope.team
    ? { label: "Create a team", detail: "Team scope keeps partners, roles, and proof review separate from solo browser state.", view: "team" as ViewKey, action: "Set up team" }
    : Number(praxis.sourcePackets) === 0
      ? { label: "Import Praxis source", detail: "Upload redacted OpenAPI, SOP, Postman, or traffic references before tool generation.", view: "praxis" as ViewKey, action: "Import source" }
      : !control.recentRuns.length
        ? { label: "Launch sandbox run", detail: "Pick a scenario and let Mesh admit or block the run with audit context.", view: "evaluations" as ViewKey, action: "Launch run" }
        : { label: "Review proof", detail: "Open the run proof views and inspect missing evidence before partner handoff.", view: "evaluations" as ViewKey, action: "Review proof" };
  return {
    readiness: {
      label: readinessLabel,
      detail: blocked
        ? `${missing.length || readiness.blockers?.length || 1} blocker(s) must be resolved before invites.`
        : demoOnly
          ? "Local/demo evidence is useful for rehearsal, but live provider proof is still required before external invites."
          : "Mesh reports no current invite-blocking readiness issue in this dashboard scope.",
      tone: blocked ? "warn" : "good",
    },
    nextStep,
    recentActivity: control.recentRuns.slice(0, 3),
    blockedEvidence: missing.slice(0, 4).map((item: any, index: number) => ({
      id: `missing-${index}`,
      label: "Missing proof",
      value: humanize(String(item)),
      detail: plainEvidenceBlocker(String(item)),
    })),
  };
}

function plainEvidenceBlocker(value: string): string {
  const lower = value.toLowerCase();
  if (lower.includes("auth")) return "Complete live provider proof for signup, OAuth, and captcha before inviting partners.";
  if (lower.includes("decision")) return "Mesh needs a signed decision record or completed run decision before this can be called ready.";
  if (lower.includes("export")) return "Create or upload the proof/export packet Mesh expects for handoff.";
  if (lower.includes("readiness")) return "Resolve readiness blockers in the Mesh control-plane snapshot.";
  return "Open the proof view for the exact Mesh evidence record and remediation path.";
}

function PraxisHomeModule({ model, setView }: { model: PraxisProductModel; setView: (view: ViewKey) => void }) {
  return (
    <section className="praxis-home" aria-label="Praxis MCP generator">
      <div className="praxis-home-copy">
        <span>Praxis Agent-Tool Mesh</span>
        <h2>Generate MCP tools, certify scopes, then expose only the dry-run pilot runtime Mesh admits.</h2>
        <p>OpenAPI, SOP, traffic refs, Akto evidence, ACP supervision, certification, revocation, and proof packet are bound into one product path.</p>
      </div>
      <div className="praxis-home-grid">
        <PraxisStat label="Live runs" value={model.runCount} detail={model.requestId ? `latest ${model.requestId}` : "team-scoped runtime state"} />
        <PraxisStat label="Proof packet" value={model.proofStatus} detail={model.status} />
        <PraxisStat label="Sources" value={model.sourcePackets} detail="redacted source packets" />
        <PraxisStat label="Tools" value={model.toolCandidates} detail={`${model.certifiedTools} certified / ${model.deniedTools} denied`} />
        <PraxisStat label="Runtime" value={model.runtimeStatus} detail={model.managedRuntime ? "managed runtime deployed" : "dry-run only"} />
      </div>
      <div className="praxis-home-actions">
        <button type="button" onClick={() => setView("praxis")}>Open Praxis <ArrowRight size={15} /></button>
        <small>{model.mcpEndpoint}</small>
      </div>
    </section>
  );
}

function PraxisStat({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="praxis-stat">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function PraxisFileInput({
  label,
  accept,
  file,
  onFile,
}: {
  label: string;
  accept: string;
  file: File | null;
  onFile: (file: File | null) => void;
}) {
  return (
    <label className="praxis-file-input">
      <span>{label}</span>
      <input
        type="file"
        accept={accept}
        onChange={(event) => onFile(event.currentTarget.files?.[0] ?? null)}
      />
      <small>{file?.name || "No file selected"}</small>
    </label>
  );
}

async function readPraxisSources(files: Record<string, File | null>): Promise<PraxisSourceInput[]> {
  const sources: PraxisSourceInput[] = [];
  for (const [sourceType, file] of Object.entries(files)) {
    if (!file) continue;
    const content = await file.text();
    rejectClientRawSecret(content, file.name);
    sources.push({ source_type: praxisSourceType(sourceType), filename: file.name, content });
  }
  return sources;
}

function praxisSourceType(sourceType: string): PraxisSourceInput["source_type"] {
  if (sourceType === "postman") return "postman_json";
  if (sourceType === "traffic_ref") return "redacted_traffic_ref";
  return sourceType;
}

function rejectClientRawSecret(content: string, filename: string) {
  const secretPattern = /\b(?:api[_-]?key|authorization|bearer|secret|token|password)\b\s*[:=]\s*["']?[A-Za-z0-9._~+/-]{16,}/i;
  if (secretPattern.test(content)) {
    throw new Error(`Raw secret-like value rejected in ${filename}. Upload a redacted source ref.`);
  }
}

function PraxisView({
  dashboard,
  setView,
  onDashboardRefresh,
}: {
  dashboard: DashboardPayload;
  setView: (view: ViewKey) => void;
  onDashboardRefresh: () => Promise<void>;
}) {
  const model = buildPraxisProductModel(dashboard);
  const praxis = dashboard.mesh.praxis || {};
  const sourcePackets = praxis.source_bundle?.packets || [];
  const securityFindings = praxis.security_evidence?.findings || [];
  const teamId = dashboard.scope.kind === "team" ? dashboard.scope.team?.id ?? null : null;
  const [sourceFiles, setSourceFiles] = useState<Record<string, File | null>>({});
  const [aktoFile, setAktoFile] = useState<File | null>(null);
  const [lastRecord, setLastRecord] = useState<Record<string, any> | null>(null);
  const [message, setMessage] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const requestId = String(lastRecord?.request_id || model.requestId || "");
  const callableToolId = model.tools.find((tool) => tool.value === "read only")?.id || model.tools[0]?.id || "";

  function setSourceFile(sourceType: string, file: File | null) {
    setSourceFiles({ ...sourceFiles, [sourceType]: file });
  }

  async function withPraxisAction(action: string, fn: () => Promise<Record<string, any> | void>) {
    setBusyAction(action);
    setMessage("");
    try {
      const result = await fn();
      if (result && result.request_id) setLastRecord(result);
      await onDashboardRefresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : `${action} failed`);
    } finally {
      setBusyAction("");
    }
  }

  async function generateContract() {
    await withPraxisAction("generate", async () => {
      const sources = await readPraxisSources(sourceFiles);
      if (!sources.length) throw new Error("Upload at least one Praxis source before generation.");
      const record = await productApi.createPraxisGenerationRequest({ team_id: teamId, sources });
      setMessage(`Generated Praxis request ${record.request_id}.`);
      return record;
    });
  }

  async function importAktoEvidence() {
    await withPraxisAction("akto", async () => {
      if (!requestId) throw new Error("Generate a Praxis contract before importing Akto evidence.");
      if (!aktoFile) throw new Error("Upload an Akto evidence file before import.");
      const aktoResult = JSON.parse(await aktoFile.text());
      const record = await productApi.importPraxisAktoEvidence(requestId, { team_id: teamId, akto_result: aktoResult });
      setMessage(`Imported Akto evidence for ${record.request_id}.`);
      return record;
    });
  }

  async function buildCertification() {
    await withPraxisAction("certify", async () => {
      if (!requestId) throw new Error("Generate a Praxis contract before certification.");
      const record = await productApi.buildPraxisCertificationBinding(requestId, { team_id: teamId });
      setMessage(`Built certification binding for ${record.request_id}.`);
      return record;
    });
  }

  async function startDryRun() {
    await withPraxisAction("start", async () => {
      if (!requestId) throw new Error("Build certification before starting dry-run.");
      const record = await productApi.startPraxisDryRunEndpoint(requestId, { team_id: teamId });
      setMessage(`Started dry-run MCP endpoint for ${record.request_id}.`);
      return record;
    });
  }

  async function callReadOnlyTool() {
    await withPraxisAction("call", async () => {
      if (!requestId) throw new Error("Start dry-run before calling a tool.");
      const list = await productApi.praxisMcp(requestId, { jsonrpc: "2.0", id: "tools-list", method: "tools/list", team_id: teamId });
      const toolId = String(list.result?.tools?.[0]?.name || callableToolId);
      if (!toolId) throw new Error("No certified read-only tool is available for dry-run.");
      await productApi.praxisMcp(requestId, {
        jsonrpc: "2.0",
        id: "tool-call",
        method: "tools/call",
        params: { name: toolId, arguments: { dry_run_reason: "product_e2e_validation" } },
        team_id: teamId,
      });
      const record = await productApi.exportPraxisP10Proof(requestId, teamId);
      setMessage(`MCP tool call audited. P10 proof is ${record.status}.`);
    });
  }

  async function exportP10Proof() {
    await withPraxisAction("p10", async () => {
      if (!requestId) throw new Error("Generate a Praxis request before exporting P10 proof.");
      const packet = await productApi.exportPraxisP10Proof(requestId, teamId);
      setMessage(`Exported P10 proof packet ${packet.packet_id}: ${packet.status}.`);
    });
  }

  async function revokeConnector() {
    await withPraxisAction("revoke", async () => {
      if (!requestId) throw new Error("Generate a Praxis request before revocation.");
      const record = await productApi.revokePraxisGeneratedConnector(requestId, { team_id: teamId, reason: "product_operator_revocation" });
      setMessage(`Revoked generated connector for ${record.request_id}.`);
      return record;
    });
  }

  return (
    <div className="content-stack">
      <Toolbar
        title="Praxis MCP Generator"
        detail="Generate candidate MCP tools from source packets, import Akto evidence, bind Mesh certification, and keep pilot runtime dry-run until production proof exists."
        action="Back Home"
        onAction={() => setView("home")}
      />
      <section className="praxis-import-panel" aria-label="Praxis source import">
        <div className="panel-heading">
          <div>
            <span>Product source intake</span>
            <h3>Upload redacted API, workflow, SOP, and traffic sources</h3>
            <p>Files are sent to Mesh for secret rejection and persisted as redacted source refs under `praxis.managed-dry-run-runtime.v1`.</p>
          </div>
          <button type="button" onClick={generateContract} disabled={busyAction === "generate"}>
            {busyAction === "generate" ? "Generating" : "Generate Praxis contract"}
          </button>
        </div>
        <div className="praxis-import-grid">
          <PraxisFileInput label="OpenAPI file" accept=".json,.yaml,.yml" file={sourceFiles.openapi || null} onFile={(file) => setSourceFile("openapi", file)} />
          <PraxisFileInput label="Postman file" accept=".json" file={sourceFiles.postman || null} onFile={(file) => setSourceFile("postman", file)} />
          <PraxisFileInput label="SOP Markdown file" accept=".md,.markdown,.txt" file={sourceFiles.sop_markdown || null} onFile={(file) => setSourceFile("sop_markdown", file)} />
          <PraxisFileInput label="Traffic refs file" accept=".json,.har" file={sourceFiles.traffic_ref || null} onFile={(file) => setSourceFile("traffic_ref", file)} />
          <PraxisFileInput label="Akto evidence file" accept=".json" file={aktoFile} onFile={setAktoFile} />
        </div>
        <PraxisStepper
          steps={[
            { label: "Upload sources", detail: "Redacted source files selected", complete: Object.values(sourceFiles).some(Boolean), action: "Select files" },
            { label: "Generate tools", detail: requestId || "Create candidate MCP contract", complete: Boolean(requestId), action: busyAction === "generate" ? "Generating" : "Generate", onAction: generateContract, disabled: busyAction === "generate" },
            { label: "Import security evidence", detail: securityFindings.length ? `${securityFindings.length} finding(s) imported` : "Attach Akto result", complete: securityFindings.length > 0, action: busyAction === "akto" ? "Importing" : "Import", onAction: importAktoEvidence, disabled: busyAction === "akto" || !requestId },
            { label: "Certify", detail: `${model.certifiedTools} read-only / ${model.deniedTools} denied`, complete: Number(model.certifiedTools) > 0 || Number(model.deniedTools) > 0, action: busyAction === "certify" ? "Certifying" : "Certify", onAction: buildCertification, disabled: busyAction === "certify" || !requestId },
            { label: "Start dry run", detail: model.runtimeStatus, complete: model.runtimeStatus.includes("ready") || model.managedRuntime, action: busyAction === "start" ? "Starting" : "Start dry run", onAction: startDryRun, disabled: busyAction === "start" || !requestId },
            { label: "Export proof", detail: model.proofStatus, complete: model.proofStatus === "complete", action: busyAction === "p10" ? "Exporting" : "Export", onAction: exportP10Proof, disabled: busyAction === "p10" || !requestId },
          ]}
          secondaryActions={[
            { label: "Call read-only tool", onAction: callReadOnlyTool, disabled: busyAction === "call" || !requestId },
            { label: "Revoke connector", onAction: revokeConnector, disabled: busyAction === "revoke" || !requestId },
          ]}
        />
        {message ? <div className={message.toLowerCase().includes("failed") || message.toLowerCase().includes("required") || message.toLowerCase().includes("upload") ? "auth-error" : "product-alert success"}>{message}</div> : null}
      </section>
      <section className="praxis-workbench" aria-label="Praxis generator workbench">
        <div className="praxis-stage primary">
          <span>State slice</span>
          <h2>praxis.managed-dry-run-runtime.v1</h2>
          <p>Current runtime posture: {model.runtimeStatus}. Managed runtime deployed: {model.managedRuntime ? "yes" : "no"}.</p>
          <div className="praxis-stage-actions">
            {model.controls.map((control) => (
              <button key={control.id} type="button" disabled={control.state === "blocked"} title={control.detail}>
                {control.label}
                <small>{control.requiresMeshApproval ? "Mesh approval" : control.state}</small>
              </button>
            ))}
          </div>
        </div>
        <div className="praxis-stage">
          <span>Proof binding</span>
          <strong>{model.proofStatus}</strong>
          <small>{model.blockerCount} blocker(s) remain on denied or unadmitted scopes</small>
        </div>
        <div className="praxis-stage">
          <span>Dry-run endpoint</span>
          <strong>{model.mcpEndpoint}</strong>
          <small>Agents can only use certified tool scopes.</small>
        </div>
      </section>
      <section className="praxis-lanes" aria-label="Praxis product lanes">
        <PraxisLane title="Source intake" icon={Database}>
          {sourcePackets.length ? sourcePackets.map((packet: any) => (
            <div className="praxis-list-row" key={packet.packet_id}>
              <span>{packet.source_type}</span>
              <strong>{packet.source_ref}</strong>
              <small>{packet.raw_credentials_present ? "raw credential blocker" : "redacted"}</small>
            </div>
          )) : <EmptyInline text="No Praxis source bundle returned by Mesh." />}
        </PraxisLane>
        <PraxisLane title="Generated tools" icon={Boxes}>
          {model.tools.map((tool) => (
            <div className={`praxis-tool ${tool.tone}`} key={tool.id}>
              <span>{tool.method} {tool.path}</span>
              <strong>{tool.label}</strong>
              <small>{tool.value} · {tool.detail}</small>
            </div>
          ))}
        </PraxisLane>
        <PraxisLane title="Akto evidence" icon={ShieldCheck}>
          {securityFindings.length ? securityFindings.map((finding: any) => (
            <div className="praxis-list-row" key={finding.finding_id}>
              <span>{finding.severity} / {finding.status}</span>
              <strong>{finding.summary}</strong>
              <small>{finding.evidence_ref}</small>
            </div>
          )) : <EmptyInline text="No Akto findings in the dashboard read model." />}
        </PraxisLane>
      </section>
    </div>
  );
}

function PraxisStepper({
  steps,
  secondaryActions,
}: {
  steps: { label: string; detail: string; complete: boolean; action: string; onAction?: () => void; disabled?: boolean }[];
  secondaryActions: { label: string; onAction: () => void; disabled?: boolean }[];
}) {
  return (
    <div className="praxis-stepper" aria-label="Praxis workflow">
      {steps.map((step, index) => (
        <div className={step.complete ? "praxis-step complete" : "praxis-step"} key={step.label}>
          <div className="step-index">{step.complete ? <CheckCircle2 size={16} /> : index + 1}</div>
          <div>
            <strong>{step.label}</strong>
            <small>{step.detail}</small>
          </div>
          {step.onAction ? <button type="button" onClick={step.onAction} disabled={step.disabled}>{step.action}</button> : <span>{step.action}</span>}
        </div>
      ))}
      <div className="praxis-step-secondary">
        {secondaryActions.map((action) => (
          <button key={action.label} type="button" onClick={action.onAction} disabled={action.disabled}>{action.label}</button>
        ))}
      </div>
    </div>
  );
}

function PraxisLane({ title, icon: Icon, children }: { title: string; icon: any; children: ReactNode }) {
  return (
    <section className="praxis-lane">
      <div className="panel-title"><Icon size={15} /><span>{title}</span></div>
      {children}
    </section>
  );
}

function OperatorCommandCenter({ dashboard, setView }: { dashboard: DashboardPayload; setView: (view: ViewKey) => void }) {
  const model = buildDashboardControlModel(dashboard);
  return (
    <section className="operator-console" aria-label="Mesh operator control summary">
      <div className="console-heading">
        <div>
          <span>Mesh Control Summary</span>
          <h2>Runtime, evidence, policy, and connectors in one dashboard.</h2>
        </div>
        <button type="button" onClick={() => setView("evaluations")}>
          Review runs <ArrowRight size={15} />
        </button>
      </div>
      <div className="console-metrics">
        <ConsoleMetric icon={Zap} label="Readiness" value={model.readiness.value} detail={model.readiness.detail} tone={model.readiness.tone} />
        <ConsoleMetric icon={Play} label="Run admission" value={model.runs.value} detail={model.runs.detail} tone={model.runs.tone} />
        <ConsoleMetric icon={Lock} label="Approvals" value={model.approvals.value} detail={model.approvals.detail} tone={model.approvals.tone} />
        <ConsoleMetric icon={ShieldCheck} label="Evidence" value={model.evidence.value} detail={model.evidence.detail} tone={model.evidence.tone} />
      </div>
      <div className="console-panels">
        <section className="console-panel">
          <div className="panel-title"><Activity size={15} /><span>Recent runs</span></div>
          {model.recentRuns.length ? model.recentRuns.map((run) => (
            <button className="console-row" key={run.id} type="button" onClick={() => setView("evaluations")}>
              <span>{run.label}</span>
              <strong>{run.value}</strong>
              <small>{run.detail}</small>
            </button>
          )) : <EmptyInline text="No run summaries in the dashboard read model." />}
        </section>
        <section className="console-panel">
          <div className="panel-title"><Boxes size={15} /><span>Connector posture</span></div>
          {model.connectors.length ? model.connectors.map((connector) => (
            <button className="console-row" key={connector.id} type="button" onClick={() => setView("environments")}>
              <span>{connector.label}</span>
              <strong>{connector.value}</strong>
              <small>{connector.detail}</small>
            </button>
          )) : <EmptyInline text="No connector certification records returned." />}
        </section>
        <section className="console-panel">
          <div className="panel-title"><Network size={15} /><span>Topology and memory</span></div>
          {model.systemRows.map((row) => (
            <button className="console-row" key={row.id} type="button" onClick={() => setView(row.view)}>
              <span>{row.label}</span>
              <strong>{row.value}</strong>
              <small>{row.detail}</small>
            </button>
          ))}
        </section>
      </div>
    </section>
  );
}

function ConsoleMetric({
  icon: Icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: any;
  label: string;
  value: string;
  detail: string;
  tone: ConsoleTone;
}) {
  return (
    <div className={`console-metric ${tone}`}>
      <Icon size={16} />
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function EmptyInline({ text }: { text: string }) {
  return <div className="empty-inline"><AlertTriangle size={15} /> {text}</div>;
}

export function dashboardSectionState(payload: any): { state: DashboardSurfaceState; reason: string } {
  if (!payload || (typeof payload === "object" && Object.keys(payload).length === 0)) {
    return { state: "empty", reason: "No payload returned by the dashboard read model." };
  }
  if (payload.error || payload.status === "unavailable") {
    return { state: "degraded", reason: String(payload.error || payload.reason || "Dashboard section is unavailable.") };
  }
  const status = String(payload.status || payload.state || payload.decision || "").toLowerCase();
  if (payload.ready === false || status.includes("blocked") || status === "denied") {
    return { state: "blocked", reason: String(payload.reason || payload.error || "Mesh reports this section blocked.") };
  }
  const arrayKeys = ["runs", "items", "connectors", "entries"];
  for (const key of arrayKeys) {
    if (Array.isArray(payload[key]) && payload[key].length === 0) {
      return { state: "empty", reason: `${key} returned no records.` };
    }
  }
  return { state: "ready", reason: status || "Dashboard section returned a usable payload." };
}

export function dashboardLoadSurfaceState(state: LoadState<DashboardPayload>): DashboardSurfaceState {
  if (state.state === "ready") return "ready";
  if (state.state === "unauthorized") return "unauthorized";
  if (state.state === "backend-unavailable") return "backend-unavailable";
  if (state.state === "forbidden") return "blocked";
  if (state.state === "error") return "degraded";
  return "empty";
}

export function buildDashboardTiles(dashboard: DashboardPayload): DashboardTileModel[] {
  const mesh = dashboard.mesh;
  const readiness = mesh.readiness || {};
  const runs = mesh.runs || { runs: [] };
  const approvals = mesh.approvals || { items: [] };
  const connectors = mesh.connectors || {};
  const connectorRecords = connectors.connectors || connectors.connector_certification || {};
  const praxis = buildPraxisProductModel(dashboard);
  const consolePayload = {
    status: "ready",
    workflows: CONSOLE_WORKFLOW_MATRIX.map((workflow) => workflow.consoleView),
  };
  const rawTiles = [
    {
      title: "Control console",
      detail: `${CONSOLE_WORKFLOW_MATRIX.length} migrated workflows`,
      icon: Cpu,
      view: "console" as ViewKey,
      apiSection: "meshapp.frontend.control_plane_api_client.v1",
      payload: consolePayload,
    },
    {
      title: "Praxis MCP generator",
      detail: `${praxis.certifiedTools} read-only / ${praxis.deniedTools} denied`,
      icon: Sparkles,
      view: "praxis" as ViewKey,
      apiSection: "mesh.praxis",
      payload: mesh.praxis,
    },
    {
      title: "Runtime readiness",
      detail: readModelSummary(readiness, "Read-only: readiness status unavailable"),
      icon: Zap,
      view: "gpu" as ViewKey,
      apiSection: "mesh.readiness",
      payload: readiness,
    },
    {
      title: "Run admission",
      detail: `${Array.isArray(runs.runs) ? runs.runs.length : 0} recent runs`,
      icon: Play,
      view: "evaluations" as ViewKey,
      apiSection: "mesh.runs.runs",
      payload: runs,
    },
    {
      title: "Connector status",
      detail: `${Object.keys(connectorRecords).length} connectors tracked`,
      icon: Boxes,
      view: "environments" as ViewKey,
      apiSection: "mesh.connectors",
      payload: connectors,
    },
    {
      title: "Orchestration topology",
      detail: readModelSummary(readiness.orchestration_topology || mesh.graph, "Read-only: topology profile unavailable"),
      icon: Network,
      view: "training" as ViewKey,
      apiSection: "mesh.readiness.orchestration_topology || mesh.graph",
      payload: readiness.orchestration_topology || mesh.graph,
    },
    {
      title: "Evidence packets",
      detail: readModelSummary(mesh.pilot_go_no_go, "Read-only: pilot packet unavailable"),
      icon: ShieldCheck,
      view: "evaluations" as ViewKey,
      apiSection: "mesh.pilot_go_no_go",
      payload: mesh.pilot_go_no_go,
    },
    {
      title: "Policy approvals",
      detail: `${Array.isArray(approvals.items) ? approvals.items.length : 0} pending`,
      icon: Lock,
      view: "evaluations" as ViewKey,
      apiSection: "mesh.approvals.items",
      payload: approvals,
    },
    {
      title: "Memory projection",
      detail: readModelSummary(mesh.memory?.graph, "Read-only: memory graph unavailable"),
      icon: Database,
      view: "inference" as ViewKey,
      apiSection: "mesh.memory.graph",
      payload: mesh.memory?.graph,
    },
    {
      title: "Settings parity",
      detail: "UI and CLI share validation",
      icon: Settings,
      view: "settings" as ViewKey,
      apiSection: "settings + settings_schema",
      payload: { settings: dashboard.settings, settings_schema: dashboard.settings_schema },
    },
    {
      title: "Trust ladder",
      detail: `${Array.isArray(mesh.trust_ladder?.entries) ? mesh.trust_ladder.entries.length : 0} trust entries`,
      icon: ShieldCheck,
      view: "instances" as ViewKey,
      apiSection: "mesh.trust_ladder.entries",
      payload: mesh.trust_ladder,
    },
    {
      title: "Watchers",
      detail: readModelSummary(mesh.watchers, "Read-only: watcher state unavailable"),
      icon: Activity,
      view: "gpu" as ViewKey,
      apiSection: "mesh.watchers",
      payload: mesh.watchers,
    },
  ];
  return rawTiles.map((tile) => {
    const state = dashboardSectionState(tile.payload);
    return { ...tile, state: state.state, stateReason: state.reason };
  });
}

export function buildDashboardControlModel(dashboard: DashboardPayload): DashboardControlModel {
  const mesh = dashboard.mesh || {};
  const readiness = mesh.readiness || {};
  const runs = Array.isArray(mesh.runs?.runs) ? mesh.runs.runs : [];
  const approvals = Array.isArray(mesh.approvals?.items) ? mesh.approvals.items : [];
  const connectors = mesh.connectors?.connectors || mesh.connectors?.connector_certification || {};
  const connectorEntries = Object.entries(connectors) as Array<[string, any]>;
  const pilot = mesh.pilot_go_no_go || {};
  const missingEvidence = Array.isArray(pilot.missing_evidence) ? pilot.missing_evidence.length : 0;
  const readinessStatus = readiness.status || (readiness.ready === true ? "ready" : readiness.ready === false ? "blocked" : "unknown");
  const activeRuns = runs.filter((run: any) => !["completed", "failed", "cancelled"].includes(String(run.status || "")));
  const connectorReady = connectorEntries.filter(([, value]) => String(value?.state || value?.status || "").includes("ready")).length;
  const killSwitch = mesh.kill_switch || {};
  const memoryGraph = mesh.memory?.graph || {};
  const topology = readiness.orchestration_topology || mesh.graph || {};

  return {
    readiness: {
      value: humanize(String(readinessStatus)),
      detail: readiness.blockers?.length ? `${readiness.blockers.length} blocker(s)` : readiness.detail || "Readiness snapshot from Mesh",
      tone: readinessStatus === "ready" || readiness.ready === true ? "good" as const : "warn" as const,
    },
    runs: {
      value: String(activeRuns.length),
      detail: runs[0]?.scenario_key || `${runs.length} total run summary record(s)`,
      tone: activeRuns.length ? "warn" as const : "neutral" as const,
    },
    approvals: {
      value: String(approvals.length),
      detail: approvals[0]?.blockers?.[0] || approvals[0]?.decision_type || "No pending approval queue item",
      tone: approvals.length ? "warn" as const : "good" as const,
    },
    evidence: {
      value: missingEvidence ? `${missingEvidence} missing` : humanize(String(pilot.status || pilot.final_release_decision || "read-only")),
      detail: pilot.evidence_packet_id || pilot.reason || "Pilot packet and evidence posture from Mesh",
      tone: missingEvidence ? "warn" as const : "neutral" as const,
    },
    recentRuns: runs.slice(0, 4).map((run: any) => ({
      id: String(run.run_id || run.id || run.scenario_key),
      label: String(run.scenario_key || "custom"),
      value: humanize(String(run.status || run.stage || "unknown")),
      detail: String(run.run_id || "run id unavailable"),
    })),
    connectors: connectorEntries.slice(0, 5).map(([id, value]) => ({
      id,
      label: String(value?.name || id),
      value: humanize(String(value?.state || value?.status || "unknown")),
      detail: String(value?.authority_posture || value?.detail || value?.credential_boundary?.credential_source || "Mesh connector certification"),
    })),
    systemRows: [
      {
        id: "connector-total",
        label: "Connector matrix",
        value: `${connectorReady}/${connectorEntries.length}`,
        detail: "Ready connectors over tracked connectors",
        view: "environments" as ViewKey,
      },
      {
        id: "topology",
        label: "Orchestration topology",
        value: humanize(String(topology.status || topology.state || topology.mode || "read-only")),
        detail: String(topology.detail || topology.degraded_reason || "Topology profile remains Mesh-owned"),
        view: "training" as ViewKey,
      },
      {
        id: "memory",
        label: "Memory projection",
        value: humanize(String(memoryGraph.status || memoryGraph.state || "read-only")),
        detail: String(memoryGraph.detail || memoryGraph.reason || "Memory graph summary from Mesh read model"),
        view: "inference" as ViewKey,
      },
      {
        id: "kill-switch",
        label: "Kill switch",
        value: humanize(String(killSwitch.status || killSwitch.state || (killSwitch.enabled === true ? "enabled" : "available"))),
        detail: String(killSwitch.reason || killSwitch.detail || "Emergency controls remain Mesh-owned"),
        view: "clusters" as ViewKey,
      },
    ],
  };
}

export function buildPraxisProductModel(dashboard: DashboardPayload): PraxisProductModel {
  const praxis = dashboard.mesh?.praxis || {};
  const summary = praxis.summary || {};
  const proof = praxis.p10_proof_packet || praxis.proof_packet || {};
  const readiness = proof.mcp_readiness || {};
  const runtime = praxis.pilot_runtime || {};
  const tools = Array.isArray(praxis.generated_contract?.tools) ? praxis.generated_contract.tools : [];
  const controls = Array.isArray(runtime.controls) ? runtime.controls : [];
  const blockers = Array.isArray(readiness.readiness_blockers) ? readiness.readiness_blockers : [];
  const runs = Array.isArray(praxis.runs) ? praxis.runs : [];
  const latestRun = runs[0] || {};
  return {
    requestId: String(latestRun.request_id || proof.request_id || ""),
    runCount: String(summary.runs ?? runs.length ?? 0),
    status: humanize(String(praxis.status || "unavailable")),
    proofStatus: humanize(String(proof.status || "missing")),
    sourcePackets: String(summary.source_packets ?? proof.source_bundle?.source_packet_count ?? 0),
    toolCandidates: String(summary.tool_candidates ?? proof.generated_contract?.tool_candidate_count ?? tools.length),
    certifiedTools: String(summary.certified_read_only_tools ?? readiness.certified_tool_ids?.length ?? 0),
    deniedTools: String(summary.denied_tools ?? readiness.denied_tool_ids?.length ?? 0),
    mcpEndpoint: String(runtime.mcp_endpoint_ref || "mcp-dry-run://unavailable"),
    runtimeStatus: humanize(String(runtime.status || readiness.status || "blocked")),
    managedRuntime: Boolean(runtime.managed_runtime_deployed),
    blockerCount: blockers.length,
    tools: tools.map((tool: any) => {
      const result = String(tool.certification_result || tool.approval_posture || "candidate");
      return {
        id: String(tool.tool_id || tool.name),
        label: String(tool.name || tool.tool_id),
        value: humanize(result),
        detail: tool.readiness_blockers?.length ? `${tool.readiness_blockers.length} blocker(s)` : String(tool.mutation_class || "unknown"),
        method: String(tool.method || "GET"),
        path: String(tool.path || "/"),
        tone: result === "read_only" || result === "staging_ready" ? "good" as const : result === "denied" ? "warn" as const : "neutral" as const,
      };
    }),
    controls: controls.map((control: any) => ({
      id: String(control.control_id || control.label),
      label: String(control.label || control.control_id),
      value: humanize(String(control.state || "unknown")),
      detail: String(control.reason || (control.requires_mesh_approval ? "Requires Mesh approval" : "Dry-run control")),
      state: String(control.state || "unknown"),
      requiresMeshApproval: Boolean(control.requires_mesh_approval),
    })),
  };
}

export function settingsParityRows(dashboard: DashboardPayload): SettingsParityRow[] {
  const scope = dashboard.scope.team ? `team:${dashboard.scope.team.id}` : `user:${dashboard.session.user.id}`;
  const operatorId = dashboard.session.user.email || dashboard.session.user.id;
  const mutableRows = Object.entries(dashboard.settings_schema).map(([key, schema]) => ({
    key,
    label: titleize(key),
    value: dashboard.settings[key] ?? schema.default,
    description: schema.description,
    mutable: true,
    values: schema.values,
    uiMutationPath: "/api/operator/settings",
    cliPath: `python scripts/operator_config.py set --scope ${scope} --operator-id ${operatorId} --reason "<audit reason>" ${key}=...`,
  }));
  const readonlyRows: SettingsParityRow[] = [
    {
      key: "api_base_url",
      label: "API base URL",
      value: "Browser runtime target",
      description: "Read-only in UI. Change via frontend environment or deployment config.",
      mutable: false,
      readOnlyReason: "Product runtime target is deployment-owned, not operator settings state.",
    },
    {
      key: "build_commit",
      label: "Build commit",
      value: dashboard.mesh.health?.commit || "unknown",
      description: "Read-only in UI. Change by building and deploying a new artifact.",
      mutable: false,
      readOnlyReason: "Build provenance is release metadata, not mutable operator preference.",
    },
    {
      key: "state_backend",
      label: "State backend",
      value: dashboard.mesh.readiness?.state_backend || "RuntimeConfig-owned",
      description: "Read-only in UI. Change via environment or deployment config.",
      mutable: false,
      readOnlyReason: "Runtime persistence backend is owned by Mesh deployment configuration.",
    },
    {
      key: "captcha_provider",
      label: "Captcha provider",
      value: "Auth config owned by environment",
      description: "Read-only in UI. Change through ignored env files or deployment secret manager.",
      mutable: false,
      readOnlyReason: "Auth provider secrets must not be written through the product dashboard.",
    },
  ];
  return [...mutableRows, ...readonlyRows];
}

function EnvironmentView({ dashboard, setView }: { dashboard: DashboardPayload; setView: (view: ViewKey) => void }) {
  const connectorPosture = operatorWorkflowPosture("connector");
  const connectors = dashboard.mesh.connectors?.connectors || dashboard.mesh.connectors?.connector_certification || {};
  const [query, setQuery] = useState("");
  const [stateFilter, setStateFilter] = useState("all");
  const [domainFilter, setDomainFilter] = useState("all");
  const cards = Object.entries(connectors).map(([id, value]: [string, any]) => ({
    id,
    owner: "Mesh",
    blockers: Array.isArray(value.blockers) ? value.blockers : [],
    state: String(value.state || value.status || "unknown"),
    domain: String(value.domain || value.credential_boundary?.credential_source || "Deployment"),
    title: value.name || id,
    detail: value.detail || value.authority_posture || "Connector certification state",
    tags: [value.state || "unknown", value.credential_boundary?.credential_source || "config"],
    version: value.schema_version || "v1",
  }));
  const stateOptions = ["all", ...Array.from(new Set(cards.map((card) => card.state))).sort()];
  const domainOptions = ["all", ...Array.from(new Set(cards.map((card) => card.domain))).sort()];
  const loweredQuery = query.trim().toLowerCase();
  const filteredCards = cards.filter((card) => {
    const matchesQuery = !loweredQuery || [card.id, card.title, card.detail, card.state, card.domain, ...card.tags].join(" ").toLowerCase().includes(loweredQuery);
    const matchesState = stateFilter === "all" || card.state === stateFilter;
    const matchesDomain = domainFilter === "all" || card.domain === domainFilter;
    return matchesQuery && matchesState && matchesDomain;
  });
  const grouped = groupConnectorCards(filteredCards);

  return (
    <div className="content-stack">
      <Toolbar
        title="Connectors"
        detail={connectorPosture.reason}
        action="Review Dashboard"
        onAction={() => setView("home")}
      />
      <SearchBar value={query} onChange={setQuery} placeholder="Filter connectors by name, status, domain, blocker..." />
      <div className="filter-row">
        <label>
          State
          <select value={stateFilter} onChange={(event) => setStateFilter(event.target.value)}>
            {stateOptions.map((state) => <option key={state} value={state}>{humanize(state)}</option>)}
          </select>
        </label>
        <label>
          Domain
          <select value={domainFilter} onChange={(event) => setDomainFilter(event.target.value)}>
            {domainOptions.map((domain) => <option key={domain} value={domain}>{humanize(domain)}</option>)}
          </select>
        </label>
      </div>
      <div className="connector-legend">
        {["ready", "staging-ready", "read-only", "config-only", "blocked", "stub", "disconnected"].map((state) => (
          <span key={state}><CircleDot size={10} /> {humanize(state)}</span>
        ))}
      </div>
      {filteredCards.length ? <CardRows sections={grouped} /> : <EmptyInline text="No connectors match the current filters." />}
    </div>
  );
}

function groupConnectorCards(cards: Array<{ id: string; state: string; domain: string; [key: string]: any }>): { title: string; count: number; cards: any[] }[] {
  const groups = new Map<string, any[]>();
  for (const card of cards) {
    const key = `${humanize(card.state)} / ${card.domain}`;
    groups.set(key, [...(groups.get(key) || []), card]);
  }
  return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b)).map(([title, groupCards]) => ({ title, count: groupCards.length, cards: groupCards }));
}

function EvaluationsView({
  dashboard,
  setView,
  onDashboardRefresh,
}: {
  dashboard: DashboardPayload;
  setView: (view: ViewKey) => void;
  onDashboardRefresh: () => Promise<void>;
}) {
  const launchPosture = operatorWorkflowPosture("launch");
  const runs = dashboard.mesh.runs?.runs || [];
  const [query, setQuery] = useState("");
  const active = runs.filter((run: any) => !["completed", "failed", "cancelled"].includes(run.status)).length;
  const failed = runs.filter((run: any) => run.status === "failed").length;
  const traceSteps = evidenceTraceSteps(dashboard);
  const loweredQuery = query.trim().toLowerCase();
  const filteredRuns = runs.filter((run: any) => {
    if (!loweredQuery) return true;
    return [
      run.run_id,
      run.id,
      run.scenario_key,
      run.status,
      run.stage,
      run.created_at,
      run.operator_id,
    ].map((value) => String(value || "")).join(" ").toLowerCase().includes(loweredQuery);
  });
  return (
    <div className="content-stack">
      <Toolbar
        title="Evaluations"
        detail={launchPosture.reason}
        action="Review Dashboard"
        onAction={() => setView("home")}
      />
      <LaunchRunPanel dashboard={dashboard} onDashboardRefresh={onDashboardRefresh} />
      <ApprovalQueuePanel dashboard={dashboard} onDashboardRefresh={onDashboardRefresh} />
      <div className="stat-row">
        <Stat label="Active evals" value={String(active)} detail="Pending, running, or processing" />
        <Stat label="Failed evals" value={String(failed)} detail="Failed or timed out evaluations" />
        <Stat label="Total evals" value={String(runs.length)} detail="All evaluations in this account" />
      </div>
      <TraceRail steps={traceSteps} />
      <ProofDrilldownPanel dashboard={dashboard} />
      <SearchBar value={query} onChange={setQuery} placeholder="Search by run, scenario, status, operator..." />
      <div className="data-table">
        <div className="table-head"><span>Name</span><span>Scenario</span><span>Status</span><span>Created</span><span>Created by</span></div>
        {filteredRuns.length ? filteredRuns.map((run: any) => (
          <div className="table-row" key={run.run_id}>
            <span>{run.run_id}</span><span>{run.scenario_key || "custom"}</span><span>{run.status}</span><span>{run.created_at}</span><span>{run.operator_id || "Mesh"}</span>
          </div>
        )) : runs.length ? (
          <div className="empty-eval"><Search size={24} /><strong>No matching evaluations</strong><p>Adjust the search terms to inspect run state returned by Mesh.</p></div>
        ) : (
          <div className="empty-eval"><BarChart3 size={24} /><strong>Run your first evaluation</strong><p>Use the launch form above. Mesh owns admission and policy.</p></div>
        )}
      </div>
    </div>
  );
}

function ApprovalQueuePanel({ dashboard, onDashboardRefresh }: { dashboard: DashboardPayload; onDashboardRefresh: () => Promise<void> }) {
  const queue = dashboard.mesh.approvals || {};
  const items = Array.isArray(queue.items) ? queue.items : [];
  const [reasonByRun, setReasonByRun] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [busyCommand, setBusyCommand] = useState("");

  async function runCommand(runId: string, command: ApprovalCommand) {
    const reason = (reasonByRun[runId] || "").trim();
    if (command !== "cancel" && !reason) {
      setMessage("Approval action reason is required before product steering calls Mesh.");
      return;
    }
    setBusyCommand(`${runId}:${command}`);
    setMessage("");
    try {
      await productApi.steerRun(runId, { command, reason });
      await onDashboardRefresh();
      setMessage(`Mesh accepted ${command} for ${runId}.`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Approval command failed");
    } finally {
      setBusyCommand("");
    }
  }

  return (
    <section className="approval-panel" aria-label="Approval queue">
      <div className="panel-heading">
        <div>
          <span>Approval queue</span>
          <h3>Mesh owns this decision</h3>
          <p>Actions call `POST /api/runs/:id/steer` with Mesh role checks, command validation, and audit context.</p>
        </div>
        <strong>{queue.status || "empty"}</strong>
      </div>
      {items.length ? (
        <div className="approval-list">
          {items.map((item: any) => {
            const commands = approvalCommands(item.allowed_commands);
            return (
              <article className={`approval-card ${item.approval_state || "pending"}`} key={item.queue_id || item.run_id}>
                <div>
                  <span>{item.scenario_key || "custom"}</span>
                  <strong>{item.approval_state || "pending"}</strong>
                  <small>{item.run_id}</small>
                </div>
                <p>{item.blockers?.length ? `Blocked by ${item.blockers.join(", ")}` : item.final_recommendation || "Awaiting Mesh-approved operator decision."}</p>
                <label>
                  Action reason
                  <input
                    value={reasonByRun[item.run_id] || ""}
                    onChange={(event) => setReasonByRun({ ...reasonByRun, [item.run_id]: event.target.value })}
                    placeholder="why this approval action is correct"
                  />
                </label>
                <div className="approval-actions">
                  {commands.map((command) => (
                    <button
                      key={command}
                      type="button"
                      onClick={() => runCommand(item.run_id, command)}
                      disabled={busyCommand === `${item.run_id}:${command}`}
                    >
                      {humanize(command)}
                    </button>
                  ))}
                </div>
                <small>{(item.evidence_refs || []).slice(0, 3).join(" | ")}</small>
              </article>
            );
          })}
        </div>
      ) : <EmptyInline text="No approval queue items returned by Mesh." />}
      {message ? <div className={message.startsWith("Mesh accepted") ? "product-alert success" : "auth-error"}>{message}</div> : null}
    </section>
  );
}

export function approvalCommands(raw: any): ApprovalCommand[] {
  const allowed = Array.isArray(raw) ? raw.map(String) : [];
  return (["approve", "resume", "explain_blockers", "override_decision", "cancel"] as ApprovalCommand[]).filter((command) => allowed.includes(command));
}

type ProofResult = {
  status: "idle" | "loading" | "ready" | "error";
  runId: string;
  message: string;
  payloads: Record<string, any>;
};

const SCENARIO_PICKER = [
  { key: "reth_peer_starvation", label: "Reth peer starvation", detail: "Exercise peer loss, degraded sync signal, evidence collection, and bounded remediation." },
  { key: "reth_sync_stalled_disk_pressure", label: "Reth disk pressure stall", detail: "Rehearse stalled sync diagnosis against disk-pressure evidence and safe remediation gates." },
  { key: "kubernetes_crashloop_patch", label: "Kubernetes crashloop patch", detail: "Check workload evidence, ownership, approval, and patch safety before cluster-facing action." },
  { key: "search_latency_regression", label: "Search latency regression", detail: "Validate service-latency triage, RCA evidence, and advisory remediation boundaries." },
];

const AUDIT_REASON_TEMPLATES = [
  "Pilot dry-run: verify readiness and proof continuity before partner invite.",
  "Partner review: explain blockers without granting production authority.",
  "Regression rehearsal: confirm Mesh admission, approval, and evidence paths.",
];

function ProofDrilldownPanel({ dashboard }: { dashboard: DashboardPayload }) {
  const runs = dashboard.mesh.runs?.runs || [];
  const [selectedRunId, setSelectedRunId] = useState(String(runs[0]?.run_id || ""));
  const [proof, setProof] = useState<ProofResult>({ status: "idle", runId: "", message: "", payloads: {} });

  useEffect(() => {
    if (!selectedRunId && runs[0]?.run_id) setSelectedRunId(String(runs[0].run_id));
  }, [runs, selectedRunId]);

  async function loadProof() {
    if (!selectedRunId) {
      setProof({ status: "error", runId: "", message: "Select a run before loading proof views.", payloads: {} });
      return;
    }
    setProof({ status: "loading", runId: selectedRunId, message: "Loading Mesh proof views.", payloads: {} });
    const loaders = {
      detail: productApi.runDetail(selectedRunId),
      events: productApi.runEvents(selectedRunId),
      evidenceGraph: productApi.evidenceGraph(selectedRunId),
      rcaTrace: productApi.scenarioAnalysis(selectedRunId),
      merkle: productApi.merkle(selectedRunId),
      timelineProof: productApi.timelineProof(selectedRunId),
      exportPackage: productApi.exportRun(selectedRunId),
    };
    const entries = await Promise.all(Object.entries(loaders).map(async ([key, promise]) => {
      try {
        return [key, { state: "ready", payload: await promise }];
      } catch (err) {
        return [key, { state: "blocked", error: err instanceof Error ? err.message : "unavailable" }];
      }
    }));
    setProof({
      status: "ready",
      runId: selectedRunId,
      message: "Loaded read-only Mesh proof views. Mesh owns evidence, RCA, export, and decision records.",
      payloads: Object.fromEntries(entries),
    });
  }

  return (
    <section className="proof-panel" aria-label="Proof packet and evidence views">
      <div className="panel-heading">
        <div>
          <span>Evidence graph / proof packet / RCA trace / export</span>
          <h3>Read-only Mesh proof views</h3>
          <p>Every drill-in uses existing Mesh proof endpoints. The product shell cannot rewrite evidence or approve decisions from these views.</p>
        </div>
        <button type="button" onClick={loadProof} disabled={proof.status === "loading" || !runs.length}>
          {proof.status === "loading" ? "Loading" : "Load proof views"}
        </button>
      </div>
      {runs.length ? (
        <label className="proof-run-select">
          Run
          <select value={selectedRunId} onChange={(event) => setSelectedRunId(event.target.value)}>
            {runs.map((run: any) => <option key={run.run_id} value={run.run_id}>{run.scenario_key || "custom"} / {run.run_id}</option>)}
          </select>
        </label>
      ) : <EmptyInline text="No run summaries available for proof drill-in." />}
      {proof.message ? <div className={proof.status === "error" ? "auth-error" : "product-alert success"}>{proof.message}</div> : null}
      {proof.status === "ready" ? (
        <div className="proof-grid">
          {Object.entries(proof.payloads).map(([key, value]) => (
            <ReadModelCard key={key} title={humanize(key)} payload={value} />
          ))}
        </div>
      ) : null}
    </section>
  );
}

function LaunchRunPanel({ dashboard, onDashboardRefresh }: { dashboard: DashboardPayload; onDashboardRefresh: () => Promise<void> }) {
  const configuredDefaultScenario = dashboard.settings.default_run_scenario || "reth_peer_starvation";
  const defaultScenarioKnown = SCENARIO_PICKER.some((scenario) => scenario.key === configuredDefaultScenario);
  const [scenarioKey, setScenarioKey] = useState(defaultScenarioKnown ? configuredDefaultScenario : "reth_peer_starvation");
  const [evaluationMode, setEvaluationMode] = useState(dashboard.settings.default_evaluation_mode || "native");
  const [orchestrationMode, setOrchestrationMode] = useState(dashboard.settings.default_orchestration_mode || "native");
  const [steeringMode, setSteeringMode] = useState(dashboard.settings.default_steering_mode || "approval_gate");
  const [auditReason, setAuditReason] = useState("");
  const [requireTargetLock, setRequireTargetLock] = useState(dashboard.settings.default_target_lock === "required");
  const [result, setResult] = useState<RunLaunchResponse | null>(null);
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function launchRun() {
    const cleanedReason = auditReason.trim();
    if (!cleanedReason) {
      setMessage("Audit reason is required before Mesh can admit a product-launched run.");
      return;
    }
    setSubmitting(true);
    setMessage("");
    setResult(null);
    try {
      const response = await productApi.createRun({
        scenario_key: scenarioKey,
        audit_reason: cleanedReason,
        evaluation_mode: evaluationMode,
        orchestration_mode: orchestrationMode,
        steering_mode: steeringMode,
        require_target_lock: requireTargetLock,
      });
      setResult(response);
      await onDashboardRefresh();
      setAuditReason("");
      const admission = runAdmission(response);
      setMessage(admission?.decision === "blocked" ? "Mesh blocked this run admission." : "Mesh admitted this run.");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Run launch failed");
    } finally {
      setSubmitting(false);
    }
  }

  const admission = result ? runAdmission(result) : null;
  const blockers = admission?.blockers || [];
  const selectedScenario = SCENARIO_PICKER.find((scenario) => scenario.key === scenarioKey) || SCENARIO_PICKER[0];
  const messageClass = message.startsWith("Mesh admitted")
    ? "product-alert success"
    : message.startsWith("Mesh blocked")
      ? "product-alert warn"
      : "auth-error";
  return (
    <section className="launch-panel" aria-label="New Evaluation / Launch Run">
      <div className="launch-heading">
        <div>
          <span>New Evaluation / Launch Run</span>
          <h3>Mesh-owned run admission</h3>
          <p>Product launch calls `POST /api/runs`; Mesh records operator context, audit reason, ownership boundary, policy, and admission blockers.</p>
        </div>
        <button className="primary-button" type="button" onClick={launchRun} disabled={submitting}>
          {submitting ? "Launching" : "Launch run"}
        </button>
      </div>
      <div className="launch-grid">
        <label>
          Scenario
          <select value={scenarioKey} onChange={(event) => setScenarioKey(event.target.value)}>
            {SCENARIO_PICKER.map((scenario) => <option key={scenario.key} value={scenario.key}>{scenario.label}</option>)}
          </select>
          <small>{selectedScenario.detail}</small>
        </label>
        <label>
          Evaluation
          <select value={evaluationMode} onChange={(event) => setEvaluationMode(event.target.value)}>
            {(dashboard.settings_schema.default_evaluation_mode?.values || ["native", "promptfoo"]).map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label>
          Orchestration
          <select value={orchestrationMode} onChange={(event) => setOrchestrationMode(event.target.value)}>
            {(dashboard.settings_schema.default_orchestration_mode?.values || ["native", "hermes", "goose", "auto"]).map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label>
          Steering
          <select value={steeringMode} onChange={(event) => setSteeringMode(event.target.value)}>
            {(dashboard.settings_schema.default_steering_mode?.values || ["approval_gate", "interruptible_auto"]).map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label className="launch-reason">
          Audit reason
          <input value={auditReason} onChange={(event) => setAuditReason(event.target.value)} placeholder="why this evaluation is being launched" />
        </label>
        <div className="audit-template-row">
          {AUDIT_REASON_TEMPLATES.map((template) => <button key={template} type="button" onClick={() => setAuditReason(template)}>{template}</button>)}
        </div>
        <label className="toggle-row">
          <input type="checkbox" checked={requireTargetLock} onChange={(event) => setRequireTargetLock(event.target.checked)} />
          Require target lock
        </label>
      </div>
      {message ? <div className={messageClass}>{message}</div> : null}
      {result ? (
        <div className={`admission-result ${admission?.decision === "blocked" ? "blocked" : "ready"}`}>
          <span>{admission?.schema_version || "mesh.run_admission.v1"}</span>
          <strong>{admission?.decision || result.status || result.stage}</strong>
          <small>{result.run_id}</small>
          {blockers.length ? <p>Blocked by: {blockers.join(", ")}</p> : <p>Queue depth: {admission?.queue?.current_depth ?? 0} / {admission?.queue?.max_size ?? "unknown"}</p>}
          <button type="button" onClick={() => setAuditReason(`Follow-up on ${result.run_id}: review Mesh proof and admission outcome.`)}>Prepare follow-up reason</button>
        </div>
      ) : null}
    </section>
  );
}

function runAdmission(run: RunLaunchResponse): RunAdmissionPacket | null {
  return run.artifacts?.run_admission || null;
}

export function evidenceTraceSteps(dashboard: DashboardPayload): { label: string; detail: string; authority: string }[] {
  const runs = dashboard.mesh.runs?.runs || [];
  const latestRun = runs[0];
  const approvals = dashboard.mesh.approvals?.items || [];
  const pilot = dashboard.mesh.pilot_go_no_go || {};
  const missingEvidence = Array.isArray(pilot.missing_evidence) ? pilot.missing_evidence.length : 0;
  return [
    {
      label: "Signal",
      detail: latestRun?.scenario_key || "No active run signal in the dashboard read model.",
      authority: "Mesh run state",
    },
    {
      label: "Evidence",
      detail: missingEvidence ? `${missingEvidence} missing proof(s) reported by Mesh.` : "Evidence packets remain Mesh-owned read models.",
      authority: "Mesh evidence artifacts",
    },
    {
      label: "Policy",
      detail: approvals.length ? `${approvals.length} approval gate(s) pending.` : "No pending approval gate in the product read model.",
      authority: "Mesh policy and approvals",
    },
    {
      label: "Decision",
      detail: latestRun?.status ? `Latest run status: ${latestRun.status}.` : "Awaiting a Mesh decision/evaluation record.",
      authority: "Mesh decision record",
    },
  ];
}

function TraceRail({ steps }: { steps: { label: string; detail: string; authority: string }[] }) {
  return (
    <section className="trace-rail" aria-label="Signal to decision trace">
      {steps.map((step) => (
        <div className="trace-step" key={step.label}>
          <span>{step.label}</span>
          <strong>{step.detail}</strong>
          <small>{step.authority}</small>
        </div>
      ))}
    </section>
  );
}

function TeamSettingsView({
  session,
  dashboard,
  onDashboardRefresh,
  onSession,
  onLogout,
  loggingOut,
}: {
  session: SessionPayload;
  dashboard: DashboardPayload;
  onDashboardRefresh: () => Promise<void>;
  onSession: (session: SessionPayload) => void;
  onLogout: () => void;
  loggingOut: boolean;
}) {
  const team = session.active_team;
  const [teamName, setTeamName] = useState("");
  const [inviteEmails, setInviteEmails] = useState("");
  const [profileName, setProfileName] = useState(team?.name || "");
  const [profileDisplayName, setProfileDisplayName] = useState(team?.display_name || "");
  const [teamMessage, setTeamMessage] = useState("");
  const [creatingTeam, setCreatingTeam] = useState(false);
  const [savingTeam, setSavingTeam] = useState(false);

  useEffect(() => {
    setProfileName(team?.name || "");
    setProfileDisplayName(team?.display_name || "");
  }, [team?.id, team?.name, team?.display_name]);

  async function createTeamFromSettings() {
    const name = teamName.trim();
    if (!name) {
      setTeamMessage("Team name is required.");
      return;
    }
    setCreatingTeam(true);
    setTeamMessage("");
    try {
      const members = inviteEmails.split(",").map((email) => email.trim()).filter(Boolean).map((email) => ({ email, role: "viewer" }));
      const payload = await productApi.createTeam({ name, members });
      onSession(payload);
      await onDashboardRefresh();
      setTeamName("");
      setInviteEmails("");
      setTeamMessage(`Created team ${payload.active_team?.name || name}.`);
    } catch (err) {
      setTeamMessage(err instanceof Error ? err.message : "Team creation failed.");
    } finally {
      setCreatingTeam(false);
    }
  }

  async function saveTeamProfile() {
    if (!team) return;
    const name = profileName.trim();
    if (!name) {
      setTeamMessage("Team name is required.");
      return;
    }
    setSavingTeam(true);
    setTeamMessage("");
    try {
      const payload = await productApi.updateTeam({ team_id: team.id, name, display_name: profileDisplayName.trim() });
      onSession(payload);
      await onDashboardRefresh();
      setTeamMessage(`Saved team profile for ${payload.active_team?.name || name}.`);
    } catch (err) {
      setTeamMessage(err instanceof Error ? err.message : "Team profile update failed.");
    } finally {
      setSavingTeam(false);
    }
  }

  return (
    <div className="settings-layout">
      <section className="profile-panel">
        <h2>Team Settings</h2>
        <p>{team ? "Review team profile and preferences for the active dashboard scope." : "Create a team when you are ready to invite partners or separate this browser from solo mode."}</p>
        <div className="avatar-disc">{team?.name?.[0] || session.user.display_name[0]}</div>
        <FormRead label="ID" value={team?.id || session.user.id} />
        <FormRead label="Email" value={session.user.email} />
        {team ? (
          <div className="create-team-panel">
            <h3>Team profile</h3>
            <label>
              Team name
              <input value={profileName} onChange={(event) => setProfileName(event.target.value)} />
            </label>
            <label>
              Display name
              <input value={profileDisplayName} onChange={(event) => setProfileDisplayName(event.target.value)} />
            </label>
            <FormRead label="Slug" value={team.slug} />
            <FormRead label="Your role" value={team.role} />
            <button className="primary-button" type="button" onClick={saveTeamProfile} disabled={savingTeam}>{savingTeam ? "Saving" : "Save team profile"}</button>
          </div>
        ) : (
          <div className="create-team-panel">
            <h3>Create team</h3>
            <label>
              Team name
              <input value={teamName} onChange={(event) => setTeamName(event.target.value)} placeholder={`${session.user.display_name || "Operator"}'s team`} />
            </label>
            <label>
              Invite members
              <input value={inviteEmails} onChange={(event) => setInviteEmails(event.target.value)} placeholder="colleague@company.com, sre@company.com" />
            </label>
            <button className="primary-button" type="button" onClick={createTeamFromSettings} disabled={creatingTeam}>{creatingTeam ? "Creating" : "Create team"}</button>
          </div>
        )}
        <FormRead label="Authority boundary" value="Mesh operator dashboard. Runtime authority remains with Mesh." large />
        {teamMessage ? <div className={teamMessage.startsWith("Created") || teamMessage.startsWith("Saved") ? "product-alert success inline" : "auth-error compact"}>{teamMessage}</div> : null}
        <div className="button-row">
          <button type="button" onClick={onLogout} disabled={loggingOut}>{loggingOut ? "Logging out" : "Log out"}</button>
        </div>
      </section>
      <SettingsView dashboard={dashboard} compact onDashboardRefresh={onDashboardRefresh} />
    </div>
  );
}

const MEMBER_ROLES: MemberRole[] = ["viewer", "launcher", "approver", "admin"];

function MembersView({
  session,
  setView,
  onSession,
  onDashboardRefresh,
}: {
  session: SessionPayload;
  setView: (view: ViewKey) => void;
  onSession: (session: SessionPayload) => void;
  onDashboardRefresh: () => Promise<void>;
}) {
  const team = session.active_team;
  const members = team?.members || [{ email: session.user.email, role: "owner", status: "active" }];
  const [inviteEmails, setInviteEmails] = useState("");
  const [inviteRole, setInviteRole] = useState<MemberRole>("viewer");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);

  async function saveMembers() {
    if (!team) {
      setMessage("Create a team before inviting members.");
      return;
    }
    const emails = inviteEmails.split(",").map((email) => email.trim()).filter(Boolean);
    if (!emails.length) {
      setMessage("At least one member email is required.");
      return;
    }
    setSaving(true);
    setMessage("");
    try {
      const payload = await productApi.upsertTeamMembers({
        team_id: team.id,
        members: emails.map((email) => ({ email, role: inviteRole })),
      });
      onSession(payload);
      await onDashboardRefresh();
      setInviteEmails("");
      setMessage(`Saved ${emails.length} member update(s) for ${payload.active_team?.name || team.name}.`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Member update failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="content-stack">
      <Toolbar title="Members" detail="Team roles map into Mesh operator roles for protected actions." action="Manage Team" onAction={() => setView("team")} />
      <section className="member-config-panel">
        <div>
          <h3>{team ? "Invite or update members" : "Team required"}</h3>
          <p>{team ? "Add comma-separated emails, choose the Mesh role mapping, and save through the team-tenancy state slice." : "Solo mode has only the current operator. Create a team before inviting partners."}</p>
        </div>
        {team ? (
          <div className="member-config-grid">
            <label>
              Emails
              <input value={inviteEmails} onChange={(event) => setInviteEmails(event.target.value)} placeholder="viewer@company.com, approver@company.com" />
            </label>
            <label>
              Role
              <select value={inviteRole} onChange={(event) => setInviteRole(event.target.value as MemberRole)}>
                {MEMBER_ROLES.map((role) => <option key={role} value={role}>{humanize(role)}</option>)}
              </select>
            </label>
            <button className="primary-button" type="button" onClick={saveMembers} disabled={saving}>{saving ? "Saving" : "Save members"}</button>
          </div>
        ) : null}
        {message ? <div className={message.startsWith("Saved") ? "product-alert success inline" : "auth-error compact"}>{message}</div> : null}
      </section>
      <div className="data-table compact">
        <div className="table-head"><span>Email</span><span>Role</span><span>Status</span></div>
        {members.map((member) => <div className="table-row" key={member.email}><span>{member.email}</span><span>{member.role}</span><span>{member.status}</span></div>)}
      </div>
    </div>
  );
}

function KeysView({ authConfig, dashboard, setView }: { authConfig: AuthConfig | null; dashboard: DashboardPayload; setView: (view: ViewKey) => void }) {
  const readiness = dashboard.mesh.readiness || {};
  const rows = authConfig ? [
    {
      title: "Auth mode",
      value: authConfig.auth_mode,
      state: authConfig.auth_mode === "app_session" ? "ready" : "read-only",
      detail: "Configured by MESH_AUTH_MODE. Product app sessions scope dashboard access; proxy-header ingress remains deployment-owned.",
    },
    {
      title: "Password signup",
      value: authConfig.signup_enabled && authConfig.password_auth_enabled ? "enabled" : "disabled",
      state: authConfig.signup_enabled && authConfig.password_auth_enabled ? "ready" : "blocked",
      detail: "Controlled by MESH_SIGNUP_ENABLED and MESH_PASSWORD_AUTH_ENABLED.",
    },
    {
      title: "Invite gate",
      value: authConfig.invite.configured ? (authConfig.invite.required ? "code required" : "allowlist") : "open local mode",
      state: authConfig.invite.configured ? "ready" : "config-only",
      detail: "Controlled by MESH_AUTH_INVITE_ALLOWLIST and MESH_AUTH_INVITE_CODES; raw invite codes stay outside product state.",
    },
    {
      title: "Captcha",
      value: authConfig.captcha.dev_bypass_enabled ? "dev bypass" : authConfig.captcha.configured ? authConfig.captcha.provider : "not configured",
      state: authConfig.captcha.configured || authConfig.captcha.dev_bypass_enabled ? "ready" : "blocked",
      detail: "Controlled by MESH_CAPTCHA_PROVIDER, MESH_CAPTCHA_SITE_KEY, and MESH_CAPTCHA_SECRET_KEY. Browser tokens are never stored.",
    },
    {
      title: "Google OAuth",
      value: authConfig.oauth.google.configured ? "configured" : "not configured",
      state: authConfig.oauth.google.configured ? "ready" : "blocked",
      detail: "Requires client id, client secret, and redirect URL. The product shell only starts the provider flow.",
    },
    {
      title: "GitHub OAuth",
      value: authConfig.oauth.github.configured ? "configured" : "not configured",
      state: authConfig.oauth.github.configured ? "ready" : "blocked",
      detail: "Requires client id, client secret, and redirect URL. Tokens never enter the dashboard read model.",
    },
  ] : [
    {
      title: "Auth config",
      value: "unavailable",
      state: "blocked",
      detail: backendUnavailableMessage(),
    },
  ];
  const deploymentRows = [
    {
      title: "State backend",
      value: String(readiness.state_backend || "RuntimeConfig-owned"),
      state: readiness.state_backend ? "ready" : "read-only",
      detail: "Runtime persistence is deployment config, not a product-secret setting.",
    },
    {
      title: "Build commit",
      value: String(dashboard.mesh.health?.commit || "unknown"),
      state: dashboard.mesh.health?.commit ? "ready" : "read-only",
      detail: "Build provenance changes only when a new artifact is deployed.",
    },
    {
      title: "Settings scope",
      value: dashboard.scope.kind === "team" ? `team:${dashboard.scope.team?.id}` : `user:${dashboard.session.user.id}`,
      state: "ready",
      detail: "Defaults on the Settings page mutate mesh-settings-control with an audit reason.",
    },
  ];

  return (
    <div className="content-stack">
      <Toolbar
        title="Keys & Secrets"
        detail="Provider secrets are deployment-owned. This page shows configuration posture and exact ownership without exposing raw values."
        action="Open Settings"
        onAction={() => setView("settings")}
      />
      <section className="keys-posture-grid">
        {[...rows, ...deploymentRows].map((row) => <ConfigPostureCard key={row.title} {...row} />)}
      </section>
      <section className="keys-env-panel">
        <h3>Deployment-owned variables</h3>
        <div className="env-var-grid">
          <code>MESH_GOOGLE_OAUTH_CLIENT_ID</code>
          <code>MESH_GOOGLE_OAUTH_CLIENT_SECRET</code>
          <code>MESH_GOOGLE_OAUTH_REDIRECT_URL</code>
          <code>MESH_GITHUB_OAUTH_CLIENT_ID</code>
          <code>MESH_GITHUB_OAUTH_CLIENT_SECRET</code>
          <code>MESH_GITHUB_OAUTH_REDIRECT_URL</code>
          <code>MESH_CAPTCHA_PROVIDER</code>
          <code>MESH_CAPTCHA_SITE_KEY</code>
          <code>MESH_CAPTCHA_SECRET_KEY</code>
          <code>MESH_AUTH_INVITE_ALLOWLIST</code>
          <code>MESH_AUTH_INVITE_CODES</code>
          <code>MESH_AUTH_PRODUCT_REDIRECT_URL</code>
        </div>
      </section>
    </div>
  );
}

function ConfigPostureCard({ title, value, detail, state }: { title: string; value: string; detail: string; state: string }) {
  return (
    <article className={`config-posture-card ${state}`}>
      <span>{title}</span>
      <strong>{humanize(value)}</strong>
      <p>{detail}</p>
    </article>
  );
}

function SettingsView({
  dashboard,
  compact = false,
  onDashboardRefresh,
}: {
  dashboard: DashboardPayload;
  compact?: boolean;
  onDashboardRefresh?: () => Promise<void>;
}) {
  const settingsPosture = operatorWorkflowPosture("settings");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const next: Record<string, string> = {};
    Object.entries(dashboard.settings_schema).forEach(([key, schema]) => {
      next[key] = dashboard.settings[key] || schema.default;
    });
    setDraft(next);
  }, [dashboard]);

  async function saveSettings() {
    const cleanedReason = reason.trim();
    if (!cleanedReason) {
      setMessage("Audit reason is required before settings can be saved.");
      return;
    }
    setSaving(true);
    setMessage("");
    try {
      const response = await productApi.updateSettings(dashboard.scope.team?.id || null, draft, cleanedReason);
      setDraft(response.settings);
      setReason("");
      await onDashboardRefresh?.();
      setMessage(`Saved ${response.audit.fields.join(", ")} for ${response.audit.scope}.`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Settings update failed");
    } finally {
      setSaving(false);
    }
  }
  const parityRows = settingsParityRows({ ...dashboard, settings: { ...dashboard.settings, ...draft } });

  return (
    <section className={compact ? "settings-panel compact" : "settings-panel"}>
      <h2>Settings</h2>
      <p>{settingsPosture.reason} Mesh runtime-critical values are read-only and deployment-owned.</p>
      <div className="setting-grid">
        {parityRows.map((row) => row.mutable ? (
          <div className="setting-card" key={row.key}>
            <span>{row.label}</span>
            <select value={draft[row.key] || row.value} onChange={(event) => setDraft({ ...draft, [row.key]: event.target.value })}>
              {(row.values || []).map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
            <p>{row.description}</p>
            <details className="setting-advanced">
              <summary>Advanced</summary>
              <code>{row.uiMutationPath}</code>
              <code>{row.cliPath}</code>
            </details>
          </div>
        ) : (
          <div className="setting-card readonly" key={row.key}>
            <span>{row.label}</span><strong>{row.value}</strong><p>{row.description}</p><small>{row.readOnlyReason}</small>
          </div>
        ))}
      </div>
      <div className="settings-save-row">
        <label>
          Audit reason
          <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="why this settings change is required" />
        </label>
        <button className="primary-button" type="button" onClick={saveSettings} disabled={saving}>{saving ? "Saving" : "Save settings"}</button>
      </div>
      {message ? <div className={message.startsWith("Saved") ? "product-alert success" : "auth-error"}>{message}</div> : null}
    </section>
  );
}

function CapabilityView({ view, dashboard, setView }: { view: ViewKey; dashboard: DashboardPayload; setView: (view: ViewKey) => void }) {
  const workflowPosture = operatorWorkflowPosture(workflowForView(view));
  const page = runtimeProductPage(view, dashboard);
  return (
    <div className="content-stack">
      <Toolbar
        title={page.title}
        detail={page.detail || workflowPosture.reason}
        action="Review Dashboard"
        onAction={() => setView("home")}
      />
      <div className="capability-grid two">
        {page.cards.map((card) => <ReadModelCard key={card.title} title={card.title} payload={card.payload} />)}
      </div>
    </div>
  );
}

export function runtimeProductPage(view: ViewKey, dashboard: DashboardPayload): { title: string; detail: string; cards: { title: string; payload: any }[] } {
  const mesh = dashboard.mesh || {};
  const readiness = mesh.readiness || {};
  if (view === "training") {
    return {
      title: "Topology",
      detail: "Topology is a Mesh-owned read model. Product navigation shows the profile and graph without using the legacy tab shortcut.",
      cards: [
        { title: "Orchestration topology", payload: readiness.orchestration_topology || mesh.graph },
        { title: "Runtime graph", payload: mesh.graph },
        { title: "Connector matrix", payload: mesh.connectors },
        { title: "Read model authority", payload: mesh.read_model },
      ],
    };
  }
  if (view === "inference") {
    return {
      title: "Memory Projection",
      detail: "Memory projection is surfaced as a read model; Mesh owns corpus projection, active memory, and graph persistence.",
      cards: [
        { title: "Memory graph", payload: mesh.memory?.graph },
        { title: "Active memory", payload: mesh.memory?.active },
        { title: "Trust ladder", payload: mesh.trust_ladder },
        { title: "Readiness", payload: readiness },
      ],
    };
  }
  if (view === "gpu") {
    return {
      title: "Readiness",
      detail: "Readiness stays Mesh-owned. Product cards show blockers and degraded backend state without granting remediation authority.",
      cards: [
        { title: "Runtime readiness", payload: readiness },
        { title: "Watchers", payload: mesh.watchers },
        { title: "Kill switch", payload: mesh.kill_switch },
        { title: "Connector certification", payload: mesh.connectors },
      ],
    };
  }
  if (view === "clusters") {
    return {
      title: "Kill Switch",
      detail: "Kill switch mutation remains a Mesh admin API. This page exposes state and blocked reasons only.",
      cards: [
        { title: "Kill switch", payload: mesh.kill_switch },
        { title: "Policy state", payload: mesh.approvals },
        { title: "Readiness", payload: readiness },
        { title: "Pilot go/no-go", payload: mesh.pilot_go_no_go },
      ],
    };
  }
  if (view === "instances") {
    return {
      title: "Policy State",
      detail: "Policy state combines approval queue, trust ladder, pilot packet, and evidence posture. Mesh owns decisions.",
      cards: [
        { title: "Approval queue", payload: mesh.approvals },
        { title: "Trust ladder", payload: mesh.trust_ladder },
        { title: "Pilot proof packet", payload: mesh.pilot_go_no_go },
        { title: "Read model authority", payload: mesh.read_model },
      ],
    };
  }
  if (view === "keys") {
    return {
      title: "Keys & Secrets",
      detail: "Secrets and provider configuration stay read-only in the product shell; local values must stay in ignored env files.",
      cards: [
        { title: "Auth provider posture", payload: { state: "read-only", reason: "Configured through ignored env or deployment secret manager." } },
        { title: "Build health", payload: mesh.health },
        { title: "Runtime config state", payload: readiness },
        { title: "Settings parity", payload: dashboard.settings_schema },
      ],
    };
  }
  return {
    title: view,
    detail: "Product-native read model page.",
    cards: [
      { title: "Runtime readiness", payload: readiness },
      { title: "Policy state", payload: mesh.approvals },
      { title: "Connector proof", payload: mesh.connectors },
      { title: "Memory projection", payload: mesh.memory },
    ],
  };
}

export function workflowForView(view: ViewKey): OperatorWorkflowKey {
  if (isConsoleProductView(view)) return workflowForView(consoleWorkflowForView(view).productFallback);
  if (view === "keys" || view === "settings") return "settings";
  if (view === "environments") return "connector";
  if (view === "evaluations") return "launch";
  if (view === "training" || view === "inference" || view === "gpu" || view === "clusters" || view === "instances") return "readiness";
  return "evidence";
}

function ReadModelCard({ title, payload }: { title: string; payload: any }) {
  const displayPayload = readModelCardPayload(title, payload);
  const display = readModelDisplay(displayPayload);
  return (
    <section className={`read-model-card ${display.state}`}>
      <CircleDot size={15} />
      <strong>{title}</strong>
      <span>{humanize(display.status)}</span>
      <p>{display.summary}</p>
      <details>
        <summary>Payload</summary>
        <pre>{JSON.stringify(displayPayload, null, 2).slice(0, 720)}</pre>
      </details>
    </section>
  );
}

function readModelDisplay(payload: any): { status: string; summary: string; state: DashboardSurfaceState | "read-only" } {
  const status = String(payload?.status || payload?.state || payload?.decision || "read-only");
  const sectionState = dashboardSectionState(payload).state;
  if (payload?.error) return { status, summary: String(payload.error), state: "degraded" };
  if (payload?.reason) return { status, summary: String(payload.reason), state: sectionState };
  if (payload?.detail) return { status, summary: String(payload.detail), state: sectionState };
  if (payload?.degraded_reason) return { status, summary: String(payload.degraded_reason), state: sectionState };
  if (Array.isArray(payload?.blockers) && payload.blockers.length) return { status, summary: `${payload.blockers.length} blocker(s): ${payload.blockers.slice(0, 3).join(", ")}`, state: "blocked" };
  const keys = payload && typeof payload === "object" ? Object.keys(payload) : [];
  return {
    status,
    summary: keys.length ? `Mesh returned ${keys.length} field(s) for this read model.` : "No payload is available for this read model yet.",
    state: sectionState,
  };
}

export function readModelSummary(payload: any, emptyReason: string): string {
  if (payload?.error) return `Unavailable: ${payload.error}`;
  if (payload?.status) return String(payload.status);
  if (payload?.state) return String(payload.state);
  return emptyReason;
}

export function readModelCardPayload(title: string, payload: any): any {
  if (payload && Object.keys(payload).length > 0) return payload;
  return {
    state: "empty",
    reason: `${title} read model returned no payload. This product surface is read-only until Mesh exposes data.`,
  };
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

function titleize(value: string): string {
  return humanize(value).replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function Toolbar({
  title,
  detail,
  action,
  onAction,
}: {
  title: string;
  detail: string;
  action: string;
  onAction?: () => void;
}) {
  return (
    <div className="toolbar">
      <div><h2>{title}</h2><p>{detail}</p></div>
      <button className="primary-button" type="button" onClick={onAction} disabled={!onAction}>{action}</button>
    </div>
  );
}

function SearchBar({
  placeholder = "Search by name, author, description, tags...",
  value,
  onChange,
}: {
  placeholder?: string;
  value?: string;
  onChange?: (value: string) => void;
}) {
  return (
    <label className="search-bar">
      <Search size={16} />
      <input placeholder={placeholder} value={value ?? ""} onChange={(event) => onChange?.(event.target.value)} />
    </label>
  );
}

function SectionLabel({ label }: { label: string }) {
  return <h3 className="section-label">{label}</h3>;
}

function CardRows({ sections }: { sections: { title: string; count: number; cards: any[] }[] }) {
  return (
    <>
      {sections.map((section) => (
        <section className="card-section" key={section.title}>
          <h3>{section.title} <span>{section.count}</span></h3>
          <div className="environment-grid">
            {section.cards.map((card) => (
              <article className="environment-card" key={card.id}>
                <div><span>{card.owner}</span><span>{card.state || card.tags?.[0] || "unknown"}</span></div>
                <h4>{card.title}</h4>
                <p>{card.detail}</p>
                {card.blockers?.length ? (
                  <div className="blocker-badges">
                    {card.blockers.map((blocker: string) => <span key={blocker}><AlertTriangle size={11} /> {humanize(blocker)}</span>)}
                  </div>
                ) : null}
                <div className="tag-row">{card.tags.map((tag: string) => <span key={tag}>{tag}</span>)}</div>
                <small>{card.version}</small>
              </article>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}

function Stat({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="stat-card"><span>{label}</span><strong>{value}</strong><p>{detail}</p></div>;
}

function FormRead({ label, value, large = false }: { label: string; value: string; large?: boolean }) {
  return <label className={large ? "form-read large" : "form-read"}>{label}<span>{value}</span></label>;
}
