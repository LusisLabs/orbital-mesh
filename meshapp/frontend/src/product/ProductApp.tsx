"use client";

import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  BookOpen,
  Boxes,
  Calendar,
  ChevronDown,
  CircleDot,
  Cpu,
  Database,
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
  Sparkles,
  Users,
  Zap,
} from "lucide-react";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import LegacyMeshConsole from "../App";
import {
  type AuthConfig,
  type DashboardPayload,
  type LoadState,
  type SessionPayload,
  backendUnavailableMessage,
  loadStateFromError,
  productApi,
} from "./api";

type ViewKey =
  | "home"
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
  | "settings"
  | "legacy";

const NAV_GROUPS: { label: string; items: { key: ViewKey; label: string; icon: any }[] }[] = [
  { label: "", items: [{ key: "home", label: "Home", icon: Home }] },
  {
    label: "Lab",
    items: [
      { key: "environments", label: "Environments Hub", icon: Boxes },
      { key: "evaluations", label: "Evaluations", icon: BarChart3 },
      { key: "training", label: "Training", icon: Network },
      { key: "inference", label: "Inference", icon: Activity },
    ],
  },
  {
    label: "Compute",
    items: [
      { key: "gpu", label: "On-Demand GPUs", icon: Cpu },
      { key: "clusters", label: "Reserved Clusters", icon: Calendar },
      { key: "instances", label: "Team Instances", icon: Layers },
    ],
  },
  {
    label: "Team",
    items: [
      { key: "team", label: "Team Settings", icon: Settings },
      { key: "members", label: "Members", icon: Users },
      { key: "keys", label: "Keys & Secrets", icon: KeyRound },
    ],
  },
];

type OperatorWorkflowKey = "launch" | "approval" | "evidence" | "readiness" | "connector" | "settings";

export function operatorWorkflowPosture(workflow: OperatorWorkflowKey): { callPath: string; posture: "native" | "delegated" | "read_only"; reason: string } {
  const postures: Record<OperatorWorkflowKey, { callPath: string; posture: "native" | "delegated" | "read_only"; reason: string }> = {
    launch: {
      callPath: "/api/runs via the preserved Mesh control-plane console",
      posture: "delegated",
      reason: "Run launch is delegated to Mesh admission in the control-plane console; this product view stays read-only.",
    },
    approval: {
      callPath: "/api/approvals and /api/runs/{run_id}/steer",
      posture: "delegated",
      reason: "Approvals remain Mesh-controlled and require the preserved approval/steering surface.",
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
        setSession(payload);
        setSessionState({ state: "ready", data: payload });
        setOnboardingComplete(Boolean(payload.active_team || window.localStorage.getItem("mesh.product.solo") === "1"));
      } catch (error) {
        if (!mounted) return;
        setSessionState(loadStateFromError(error));
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
    setDashboardState({ state: "loading" });
    productApi.dashboard(session.active_team?.id ?? null)
      .then((payload) => {
        if (!mounted) return;
        setDashboardState({ state: "ready", data: payload });
      })
      .catch((error) => {
        if (!mounted) return;
        setDashboardState(loadStateFromError(error));
      });
    return () => {
      mounted = false;
    };
  }, [session, onboardingComplete]);

  async function refreshSession() {
    const payload = await productApi.me();
    setSession(payload);
    setSessionState({ state: "ready", data: payload });
    return payload;
  }

  async function logout() {
    if (loggingOut) return;
    setLoggingOut(true);
    setLogoutError("");
    try {
      await productApi.logout();
      setSession(null);
      setSessionState({ state: "unauthorized", message: "Logged out" });
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
    return <AuthScreen config={authConfig} sessionState={sessionState} onSession={setSession} />;
  }

  if (!session.active_team && !onboardingComplete) {
    return (
      <TeamSetupScreen
        session={session}
        onSolo={() => {
          window.localStorage.setItem("mesh.product.solo", "1");
          setOnboardingComplete(true);
        }}
        onTeam={(payload) => {
          setSession(payload);
          setOnboardingComplete(true);
        }}
      />
    );
  }

  if (view === "legacy") {
    return (
      <div className="product-legacy">
        <button className="product-return" type="button" onClick={() => setView("home")}>
          <ArrowRight size={14} /> Return to product dashboard
        </button>
        <LegacyMeshConsole />
      </div>
    );
  }

  const dashboard = dashboardState.state === "ready" ? dashboardState.data : null;

  return (
    <div className="product-shell">
      <Sidebar session={session} activeView={view} onView={setView} onLogout={logout} loggingOut={loggingOut} />
      <main className="product-main">
        <Header session={session} dashboard={dashboard} onSession={setSession} refreshSession={refreshSession} />
        {logoutError ? (
          <div className="product-alert" role="alert">
            <AlertTriangle size={16} />
            <span>{logoutError}</span>
          </div>
        ) : null}
        <ContentRouter
          view={view}
          session={session}
          dashboardState={dashboardState}
          setView={setView}
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
  const [displayName, setDisplayName] = useState("");
  const [captchaToken, setCaptchaToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const backendUnavailable = !config;
  const sessionIssueMessage = sessionLoadIssueMessage(sessionState);
  const authUnavailable = backendUnavailable || sessionState?.state === "backend-unavailable";
  const signupMode = mode === "signup";
  const captchaSatisfied =
    !signupMode ||
    Boolean(config?.captcha.dev_bypass_enabled) ||
    (Boolean(config?.captcha.configured) && Boolean(captchaToken));
  const submitDisabled = busy || authUnavailable || !email.trim() || !password || !captchaSatisfied;

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
        })
        : await productApi.login({ email, password });
      onSession(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setBusy(false);
    }
  }

  async function oauth(provider: "google" | "github") {
    if (!config || authUnavailable) {
      setError(backendUnavailable ? backendUnavailableMessage() : sessionIssueMessage || "Authentication is unavailable.");
      return;
    }
    if (!config.oauth[provider].configured) {
      setError(`${provider} OAuth is not configured. Set the provider client ID, client secret, and redirect URL on the Mesh API server.`);
      return;
    }
    setError("");
    try {
      const payload = await productApi.oauthStart(provider);
      window.location.assign(payload.authorize_url);
    } catch (err) {
      setError(err instanceof Error ? err.message : `${provider} login unavailable`);
    }
  }

  return (
    <div className="auth-scene">
      <div className="auth-orbit" />
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
        <div className="oauth-stack">
          <button type="button" onClick={() => oauth("google")} disabled={authUnavailable || !config?.oauth.google.configured}>
            <Globe size={18} /> Continue with Google
          </button>
          <button type="button" onClick={() => oauth("github")} disabled={authUnavailable || !config?.oauth.github.configured}>
            <Github size={18} /> Continue with GitHub
          </button>
        </div>
        {config && (!config.oauth.google.configured || !config.oauth.github.configured) ? (
          <p className="auth-provider-note">OAuth buttons enable after provider environment variables are configured on the Mesh API server.</p>
        ) : null}
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
            setError("");
          }}
        >
          {mode === "login" ? "Need an account? Sign up" : "Have an account? Log in"}
        </button>
      </form>
    </div>
  );
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

  async function createTeam() {
    setError("");
    try {
      const members = invite.split(",").map((email) => email.trim()).filter(Boolean).map((email) => ({ email, role: "viewer" }));
      const payload = await productApi.createTeam({ name, members });
      onTeam(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Team creation failed");
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
        <button className="primary-button" type="button" onClick={createTeam}>Create team</button>
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
}: {
  session: SessionPayload;
  activeView: ViewKey;
  onView: (view: ViewKey) => void;
  onLogout: () => void;
  loggingOut: boolean;
}) {
  function openDocs() {
    window.open("https://github.com/LusisLabs/orbital-mesh/tree/master/docs", "_blank", "noopener,noreferrer");
  }

  return (
    <aside className="product-sidebar">
      <div className="brand-row"><BrandLogo /><button type="button" aria-label="Collapse"><ChevronDown size={14} /></button></div>
      <nav>
        {NAV_GROUPS.map((group) => (
          <div className="nav-group" key={group.label || "home"}>
            {group.label ? <p>{group.label}</p> : null}
            {group.items.map((item) => {
              const Icon = item.icon;
              return (
                <button key={item.key} className={activeView === item.key ? "active" : ""} type="button" onClick={() => onView(item.key)}>
                  <Icon size={16} /> {item.label}
                </button>
              );
            })}
          </div>
        ))}
        <div className="nav-group">
          <p>Support</p>
          <button type="button" onClick={() => onView("legacy")}><Mail size={16} /> Chat</button>
          <button type="button" onClick={openDocs}><BookOpen size={16} /> Documentation</button>
          <button type="button" onClick={() => onView("legacy")}><Database size={16} /> Control Plane</button>
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
}: {
  session: SessionPayload;
  dashboard: DashboardPayload | null;
  onSession: (session: SessionPayload | null) => void;
  refreshSession: () => Promise<SessionPayload>;
}) {
  return (
    <header className="product-header">
      <div>
        <h1>{dashboard?.scope.kind === "team" ? dashboard.scope.team?.display_name : "Home"}</h1>
        <p>{dashboard?.authority_boundary || "Mesh controls policy, approvals, run state, readiness, evidence, and actuation."}</p>
      </div>
      <div className="header-actions">
        <TeamSwitcher session={session} refreshSession={refreshSession} />
      </div>
    </header>
  );
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
  session,
  dashboardState,
  setView,
  onLogout,
  loggingOut,
}: {
  view: ViewKey;
  session: SessionPayload;
  dashboardState: LoadState<DashboardPayload>;
  setView: (view: ViewKey) => void;
  onLogout: () => void;
  loggingOut: boolean;
}) {
  if (dashboardState.state !== "ready") {
    return <LoadStatePanel state={dashboardState} />;
  }
  const dashboard = dashboardState.data;
  if (view === "home") return <HomeView dashboard={dashboard} setView={setView} />;
  if (view === "environments") return <EnvironmentView dashboard={dashboard} setView={setView} />;
  if (view === "evaluations") return <EvaluationsView dashboard={dashboard} setView={setView} />;
  if (view === "team") return <TeamSettingsView session={session} dashboard={dashboard} onLogout={onLogout} loggingOut={loggingOut} />;
  if (view === "members") return <MembersView session={session} setView={setView} />;
  if (view === "settings") return <SettingsView dashboard={dashboard} />;
  return <CapabilityView view={view} dashboard={dashboard} setView={setView} />;
}

function LoadStatePanel<T>({ state }: { state: LoadState<T> }) {
  if (state.state === "loading") return <div className="skeleton-panel"><span /><span /><span /></div>;
  if (state.state === "ready") return null;
  return <div className={`state-panel ${state.state}`}><AlertTriangle size={18} /> {state.message}</div>;
}

function HomeView({ dashboard, setView }: { dashboard: DashboardPayload; setView: (view: ViewKey) => void }) {
  const mesh = dashboard.mesh;
  const readiness = mesh.readiness || {};
  const runs = mesh.runs?.runs || [];
  const approvals = mesh.approvals?.items || [];
  const connectors = mesh.connectors?.connectors || mesh.connectors?.connector_certification || {};
  const capabilityCards = [
    { title: "Runtime readiness", detail: readModelSummary(readiness, "Read-only: readiness status unavailable"), icon: Zap, view: "settings" as ViewKey },
    { title: "Run admission", detail: `${runs.length} recent runs`, icon: Play, view: "evaluations" as ViewKey },
    { title: "Connector status", detail: `${Object.keys(connectors).length} connectors tracked`, icon: Boxes, view: "environments" as ViewKey },
    { title: "Orchestration topology", detail: readModelSummary(readiness.orchestration_topology, "Read-only: topology profile unavailable"), icon: Network, view: "training" as ViewKey },
    { title: "Evidence packets", detail: readModelSummary(mesh.pilot_go_no_go, "Read-only: pilot packet unavailable"), icon: ShieldCheck, view: "evaluations" as ViewKey },
    { title: "Policy approvals", detail: `${approvals.length} pending`, icon: Lock, view: "evaluations" as ViewKey },
    { title: "Memory projection", detail: readModelSummary(mesh.memory?.graph, "Read-only: memory graph unavailable"), icon: Database, view: "settings" as ViewKey },
    { title: "Settings parity", detail: "UI and CLI share validation", icon: Settings, view: "settings" as ViewKey },
  ];

  return (
    <div className="content-stack">
      <section className="quickstart-card">
        <Sparkles size={20} />
        <div>
          <h2>Quickstart</h2>
          <p>Check readiness, launch a controlled run, and keep approvals inside Mesh authority.</p>
        </div>
        <button type="button" onClick={() => setView("evaluations")}>Get started <ArrowRight size={16} /></button>
      </section>
      <SectionLabel label="Mesh capabilities" />
      <div className="capability-grid">
        {capabilityCards.map((card) => {
          const Icon = card.icon;
          return (
            <button className="capability-card" key={card.title} type="button" onClick={() => setView(card.view)}>
              <Icon size={18} />
              <strong>{card.title}</strong>
              <span>{card.detail}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function EnvironmentView({ dashboard, setView }: { dashboard: DashboardPayload; setView: (view: ViewKey) => void }) {
  const connectorPosture = operatorWorkflowPosture("connector");
  const connectors = dashboard.mesh.connectors?.connectors || dashboard.mesh.connectors?.connector_certification || {};
  const cards = Object.entries(connectors).map(([id, value]: [string, any]) => ({
    id,
    owner: "Mesh",
    stars: value.blockers?.length || 0,
    title: value.name || id,
    detail: value.detail || value.authority_posture || "Connector certification state",
    tags: [value.state || "unknown", value.credential_boundary?.credential_source || "config"],
    version: value.schema_version || "v1",
  }));

  return (
    <div className="content-stack">
      <Toolbar
        title="Environments Hub"
        detail={connectorPosture.reason}
        action="Open Control Plane"
        onAction={() => setView("legacy")}
      />
      <SearchBar />
      <CardRows sections={[{ title: "Connectors", count: cards.length, cards }]} />
    </div>
  );
}

function EvaluationsView({ dashboard, setView }: { dashboard: DashboardPayload; setView: (view: ViewKey) => void }) {
  const launchPosture = operatorWorkflowPosture("launch");
  const runs = dashboard.mesh.runs?.runs || [];
  const active = runs.filter((run: any) => !["completed", "failed", "cancelled"].includes(run.status)).length;
  const failed = runs.filter((run: any) => run.status === "failed").length;
  const traceSteps = evidenceTraceSteps(dashboard);
  return (
    <div className="content-stack">
      <Toolbar
        title="Evaluations"
        detail={launchPosture.reason}
        action="Open Control Plane"
        onAction={() => setView("legacy")}
      />
      <div className="stat-row">
        <Stat label="Active evals" value={String(active)} detail="Pending, running, or processing" />
        <Stat label="Failed evals" value={String(failed)} detail="Failed or timed out evaluations" />
        <Stat label="Total evals" value={String(runs.length)} detail="All evaluations in this account" />
      </div>
      <TraceRail steps={traceSteps} />
      <SearchBar placeholder="Search by run, scenario, model..." />
      <div className="data-table">
        <div className="table-head"><span>Name</span><span>Scenario</span><span>Status</span><span>Created</span><span>Created by</span></div>
        {runs.length ? runs.map((run: any) => (
          <div className="table-row" key={run.run_id}>
            <span>{run.run_id}</span><span>{run.scenario_key || "custom"}</span><span>{run.status}</span><span>{run.created_at}</span><span>{run.operator_id || "Mesh"}</span>
          </div>
        )) : (
          <div className="empty-eval"><BarChart3 size={24} /><strong>Run your first evaluation</strong><p>Launch from the preserved control-plane view or CLI. Mesh will own admission and policy.</p></div>
        )}
      </div>
    </div>
  );
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
  onLogout,
  loggingOut,
}: {
  session: SessionPayload;
  dashboard: DashboardPayload;
  onLogout: () => void;
  loggingOut: boolean;
}) {
  const team = session.active_team;
  return (
    <div className="settings-layout">
      <section className="profile-panel">
        <h2>Team Settings</h2>
        <p>Manage product profile and preferences for the active dashboard scope.</p>
        <div className="avatar-disc">{team?.name?.[0] || session.user.display_name[0]}</div>
        <FormRead label="ID" value={team?.id || session.user.id} />
        <FormRead label="Email" value={session.user.email} />
        <FormRead label="Team Name" value={team?.name || "Solo mode"} />
        <FormRead label="Team Username" value={team?.slug || "solo"} />
        <FormRead label="Bio" value="Mesh operator dashboard. Runtime authority remains with Mesh." large />
        <div className="button-row">
          <button type="button" onClick={onLogout} disabled={loggingOut}>{loggingOut ? "Logging out" : "Log out"}</button>
          <button
            className="primary-button"
            type="button"
            disabled
            title="Read-only: team profile mutation API is not exposed by Mesh yet."
          >
            Save
          </button>
        </div>
      </section>
      <SettingsView dashboard={dashboard} compact />
    </div>
  );
}

function MembersView({ session, setView }: { session: SessionPayload; setView: (view: ViewKey) => void }) {
  const members = session.active_team?.members || [{ email: session.user.email, role: "owner", status: "active" }];
  return (
    <div className="content-stack">
      <Toolbar title="Members" detail="Team roles map into Mesh operator roles for protected actions." action="Manage Team" onAction={() => setView("team")} />
      <div className="data-table compact">
        <div className="table-head"><span>Email</span><span>Role</span><span>Status</span></div>
        {members.map((member) => <div className="table-row" key={member.email}><span>{member.email}</span><span>{member.role}</span><span>{member.status}</span></div>)}
      </div>
    </div>
  );
}

function SettingsView({ dashboard, compact = false }: { dashboard: DashboardPayload; compact?: boolean }) {
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
    setMessage("");
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
      setMessage(`Saved ${response.audit.fields.join(", ")} for ${response.audit.scope}.`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Settings update failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className={compact ? "settings-panel compact" : "settings-panel"}>
      <h2>Configuration</h2>
      <p>{settingsPosture.reason} Mesh runtime-critical values are read-only here.</p>
      <div className="setting-grid">
        {Object.entries(dashboard.settings_schema).map(([key, schema]) => (
          <div className="setting-card" key={key}>
            <span>{key}</span>
            <select value={draft[key] || schema.default} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })}>
              {schema.values.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
            <p>{schema.description}</p>
            <code>python scripts/operator_config.py set --scope {dashboard.scope.team ? `team:${dashboard.scope.team.id}` : `user:${dashboard.session.user.id}`} {key}=...</code>
          </div>
        ))}
        {[
          ["API base URL", "Read-only: browser runtime target"],
          ["Build commit", dashboard.mesh.health?.commit || "unknown"],
          ["State backend", dashboard.mesh.readiness?.state_backend || "RuntimeConfig-owned"],
          ["Captcha provider", "Auth config owned by environment"],
        ].map(([label, value]) => (
          <div className="setting-card readonly" key={label}>
            <span>{label}</span><strong>{value}</strong><p>Read-only in UI. Change via environment or deployment config.</p>
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
  const labels: Record<string, string> = {
    training: "Training",
    inference: "Inference",
    gpu: "On-Demand GPUs",
    clusters: "Reserved Clusters",
    instances: "Team Instances",
    keys: "Keys & Secrets",
  };
  return (
    <div className="content-stack">
      <Toolbar
        title={labels[view] || view}
        detail={workflowPosture.reason}
        action="Open Control Plane"
        onAction={() => setView("legacy")}
      />
      <div className="capability-grid two">
        <ReadModelCard title="Runtime readiness" payload={dashboard.mesh.readiness} />
        <ReadModelCard title="Policy state" payload={dashboard.mesh.approvals} />
        <ReadModelCard title="Connector proof" payload={dashboard.mesh.connectors} />
        <ReadModelCard title="Memory projection" payload={dashboard.mesh.memory} />
      </div>
    </div>
  );
}

export function workflowForView(view: ViewKey): OperatorWorkflowKey {
  if (view === "keys" || view === "settings") return "settings";
  if (view === "environments") return "connector";
  if (view === "evaluations") return "launch";
  if (view === "training" || view === "inference" || view === "gpu" || view === "clusters" || view === "instances") return "readiness";
  return "evidence";
}

function ReadModelCard({ title, payload }: { title: string; payload: any }) {
  const displayPayload = readModelCardPayload(title, payload);
  const status = displayPayload.status || displayPayload.state || "read-only";
  return (
    <section className="read-model-card">
      <CircleDot size={15} />
      <strong>{title}</strong>
      <span>{status}</span>
      <pre>{JSON.stringify(displayPayload, null, 2).slice(0, 480)}</pre>
    </section>
  );
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

function SearchBar({ placeholder = "Search by name, author, description, tags..." }: { placeholder?: string }) {
  return <label className="search-bar"><Search size={16} /><input placeholder={placeholder} /></label>;
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
                <div><span>{card.owner}</span><span>{card.stars} <Sparkles size={12} /></span></div>
                <h4>{card.title}</h4>
                <p>{card.detail}</p>
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
