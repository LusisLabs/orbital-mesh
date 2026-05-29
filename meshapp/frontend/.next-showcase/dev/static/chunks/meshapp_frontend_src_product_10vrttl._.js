(globalThis["TURBOPACK"] || (globalThis["TURBOPACK"] = [])).push([typeof document === "object" ? document.currentScript : undefined,
"[project]/meshapp/frontend/src/product/entryMode.ts [app-client] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "shouldRenderLanding",
    ()=>shouldRenderLanding
]);
const APP_HOST = "app.lusislabs.com";
const MARKETING_HOSTS = new Set([
    "lusislabs.com",
    "www.lusislabs.com"
]);
const LOCAL_HOSTS = new Set([
    "localhost",
    "127.0.0.1",
    "::1",
    "[::1]"
]);
function shouldRenderLanding(hostname, search = "") {
    const normalizedHost = hostname.toLowerCase();
    const params = new URLSearchParams(search);
    if (params.get("landing") === "1") return true;
    if (params.get("app") === "1") return false;
    if (normalizedHost === APP_HOST) return false;
    if (LOCAL_HOSTS.has(normalizedHost)) return false;
    return MARKETING_HOSTS.has(normalizedHost);
}
if (typeof globalThis.$RefreshHelpers$ === 'object' && globalThis.$RefreshHelpers !== null) {
    __turbopack_context__.k.registerExports(__turbopack_context__.m, globalThis.$RefreshHelpers$);
}
}),
"[project]/meshapp/frontend/src/product/api.ts [app-client] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "HttpError",
    ()=>HttpError,
    "backendUnavailableMessage",
    ()=>backendUnavailableMessage,
    "loadStateFromError",
    ()=>loadStateFromError,
    "normalizeLoopbackBaseUrl",
    ()=>normalizeLoopbackBaseUrl,
    "productApi",
    ()=>productApi,
    "resolveBaseUrl",
    ()=>resolveBaseUrl
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$build$2f$polyfills$2f$process$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = /*#__PURE__*/ __turbopack_context__.i("[project]/node_modules/.pnpm/next@16.2.6_@playwright+test@1.60.0_react-dom@19.2.6_react@19.2.6__react@19.2.6/node_modules/next/dist/build/polyfills/process.js [app-client] (ecmascript)");
class HttpError extends Error {
    status;
    constructor(status, message){
        super(message);
        this.status = status;
    }
}
const DEFAULT_API_BASE_URL = ("TURBOPACK compile-time value", "http://127.0.0.1:8799")?.trim() || "http://127.0.0.1:8787";
const LOOPBACK_HOSTS = new Set([
    "localhost",
    "127.0.0.1",
    "::1",
    "[::1]"
]);
function isLoopbackHost(hostname) {
    return LOOPBACK_HOSTS.has(hostname.toLowerCase());
}
function normalizeLoopbackBaseUrl(baseUrl, pageLocation) {
    const trimmed = baseUrl.replace(/\/+$/, "");
    if (!pageLocation?.hostname || !isLoopbackHost(pageLocation.hostname)) return trimmed;
    try {
        const parsed = new URL(trimmed);
        if (!isLoopbackHost(parsed.hostname) || parsed.hostname === pageLocation.hostname) return trimmed;
        parsed.hostname = pageLocation.hostname;
        return parsed.toString().replace(/\/+$/, "");
    } catch  {
        return trimmed;
    }
}
function resolveBaseUrl() {
    if ("TURBOPACK compile-time falsy", 0) //TURBOPACK unreachable
    ;
    const params = new URLSearchParams(window.location.search);
    const explicitServer = params.get("server");
    if (explicitServer) return explicitServer.replace(/\/+$/, "");
    const configured = ("TURBOPACK compile-time value", "http://127.0.0.1:8799")?.trim();
    if (configured) {
        return normalizeLoopbackBaseUrl(configured, window.location);
    }
    if (window.location.protocol === "http:" || window.location.protocol === "https:") {
        return window.location.origin;
    }
    return normalizeLoopbackBaseUrl(DEFAULT_API_BASE_URL, window.location);
}
function backendUnavailableMessage() {
    return `Mesh API unavailable at ${resolveBaseUrl()}. Start the control-plane API, then reload. Local dev: MESH_AUTH_MODE=app_session MESH_CAPTCHA_DEV_BYPASS=1 python run_server.py`;
}
async function request(path, init) {
    const controller = new AbortController();
    const timeout = window.setTimeout(()=>controller.abort(), 8_000);
    try {
        const response = await fetch(`${resolveBaseUrl()}${path}`, {
            credentials: "include",
            headers: {
                "Content-Type": "application/json",
                ...init?.headers ?? {}
            },
            signal: init?.signal ?? controller.signal,
            ...init
        });
        if (!response.ok) {
            let detail = `${response.status} ${response.statusText}`;
            try {
                const body = await response.json();
                detail = body?.error || body?.detail || body?.message || detail;
            } catch  {
            /* non-json error */ }
            throw new HttpError(response.status, detail);
        }
        return await response.json();
    } catch (error) {
        if (error instanceof HttpError) throw error;
        if (error instanceof DOMException && error.name === "AbortError") {
            throw new HttpError(0, `Mesh API timed out at ${resolveBaseUrl()}`);
        }
        throw new HttpError(0, backendUnavailableMessage());
    } finally{
        window.clearTimeout(timeout);
    }
}
function loadStateFromError(error) {
    if (error instanceof HttpError) {
        if (error.status === 0) return {
            state: "backend-unavailable",
            message: error.message
        };
        if (error.status === 401) return {
            state: "unauthorized",
            message: error.message
        };
        if (error.status === 403) return {
            state: "forbidden",
            message: error.message
        };
        if (error.status >= 500) return {
            state: "backend-unavailable",
            message: error.message
        };
        return {
            state: "error",
            message: error.message
        };
    }
    return {
        state: "backend-unavailable",
        message: error instanceof Error ? error.message : "Backend unavailable"
    };
}
const productApi = {
    health () {
        return request("/api/health");
    },
    authConfig () {
        return request("/api/auth/config");
    },
    me () {
        return request("/api/auth/me");
    },
    signup (payload) {
        return request("/api/auth/signup", {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    login (payload) {
        return request("/api/auth/login", {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    logout () {
        return request("/api/auth/logout", {
            method: "POST",
            body: "{}"
        });
    },
    oauthStart (provider) {
        return request(`/api/auth/oauth/${provider}/start`);
    },
    createTeam (payload) {
        return request("/api/auth/team", {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    updateTeam (payload) {
        return request("/api/auth/team/update", {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    upsertTeamMembers (payload) {
        return request("/api/auth/team/members", {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    switchTeam (teamId) {
        return request("/api/auth/switch-team", {
            method: "POST",
            body: JSON.stringify({
                team_id: teamId
            })
        });
    },
    dashboard (teamId) {
        const query = teamId ? `?team_id=${encodeURIComponent(teamId)}` : "";
        return request(`/api/operator/dashboard${query}`);
    },
    agentFlowChat (payload) {
        return request("/api/operator/agent-flow/chat", {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    agentFlowLiveKitSession (payload) {
        return request("/api/operator/agent-flow/livekit-session", {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    confirmAgentFlowPreview (payload) {
        return request("/api/operator/agent-flow/confirm-preview", {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    updateSettings (teamId, settings, reason) {
        return request("/api/operator/settings", {
            method: "POST",
            body: JSON.stringify({
                team_id: teamId,
                settings,
                reason
            })
        });
    },
    updateOperatorPreferences (teamId, operatorPreferences, reason) {
        return request("/api/operator/preferences", {
            method: "POST",
            body: JSON.stringify({
                team_id: teamId,
                operator_preferences: operatorPreferences,
                reason
            })
        });
    },
    createRun (payload) {
        return request("/api/runs", {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    steerRun (runId, payload) {
        return request(`/api/runs/${encodeURIComponent(runId)}/steer`, {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    runDetail (runId) {
        return request(`/api/runs/${encodeURIComponent(runId)}`);
    },
    runEvents (runId) {
        return request(`/api/runs/${encodeURIComponent(runId)}/events`);
    },
    evidenceGraph (runId) {
        return request(`/api/runs/${encodeURIComponent(runId)}/evidence-graph`);
    },
    scenarioAnalysis (runId) {
        return request(`/api/runs/${encodeURIComponent(runId)}/scenario-analysis`);
    },
    merkle (runId) {
        return request(`/api/runs/${encodeURIComponent(runId)}/merkle`);
    },
    timelineProof (runId) {
        return request(`/api/runs/${encodeURIComponent(runId)}/timeline-proof`);
    },
    exportRun (runId) {
        return request(`/api/runs/${encodeURIComponent(runId)}/export`, {
            method: "POST",
            body: "{}"
        });
    },
    praxisRuns (teamId) {
        const query = teamId ? `?team_id=${encodeURIComponent(teamId)}` : "";
        return request(`/api/operator/praxis/runs${query}`);
    },
    createPraxisGenerationRequest (payload) {
        return request("/api/operator/praxis/generation-requests", {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    importPraxisAktoEvidence (requestId, payload) {
        return request(`/api/operator/praxis/generation-requests/${encodeURIComponent(requestId)}/akto-evidence`, {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    buildPraxisCertificationBinding (requestId, payload) {
        return request(`/api/operator/praxis/generation-requests/${encodeURIComponent(requestId)}/certification-binding`, {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    startPraxisDryRunEndpoint (requestId, payload) {
        return request(`/api/operator/praxis/generation-requests/${encodeURIComponent(requestId)}/dry-run/start`, {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    callPraxisDryRunTool (requestId, payload) {
        return request(`/api/operator/praxis/generation-requests/${encodeURIComponent(requestId)}/dry-run/call`, {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    praxisMcp (requestId, payload) {
        return request(`/api/operator/praxis/generation-requests/${encodeURIComponent(requestId)}/mcp`, {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    revokePraxisGeneratedConnector (requestId, payload) {
        return request(`/api/operator/praxis/generation-requests/${encodeURIComponent(requestId)}/revoke`, {
            method: "POST",
            body: JSON.stringify(payload)
        });
    },
    exportPraxisP10Proof (requestId, teamId) {
        const query = teamId ? `?team_id=${encodeURIComponent(teamId)}` : "";
        return request(`/api/operator/praxis/runs/${encodeURIComponent(requestId)}/p10-proof${query}`);
    },
    hardenedArenaProfiles () {
        return request("/api/hardened-arena/profiles");
    },
    hardenedArenaCatalog () {
        return request("/api/hardened-arena/catalog");
    },
    generateHardenedArenaPacket (profileId) {
        return request("/api/hardened-arena/packets", {
            method: "POST",
            body: JSON.stringify({
                profile_id: profileId
            })
        });
    },
    hardenedArenaPacket (packetId) {
        return request(`/api/hardened-arena/packets/${encodeURIComponent(packetId)}`);
    }
};
if (typeof globalThis.$RefreshHelpers$ === 'object' && globalThis.$RefreshHelpers !== null) {
    __turbopack_context__.k.registerExports(__turbopack_context__.m, globalThis.$RefreshHelpers$);
}
}),
"[project]/meshapp/frontend/src/product/ProductApp.tsx [app-client] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "AuthScreen",
    ()=>AuthScreen,
    "agentFlowVoiceUnavailableMessage",
    ()=>agentFlowVoiceUnavailableMessage,
    "approvalCommands",
    ()=>approvalCommands,
    "askMesh",
    ()=>askMesh,
    "authCallbackErrorMessage",
    ()=>authCallbackErrorMessage,
    "authFailureMessage",
    ()=>authFailureMessage,
    "buildAgentFabricObservability",
    ()=>buildAgentFabricObservability,
    "buildDashboardControlModel",
    ()=>buildDashboardControlModel,
    "buildDashboardInsights",
    ()=>buildDashboardInsights,
    "buildDashboardTiles",
    ()=>buildDashboardTiles,
    "buildHardenedArenaProfileCards",
    ()=>buildHardenedArenaProfileCards,
    "buildKeysReadinessRows",
    ()=>buildKeysReadinessRows,
    "buildOperatorSetupModel",
    ()=>buildOperatorSetupModel,
    "buildPartnerHomeModel",
    ()=>buildPartnerHomeModel,
    "buildPraxisProductModel",
    ()=>buildPraxisProductModel,
    "buildRunPreflightModel",
    ()=>buildRunPreflightModel,
    "buildRunWorkbenchModel",
    ()=>buildRunWorkbenchModel,
    "canAttemptHarperVoiceConnection",
    ()=>canAttemptHarperVoiceConnection,
    "consoleParityMatrix",
    ()=>consoleParityMatrix,
    "consoleWorkflowForView",
    ()=>consoleWorkflowForView,
    "dashboardLoadSurfaceState",
    ()=>dashboardLoadSurfaceState,
    "dashboardSectionState",
    ()=>dashboardSectionState,
    "default",
    ()=>ProductApp,
    "defaultLensForSession",
    ()=>defaultLensForSession,
    "evidenceTraceSteps",
    ()=>evidenceTraceSteps,
    "isConsoleProductView",
    ()=>isConsoleProductView,
    "isLiveKitSessionFresh",
    ()=>isLiveKitSessionFresh,
    "lensStorageKey",
    ()=>lensStorageKey,
    "operatorWorkflowPosture",
    ()=>operatorWorkflowPosture,
    "orderDashboardInsights",
    ()=>orderDashboardInsights,
    "orderDashboardTiles",
    ()=>orderDashboardTiles,
    "readModelCardPayload",
    ()=>readModelCardPayload,
    "readModelSummary",
    ()=>readModelSummary,
    "runtimeProductPage",
    ()=>runtimeProductPage,
    "sensitivityBadgesForSource",
    ()=>sensitivityBadgesForSource,
    "settingsParityRows",
    ()=>settingsParityRows,
    "workflowForView",
    ()=>workflowForView
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/next@16.2.6_@playwright+test@1.60.0_react-dom@19.2.6_react@19.2.6__react@19.2.6/node_modules/next/dist/compiled/react/jsx-dev-runtime.js [app-client] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$activity$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Activity$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/activity.js [app-client] (ecmascript) <export default as Activity>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$triangle$2d$alert$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__AlertTriangle$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/triangle-alert.js [app-client] (ecmascript) <export default as AlertTriangle>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$arrow$2d$right$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__ArrowRight$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/arrow-right.js [app-client] (ecmascript) <export default as ArrowRight>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$chart$2d$column$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__BarChart3$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/chart-column.js [app-client] (ecmascript) <export default as BarChart3>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$book$2d$open$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__BookOpen$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/book-open.js [app-client] (ecmascript) <export default as BookOpen>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$bot$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Bot$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/bot.js [app-client] (ecmascript) <export default as Bot>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$boxes$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Boxes$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/boxes.js [app-client] (ecmascript) <export default as Boxes>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$calendar$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Calendar$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/calendar.js [app-client] (ecmascript) <export default as Calendar>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$circle$2d$check$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__CheckCircle2$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/circle-check.js [app-client] (ecmascript) <export default as CheckCircle2>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$chevron$2d$down$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__ChevronDown$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/chevron-down.js [app-client] (ecmascript) <export default as ChevronDown>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$circle$2d$dot$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__CircleDot$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/circle-dot.js [app-client] (ecmascript) <export default as CircleDot>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$cpu$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Cpu$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/cpu.js [app-client] (ecmascript) <export default as Cpu>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$database$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Database$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/database.js [app-client] (ecmascript) <export default as Database>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$file$2d$check$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__FileCheck$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/file-check.js [app-client] (ecmascript) <export default as FileCheck>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$github$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Github$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/github.js [app-client] (ecmascript) <export default as Github>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$globe$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Globe$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/globe.js [app-client] (ecmascript) <export default as Globe>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$house$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Home$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/house.js [app-client] (ecmascript) <export default as Home>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$key$2d$round$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__KeyRound$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/key-round.js [app-client] (ecmascript) <export default as KeyRound>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$layers$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Layers$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/layers.js [app-client] (ecmascript) <export default as Layers>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$lock$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Lock$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/lock.js [app-client] (ecmascript) <export default as Lock>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$log$2d$out$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__LogOut$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/log-out.js [app-client] (ecmascript) <export default as LogOut>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$mail$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Mail$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/mail.js [app-client] (ecmascript) <export default as Mail>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$network$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Network$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/network.js [app-client] (ecmascript) <export default as Network>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$play$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Play$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/play.js [app-client] (ecmascript) <export default as Play>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$refresh$2d$cw$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__RefreshCw$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/refresh-cw.js [app-client] (ecmascript) <export default as RefreshCw>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$search$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Search$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/search.js [app-client] (ecmascript) <export default as Search>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$settings$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Settings$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/settings.js [app-client] (ecmascript) <export default as Settings>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$shield$2d$check$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__ShieldCheck$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/shield-check.js [app-client] (ecmascript) <export default as ShieldCheck>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$sliders$2d$horizontal$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__SlidersHorizontal$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/sliders-horizontal.js [app-client] (ecmascript) <export default as SlidersHorizontal>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$sparkles$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Sparkles$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/sparkles.js [app-client] (ecmascript) <export default as Sparkles>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$users$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Users$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/users.js [app-client] (ecmascript) <export default as Users>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$zap$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Zap$3e$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/lucide-react@0.562.0_react@19.2.6/node_modules/lucide-react/dist/esm/icons/zap.js [app-client] (ecmascript) <export default as Zap>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/.pnpm/next@16.2.6_@playwright+test@1.60.0_react-dom@19.2.6_react@19.2.6__react@19.2.6/node_modules/next/dist/compiled/react/index.js [app-client] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$landing$2f$AsciiFlowCanvas$2e$tsx__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/meshapp/frontend/src/landing/AsciiFlowCanvas.tsx [app-client] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$App$2e$tsx__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/meshapp/frontend/src/App.tsx [app-client] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$components$2f$ui$2f$agent$2d$lifecycle$2d$plan$2e$tsx__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/meshapp/frontend/components/ui/agent-lifecycle-plan.tsx [app-client] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$components$2f$ui$2f$prompt$2d$input$2d$box$2e$tsx__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/meshapp/frontend/components/ui/prompt-input-box.tsx [app-client] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/meshapp/frontend/src/product/api.ts [app-client] (ecmascript)");
;
var _s = __turbopack_context__.k.signature(), _s1 = __turbopack_context__.k.signature(), _s2 = __turbopack_context__.k.signature(), _s3 = __turbopack_context__.k.signature(), _s4 = __turbopack_context__.k.signature(), _s5 = __turbopack_context__.k.signature(), _s6 = __turbopack_context__.k.signature(), _s7 = __turbopack_context__.k.signature(), _s8 = __turbopack_context__.k.signature(), _s9 = __turbopack_context__.k.signature(), _s10 = __turbopack_context__.k.signature(), _s11 = __turbopack_context__.k.signature(), _s12 = __turbopack_context__.k.signature(), _s13 = __turbopack_context__.k.signature(), _s14 = __turbopack_context__.k.signature(), _s15 = __turbopack_context__.k.signature(), _s16 = __turbopack_context__.k.signature(), _s17 = __turbopack_context__.k.signature(), _s18 = __turbopack_context__.k.signature();
"use client";
;
;
;
;
;
;
;
const VIEW_KEYS = new Set([
    "home",
    "console",
    "console-runs",
    "console-approvals",
    "console-launch",
    "console-simulator",
    "console-trust",
    "console-packets",
    "console-readiness",
    "console-evidence",
    "console-connectors",
    "console-agents",
    "console-signals",
    "console-hermes",
    "console-audit",
    "console-roadmap",
    "praxis",
    "agent-flow",
    "hardened-arena",
    "environments",
    "evaluations",
    "training",
    "inference",
    "gpu",
    "clusters",
    "instances",
    "team",
    "members",
    "keys",
    "operator-setup",
    "settings"
]);
function isViewKey(value) {
    return Boolean(value && VIEW_KEYS.has(value));
}
function useMeshApiConnection(enabled) {
    _s();
    const [connection, setConnection] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("checking");
    const [apiBase, setApiBase] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "useMeshApiConnection.useEffect": ()=>{
            if (!enabled || ("TURBOPACK compile-time value", "object") === "undefined") return undefined;
            setApiBase((0, __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["resolveBaseUrl"])());
            let cancelled = false;
            async function ping() {
                try {
                    await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].health();
                    if (!cancelled) setConnection("connected");
                } catch  {
                    if (!cancelled) setConnection("offline");
                }
            }
            setConnection("checking");
            ping();
            const interval = window.setInterval(ping, 30_000);
            return ({
                "useMeshApiConnection.useEffect": ()=>{
                    cancelled = true;
                    window.clearInterval(interval);
                }
            })["useMeshApiConnection.useEffect"];
        }
    }["useMeshApiConnection.useEffect"], [
        enabled
    ]);
    return {
        connection,
        apiBase
    };
}
_s(useMeshApiConnection, "aLaYtFZNSd5CfTBajaH5Rx4tJx4=");
function BackendStatusChip({ connection, apiBase }) {
    const label = connection === "connected" ? "API connected" : connection === "checking" ? "Checking API" : "API offline";
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: `backend-status ${connection}`,
        title: apiBase || "Mesh control plane",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                className: "backend-status-dot",
                "aria-hidden": "true"
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 175,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                children: label
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 176,
                columnNumber: 7
            }, this),
            apiBase ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                children: apiBase.replace(/^https?:\/\//, "")
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 177,
                columnNumber: 18
            }, this) : null
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 174,
        columnNumber: 5
    }, this);
}
_c = BackendStatusChip;
function clearAgentFlowAudioElements() {
    if (typeof document === "undefined") return;
    document.querySelectorAll("[data-agent-flow-audio='harper-696']").forEach((element)=>{
        element.pause();
        element.remove();
    });
}
function attachAgentFlowAudioTrack(track) {
    if (typeof document === "undefined" || track.kind !== "audio") return;
    const element = track.attach();
    element.autoplay = true;
    element.dataset.agentFlowAudio = "harper-696";
    element.style.display = "none";
    document.body.appendChild(element);
}
function isLiveKitSessionFresh(session) {
    if (!session?.token || !session.livekit_url || session.status !== "ready") return false;
    if (!session.token_expires_at) return true;
    const expiresAt = Date.parse(session.token_expires_at);
    return Number.isFinite(expiresAt) && expiresAt - Date.now() > 60_000;
}
function agentFlowVoiceUnavailableMessage(status) {
    if (status === "permission_required") {
        return "LiveKit voice publishing requires a launcher, approver, or admin role for mesh.agent_flow.livekit_session.v1.";
    }
    if (status === "expired") {
        return "LiveKit voice token expired for mesh.agent_flow.livekit_session.v1. Rotate MESH_LIVEKIT_ACCESS_TOKEN or configure MESH_LIVEKIT_API_KEY and MESH_LIVEKIT_API_SECRET.";
    }
    if (status === "invalid_token") {
        return "LiveKit voice token is invalid for mesh.agent_flow.livekit_session.v1.";
    }
    return "LiveKit is not configured for mesh.agent_flow.livekit_session.v1.";
}
function canAttemptHarperVoiceConnection(session, voiceStatus) {
    return voiceStatus === "connected" || voiceStatus !== "connecting" && Boolean(session);
}
const NAV_GROUPS = [
    {
        label: "Product",
        items: [
            {
                key: "home",
                label: "Home",
                icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$house$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Home$3e$__["Home"]
            },
            {
                key: "praxis",
                label: "Praxis",
                icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$sparkles$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Sparkles$3e$__["Sparkles"]
            },
            {
                key: "agent-flow",
                label: "Agent Flow",
                icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$bot$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Bot$3e$__["Bot"]
            },
            {
                key: "hardened-arena",
                label: "Build Arena",
                icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$shield$2d$check$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__ShieldCheck$3e$__["ShieldCheck"]
            },
            {
                key: "evaluations",
                label: "Evaluations",
                icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$chart$2d$column$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__BarChart3$3e$__["BarChart3"]
            },
            {
                key: "environments",
                label: "Connectors",
                icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$boxes$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Boxes$3e$__["Boxes"]
            },
            {
                key: "gpu",
                label: "Readiness",
                icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$cpu$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Cpu$3e$__["Cpu"]
            },
            {
                key: "instances",
                label: "Policy State",
                icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$layers$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Layers$3e$__["Layers"]
            }
        ]
    },
    {
        label: "Runtime",
        items: [
            {
                key: "training",
                label: "Topology",
                icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$network$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Network$3e$__["Network"]
            },
            {
                key: "inference",
                label: "Memory Projection",
                icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$database$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Database$3e$__["Database"]
            },
            {
                key: "clusters",
                label: "Kill Switch",
                icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$calendar$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Calendar$3e$__["Calendar"]
            }
        ]
    },
    {
        label: "Team",
        items: [
            {
                key: "team",
                label: "Team Settings",
                icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$settings$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Settings$3e$__["Settings"]
            },
            {
                key: "members",
                label: "Members",
                icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$users$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Users$3e$__["Users"]
            },
            {
                key: "keys",
                label: "Keys & Secrets",
                icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$key$2d$round$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__KeyRound$3e$__["KeyRound"]
            },
            {
                key: "operator-setup",
                label: "Operator Setup",
                icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$sliders$2d$horizontal$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__SlidersHorizontal$3e$__["SlidersHorizontal"]
            },
            {
                key: "settings",
                label: "Settings",
                icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$sliders$2d$horizontal$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__SlidersHorizontal$3e$__["SlidersHorizontal"]
            }
        ]
    }
];
const ADVANCED_CONSOLE_NAV_ITEMS = [
    {
        key: "console",
        label: "Command",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$house$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Home$3e$__["Home"]
    },
    {
        key: "console-runs",
        label: "Evidence Runs",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$activity$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Activity$3e$__["Activity"]
    },
    {
        key: "console-approvals",
        label: "Approvals",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$lock$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Lock$3e$__["Lock"]
    },
    {
        key: "console-launch",
        label: "Launch",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$play$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Play$3e$__["Play"]
    },
    {
        key: "console-readiness",
        label: "Control Plane",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$cpu$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Cpu$3e$__["Cpu"]
    },
    {
        key: "console-evidence",
        label: "Evidence",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$shield$2d$check$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__ShieldCheck$3e$__["ShieldCheck"]
    },
    {
        key: "console-connectors",
        label: "Connector Matrix",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$boxes$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Boxes$3e$__["Boxes"]
    },
    {
        key: "console-packets",
        label: "Pilot Packet",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$book$2d$open$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__BookOpen$3e$__["BookOpen"]
    },
    {
        key: "console-hermes",
        label: "Hermes",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$sparkles$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Sparkles$3e$__["Sparkles"]
    },
    {
        key: "console-agents",
        label: "Proposal Lanes",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$network$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Network$3e$__["Network"]
    },
    {
        key: "console-signals",
        label: "Signals",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$zap$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Zap$3e$__["Zap"]
    },
    {
        key: "console-simulator",
        label: "Simulator",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$layers$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Layers$3e$__["Layers"]
    },
    {
        key: "console-trust",
        label: "Trust Ladder",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$shield$2d$check$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__ShieldCheck$3e$__["ShieldCheck"]
    },
    {
        key: "console-audit",
        label: "Audit",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$search$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Search$3e$__["Search"]
    },
    {
        key: "console-roadmap",
        label: "Roadmap",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$calendar$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Calendar$3e$__["Calendar"]
    }
];
const CONSOLE_WORKFLOW_MATRIX = [
    {
        productView: "console",
        consoleView: "overview",
        productFallback: "home",
        label: "Command",
        description: "Production readiness cockpit, live system stream, launch prompts, and active run context."
    },
    {
        productView: "console-runs",
        consoleView: "runs",
        productFallback: "evaluations",
        label: "Evidence Runs",
        description: "Run timeline, delivery context, evidence graph, RCA, approvals, actions, Darkharness, audit, agents, and topology."
    },
    {
        productView: "console-approvals",
        consoleView: "approvals",
        productFallback: "evaluations",
        label: "Approvals",
        description: "Approval queue, steering commands, operator notes, and Hermes escalation hooks."
    },
    {
        productView: "console-launch",
        consoleView: "automation",
        productFallback: "evaluations",
        label: "Launch",
        description: "Goal creation, scenario launch, evaluation mode, orchestration mode, steering mode, and target lock controls."
    },
    {
        productView: "console-simulator",
        consoleView: "simulator",
        productFallback: "evaluations",
        label: "Simulator",
        description: "Scenario simulator and policy dry-run controls backed by Mesh admission and evaluation state."
    },
    {
        productView: "console-trust",
        consoleView: "trust",
        productFallback: "instances",
        label: "Trust Ladder",
        description: "Trust ladder entries, autonomy tiers, service authority, and promotion posture."
    },
    {
        productView: "console-packets",
        consoleView: "packets",
        productFallback: "evaluations",
        label: "Pilot Packet",
        description: "Pilot go/no-go, Darkharness packet, evidence packet, release proof, and boundary status."
    },
    {
        productView: "console-readiness",
        consoleView: "control-plane",
        productFallback: "gpu",
        label: "Readiness",
        description: "Control-plane readiness, connector certification, watcher state, kill switch, and deployment blockers."
    },
    {
        productView: "console-evidence",
        consoleView: "evidence",
        productFallback: "evaluations",
        label: "Evidence",
        description: "Evidence graph, proof drill-ins, selected event context, Merkle continuity, and export path."
    },
    {
        productView: "console-connectors",
        consoleView: "integrations",
        productFallback: "environments",
        label: "Connectors",
        description: "Connector certification matrix, credential boundaries, authority posture, and integration groups."
    },
    {
        productView: "console-agents",
        consoleView: "agents",
        productFallback: "training",
        label: "Proposal Lanes",
        description: "Hermes, Goose, native, custom HTTP agent lanes, certification, and bounded proposal posture."
    },
    {
        productView: "console-signals",
        consoleView: "fleet",
        productFallback: "gpu",
        label: "Signals",
        description: "Fleet health, watcher signals, live events, and system stream status."
    },
    {
        productView: "console-hermes",
        consoleView: "hermes",
        productFallback: "evaluations",
        label: "Hermes",
        description: "Hermes chat, explanation, advisory context, and steering-bound operator interaction."
    },
    {
        productView: "console-audit",
        consoleView: "audit",
        productFallback: "evaluations",
        label: "Audit",
        description: "Timeline proof, Merkle proof, evidence continuity, operator audit, and export validation."
    },
    {
        productView: "console-roadmap",
        consoleView: "roadmap",
        productFallback: "home",
        label: "Roadmap",
        description: "Operator roadmap, release gates, readiness milestones, and migration status."
    }
];
function consoleParityMatrix() {
    return CONSOLE_WORKFLOW_MATRIX;
}
function isConsoleProductView(view) {
    return CONSOLE_WORKFLOW_MATRIX.some((workflow)=>workflow.productView === view);
}
function consoleWorkflowForView(view) {
    return CONSOLE_WORKFLOW_MATRIX.find((workflow)=>workflow.productView === view) ?? CONSOLE_WORKFLOW_MATRIX[0];
}
function operatorWorkflowPosture(workflow) {
    const postures = {
        launch: {
            callPath: "/api/operator/dashboard mesh.runs and Mesh-owned POST /api/runs admission",
            posture: "native",
            reason: "Run launch is product-native, but mutation still goes through Mesh-owned /api/runs admission, role checks, policy, and audit context."
        },
        approval: {
            callPath: "/api/operator/dashboard mesh.approvals and Mesh-owned /api/runs/{run_id}/steer",
            posture: "read_only",
            reason: "Approval state is embedded in the dashboard. Steering remains Mesh-controlled and is not bypassed by this product shell."
        },
        evidence: {
            callPath: "/api/runs/{run_id}/evidence-graph and export endpoints",
            posture: "read_only",
            reason: "Evidence is inspectable here as a read model; Mesh remains the evidence and export authority."
        },
        readiness: {
            callPath: "/api/readiness through /api/operator/dashboard",
            posture: "read_only",
            reason: "Readiness is a Mesh-owned read model in the product shell; remediation and actuation stay in Mesh."
        },
        connector: {
            callPath: "/api/connectors/certification through /api/operator/dashboard",
            posture: "read_only",
            reason: "Connector certification is read-only here until Mesh exposes a product-native mutation endpoint."
        },
        settings: {
            callPath: "/api/operator/settings and scripts/operator_config.py",
            posture: "native",
            reason: "Settings mutate the shared validated settings slice used by the UI and CLI."
        }
    };
    return postures[workflow];
}
function ProductApp() {
    _s1();
    const [authConfig, setAuthConfig] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(null);
    const [session, setSession] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(null);
    const [sessionState, setSessionState] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])({
        state: "loading"
    });
    const [dashboardState, setDashboardState] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])({
        state: "loading"
    });
    const [view, setView] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("home");
    const [onboardingComplete, setOnboardingComplete] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(false);
    const [logoutError, setLogoutError] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [loggingOut, setLoggingOut] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(false);
    const [sidebarCollapsed, setSidebarCollapsed] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(false);
    const [lens, setLens] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("operator");
    const { connection: apiConnection, apiBase } = useMeshApiConnection(true);
    function soloOnboardingKey(userId) {
        return `mesh.product.solo.${userId}`;
    }
    function acceptSession(payload) {
        setSession(payload);
        setSessionState({
            state: "ready",
            data: payload
        });
        setOnboardingComplete(Boolean(payload.active_team || window.localStorage.getItem(soloOnboardingKey(payload.user.id)) === "1"));
    }
    function clearSession(state) {
        setSession(null);
        setSessionState(state);
        setOnboardingComplete(false);
        setDashboardState({
            state: "empty",
            message: "Sign in to load the dashboard."
        });
    }
    function updateLens(nextLens) {
        setLens(nextLens);
        if (session && ("TURBOPACK compile-time value", "object") !== "undefined") {
            window.localStorage.setItem(lensStorageKey(session), nextLens);
        }
    }
    async function refreshDashboard() {
        if (!session || !session.active_team && !onboardingComplete) return;
        setDashboardState((current)=>current.state === "ready" ? current : {
                state: "loading"
            });
        try {
            const payload = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].dashboard(session.active_team?.id ?? null);
            setDashboardState({
                state: "ready",
                data: payload
            });
        } catch (error) {
            const nextState = (0, __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["loadStateFromError"])(error);
            setDashboardState(nextState);
            if (nextState.state === "unauthorized") {
                clearSession({
                    state: "unauthorized",
                    message: "Session expired or missing. Sign in again."
                });
            }
        }
    }
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "ProductApp.useEffect": ()=>{
            let mounted = true;
            async function boot() {
                try {
                    const config = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].authConfig();
                    if (!mounted) return;
                    setAuthConfig(config);
                } catch  {
                    if (!mounted) return;
                    setAuthConfig(null);
                }
                try {
                    const payload = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].me();
                    if (!mounted) return;
                    acceptSession(payload);
                } catch (error) {
                    if (!mounted) return;
                    clearSession((0, __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["loadStateFromError"])(error));
                }
            }
            boot();
            return ({
                "ProductApp.useEffect": ()=>{
                    mounted = false;
                }
            })["ProductApp.useEffect"];
        }
    }["ProductApp.useEffect"], []);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "ProductApp.useEffect": ()=>{
            if (!session || !session.active_team && !onboardingComplete) return;
            let mounted = true;
            setDashboardState({
                "ProductApp.useEffect": (current)=>current.state === "ready" ? current : {
                        state: "loading"
                    }
            }["ProductApp.useEffect"]);
            __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].dashboard(session.active_team?.id ?? null).then({
                "ProductApp.useEffect": (payload)=>{
                    if (!mounted) return;
                    setDashboardState({
                        state: "ready",
                        data: payload
                    });
                }
            }["ProductApp.useEffect"]).catch({
                "ProductApp.useEffect": (error)=>{
                    if (!mounted) return;
                    const nextState = (0, __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["loadStateFromError"])(error);
                    setDashboardState(nextState);
                    if (nextState.state === "unauthorized") {
                        clearSession({
                            state: "unauthorized",
                            message: "Session expired or missing. Sign in again."
                        });
                    }
                }
            }["ProductApp.useEffect"]);
            return ({
                "ProductApp.useEffect": ()=>{
                    mounted = false;
                }
            })["ProductApp.useEffect"];
        }
    }["ProductApp.useEffect"], [
        session,
        onboardingComplete
    ]);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "ProductApp.useEffect": ()=>{
            if (!session || ("TURBOPACK compile-time value", "object") === "undefined") return;
            const savedLens = window.localStorage.getItem(lensStorageKey(session));
            setLens(isLensKey(savedLens) ? savedLens : defaultLensForSession(session));
        }
    }["ProductApp.useEffect"], [
        session?.user.id,
        session?.active_team?.id
    ]);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "ProductApp.useEffect": ()=>{
            if ("TURBOPACK compile-time falsy", 0) //TURBOPACK unreachable
            ;
            const viewParam = new URLSearchParams(window.location.search).get("view");
            if (isViewKey(viewParam)) setView(viewParam);
        }
    }["ProductApp.useEffect"], []);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "ProductApp.useEffect": ()=>{
            if (("TURBOPACK compile-time value", "object") === "undefined" || !session) return;
            const params = new URLSearchParams(window.location.search);
            if (params.get("view") === view) return;
            params.set("view", view);
            const query = params.toString();
            const nextUrl = query ? `${window.location.pathname}?${query}` : window.location.pathname;
            window.history.replaceState(null, "", `${nextUrl}${window.location.hash}`);
        }
    }["ProductApp.useEffect"], [
        view,
        session
    ]);
    async function refreshSession() {
        const payload = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].me();
        acceptSession(payload);
        return payload;
    }
    async function logout() {
        if (loggingOut) return;
        setLoggingOut(true);
        setLogoutError("");
        try {
            await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].logout();
            setSession(null);
            setOnboardingComplete(false);
            setView("home");
            setSessionState({
                state: "unauthorized",
                message: "Logged out"
            });
            setDashboardState({
                state: "empty",
                message: "Sign in to load the dashboard."
            });
            if ("TURBOPACK compile-time truthy", 1) {
                const params = new URLSearchParams(window.location.search);
                params.delete("view");
                const query = params.toString();
                window.history.replaceState(null, "", query ? `${window.location.pathname}?${query}` : window.location.pathname);
            }
        } catch (err) {
            setLogoutError(err instanceof Error ? err.message : "Logout failed. Session was not cleared.");
        } finally{
            setLoggingOut(false);
        }
    }
    if (sessionState.state === "loading") {
        return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(BootScreen, {}, void 0, false, {
            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
            lineNumber: 676,
            columnNumber: 12
        }, this);
    }
    if (!session) {
        return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(AuthScreen, {
            apiBase: apiBase,
            apiConnection: apiConnection,
            config: authConfig,
            sessionState: sessionState,
            onSession: acceptSession
        }, void 0, false, {
            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
            lineNumber: 681,
            columnNumber: 7
        }, this);
    }
    if (!session.active_team && !onboardingComplete) {
        return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(TeamSetupScreen, {
            session: session,
            onSolo: ()=>{
                window.localStorage.setItem(soloOnboardingKey(session.user.id), "1");
                setOnboardingComplete(true);
            },
            onTeam: (payload)=>{
                acceptSession(payload);
                setOnboardingComplete(true);
            }
        }, void 0, false, {
            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
            lineNumber: 693,
            columnNumber: 7
        }, this);
    }
    const dashboard = dashboardState.state === "ready" ? dashboardState.data : null;
    const consoleMode = isConsoleProductView(view);
    const activePage = pageMetaForView(view);
    const openView = (nextView)=>{
        setView(nextView);
        if ("TURBOPACK compile-time truthy", 1) window.scrollTo({
            top: 0,
            left: 0
        });
    };
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: `product-shell ${consoleMode ? "console-mode" : ""} ${sidebarCollapsed ? "sidebar-collapsed" : ""}`,
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Sidebar, {
                session: session,
                activeView: view,
                onView: openView,
                onLogout: logout,
                loggingOut: loggingOut,
                collapsed: sidebarCollapsed,
                onCollapsedChange: setSidebarCollapsed
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 717,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("main", {
                className: "product-main",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Header, {
                        session: session,
                        dashboard: dashboard,
                        refreshSession: refreshSession,
                        onRefreshDashboard: refreshDashboard,
                        apiConnection: apiConnection,
                        apiBase: apiBase,
                        consoleMode: consoleMode,
                        activePage: activePage,
                        lens: lens,
                        onLens: updateLens
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 727,
                        columnNumber: 9
                    }, this),
                    logoutError ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "product-alert",
                        role: "alert",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$triangle$2d$alert$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__AlertTriangle$3e$__["AlertTriangle"], {
                                size: 16
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 741,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: logoutError
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 742,
                                columnNumber: 13
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 740,
                        columnNumber: 11
                    }, this) : null,
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ContentRouter, {
                        view: view,
                        authConfig: authConfig,
                        session: session,
                        dashboardState: dashboardState,
                        lens: lens,
                        setView: openView,
                        onDashboardRefresh: refreshDashboard,
                        onSession: acceptSession,
                        onLogout: logout,
                        loggingOut: loggingOut,
                        onSignInAgain: ()=>{
                            clearSession({
                                state: "unauthorized",
                                message: "Session expired or missing. Sign in again."
                            });
                        }
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 745,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 726,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 716,
        columnNumber: 5
    }, this);
}
_s1(ProductApp, "ARhyTf5Rb6z/27zQ/5481tLBJe8=", false, function() {
    return [
        useMeshApiConnection
    ];
});
_c1 = ProductApp;
function BootScreen() {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "product-boot",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(BrandLogo, {
                compact: true
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 768,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                children: "Loading operator surface"
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 769,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 767,
        columnNumber: 5
    }, this);
}
_c2 = BootScreen;
function BrandLogo({ compact = false }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
        className: compact ? "mesh-logo compact" : "mesh-logo",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("img", {
                src: "/orbital-mesh-logo.svg",
                alt: "Mesh"
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 777,
                columnNumber: 7
            }, this),
            compact ? null : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                children: "Mesh"
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 778,
                columnNumber: 25
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 776,
        columnNumber: 5
    }, this);
}
_c3 = BrandLogo;
function AsciiFlowBackground() {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "auth-ascii-flow",
        "aria-hidden": "true",
        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$landing$2f$AsciiFlowCanvas$2e$tsx__$5b$app$2d$client$5d$__$28$ecmascript$29$__["default"], {
            progress: 0
        }, void 0, false, {
            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
            lineNumber: 786,
            columnNumber: 7
        }, this)
    }, void 0, false, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 785,
        columnNumber: 5
    }, this);
}
_c4 = AsciiFlowBackground;
function AuthScreen({ apiBase, apiConnection, config, sessionState, onSession }) {
    _s2();
    const [mode, setMode] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("login");
    const [email, setEmail] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [password, setPassword] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [passwordConfirm, setPasswordConfirm] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [displayName, setDisplayName] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [captchaToken, setCaptchaToken] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [inviteCode, setInviteCode] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [acceptedTerms, setAcceptedTerms] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(false);
    const [error, setError] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [busy, setBusy] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(false);
    const backendUnavailable = !config;
    const sessionIssueMessage = sessionLoadIssueMessage(sessionState);
    const authUnavailable = backendUnavailable || sessionState?.state === "backend-unavailable";
    const signupMode = mode === "signup";
    const passwordMatches = !signupMode || password === passwordConfirm;
    const signupEnabled = !signupMode || Boolean(config?.signup_enabled && config?.password_auth_enabled);
    const inviteRequired = signupMode && Boolean(config?.invite?.required);
    const inviteSatisfied = !inviteRequired || Boolean(inviteCode.trim());
    const captchaSatisfied = !signupMode || Boolean(config?.captcha.dev_bypass_enabled) || Boolean(config?.captcha.configured) && Boolean(captchaToken);
    const submitDisabled = busy || authUnavailable || !email.trim() || !password || !passwordMatches || !signupEnabled || !captchaSatisfied || !inviteSatisfied || signupMode && !acceptedTerms;
    const enabledOauthProviders = [
        "google",
        "github"
    ].filter((provider)=>config?.oauth[provider].configured);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "AuthScreen.useEffect": ()=>{
            if ("TURBOPACK compile-time falsy", 0) //TURBOPACK unreachable
            ;
            const params = new URLSearchParams(window.location.search);
            const authError = params.get("auth_error");
            if (!authError) return;
            setError(authCallbackErrorMessage(authError));
            params.delete("auth_error");
            const query = params.toString();
            window.history.replaceState(null, "", query ? `${window.location.pathname}?${query}` : window.location.pathname);
        }
    }["AuthScreen.useEffect"], []);
    async function submit(event) {
        event.preventDefault();
        if (submitDisabled) return;
        setBusy(true);
        setError("");
        try {
            const payload = mode === "signup" ? await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].signup({
                email,
                password,
                display_name: displayName,
                captcha_token: captchaToken || (config?.captcha.dev_bypass_enabled ? "dev-captcha-ok" : ""),
                invite_code: inviteCode.trim() || undefined,
                accepted_terms: acceptedTerms
            }) : await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].login({
                email,
                password
            });
            onSession(payload);
        } catch (err) {
            setError(authFailureMessage(err));
        } finally{
            setBusy(false);
        }
    }
    async function oauth(provider) {
        if (!config || authUnavailable) {
            setError(backendUnavailable ? (0, __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["backendUnavailableMessage"])() : sessionIssueMessage || "Authentication is unavailable.");
            return;
        }
        if (!config.oauth[provider].configured) {
            setError(`${providerLabel(provider)} sign-in is not available for this environment.`);
            return;
        }
        setError("");
        try {
            const payload = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].oauthStart(provider);
            window.location.assign(payload.authorize_url);
        } catch (err) {
            setError(authFailureMessage(err));
        }
    }
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "auth-scene",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(AsciiFlowBackground, {}, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 884,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("form", {
                className: "auth-card",
                onSubmit: submit,
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "auth-brand",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(BrandLogo, {
                                compact: true
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 887,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Mesh"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 888,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 886,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h1", {
                        children: mode === "login" ? "Welcome" : "Create your account"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 890,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                        children: "Sign in to operate Mesh without changing its control-plane authority."
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 891,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "auth-connection-row",
                        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(BackendStatusChip, {
                            connection: apiConnection,
                            apiBase: apiBase
                        }, void 0, false, {
                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                            lineNumber: 893,
                            columnNumber: 11
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 892,
                        columnNumber: 9
                    }, this),
                    backendUnavailable || sessionIssueMessage ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "auth-backend-banner",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$triangle$2d$alert$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__AlertTriangle$3e$__["AlertTriangle"], {
                                size: 16
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 897,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: backendUnavailable ? (0, __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["backendUnavailableMessage"])() : sessionIssueMessage
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 898,
                                columnNumber: 13
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 896,
                        columnNumber: 11
                    }, this) : null,
                    enabledOauthProviders.length ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "oauth-stack",
                        children: enabledOauthProviders.map((provider)=>{
                            const Icon = provider === "google" ? __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$globe$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Globe$3e$__["Globe"] : __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$github$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Github$3e$__["Github"];
                            return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                type: "button",
                                onClick: ()=>oauth(provider),
                                disabled: authUnavailable,
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Icon, {
                                        size: 18
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 907,
                                        columnNumber: 19
                                    }, this),
                                    " Continue with ",
                                    providerLabel(provider)
                                ]
                            }, provider, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 906,
                                columnNumber: 17
                            }, this);
                        })
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 902,
                        columnNumber: 11
                    }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                        className: "auth-provider-note neutral",
                        children: "Use your invited email and password for this environment."
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 913,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "divider",
                        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                            children: "OR"
                        }, void 0, false, {
                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                            lineNumber: 915,
                            columnNumber: 34
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 915,
                        columnNumber: 9
                    }, this),
                    mode === "signup" ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                        children: [
                            "Display name",
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                value: displayName,
                                onChange: (event)=>setDisplayName(event.target.value),
                                placeholder: "Shaan Patel"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 919,
                                columnNumber: 13
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 917,
                        columnNumber: 11
                    }, this) : null,
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                        children: [
                            "Email address",
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                value: email,
                                onChange: (event)=>setEmail(event.target.value),
                                placeholder: "operator@company.com",
                                autoComplete: "email"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 924,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 922,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                        children: [
                            "Password",
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                value: password,
                                onChange: (event)=>setPassword(event.target.value),
                                type: "password",
                                autoComplete: mode === "login" ? "current-password" : "new-password"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 928,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 926,
                        columnNumber: 9
                    }, this),
                    mode === "signup" ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["Fragment"], {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                                children: [
                                    "Confirm password",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                        value: passwordConfirm,
                                        onChange: (event)=>setPasswordConfirm(event.target.value),
                                        type: "password",
                                        autoComplete: "new-password"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 934,
                                        columnNumber: 15
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 932,
                                columnNumber: 13
                            }, this),
                            inviteRequired ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                                children: [
                                    "Invite code",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                        value: inviteCode,
                                        onChange: (event)=>setInviteCode(event.target.value),
                                        placeholder: "from your Mesh invite",
                                        autoComplete: "one-time-code"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 939,
                                        columnNumber: 17
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 937,
                                columnNumber: 15
                            }, this) : null,
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                                className: "consent-row",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                        type: "checkbox",
                                        checked: acceptedTerms,
                                        onChange: (event)=>setAcceptedTerms(event.target.checked)
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 943,
                                        columnNumber: 15
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: "I agree to use only redacted sources and understand Mesh keeps policy, approvals, run state, evidence, and actuation authority."
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 944,
                                        columnNumber: 15
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 942,
                                columnNumber: 13
                            }, this),
                            !passwordMatches ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "auth-error compact",
                                children: "Passwords must match."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 946,
                                columnNumber: 33
                            }, this) : null,
                            !signupEnabled ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "auth-error compact",
                                children: "Signup is invite-only for this environment."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 947,
                                columnNumber: 31
                            }, this) : null
                        ]
                    }, void 0, true) : null,
                    mode === "signup" ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(CaptchaWidget, {
                        config: config,
                        onToken: setCaptchaToken
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 950,
                        columnNumber: 30
                    }, this) : null,
                    error ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "auth-error",
                        children: error
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 951,
                        columnNumber: 18
                    }, this) : null,
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        className: "primary-button",
                        type: "submit",
                        disabled: submitDisabled,
                        children: busy ? "Working" : mode === "login" ? "Continue" : "Sign up"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 952,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        className: "link-button",
                        type: "button",
                        onClick: ()=>{
                            setMode(mode === "login" ? "signup" : "login");
                            setCaptchaToken("");
                            setPasswordConfirm("");
                            setInviteCode("");
                            setAcceptedTerms(false);
                            setError("");
                        },
                        children: mode === "login" ? "Need an account? Sign up" : "Have an account? Log in"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 955,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 885,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 883,
        columnNumber: 5
    }, this);
}
_s2(AuthScreen, "1E9XLKLsv6m0RxfdnAbVNTFlwbI=");
_c5 = AuthScreen;
function providerLabel(provider) {
    return provider === "google" ? "Google" : "GitHub";
}
function authFailureMessage(error) {
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
function authCallbackErrorMessage(code) {
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
function sessionLoadIssueMessage(state) {
    if (!state || state.state === "loading" || state.state === "ready" || state.state === "unauthorized") {
        return "";
    }
    return state.message;
}
function CaptchaWidget({ config, onToken }) {
    _s3();
    const [state, setState] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("idle");
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "CaptchaWidget.useEffect": ()=>{
            onToken("");
            if (!config?.captcha.configured || !config.captcha.site_key || config.captcha.dev_bypass_enabled) return;
            let mounted = true;
            const provider = config.captcha.provider;
            const scriptId = `mesh-captcha-script-${provider}`;
            const existingScript = document.getElementById(scriptId);
            const script = document.createElement("script");
            script.async = true;
            script.defer = true;
            script.id = scriptId;
            script.src = provider === "turnstile" ? "https://challenges.cloudflare.com/turnstile/v0/api.js" : provider === "hcaptcha" ? "https://js.hcaptcha.com/1/api.js" : "https://www.google.com/recaptcha/api.js?render=explicit";
            const render = {
                "CaptchaWidget.useEffect.render": ()=>{
                    if (!mounted) return;
                    const target = document.getElementById("mesh-captcha");
                    if (!target) return;
                    target.innerHTML = "";
                    const callback = {
                        "CaptchaWidget.useEffect.render.callback": (token)=>{
                            onToken(token);
                            setState("verified");
                        }
                    }["CaptchaWidget.useEffect.render.callback"];
                    const expiredCallback = {
                        "CaptchaWidget.useEffect.render.expiredCallback": ()=>{
                            onToken("");
                            setState("ready");
                        }
                    }["CaptchaWidget.useEffect.render.expiredCallback"];
                    setState("ready");
                    if (provider === "turnstile" && window.turnstile) {
                        window.turnstile.render(target, {
                            sitekey: config.captcha.site_key,
                            callback,
                            "expired-callback": expiredCallback
                        });
                    } else if (provider === "hcaptcha" && window.hcaptcha) {
                        window.hcaptcha.render(target, {
                            sitekey: config.captcha.site_key,
                            callback,
                            "expired-callback": expiredCallback
                        });
                    } else if (window.grecaptcha) {
                        window.grecaptcha.ready({
                            "CaptchaWidget.useEffect.render": ()=>{
                                window.grecaptcha.render(target, {
                                    sitekey: config.captcha.site_key,
                                    callback,
                                    "expired-callback": expiredCallback
                                });
                            }
                        }["CaptchaWidget.useEffect.render"]);
                    } else {
                        setState("error");
                    }
                }
            }["CaptchaWidget.useEffect.render"];
            setState("loading");
            if (existingScript) {
                render();
            } else {
                script.onload = render;
                script.onerror = ({
                    "CaptchaWidget.useEffect": ()=>setState("error")
                })["CaptchaWidget.useEffect"];
                document.body.appendChild(script);
            }
            return ({
                "CaptchaWidget.useEffect": ()=>{
                    mounted = false;
                    document.getElementById("mesh-captcha")?.replaceChildren();
                }
            })["CaptchaWidget.useEffect"];
        }
    }["CaptchaWidget.useEffect"], [
        config,
        onToken
    ]);
    if (config?.captcha.dev_bypass_enabled) {
        return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
            className: "captcha-box",
            children: [
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$shield$2d$check$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__ShieldCheck$3e$__["ShieldCheck"], {
                    size: 18
                }, void 0, false, {
                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                    lineNumber: 1072,
                    columnNumber: 41
                }, this),
                " Local captcha bypass is active for development only."
            ]
        }, void 0, true, {
            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
            lineNumber: 1072,
            columnNumber: 12
        }, this);
    }
    if (!config?.captcha.configured) {
        return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
            className: "captcha-box blocked",
            children: [
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$triangle$2d$alert$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__AlertTriangle$3e$__["AlertTriangle"], {
                    size: 18
                }, void 0, false, {
                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                    lineNumber: 1075,
                    columnNumber: 49
                }, this),
                " Signup blocked: captcha provider, site key, and secret must be configured on the Mesh API server."
            ]
        }, void 0, true, {
            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
            lineNumber: 1075,
            columnNumber: 12
        }, this);
    }
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: `captcha-box captcha-widget ${state === "error" ? "blocked" : ""}`,
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                id: "mesh-captcha",
                className: "captcha-render-target"
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1079,
                columnNumber: 7
            }, this),
            state === "loading" ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                children: "Loading captcha challenge..."
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1080,
                columnNumber: 30
            }, this) : null,
            state === "verified" ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                children: "Captcha verified."
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1081,
                columnNumber: 31
            }, this) : null,
            state === "error" ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                children: "Captcha failed to load. Check provider keys and browser network access."
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1082,
                columnNumber: 28
            }, this) : null
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1078,
        columnNumber: 5
    }, this);
}
_s3(CaptchaWidget, "DLIhk1sg29VgoOrqP7mXTpNjt3k=");
_c6 = CaptchaWidget;
function TeamSetupScreen({ session, onSolo, onTeam }) {
    _s4();
    const [name, setName] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [invite, setInvite] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [error, setError] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [creating, setCreating] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(false);
    async function createTeam() {
        const teamName = name.trim();
        if (!teamName) {
            setError("Team name is required.");
            return;
        }
        setCreating(true);
        setError("");
        try {
            const members = invite.split(",").map((email)=>email.trim()).filter(Boolean).map((email)=>({
                    email,
                    role: "viewer"
                }));
            const payload = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].createTeam({
                name: teamName,
                members
            });
            onTeam(payload);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Team creation failed");
        } finally{
            setCreating(false);
        }
    }
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "setup-scene",
        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
            className: "setup-card",
            children: [
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(BrandLogo, {
                    compact: true
                }, void 0, false, {
                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                    lineNumber: 1123,
                    columnNumber: 9
                }, this),
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h1", {
                    children: "Create a team"
                }, void 0, false, {
                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                    lineNumber: 1124,
                    columnNumber: 9
                }, this),
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                    children: "Teams scope the dashboard and roles. Mesh still owns approvals, run state, evidence, policy, and actuation."
                }, void 0, false, {
                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                    lineNumber: 1125,
                    columnNumber: 9
                }, this),
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                    children: [
                        "Team name",
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                            value: name,
                            onChange: (event)=>setName(event.target.value),
                            placeholder: `${session.user.display_name}'s team`
                        }, void 0, false, {
                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                            lineNumber: 1128,
                            columnNumber: 11
                        }, this)
                    ]
                }, void 0, true, {
                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                    lineNumber: 1126,
                    columnNumber: 9
                }, this),
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                    children: [
                        "Invite members",
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                            value: invite,
                            onChange: (event)=>setInvite(event.target.value),
                            placeholder: "colleague@company.com, sre@company.com"
                        }, void 0, false, {
                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                            lineNumber: 1132,
                            columnNumber: 11
                        }, this)
                    ]
                }, void 0, true, {
                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                    lineNumber: 1130,
                    columnNumber: 9
                }, this),
                error ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                    className: "auth-error",
                    children: error
                }, void 0, false, {
                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                    lineNumber: 1134,
                    columnNumber: 18
                }, this) : null,
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                    className: "primary-button",
                    type: "button",
                    onClick: createTeam,
                    disabled: creating,
                    children: creating ? "Creating" : "Create team"
                }, void 0, false, {
                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                    lineNumber: 1135,
                    columnNumber: 9
                }, this),
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                    className: "link-button",
                    type: "button",
                    onClick: onSolo,
                    children: "Continue solo"
                }, void 0, false, {
                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                    lineNumber: 1136,
                    columnNumber: 9
                }, this)
            ]
        }, void 0, true, {
            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
            lineNumber: 1122,
            columnNumber: 7
        }, this)
    }, void 0, false, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1121,
        columnNumber: 5
    }, this);
}
_s4(TeamSetupScreen, "qwR/sL7Kj9zio9b4aEFw1TAQOPo=");
_c7 = TeamSetupScreen;
function Sidebar({ session, activeView, onView, onLogout, loggingOut, collapsed, onCollapsedChange }) {
    _s5();
    function openDocs() {
        window.open("https://github.com/LusisLabs/orbital-mesh/tree/master/docs", "_blank", "noopener,noreferrer");
    }
    const [advancedOpen, setAdvancedOpen] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(isConsoleProductView(activeView));
    const [advancedQuery, setAdvancedQuery] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const filteredAdvancedItems = ADVANCED_CONSOLE_NAV_ITEMS.filter((item)=>item.label.toLowerCase().includes(advancedQuery.trim().toLowerCase()));
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "Sidebar.useEffect": ()=>{
            if (isConsoleProductView(activeView)) setAdvancedOpen(true);
        }
    }["Sidebar.useEffect"], [
        activeView
    ]);
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("aside", {
        className: "product-sidebar",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "brand-row",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(BrandLogo, {}, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1173,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        type: "button",
                        "aria-label": collapsed ? "Expand navigation" : "Collapse navigation",
                        title: collapsed ? "Expand navigation" : "Collapse navigation",
                        onClick: ()=>onCollapsedChange(!collapsed),
                        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$chevron$2d$down$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__ChevronDown$3e$__["ChevronDown"], {
                            size: 14
                        }, void 0, false, {
                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                            lineNumber: 1180,
                            columnNumber: 11
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1174,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1172,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("nav", {
                children: [
                    NAV_GROUPS.map((group)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                            className: "nav-group",
                            children: [
                                group.label ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                    children: group.label
                                }, void 0, false, {
                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                    lineNumber: 1186,
                                    columnNumber: 28
                                }, this) : null,
                                group.items.map((item)=>{
                                    const Icon = item.icon;
                                    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                        className: activeView === item.key ? "active" : "",
                                        type: "button",
                                        onClick: ()=>onView(item.key),
                                        title: item.label,
                                        "aria-label": item.label,
                                        children: [
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Icon, {
                                                size: 16
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 1191,
                                                columnNumber: 19
                                            }, this),
                                            " ",
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                className: "nav-label",
                                                children: item.label
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 1191,
                                                columnNumber: 38
                                            }, this)
                                        ]
                                    }, item.key, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1190,
                                        columnNumber: 17
                                    }, this);
                                })
                            ]
                        }, group.label || "home", true, {
                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                            lineNumber: 1185,
                            columnNumber: 11
                        }, this)),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "nav-group advanced-nav-group",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                children: "Advanced Console"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1198,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                className: isConsoleProductView(activeView) ? "active advanced-nav-toggle" : "advanced-nav-toggle",
                                type: "button",
                                onClick: ()=>setAdvancedOpen(!advancedOpen),
                                title: "Advanced Console",
                                "aria-label": "Advanced Console",
                                "aria-expanded": advancedOpen,
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$cpu$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Cpu$3e$__["Cpu"], {
                                        size: 16
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1207,
                                        columnNumber: 13
                                    }, this),
                                    " ",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        className: "nav-label",
                                        children: "Advanced Console"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1207,
                                        columnNumber: 31
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1199,
                                columnNumber: 11
                            }, this),
                            advancedOpen ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "advanced-nav-panel",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                                        className: "advanced-nav-search",
                                        children: [
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$search$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Search$3e$__["Search"], {
                                                size: 13
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 1212,
                                                columnNumber: 17
                                            }, this),
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                                value: advancedQuery,
                                                onChange: (event)=>setAdvancedQuery(event.target.value),
                                                placeholder: "Filter console"
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 1213,
                                                columnNumber: 17
                                            }, this)
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1211,
                                        columnNumber: 15
                                    }, this),
                                    filteredAdvancedItems.map((item)=>{
                                        const Icon = item.icon;
                                        return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                            className: activeView === item.key ? "active" : "",
                                            type: "button",
                                            onClick: ()=>onView(item.key),
                                            title: item.label,
                                            "aria-label": item.label,
                                            children: [
                                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Icon, {
                                                    size: 15
                                                }, void 0, false, {
                                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                    lineNumber: 1219,
                                                    columnNumber: 21
                                                }, this),
                                                " ",
                                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                    className: "nav-label",
                                                    children: item.label
                                                }, void 0, false, {
                                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                    lineNumber: 1219,
                                                    columnNumber: 40
                                                }, this)
                                            ]
                                        }, item.key, true, {
                                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                            lineNumber: 1218,
                                            columnNumber: 19
                                        }, this);
                                    })
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1210,
                                columnNumber: 13
                            }, this) : null
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1197,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "nav-group",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                children: "Support"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1227,
                                columnNumber: 9
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                type: "button",
                                onClick: ()=>onView("evaluations"),
                                title: "Run Review",
                                "aria-label": "Run Review",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$mail$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Mail$3e$__["Mail"], {
                                        size: 16
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1228,
                                        columnNumber: 112
                                    }, this),
                                    " ",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        className: "nav-label",
                                        children: "Run Review"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1228,
                                        columnNumber: 131
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1228,
                                columnNumber: 9
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                type: "button",
                                onClick: openDocs,
                                title: "Documentation",
                                "aria-label": "Documentation",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$book$2d$open$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__BookOpen$3e$__["BookOpen"], {
                                        size: 16
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1229,
                                        columnNumber: 99
                                    }, this),
                                    " ",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        className: "nav-label",
                                        children: "Documentation"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1229,
                                        columnNumber: 122
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1229,
                                columnNumber: 9
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1226,
                        columnNumber: 7
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1183,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "sidebar-footer",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: session.active_team?.name || "Solo"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1234,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: session.user.email
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1235,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1233,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        type: "button",
                        onClick: onLogout,
                        disabled: loggingOut,
                        title: loggingOut ? "Logging out" : "Log out",
                        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$log$2d$out$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__LogOut$3e$__["LogOut"], {
                            size: 15
                        }, void 0, false, {
                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                            lineNumber: 1237,
                            columnNumber: 119
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1237,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1232,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1171,
        columnNumber: 5
    }, this);
}
_s5(Sidebar, "ks0ltR2Bl4b6iqu48vY01rstVLo=");
_c8 = Sidebar;
function Header({ session, dashboard, refreshSession, onRefreshDashboard, apiConnection, apiBase, consoleMode, activePage, lens, onLens }) {
    const scope = dashboard?.scope.kind === "team" ? dashboard.scope.team?.display_name : "Solo dashboard";
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("header", {
        className: "product-header",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "breadcrumb-row",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: scope
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1271,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$arrow$2d$right$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__ArrowRight$3e$__["ArrowRight"], {
                                size: 13
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1272,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: activePage.group
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1273,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1270,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h1", {
                        children: activePage.title
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1275,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                        children: consoleMode ? activePage.detail : activePage.detail || dashboard?.authority_boundary || "Mesh controls policy, approvals, run state, readiness, evidence, and actuation."
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1276,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1269,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "header-actions",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(BackendStatusChip, {
                        connection: apiConnection,
                        apiBase: apiBase
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1279,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        className: "header-icon-button",
                        type: "button",
                        onClick: ()=>void onRefreshDashboard(),
                        title: "Refresh dashboard from Mesh",
                        "aria-label": "Refresh dashboard",
                        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$refresh$2d$cw$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__RefreshCw$3e$__["RefreshCw"], {
                            size: 15
                        }, void 0, false, {
                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                            lineNumber: 1287,
                            columnNumber: 11
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1280,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(LensSelector, {
                        lens: lens,
                        onLens: onLens
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1289,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(TeamSwitcher, {
                        session: session,
                        refreshSession: refreshSession
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1290,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1278,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1268,
        columnNumber: 5
    }, this);
}
_c9 = Header;
function LensSelector({ lens, onLens }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
        className: "lens-selector",
        children: [
            "Lens",
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("select", {
                value: lens,
                onChange: (event)=>onLens(event.target.value),
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                        value: "operator",
                        children: "Operator"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1301,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                        value: "approver",
                        children: "Approver"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1302,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                        value: "security",
                        children: "Security"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1303,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                        value: "partner-review",
                        children: "Partner Review"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1304,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1300,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1298,
        columnNumber: 5
    }, this);
}
_c10 = LensSelector;
function pageMetaForView(view) {
    if (isConsoleProductView(view)) {
        const workflow = consoleWorkflowForView(view);
        return {
            title: workflow.label,
            group: "Advanced Console",
            detail: workflow.description
        };
    }
    const match = NAV_GROUPS.flatMap((group)=>group.items.map((item)=>({
                ...item,
                group: group.label || "Product"
            }))).find((item)=>item.key === view);
    const title = match?.label || humanize(view);
    const details = {
        home: "Readiness, next action, recent activity, and blockers before the console.",
        praxis: "Upload sources, certify generated tools, start dry-run, and export proof.",
        "agent-flow": "Chat with Harper-696, then drill into the Mesh lifecycle, agent lanes, proof gaps, and mutation preview path.",
        "hardened-arena": "Choose a recipe profile, inspect authority boundaries and blockers, then generate a review-only proof packet.",
        evaluations: "Choose a scenario, launch through Mesh admission, and inspect proof.",
        environments: "Filter connector status by domain, state, and blocker evidence.",
        settings: "Choose safe defaults for new runs; deployment and CLI parity stay in Advanced.",
        team: "Create or review the active team scope for partner-safe access.",
        members: "Review team roles that map into Mesh operator permissions.",
        keys: "Review deployment-owned auth and secret posture without exposing raw values.",
        "operator-setup": "Configure operator preferences, agent lanes, model defaults, target posture, and run templates."
    };
    return {
        title,
        group: match?.group || "Product",
        detail: details[view] || "Mesh-owned read model with product-safe controls."
    };
}
function TeamSwitcher({ session, refreshSession }) {
    async function switchTeam(teamId) {
        await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].switchTeam(teamId);
        await refreshSession();
    }
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("select", {
        value: session.active_team?.id || "solo",
        onChange: (event)=>switchTeam(event.target.value === "solo" ? null : event.target.value),
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                value: "solo",
                children: "Solo dashboard"
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1341,
                columnNumber: 7
            }, this),
            session.teams.map((team)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                    value: team.id,
                    children: team.name
                }, team.id, false, {
                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                    lineNumber: 1342,
                    columnNumber: 36
                }, this))
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1340,
        columnNumber: 5
    }, this);
}
_c11 = TeamSwitcher;
function ContentRouter({ view, authConfig, lens, session, dashboardState, setView, onDashboardRefresh, onSession, onLogout, loggingOut, onSignInAgain }) {
    if (isConsoleProductView(view)) {
        return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ConsoleWorkspace, {
            view: view,
            setView: setView
        }, void 0, false, {
            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
            lineNumber: 1373,
            columnNumber: 12
        }, this);
    }
    if (dashboardState.state !== "ready") {
        return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(LoadStatePanel, {
            state: dashboardState,
            onRetry: ()=>void onDashboardRefresh(),
            onSignInAgain: onSignInAgain
        }, void 0, false, {
            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
            lineNumber: 1377,
            columnNumber: 7
        }, this);
    }
    const dashboard = dashboardState.data;
    if (view === "home") return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(HomeView, {
        dashboard: dashboard,
        authConfig: authConfig,
        lens: lens,
        setView: setView
    }, void 0, false, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1385,
        columnNumber: 31
    }, this);
    if (view === "praxis") return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(PraxisView, {
        dashboard: dashboard,
        setView: setView,
        onDashboardRefresh: onDashboardRefresh
    }, void 0, false, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1386,
        columnNumber: 33
    }, this);
    if (view === "agent-flow") return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(AgentFlowView, {
        dashboard: dashboard,
        setView: setView
    }, void 0, false, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1387,
        columnNumber: 37
    }, this);
    if (view === "hardened-arena") return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(HardenedArenaView, {
        dashboard: dashboard,
        setView: setView
    }, void 0, false, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1388,
        columnNumber: 41
    }, this);
    if (view === "environments") return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(EnvironmentView, {
        dashboard: dashboard,
        setView: setView
    }, void 0, false, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1389,
        columnNumber: 39
    }, this);
    if (view === "evaluations") return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(EvaluationsView, {
        dashboard: dashboard,
        setView: setView,
        onDashboardRefresh: onDashboardRefresh
    }, void 0, false, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1390,
        columnNumber: 38
    }, this);
    if (view === "team") return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(TeamSettingsView, {
        session: session,
        dashboard: dashboard,
        onDashboardRefresh: onDashboardRefresh,
        onSession: onSession,
        onLogout: onLogout,
        loggingOut: loggingOut
    }, void 0, false, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1391,
        columnNumber: 31
    }, this);
    if (view === "members") return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(MembersView, {
        session: session,
        setView: setView,
        onSession: onSession,
        onDashboardRefresh: onDashboardRefresh
    }, void 0, false, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1392,
        columnNumber: 34
    }, this);
    if (view === "keys") return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(KeysView, {
        authConfig: authConfig,
        dashboard: dashboard,
        setView: setView
    }, void 0, false, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1393,
        columnNumber: 31
    }, this);
    if (view === "operator-setup") return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(OperatorSetupView, {
        dashboard: dashboard,
        onDashboardRefresh: onDashboardRefresh,
        setView: setView
    }, void 0, false, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1394,
        columnNumber: 41
    }, this);
    if (view === "settings") return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "content-stack",
        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(SettingsView, {
            dashboard: dashboard,
            onDashboardRefresh: onDashboardRefresh
        }, void 0, false, {
            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
            lineNumber: 1395,
            columnNumber: 66
        }, this)
    }, void 0, false, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1395,
        columnNumber: 35
    }, this);
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(CapabilityView, {
        view: view,
        dashboard: dashboard,
        setView: setView
    }, void 0, false, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1396,
        columnNumber: 10
    }, this);
}
_c12 = ContentRouter;
function ConsoleWorkspace({ view, setView }) {
    const workflow = consoleWorkflowForView(view);
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
        className: "console-workspace",
        "aria-label": "Full Mesh control console",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "console-workspace-toolbar",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: workflow.label
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1405,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: workflow.description
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1406,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1404,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "console-workspace-actions",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                type: "button",
                                onClick: ()=>setView("home"),
                                children: "Product Home"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1409,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                type: "button",
                                onClick: ()=>setView(workflow.productFallback),
                                children: "Product View"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1410,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1408,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1403,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$App$2e$tsx__$5b$app$2d$client$5d$__$28$ecmascript$29$__["default"], {
                initialView: workflow.consoleView
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1413,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1402,
        columnNumber: 5
    }, this);
}
_c13 = ConsoleWorkspace;
function AgentFlowView({ dashboard, setView }) {
    _s6();
    const mesh = dashboard.mesh ?? {};
    const runs = Array.isArray(mesh.runs?.runs) ? mesh.runs.runs : [];
    const approvals = Array.isArray(mesh.approvals?.items) ? mesh.approvals.items : [];
    const readinessStatus = String(mesh.readiness?.status ?? "unknown");
    const harperSource = "Harper-696/src/agent.py";
    const teamId = dashboard.scope.team?.id ?? null;
    const [activePrompt, setActivePrompt] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [messages, setMessages] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])([
        {
            role: "harper",
            content: "Harper-696 is ready as an operator-safe agent flow. I can inspect Mesh state, prepare draft previews, and keep side effects blocked until a Mesh-owned route receives explicit confirmation."
        }
    ]);
    const [lifecycleTasks, setLifecycleTasks] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])();
    const [mutationPreview, setMutationPreview] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(null);
    const [liveKitSession, setLiveKitSession] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(null);
    const [confirmation, setConfirmation] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(null);
    const [confirmationReason, setConfirmationReason] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [chatError, setChatError] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [chatBusy, setChatBusy] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(false);
    const [confirming, setConfirming] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(false);
    const [voiceStatus, setVoiceStatus] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("idle");
    const liveKitRoomRef = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useRef"])(null);
    const liveKitConnectGenerationRef = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useRef"])(0);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "AgentFlowView.useEffect": ()=>{
            let mounted = true;
            liveKitConnectGenerationRef.current += 1;
            liveKitRoomRef.current?.disconnect();
            liveKitRoomRef.current = null;
            clearAgentFlowAudioElements();
            setVoiceStatus("idle");
            setLiveKitSession(null);
            __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].agentFlowLiveKitSession({
                team_id: teamId
            }).then({
                "AgentFlowView.useEffect": (payload)=>{
                    if (mounted) setLiveKitSession(payload);
                }
            }["AgentFlowView.useEffect"]).catch({
                "AgentFlowView.useEffect": (error)=>{
                    if (!mounted) return;
                    setLiveKitSession({
                        schema_version: "mesh.agent_flow.livekit_session.v1",
                        state_slice: "mesh.agent_flow.livekit_session.v1",
                        agent: {
                            id: "harper-696",
                            name: "Harper-696",
                            source: harperSource
                        },
                        status: "unavailable",
                        livekit_url: "",
                        room: "",
                        participant_identity: "",
                        token: "",
                        token_expires_at: null,
                        required_env: [
                            "MESH_LIVEKIT_URL",
                            "MESH_LIVEKIT_API_KEY",
                            "MESH_LIVEKIT_API_SECRET"
                        ],
                        side_effects_executed: false
                    });
                    setChatError(error instanceof Error ? error.message : "LiveKit session bootstrap failed");
                }
            }["AgentFlowView.useEffect"]);
            return ({
                "AgentFlowView.useEffect": ()=>{
                    mounted = false;
                }
            })["AgentFlowView.useEffect"];
        }
    }["AgentFlowView.useEffect"], [
        teamId
    ]);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "AgentFlowView.useEffect": ()=>{
            return ({
                "AgentFlowView.useEffect": ()=>{
                    liveKitConnectGenerationRef.current += 1;
                    liveKitRoomRef.current?.disconnect();
                    liveKitRoomRef.current = null;
                    clearAgentFlowAudioElements();
                }
            })["AgentFlowView.useEffect"];
        }
    }["AgentFlowView.useEffect"], []);
    async function handleSend(message, files) {
        const clean = message.trim() || "[image prompt]";
        setActivePrompt(clean);
        setChatError("");
        setConfirmation(null);
        setConfirmationReason("");
        setMutationPreview(null);
        setLifecycleTasks(undefined);
        setChatBusy(true);
        setMessages((previous)=>[
                ...previous,
                {
                    role: "operator",
                    content: clean
                }
            ]);
        try {
            const response = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].agentFlowChat({
                team_id: teamId,
                message: clean,
                attachments: files?.map((file)=>({
                        name: file.name,
                        type: file.type,
                        size: file.size
                    })) ?? []
            });
            setLifecycleTasks(response.lifecycle.tasks);
            setMutationPreview(response.mutation_preview);
            setMessages((previous)=>[
                    ...previous,
                    {
                        role: "harper",
                        content: response.answer,
                        response
                    }
                ]);
        } catch (error) {
            const message = error instanceof Error ? error.message : "Agent Flow request failed";
            setChatError(message);
            setMessages((previous)=>[
                    ...previous,
                    {
                        role: "harper",
                        content: `State slice: mesh.agent_flow.chat_response.v1. ${message}`
                    }
                ]);
        } finally{
            setChatBusy(false);
        }
    }
    async function confirmPreview() {
        if (!mutationPreview || chatBusy) return;
        const reason = confirmationReason.trim();
        if (!reason) {
            setChatError("Confirmation reason is required for mesh.agent_flow.mutation_preview.v1.");
            return;
        }
        setConfirming(true);
        setChatError("");
        try {
            const response = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].confirmAgentFlowPreview({
                team_id: teamId,
                preview_id: mutationPreview.preview_id,
                preview: mutationPreview,
                reason
            });
            setConfirmation(response);
        } catch (error) {
            setChatError(error instanceof Error ? error.message : "Preview confirmation failed");
        } finally{
            setConfirming(false);
        }
    }
    async function connectHarperVoice() {
        let session = liveKitSession;
        if (!isLiveKitSessionFresh(session)) {
            try {
                session = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].agentFlowLiveKitSession({
                    team_id: teamId
                });
                setLiveKitSession(session);
            } catch (error) {
                setVoiceStatus("failed");
                setChatError(error instanceof Error ? error.message : "LiveKit session refresh failed");
                return;
            }
        }
        const unavailableStatus = session?.status ?? "";
        if (!isLiveKitSessionFresh(session)) {
            setVoiceStatus("unavailable");
            setChatError(agentFlowVoiceUnavailableMessage(unavailableStatus));
            return;
        }
        const activeSession = session;
        const connectGeneration = liveKitConnectGenerationRef.current + 1;
        liveKitConnectGenerationRef.current = connectGeneration;
        setChatError("");
        setVoiceStatus("connecting");
        let pendingRoom = null;
        try {
            const { Room, RoomEvent } = await __turbopack_context__.A("[project]/node_modules/.pnpm/livekit-client@2.19.0_@types+dom-mediacapture-record@1.0.22/node_modules/livekit-client/dist/livekit-client.esm.mjs [app-client] (ecmascript, async loader)");
            liveKitRoomRef.current?.disconnect();
            clearAgentFlowAudioElements();
            const room = new Room({
                adaptiveStream: true,
                dynacast: true
            });
            pendingRoom = room;
            liveKitRoomRef.current = room;
            room.on(RoomEvent.TrackSubscribed, (track)=>{
                attachAgentFlowAudioTrack(track);
            });
            room.on(RoomEvent.TrackUnsubscribed, (track)=>{
                track.detach?.().forEach((element)=>element.remove());
            });
            await room.connect(activeSession.livekit_url, activeSession.token);
            if (liveKitConnectGenerationRef.current !== connectGeneration) {
                room.disconnect();
                clearAgentFlowAudioElements();
                return;
            }
            room.remoteParticipants.forEach((participant)=>{
                participant.trackPublications.forEach((publication)=>{
                    const track = publication.track;
                    if (track) attachAgentFlowAudioTrack(track);
                });
            });
            await room.localParticipant.setMicrophoneEnabled(true);
            if (liveKitConnectGenerationRef.current !== connectGeneration) {
                room.disconnect();
                clearAgentFlowAudioElements();
                return;
            }
            setVoiceStatus("connected");
        } catch (error) {
            pendingRoom?.disconnect();
            clearAgentFlowAudioElements();
            if (liveKitConnectGenerationRef.current === connectGeneration) {
                liveKitRoomRef.current = null;
                setVoiceStatus("failed");
                setChatError(error instanceof Error ? error.message : "LiveKit voice connection failed");
            }
        }
    }
    function disconnectHarperVoice() {
        liveKitConnectGenerationRef.current += 1;
        liveKitRoomRef.current?.disconnect();
        liveKitRoomRef.current = null;
        clearAgentFlowAudioElements();
        setVoiceStatus("idle");
    }
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "content-stack agent-flow-page",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "agent-flow-hero",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Harper-696"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1625,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h2", {
                                children: "Agent flow workspace"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1626,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                children: "Chat drives the lifecycle view. Harper can explain Mesh state, prepare bounded run drafts, and surface proof gaps while Mesh keeps policy, approvals, audit, and actuation authority."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1627,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1624,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "agent-flow-posture",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: liveKitSession?.status === "ready" ? "Voice bridge ready" : "Draft-first composer"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1632,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: liveKitSession?.status === "ready" ? liveKitSession.room : harperSource
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1633,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1631,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1623,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "agent-flow-grid",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "agent-flow-chat",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "panel-title",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$bot$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Bot$3e$__["Bot"], {
                                        size: 15
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1639,
                                        columnNumber: 40
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: "Harper Chat Box"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1639,
                                        columnNumber: 57
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1639,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "agent-flow-chat-log",
                                "aria-live": "polite",
                                children: messages.slice(-6).map((message, index)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("article", {
                                        className: message.role,
                                        children: [
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                children: message.role === "operator" ? "Operator" : "Harper-696"
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 1643,
                                                columnNumber: 17
                                            }, this),
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                                children: message.content
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 1644,
                                                columnNumber: 17
                                            }, this),
                                            message.response ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                                className: "agent-flow-response-meta",
                                                children: message.response.state_slices.slice(0, 5).map((slice)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                                        children: slice
                                                    }, slice, false, {
                                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                        lineNumber: 1647,
                                                        columnNumber: 79
                                                    }, this))
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 1646,
                                                columnNumber: 19
                                            }, this) : null
                                        ]
                                    }, `${message.role}-${index}`, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1642,
                                        columnNumber: 15
                                    }, this))
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1640,
                                columnNumber: 11
                            }, this),
                            chatError ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "product-alert warning",
                                children: chatError
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1653,
                                columnNumber: 24
                            }, this) : null,
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "agent-flow-composer",
                                children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$components$2f$ui$2f$prompt$2d$input$2d$box$2e$tsx__$5b$app$2d$client$5d$__$28$ecmascript$29$__["PromptInputBox"], {
                                    onSend: (message, files)=>handleSend(message, files),
                                    isLoading: chatBusy,
                                    placeholder: "Ask Harper to inspect blockers, evidence, approvals, or lifecycle state..."
                                }, void 0, false, {
                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                    lineNumber: 1655,
                                    columnNumber: 13
                                }, this)
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1654,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1638,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "agent-flow-system",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "panel-title",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$activity$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Activity$3e$__["Activity"], {
                                        size: 15
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1664,
                                        columnNumber: 40
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: "Mesh Lifecycle Context"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1664,
                                        columnNumber: 62
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1664,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "agent-flow-metrics",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                        children: [
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                children: "Readiness"
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 1666,
                                                columnNumber: 18
                                            }, this),
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                                children: humanize(readinessStatus)
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 1666,
                                                columnNumber: 40
                                            }, this)
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1666,
                                        columnNumber: 13
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                        children: [
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                children: "Runs"
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 1667,
                                                columnNumber: 18
                                            }, this),
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                                children: runs.length
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 1667,
                                                columnNumber: 35
                                            }, this)
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1667,
                                        columnNumber: 13
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                        children: [
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                children: "Approvals"
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 1668,
                                                columnNumber: 18
                                            }, this),
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                                children: approvals.length
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 1668,
                                                columnNumber: 40
                                            }, this)
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1668,
                                        columnNumber: 13
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                        children: [
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                children: "Voice"
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 1669,
                                                columnNumber: 18
                                            }, this),
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                                children: humanize(liveKitSession?.status ?? "loading")
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 1669,
                                                columnNumber: 36
                                            }, this)
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1669,
                                        columnNumber: 13
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1665,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "agent-flow-session",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: "LiveKit room"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1672,
                                        columnNumber: 13
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                        children: liveKitSession?.room || "not minted"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1673,
                                        columnNumber: 13
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                        children: liveKitSession?.status === "ready" ? "Browser token minted without exposing API secret." : "Set MESH_LIVEKIT_URL, MESH_LIVEKIT_API_KEY, and MESH_LIVEKIT_API_SECRET."
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1674,
                                        columnNumber: 13
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1671,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "agent-flow-voice",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: "Voice connection"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1677,
                                        columnNumber: 13
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                        children: humanize(voiceStatus)
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1678,
                                        columnNumber: 13
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                        type: "button",
                                        onClick: voiceStatus === "connected" ? disconnectHarperVoice : connectHarperVoice,
                                        disabled: !canAttemptHarperVoiceConnection(liveKitSession, voiceStatus),
                                        children: voiceStatus === "connected" ? "Disconnect voice" : voiceStatus === "connecting" ? "Connecting" : "Connect voice"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1679,
                                        columnNumber: 13
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1676,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                type: "button",
                                onClick: ()=>setView("console-hermes"),
                                children: "Open Hermes"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1683,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                type: "button",
                                onClick: ()=>setView("console-runs"),
                                children: "Open Evidence Runs"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1684,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                type: "button",
                                onClick: ()=>setView("console-approvals"),
                                children: "Open Approvals"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1685,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1663,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1637,
                columnNumber: 7
            }, this),
            mutationPreview ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "agent-flow-preview",
                "aria-label": "Agent Flow mutation preview",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Mutation preview"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1692,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h3", {
                                children: [
                                    mutationPreview.proposed_resource,
                                    ": ",
                                    humanize(mutationPreview.action)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1693,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                children: [
                                    "Draft touches ",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                        children: mutationPreview.would_touch_state_slice
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1695,
                                        columnNumber: 29
                                    }, this),
                                    " through ",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                        children: mutationPreview.endpoint
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1695,
                                        columnNumber: 92
                                    }, this),
                                    ".",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                        children: [
                                            "side_effects_executed=",
                                            String(mutationPreview.side_effects_executed)
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1696,
                                        columnNumber: 15
                                    }, this),
                                    "."
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1694,
                                columnNumber: 13
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1691,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "agent-flow-preview-actions",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                children: mutationPreview.preview_id
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1700,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                                children: [
                                    "Confirmation reason",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                        value: confirmationReason,
                                        onChange: (event)=>setConfirmationReason(event.target.value),
                                        placeholder: "why this draft is ready for Mesh review"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1703,
                                        columnNumber: 15
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1701,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                type: "button",
                                onClick: confirmPreview,
                                disabled: chatBusy || confirming || !confirmationReason.trim(),
                                children: confirming ? "Confirming" : "Confirm draft"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1709,
                                columnNumber: 13
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1699,
                        columnNumber: 11
                    }, this),
                    confirmation ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "agent-flow-confirmation",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: humanize(confirmation.status)
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1715,
                                columnNumber: 15
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: confirmation.next_step
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1716,
                                columnNumber: 15
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                children: [
                                    "side_effects_executed=",
                                    String(confirmation.side_effects_executed)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1717,
                                columnNumber: 15
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1714,
                        columnNumber: 13
                    }, this) : null
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1690,
                columnNumber: 9
            }, this) : null,
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "agent-flow-plan",
                children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$components$2f$ui$2f$agent$2d$lifecycle$2d$plan$2e$tsx__$5b$app$2d$client$5d$__$28$ecmascript$29$__["default"], {
                    activePrompt: activePrompt,
                    lifecycleTasks: lifecycleTasks
                }, void 0, false, {
                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                    lineNumber: 1724,
                    columnNumber: 9
                }, this)
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1723,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1622,
        columnNumber: 5
    }, this);
}
_s6(AgentFlowView, "3l3g8d2ntoF3E++hHWgRTyCx04M=");
_c14 = AgentFlowView;
function LoadStatePanel({ state, onRetry, onSignInAgain }) {
    if (state.state === "loading") return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "skeleton-panel",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {}, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1739,
                columnNumber: 73
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {}, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1739,
                columnNumber: 81
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {}, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1739,
                columnNumber: 89
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1739,
        columnNumber: 41
    }, this);
    if (state.state === "ready") return null;
    const showRetry = onRetry && (state.state === "backend-unavailable" || state.state === "error");
    const showSignIn = onSignInAgain && (state.state === "unauthorized" || state.state === "forbidden");
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: `state-panel ${state.state}`,
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$triangle$2d$alert$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__AlertTriangle$3e$__["AlertTriangle"], {
                size: 18
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1745,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "state-panel-copy",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                        children: state.message
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1747,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "state-panel-actions",
                        children: [
                            showRetry ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                type: "button",
                                className: "primary-button",
                                onClick: onRetry,
                                children: "Retry"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1749,
                                columnNumber: 24
                            }, this) : null,
                            showSignIn ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                type: "button",
                                className: "primary-button",
                                onClick: onSignInAgain,
                                children: "Sign in again"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1750,
                                columnNumber: 25
                            }, this) : null
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1748,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1746,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1744,
        columnNumber: 5
    }, this);
}
_c15 = LoadStatePanel;
function HomeView({ dashboard, authConfig, lens, setView }) {
    const praxis = buildPraxisProductModel(dashboard);
    const capabilityCards = orderDashboardTiles(buildDashboardTiles(dashboard), lens);
    const partnerHome = buildPartnerHomeModel(dashboard);
    const insights = orderDashboardInsights(buildDashboardInsights(dashboard, authConfig), lens);
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "content-stack",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: `partner-home-hero ${partnerHome.readiness.tone}`,
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Readiness"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1767,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h2", {
                                children: partnerHome.readiness.label
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1768,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                children: partnerHome.readiness.detail
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1769,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1766,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        type: "button",
                        onClick: ()=>setView(partnerHome.nextStep.view),
                        children: [
                            partnerHome.nextStep.action,
                            " ",
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$arrow$2d$right$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__ArrowRight$3e$__["ArrowRight"], {
                                size: 16
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1772,
                                columnNumber: 41
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1771,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1765,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "partner-home-grid",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("article", {
                        className: "partner-card next",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "panel-title",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$circle$2d$check$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__CheckCircle2$3e$__["CheckCircle2"], {
                                        size: 15
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1777,
                                        columnNumber: 40
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: "Next step"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1777,
                                        columnNumber: 66
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1777,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: partnerHome.nextStep.label
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1778,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                children: partnerHome.nextStep.detail
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1779,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                type: "button",
                                onClick: ()=>setView(partnerHome.nextStep.view),
                                children: partnerHome.nextStep.action
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1780,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1776,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("article", {
                        className: "partner-card",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "panel-title",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$activity$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Activity$3e$__["Activity"], {
                                        size: 15
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1783,
                                        columnNumber: 40
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: "Recent activity"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1783,
                                        columnNumber: 62
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1783,
                                columnNumber: 11
                            }, this),
                            partnerHome.recentActivity.length ? partnerHome.recentActivity.map((item)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                    className: "console-row",
                                    type: "button",
                                    onClick: ()=>setView("evaluations"),
                                    children: [
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                            children: item.label
                                        }, void 0, false, {
                                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                            lineNumber: 1786,
                                            columnNumber: 15
                                        }, this),
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                            children: item.value
                                        }, void 0, false, {
                                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                            lineNumber: 1787,
                                            columnNumber: 15
                                        }, this),
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                            children: item.detail
                                        }, void 0, false, {
                                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                            lineNumber: 1788,
                                            columnNumber: 15
                                        }, this)
                                    ]
                                }, item.id, true, {
                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                    lineNumber: 1785,
                                    columnNumber: 13
                                }, this)) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(EmptyInline, {
                                text: "No recent Mesh activity for this scope."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1790,
                                columnNumber: 16
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1782,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("article", {
                        className: "partner-card",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "panel-title",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$file$2d$check$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__FileCheck$3e$__["FileCheck"], {
                                        size: 15
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1793,
                                        columnNumber: 40
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: "Blocked evidence"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1793,
                                        columnNumber: 63
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1793,
                                columnNumber: 11
                            }, this),
                            partnerHome.blockedEvidence.length ? partnerHome.blockedEvidence.map((item)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                    className: "console-row",
                                    type: "button",
                                    onClick: ()=>setView("evaluations"),
                                    children: [
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                            children: item.label
                                        }, void 0, false, {
                                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                            lineNumber: 1796,
                                            columnNumber: 15
                                        }, this),
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                            children: item.value
                                        }, void 0, false, {
                                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                            lineNumber: 1797,
                                            columnNumber: 15
                                        }, this),
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                            children: item.detail
                                        }, void 0, false, {
                                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                            lineNumber: 1798,
                                            columnNumber: 15
                                        }, this)
                                    ]
                                }, item.id, true, {
                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                    lineNumber: 1795,
                                    columnNumber: 13
                                }, this)) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(EmptyInline, {
                                text: "No missing proof reported by Mesh."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1800,
                                columnNumber: 16
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1792,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1775,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "insights-ask-grid",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(InsightsPanel, {
                        insights: insights,
                        setView: setView
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1804,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(AskMeshPanel, {
                        dashboard: dashboard,
                        authConfig: authConfig,
                        setView: setView
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1805,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1803,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(PraxisHomeModule, {
                model: praxis,
                setView: setView
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1807,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "advanced-console-band",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Advanced operator console"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1810,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: "Full Mesh console workflows are still available, but product tasks come first."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1811,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1809,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        type: "button",
                        onClick: ()=>setView("console"),
                        children: "Open Advanced Console"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1813,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1808,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(SectionLabel, {
                label: "Product paths"
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1815,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "capability-grid",
                children: capabilityCards.filter((card)=>card.view !== "console").slice(0, 6).map((card)=>{
                    const Icon = card.icon;
                    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        className: "capability-card",
                        type: "button",
                        onClick: ()=>setView(card.view),
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Icon, {
                                size: 18
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1821,
                                columnNumber: 15
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: card.title
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1822,
                                columnNumber: 15
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                className: `tile-state ${card.state}`,
                                children: card.state
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1823,
                                columnNumber: 15
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: card.detail
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1824,
                                columnNumber: 15
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(SensitivityBadges, {
                                badges: sensitivityBadgesForSource(card.apiSection)
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1825,
                                columnNumber: 15
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: card.apiSection
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1826,
                                columnNumber: 15
                            }, this)
                        ]
                    }, card.title, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1820,
                        columnNumber: 13
                    }, this);
                })
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1816,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1764,
        columnNumber: 5
    }, this);
}
_c16 = HomeView;
function InsightsPanel({ insights, setView }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
        className: "insights-panel",
        "aria-label": "Insights and recommendations",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "panel-title",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$sparkles$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Sparkles$3e$__["Sparkles"], {
                        size: 15
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1838,
                        columnNumber: 36
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        children: "Insights & Recommendations"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1838,
                        columnNumber: 58
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1838,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "insight-list",
                children: insights.slice(0, 5).map((insight)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("article", {
                        className: `insight-card ${insight.severity}`,
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "insight-card-head",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: humanize(insight.severity)
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1843,
                                        columnNumber: 15
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                        children: [
                                            Math.round(insight.confidence * 100),
                                            "%"
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 1844,
                                        columnNumber: 15
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1842,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h3", {
                                children: insight.title
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1846,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                children: insight.why
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1847,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(SensitivityBadges, {
                                badges: insight.badges
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1848,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(SourceLine, {
                                sourcePath: insight.sourcePath,
                                authority: insight.authority
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1849,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                type: "button",
                                onClick: ()=>setView(insight.actionView),
                                children: insight.actionLabel
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1850,
                                columnNumber: 13
                            }, this)
                        ]
                    }, insight.id, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1841,
                        columnNumber: 11
                    }, this))
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1839,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1837,
        columnNumber: 5
    }, this);
}
_c17 = InsightsPanel;
function AskMeshPanel({ dashboard, authConfig, setView }) {
    _s7();
    var _s = __turbopack_context__.k.signature();
    const [query, setQuery] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("why blocked");
    const [result, setResult] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])({
        "AskMeshPanel.useState": ()=>askMesh("why blocked", dashboard, authConfig)
    }["AskMeshPanel.useState"]);
    function submit(event) {
        event.preventDefault();
        setResult(askMesh(query, dashboard, authConfig));
    }
    function useSuggestion(suggestion) {
        setQuery(suggestion);
        setResult(askMesh(suggestion, dashboard, authConfig));
    }
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
        className: "ask-mesh-panel",
        "aria-label": "Ask Mesh",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "panel-title",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$search$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Search$3e$__["Search"], {
                        size: 15
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1874,
                        columnNumber: 36
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        children: "Ask Mesh"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1874,
                        columnNumber: 56
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1874,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("form", {
                className: "ask-mesh-form",
                onSubmit: submit,
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                        value: query,
                        onChange: (event)=>setQuery(event.target.value),
                        placeholder: "Ask about blockers, runs, approvals, proof..."
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1876,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        type: "submit",
                        children: "Ask"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1877,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1875,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("article", {
                className: result.supported ? "ask-result" : "ask-result unsupported",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        children: result.supported ? humanize(result.intent) : "Suggested queries"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1880,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                        children: result.answer
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1881,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(SourceLine, {
                        sourcePath: result.sourcePath,
                        authority: "Mesh read models"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1882,
                        columnNumber: 9
                    }, this),
                    result.filters.length ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                        children: result.filters.join(" | ")
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1883,
                        columnNumber: 34
                    }, this) : null,
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        type: "button",
                        onClick: ()=>setView(result.targetView),
                        children: [
                            "Open ",
                            pageMetaForView(result.targetView).title
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1884,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1879,
                columnNumber: 7
            }, this),
            !result.supported ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "ask-suggestions",
                children: result.suggestions.map((suggestion)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        type: "button",
                        onClick: _s(()=>{
                            _s();
                            return useSuggestion(suggestion);
                        }, "Tm3IhIaFQeTaErUPTEGljA7SgqU=", false, function() {
                            return [
                                useSuggestion
                            ];
                        }),
                        children: suggestion
                    }, suggestion, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1888,
                        columnNumber: 51
                    }, this))
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1887,
                columnNumber: 9
            }, this) : null
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1873,
        columnNumber: 5
    }, this);
}
_s7(AskMeshPanel, "nSeoI6bdhM8pOmgf0KHviFWpzn0=");
_c18 = AskMeshPanel;
function buildPartnerHomeModel(dashboard) {
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
    const nextStep = !dashboard.scope.team ? {
        label: "Create a team",
        detail: "Team scope keeps partners, roles, and proof review separate from solo browser state.",
        view: "team",
        action: "Set up team"
    } : Number(praxis.sourcePackets) === 0 ? {
        label: "Import Praxis source",
        detail: "Upload redacted OpenAPI, SOP, Postman, or traffic references before tool generation.",
        view: "praxis",
        action: "Import source"
    } : !control.recentRuns.length ? {
        label: "Launch sandbox run",
        detail: "Pick a scenario and let Mesh admit or block the run with audit context.",
        view: "evaluations",
        action: "Launch run"
    } : {
        label: "Review proof",
        detail: "Open the run proof views and inspect missing evidence before partner handoff.",
        view: "evaluations",
        action: "Review proof"
    };
    return {
        readiness: {
            label: readinessLabel,
            detail: blocked ? `${missing.length || readiness.blockers?.length || 1} blocker(s) must be resolved before invites.` : demoOnly ? "Local/demo evidence is useful for rehearsal, but live provider proof is still required before external invites." : "Mesh reports no current invite-blocking readiness issue in this dashboard scope.",
            tone: blocked ? "warn" : "good"
        },
        nextStep,
        recentActivity: control.recentRuns.slice(0, 3),
        blockedEvidence: missing.slice(0, 4).map((item, index)=>({
                id: `missing-${index}`,
                label: "Missing proof",
                value: humanize(String(item)),
                detail: plainEvidenceBlocker(String(item))
            }))
    };
}
function plainEvidenceBlocker(value) {
    const lower = value.toLowerCase();
    if (lower.includes("auth")) return "Complete live provider proof for signup, OAuth, and captcha before inviting partners.";
    if (lower.includes("decision")) return "Mesh needs a signed decision record or completed run decision before this can be called ready.";
    if (lower.includes("export")) return "Create or upload the proof/export packet Mesh expects for handoff.";
    if (lower.includes("readiness")) return "Resolve readiness blockers in the Mesh control-plane snapshot.";
    return "Open the proof view for the exact Mesh evidence record and remediation path.";
}
function PraxisHomeModule({ model, setView }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
        className: "praxis-home",
        "aria-label": "Praxis MCP generator",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "praxis-home-copy",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        children: "Praxis Agent-Tool Mesh"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1947,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h2", {
                        children: "Generate MCP tools, certify scopes, then expose only the dry-run pilot runtime Mesh admits."
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1948,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                        children: "OpenAPI, SOP, traffic refs, Akto evidence, ACP supervision, Docker Dynamic MCP session discovery, certification, revocation, and proof packet are bound into one product path."
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1949,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1946,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "praxis-home-grid",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(PraxisStat, {
                        label: "Live runs",
                        value: model.runCount,
                        detail: model.requestId ? `latest ${model.requestId}` : "team-scoped runtime state"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1952,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(PraxisStat, {
                        label: "Proof packet",
                        value: model.proofStatus,
                        detail: model.status
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1953,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(PraxisStat, {
                        label: "Sources",
                        value: model.sourcePackets,
                        detail: "redacted source packets"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1954,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(PraxisStat, {
                        label: "Tools",
                        value: model.toolCandidates,
                        detail: `${model.certifiedTools} certified / ${model.deniedTools} denied`
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1955,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(PraxisStat, {
                        label: "Docker Dynamic MCP",
                        value: model.dockerDynamicMcpStatus,
                        detail: model.dockerDynamicMcpSession
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1956,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(PraxisStat, {
                        label: "Runtime",
                        value: model.runtimeStatus,
                        detail: model.managedRuntime ? "managed runtime deployed" : "dry-run only"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1957,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1951,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "praxis-home-actions",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        type: "button",
                        onClick: ()=>setView("praxis"),
                        children: [
                            "Open Praxis ",
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$arrow$2d$right$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__ArrowRight$3e$__["ArrowRight"], {
                                size: 15
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 1960,
                                columnNumber: 77
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1960,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                        children: model.mcpEndpoint
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 1961,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1959,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1945,
        columnNumber: 5
    }, this);
}
_c19 = PraxisHomeModule;
function PraxisStat({ label, value, detail }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "praxis-stat",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                children: label
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1970,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                children: value
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1971,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                children: detail
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1972,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1969,
        columnNumber: 5
    }, this);
}
_c20 = PraxisStat;
function PraxisFileInput({ label, accept, file, onFile }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
        className: "praxis-file-input",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                children: label
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1990,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                type: "file",
                accept: accept,
                onChange: (event)=>onFile(event.currentTarget.files?.[0] ?? null)
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1991,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                children: file?.name || "No file selected"
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 1996,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 1989,
        columnNumber: 5
    }, this);
}
_c21 = PraxisFileInput;
async function readPraxisSources(files) {
    const sources = [];
    for (const [sourceType, file] of Object.entries(files)){
        if (!file) continue;
        const content = await file.text();
        rejectClientRawSecret(content, file.name);
        sources.push({
            source_type: praxisSourceType(sourceType),
            filename: file.name,
            content
        });
    }
    return sources;
}
function praxisSourceType(sourceType) {
    if (sourceType === "postman") return "postman_json";
    if (sourceType === "traffic_ref") return "redacted_traffic_ref";
    return sourceType;
}
function rejectClientRawSecret(content, filename) {
    const secretPattern = /\b(?:api[_-]?key|authorization|bearer|secret|token|password)\b\s*[:=]\s*["']?[A-Za-z0-9._~+/-]{16,}/i;
    if (secretPattern.test(content)) {
        throw new Error(`Raw secret-like value rejected in ${filename}. Upload a redacted source ref.`);
    }
}
function PraxisView({ dashboard, setView, onDashboardRefresh }) {
    _s8();
    const model = buildPraxisProductModel(dashboard);
    const praxis = dashboard.mesh.praxis || {};
    const sourcePackets = praxis.source_bundle?.packets || [];
    const securityFindings = praxis.security_evidence?.findings || [];
    const teamId = dashboard.scope.kind === "team" ? dashboard.scope.team?.id ?? null : null;
    const [sourceFiles, setSourceFiles] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])({});
    const [aktoFile, setAktoFile] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(null);
    const [lastRecord, setLastRecord] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(null);
    const [message, setMessage] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [busyAction, setBusyAction] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const requestId = String(lastRecord?.request_id || model.requestId || "");
    const callableToolId = model.tools.find((tool)=>tool.value === "read only")?.id || model.tools[0]?.id || "";
    function setSourceFile(sourceType, file) {
        setSourceFiles({
            ...sourceFiles,
            [sourceType]: file
        });
    }
    async function withPraxisAction(action, fn) {
        setBusyAction(action);
        setMessage("");
        try {
            const result = await fn();
            if (result && result.request_id) setLastRecord(result);
            await onDashboardRefresh();
        } catch (err) {
            setMessage(err instanceof Error ? err.message : `${action} failed`);
        } finally{
            setBusyAction("");
        }
    }
    async function generateContract() {
        await withPraxisAction("generate", async ()=>{
            const sources = await readPraxisSources(sourceFiles);
            if (!sources.length) throw new Error("Upload at least one Praxis source before generation.");
            const record = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].createPraxisGenerationRequest({
                team_id: teamId,
                sources
            });
            setMessage(`Generated Praxis request ${record.request_id}.`);
            return record;
        });
    }
    async function importAktoEvidence() {
        await withPraxisAction("akto", async ()=>{
            if (!requestId) throw new Error("Generate a Praxis contract before importing Akto evidence.");
            if (!aktoFile) throw new Error("Upload an Akto evidence file before import.");
            const aktoResult = JSON.parse(await aktoFile.text());
            const record = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].importPraxisAktoEvidence(requestId, {
                team_id: teamId,
                akto_result: aktoResult
            });
            setMessage(`Imported Akto evidence for ${record.request_id}.`);
            return record;
        });
    }
    async function buildCertification() {
        await withPraxisAction("certify", async ()=>{
            if (!requestId) throw new Error("Generate a Praxis contract before certification.");
            const record = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].buildPraxisCertificationBinding(requestId, {
                team_id: teamId
            });
            setMessage(`Built certification binding for ${record.request_id}.`);
            return record;
        });
    }
    async function startDryRun() {
        await withPraxisAction("start", async ()=>{
            if (!requestId) throw new Error("Build certification before starting dry-run.");
            const record = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].startPraxisDryRunEndpoint(requestId, {
                team_id: teamId
            });
            setMessage(`Started dry-run MCP endpoint for ${record.request_id}.`);
            return record;
        });
    }
    async function callReadOnlyTool() {
        await withPraxisAction("call", async ()=>{
            if (!requestId) throw new Error("Start dry-run before calling a tool.");
            const list = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].praxisMcp(requestId, {
                jsonrpc: "2.0",
                id: "tools-list",
                method: "tools/list",
                team_id: teamId
            });
            const toolId = String(list.result?.tools?.[0]?.name || callableToolId);
            if (!toolId) throw new Error("No certified read-only tool is available for dry-run.");
            await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].praxisMcp(requestId, {
                jsonrpc: "2.0",
                id: "tool-call",
                method: "tools/call",
                params: {
                    name: toolId,
                    arguments: {
                        dry_run_reason: "product_e2e_validation"
                    }
                },
                team_id: teamId
            });
            const record = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].exportPraxisP10Proof(requestId, teamId);
            setMessage(`MCP tool call audited. P10 proof is ${record.status}.`);
        });
    }
    async function exportP10Proof() {
        await withPraxisAction("p10", async ()=>{
            if (!requestId) throw new Error("Generate a Praxis request before exporting P10 proof.");
            const packet = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].exportPraxisP10Proof(requestId, teamId);
            setMessage(`Exported P10 proof packet ${packet.packet_id}: ${packet.status}.`);
        });
    }
    async function revokeConnector() {
        await withPraxisAction("revoke", async ()=>{
            if (!requestId) throw new Error("Generate a Praxis request before revocation.");
            const record = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].revokePraxisGeneratedConnector(requestId, {
                team_id: teamId,
                reason: "product_operator_revocation"
            });
            setMessage(`Revoked generated connector for ${record.request_id}.`);
            return record;
        });
    }
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "content-stack",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Toolbar, {
                title: "Praxis MCP Generator",
                detail: "Generate candidate MCP tools from source packets, import Akto evidence, bind Mesh certification, and expose Docker Dynamic MCP as a session-only dry-run bridge.",
                action: "Back Home",
                onAction: ()=>setView("home")
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2141,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(PraxisJourney, {
                model: model,
                sourcePackets: sourcePackets.length,
                securityFindings: securityFindings.length
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2147,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "praxis-import-panel",
                "aria-label": "Praxis source import",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "panel-heading",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: "Product source intake"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2151,
                                        columnNumber: 13
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h3", {
                                        children: "Upload redacted API, workflow, SOP, and traffic sources"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2152,
                                        columnNumber: 13
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                        children: "Files are sent to Mesh for secret rejection and persisted as redacted source refs under `praxis.managed-dry-run-runtime.v1`."
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2153,
                                        columnNumber: 13
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2150,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                type: "button",
                                onClick: generateContract,
                                disabled: busyAction === "generate",
                                children: busyAction === "generate" ? "Generating" : "Generate Praxis contract"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2155,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2149,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "praxis-import-grid",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(PraxisFileInput, {
                                label: "OpenAPI file",
                                accept: ".json,.yaml,.yml",
                                file: sourceFiles.openapi || null,
                                onFile: (file)=>setSourceFile("openapi", file)
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2160,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(PraxisFileInput, {
                                label: "Postman file",
                                accept: ".json",
                                file: sourceFiles.postman || null,
                                onFile: (file)=>setSourceFile("postman", file)
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2161,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(PraxisFileInput, {
                                label: "SOP Markdown file",
                                accept: ".md,.markdown,.txt",
                                file: sourceFiles.sop_markdown || null,
                                onFile: (file)=>setSourceFile("sop_markdown", file)
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2162,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(PraxisFileInput, {
                                label: "Traffic refs file",
                                accept: ".json,.har",
                                file: sourceFiles.traffic_ref || null,
                                onFile: (file)=>setSourceFile("traffic_ref", file)
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2163,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(PraxisFileInput, {
                                label: "Akto evidence file",
                                accept: ".json",
                                file: aktoFile,
                                onFile: setAktoFile
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2164,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2159,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(PraxisStepper, {
                        steps: [
                            {
                                label: "Upload sources",
                                detail: "Redacted source files selected",
                                complete: Object.values(sourceFiles).some(Boolean),
                                action: "Select files"
                            },
                            {
                                label: "Generate tools",
                                detail: requestId || "Create candidate MCP contract",
                                complete: Boolean(requestId),
                                action: busyAction === "generate" ? "Generating" : "Generate",
                                onAction: generateContract,
                                disabled: busyAction === "generate"
                            },
                            {
                                label: "Import security evidence",
                                detail: securityFindings.length ? `${securityFindings.length} finding(s) imported` : "Attach Akto result",
                                complete: securityFindings.length > 0,
                                action: busyAction === "akto" ? "Importing" : "Import",
                                onAction: importAktoEvidence,
                                disabled: busyAction === "akto" || !requestId
                            },
                            {
                                label: "Certify",
                                detail: `${model.certifiedTools} read-only / ${model.deniedTools} denied`,
                                complete: Number(model.certifiedTools) > 0 || Number(model.deniedTools) > 0,
                                action: busyAction === "certify" ? "Certifying" : "Certify",
                                onAction: buildCertification,
                                disabled: busyAction === "certify" || !requestId
                            },
                            {
                                label: "Start dry run",
                                detail: model.runtimeStatus,
                                complete: model.runtimeStatus.includes("ready") || model.managedRuntime,
                                action: busyAction === "start" ? "Starting" : "Start dry run",
                                onAction: startDryRun,
                                disabled: busyAction === "start" || !requestId
                            },
                            {
                                label: "Export proof",
                                detail: model.proofStatus,
                                complete: model.proofStatus === "complete",
                                action: busyAction === "p10" ? "Exporting" : "Export",
                                onAction: exportP10Proof,
                                disabled: busyAction === "p10" || !requestId
                            }
                        ],
                        secondaryActions: [
                            {
                                label: "Call read-only tool",
                                onAction: callReadOnlyTool,
                                disabled: busyAction === "call" || !requestId
                            },
                            {
                                label: "Revoke connector",
                                onAction: revokeConnector,
                                disabled: busyAction === "revoke" || !requestId
                            }
                        ]
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2166,
                        columnNumber: 9
                    }, this),
                    message ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: message.toLowerCase().includes("failed") || message.toLowerCase().includes("required") || message.toLowerCase().includes("upload") ? "auth-error" : "product-alert success",
                        children: message
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2180,
                        columnNumber: 20
                    }, this) : null
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2148,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "praxis-workbench",
                "aria-label": "Praxis generator workbench",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "praxis-stage primary",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "State slice"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2184,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h2", {
                                children: "praxis.managed-dry-run-runtime.v1"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2185,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                children: [
                                    "Current runtime posture: ",
                                    model.runtimeStatus,
                                    ". Managed runtime deployed: ",
                                    model.managedRuntime ? "yes" : "no",
                                    "."
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2186,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "praxis-stage-actions",
                                children: model.controls.map((control)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                        type: "button",
                                        disabled: control.state === "blocked",
                                        title: control.detail,
                                        children: [
                                            control.label,
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                                children: control.requiresMeshApproval ? "Mesh approval" : control.state
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 2191,
                                                columnNumber: 17
                                            }, this)
                                        ]
                                    }, control.id, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2189,
                                        columnNumber: 15
                                    }, this))
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2187,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2183,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "praxis-stage",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Proof binding"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2197,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: model.proofStatus
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2198,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: [
                                    model.blockerCount,
                                    " blocker(s) remain on denied or unadmitted scopes"
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2199,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2196,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "praxis-stage",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Dry-run endpoint"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2202,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: model.mcpEndpoint
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2203,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: "Agents can only use certified tool scopes."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2204,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2201,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "praxis-stage",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Docker Dynamic MCP"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2207,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: model.dockerDynamicMcpGateway
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2208,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: [
                                    model.dockerDynamicMcpToolCount,
                                    " management tool(s); ",
                                    model.dockerDynamicMcpSession,
                                    "."
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2209,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2206,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2182,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "praxis-lanes",
                "aria-label": "Praxis product lanes",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(PraxisLane, {
                        title: "Source intake",
                        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$database$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Database$3e$__["Database"],
                        children: sourcePackets.length ? sourcePackets.map((packet)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "praxis-list-row",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: packet.source_type
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2216,
                                        columnNumber: 15
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                        children: packet.source_ref
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2217,
                                        columnNumber: 15
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                        children: packet.raw_credentials_present ? "raw credential blocker" : "redacted"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2218,
                                        columnNumber: 15
                                    }, this)
                                ]
                            }, packet.packet_id, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2215,
                                columnNumber: 13
                            }, this)) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(EmptyInline, {
                            text: "No Praxis source bundle returned by Mesh."
                        }, void 0, false, {
                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                            lineNumber: 2220,
                            columnNumber: 16
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2213,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(PraxisLane, {
                        title: "Generated tools",
                        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$boxes$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Boxes$3e$__["Boxes"],
                        children: model.tools.map((tool)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: `praxis-tool ${tool.tone}`,
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: [
                                            tool.method,
                                            " ",
                                            tool.path
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2225,
                                        columnNumber: 15
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                        children: tool.label
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2226,
                                        columnNumber: 15
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                        children: [
                                            tool.value,
                                            " · scopes ",
                                            tool.authScopes.length ? tool.authScopes.join(", ") : "none",
                                            " · ",
                                            tool.detail
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2227,
                                        columnNumber: 15
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("details", {
                                        children: [
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("summary", {
                                                children: "Review plan"
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 2229,
                                                columnNumber: 17
                                            }, this),
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                                children: [
                                                    "Blockers: ",
                                                    tool.blockers.length ? tool.blockers.join(", ") : "none"
                                                ]
                                            }, void 0, true, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 2230,
                                                columnNumber: 17
                                            }, this),
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                                children: [
                                                    "Tests: ",
                                                    tool.testPlan.join(" / ")
                                                ]
                                            }, void 0, true, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 2231,
                                                columnNumber: 17
                                            }, this)
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2228,
                                        columnNumber: 15
                                    }, this)
                                ]
                            }, tool.id, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2224,
                                columnNumber: 13
                            }, this))
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2222,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(PraxisLane, {
                        title: "Akto evidence",
                        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$shield$2d$check$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__ShieldCheck$3e$__["ShieldCheck"],
                        children: securityFindings.length ? securityFindings.map((finding)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "praxis-list-row",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: [
                                            finding.severity,
                                            " / ",
                                            finding.status
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2239,
                                        columnNumber: 15
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                        children: finding.summary
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2240,
                                        columnNumber: 15
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                        children: finding.evidence_ref
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2241,
                                        columnNumber: 15
                                    }, this)
                                ]
                            }, finding.finding_id, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2238,
                                columnNumber: 13
                            }, this)) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(EmptyInline, {
                            text: "No Akto findings in the dashboard read model."
                        }, void 0, false, {
                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                            lineNumber: 2243,
                            columnNumber: 16
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2236,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2212,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 2140,
        columnNumber: 5
    }, this);
}
_s8(PraxisView, "T1eyQqr85iVvJlLgWJmaPTl7Ays=");
_c22 = PraxisView;
function PraxisStepper({ steps, secondaryActions }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "praxis-stepper",
        "aria-label": "Praxis workflow",
        children: [
            steps.map((step, index)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                    className: step.complete ? "praxis-step complete" : "praxis-step",
                    children: [
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                            className: "step-index",
                            children: step.complete ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$circle$2d$check$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__CheckCircle2$3e$__["CheckCircle2"], {
                                size: 16
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2261,
                                columnNumber: 56
                            }, this) : index + 1
                        }, void 0, false, {
                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                            lineNumber: 2261,
                            columnNumber: 11
                        }, this),
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                            children: [
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                    children: step.label
                                }, void 0, false, {
                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                    lineNumber: 2263,
                                    columnNumber: 13
                                }, this),
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                    children: step.detail
                                }, void 0, false, {
                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                    lineNumber: 2264,
                                    columnNumber: 13
                                }, this)
                            ]
                        }, void 0, true, {
                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                            lineNumber: 2262,
                            columnNumber: 11
                        }, this),
                        step.onAction ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                            type: "button",
                            onClick: step.onAction,
                            disabled: step.disabled,
                            children: step.action
                        }, void 0, false, {
                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                            lineNumber: 2266,
                            columnNumber: 28
                        }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                            children: step.action
                        }, void 0, false, {
                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                            lineNumber: 2266,
                            columnNumber: 124
                        }, this)
                    ]
                }, step.label, true, {
                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                    lineNumber: 2260,
                    columnNumber: 9
                }, this)),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "praxis-step-secondary",
                children: secondaryActions.map((action)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        type: "button",
                        onClick: action.onAction,
                        disabled: action.disabled,
                        children: action.label
                    }, action.label, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2271,
                        columnNumber: 11
                    }, this))
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2269,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 2258,
        columnNumber: 5
    }, this);
}
_c23 = PraxisStepper;
function PraxisJourney({ model, sourcePackets, securityFindings }) {
    const stages = [
        {
            label: "Source",
            value: `${sourcePackets || model.sourcePackets} packet(s)`,
            detail: "OpenAPI, Postman, SOP, and traffic refs are redacted before persistence."
        },
        {
            label: "Candidate Tools",
            value: `${model.toolCandidates} candidate(s)`,
            detail: "Generated MCP tools stay candidates until Mesh certification."
        },
        {
            label: "Security Evidence",
            value: `${securityFindings} finding(s)`,
            detail: "Akto evidence is advisory and cannot grant authority."
        },
        {
            label: "Certification",
            value: `${model.certifiedTools}/${model.deniedTools}`,
            detail: "Read-only scopes can be admitted; unsafe mutations stay denied."
        },
        {
            label: "Docker Dynamic MCP",
            value: model.dockerDynamicMcpStatus,
            detail: "Gateway discovery is session-scoped; Praxis keeps generated tools dry-run only."
        },
        {
            label: "Dry-run MCP",
            value: model.runtimeStatus,
            detail: "Calls are audited and side effects stay disabled."
        },
        {
            label: "Operator Decision",
            value: model.proofStatus,
            detail: "Approval evidence is bound into proof, not inferred from UI state."
        },
        {
            label: "Proof Packet",
            value: model.proofStatus,
            detail: "P10 export binds source, tools, evidence, certification, runtime, and revocation."
        },
        {
            label: "Revocation",
            value: model.managedRuntime ? "pilot blocked" : "available",
            detail: "Managed pilot runtime remains blocked until production-like proof exists."
        }
    ];
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
        className: "praxis-journey",
        "aria-label": "Praxis V2 journey",
        children: stages.map((stage)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        children: stage.label
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2294,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                        children: humanize(stage.value)
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2295,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                        children: stage.detail
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2296,
                        columnNumber: 11
                    }, this)
                ]
            }, stage.label, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2293,
                columnNumber: 9
            }, this))
    }, void 0, false, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 2291,
        columnNumber: 5
    }, this);
}
_c24 = PraxisJourney;
function PraxisLane({ title, icon: Icon, children }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
        className: "praxis-lane",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "panel-title",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Icon, {
                        size: 15
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2306,
                        columnNumber: 36
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        children: title
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2306,
                        columnNumber: 54
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2306,
                columnNumber: 7
            }, this),
            children
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 2305,
        columnNumber: 5
    }, this);
}
_c25 = PraxisLane;
function OperatorCommandCenter({ dashboard, setView }) {
    const model = buildDashboardControlModel(dashboard);
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
        className: "operator-console",
        "aria-label": "Mesh operator control summary",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "console-heading",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Mesh Control Summary"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2318,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h2", {
                                children: "Runtime, evidence, policy, and connectors in one dashboard."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2319,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2317,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        type: "button",
                        onClick: ()=>setView("evaluations"),
                        children: [
                            "Review runs ",
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$arrow$2d$right$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__ArrowRight$3e$__["ArrowRight"], {
                                size: 15
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2322,
                                columnNumber: 23
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2321,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2316,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "console-metrics",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ConsoleMetric, {
                        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$zap$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Zap$3e$__["Zap"],
                        label: "Readiness",
                        value: model.readiness.value,
                        detail: model.readiness.detail,
                        tone: model.readiness.tone
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2326,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ConsoleMetric, {
                        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$play$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Play$3e$__["Play"],
                        label: "Run admission",
                        value: model.runs.value,
                        detail: model.runs.detail,
                        tone: model.runs.tone
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2327,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ConsoleMetric, {
                        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$lock$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Lock$3e$__["Lock"],
                        label: "Approvals",
                        value: model.approvals.value,
                        detail: model.approvals.detail,
                        tone: model.approvals.tone
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2328,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ConsoleMetric, {
                        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$shield$2d$check$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__ShieldCheck$3e$__["ShieldCheck"],
                        label: "Evidence",
                        value: model.evidence.value,
                        detail: model.evidence.detail,
                        tone: model.evidence.tone
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2329,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2325,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "console-panels",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                        className: "console-panel",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "panel-title",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$activity$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Activity$3e$__["Activity"], {
                                        size: 15
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2333,
                                        columnNumber: 40
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: "Recent runs"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2333,
                                        columnNumber: 62
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2333,
                                columnNumber: 11
                            }, this),
                            model.recentRuns.length ? model.recentRuns.map((run)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                    className: "console-row",
                                    type: "button",
                                    onClick: ()=>setView("evaluations"),
                                    children: [
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                            children: run.label
                                        }, void 0, false, {
                                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                            lineNumber: 2336,
                                            columnNumber: 15
                                        }, this),
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                            children: run.value
                                        }, void 0, false, {
                                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                            lineNumber: 2337,
                                            columnNumber: 15
                                        }, this),
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                            children: run.detail
                                        }, void 0, false, {
                                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                            lineNumber: 2338,
                                            columnNumber: 15
                                        }, this)
                                    ]
                                }, run.id, true, {
                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                    lineNumber: 2335,
                                    columnNumber: 13
                                }, this)) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(EmptyInline, {
                                text: "No run summaries in the dashboard read model."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2340,
                                columnNumber: 16
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2332,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                        className: "console-panel",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "panel-title",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$boxes$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Boxes$3e$__["Boxes"], {
                                        size: 15
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2343,
                                        columnNumber: 40
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: "Connector posture"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2343,
                                        columnNumber: 59
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2343,
                                columnNumber: 11
                            }, this),
                            model.connectors.length ? model.connectors.map((connector)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                    className: "console-row",
                                    type: "button",
                                    onClick: ()=>setView("environments"),
                                    children: [
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                            children: connector.label
                                        }, void 0, false, {
                                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                            lineNumber: 2346,
                                            columnNumber: 15
                                        }, this),
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                            children: connector.value
                                        }, void 0, false, {
                                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                            lineNumber: 2347,
                                            columnNumber: 15
                                        }, this),
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                            children: connector.detail
                                        }, void 0, false, {
                                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                            lineNumber: 2348,
                                            columnNumber: 15
                                        }, this)
                                    ]
                                }, connector.id, true, {
                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                    lineNumber: 2345,
                                    columnNumber: 13
                                }, this)) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(EmptyInline, {
                                text: "No connector certification records returned."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2350,
                                columnNumber: 16
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2342,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                        className: "console-panel",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "panel-title",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$network$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Network$3e$__["Network"], {
                                        size: 15
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2353,
                                        columnNumber: 40
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: "Topology and memory"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2353,
                                        columnNumber: 61
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2353,
                                columnNumber: 11
                            }, this),
                            model.systemRows.map((row)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                    className: "console-row",
                                    type: "button",
                                    onClick: ()=>setView(row.view),
                                    children: [
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                            children: row.label
                                        }, void 0, false, {
                                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                            lineNumber: 2356,
                                            columnNumber: 15
                                        }, this),
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                            children: row.value
                                        }, void 0, false, {
                                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                            lineNumber: 2357,
                                            columnNumber: 15
                                        }, this),
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                            children: row.detail
                                        }, void 0, false, {
                                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                            lineNumber: 2358,
                                            columnNumber: 15
                                        }, this)
                                    ]
                                }, row.id, true, {
                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                    lineNumber: 2355,
                                    columnNumber: 13
                                }, this))
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2352,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2331,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 2315,
        columnNumber: 5
    }, this);
}
_c26 = OperatorCommandCenter;
function ConsoleMetric({ icon: Icon, label, value, detail, tone }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: `console-metric ${tone}`,
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Icon, {
                size: 16
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2382,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                children: label
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2383,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                children: value
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2384,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                children: detail
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2385,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 2381,
        columnNumber: 5
    }, this);
}
_c27 = ConsoleMetric;
function EmptyInline({ text }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "empty-inline",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$triangle$2d$alert$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__AlertTriangle$3e$__["AlertTriangle"], {
                size: 15
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2391,
                columnNumber: 40
            }, this),
            " ",
            text
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 2391,
        columnNumber: 10
    }, this);
}
_c28 = EmptyInline;
function dashboardSectionState(payload) {
    if (!payload || typeof payload === "object" && Object.keys(payload).length === 0) {
        return {
            state: "empty",
            reason: "No payload returned by the dashboard read model."
        };
    }
    if (payload.error || payload.status === "unavailable") {
        return {
            state: "degraded",
            reason: String(payload.error || payload.reason || "Dashboard section is unavailable.")
        };
    }
    const status = String(payload.status || payload.state || payload.decision || "").toLowerCase();
    if (payload.ready === false || status.includes("blocked") || status === "denied") {
        return {
            state: "blocked",
            reason: String(payload.reason || payload.error || "Mesh reports this section blocked.")
        };
    }
    const arrayKeys = [
        "runs",
        "items",
        "connectors",
        "entries"
    ];
    for (const key of arrayKeys){
        if (Array.isArray(payload[key]) && payload[key].length === 0) {
            return {
                state: "empty",
                reason: `${key} returned no records.`
            };
        }
    }
    const connectorRecords = payload.connectors || payload.connector_certification;
    if (connectorRecords && typeof connectorRecords === "object") {
        const connectorStates = Object.values(connectorRecords).map((value)=>String(value?.state || value?.status || "").toLowerCase());
        if (connectorStates.some((connectorState)=>connectorState.includes("blocked") || connectorState.includes("degraded") || connectorState.includes("failed"))) {
            return {
                state: "blocked",
                reason: "One or more connector certification records are blocked or degraded."
            };
        }
    }
    return {
        state: "ready",
        reason: status || "Dashboard section returned a usable payload."
    };
}
function dashboardLoadSurfaceState(state) {
    if (state.state === "ready") return "ready";
    if (state.state === "unauthorized") return "unauthorized";
    if (state.state === "backend-unavailable") return "backend-unavailable";
    if (state.state === "forbidden") return "blocked";
    if (state.state === "error") return "degraded";
    return "empty";
}
function buildDashboardTiles(dashboard) {
    const mesh = dashboard.mesh;
    const readiness = mesh.readiness || {};
    const runs = mesh.runs || {
        runs: []
    };
    const approvals = mesh.approvals || {
        items: []
    };
    const connectors = mesh.connectors || {};
    const connectorRecords = connectors.connectors || connectors.connector_certification || {};
    const praxis = buildPraxisProductModel(dashboard);
    const consolePayload = {
        status: "ready",
        workflows: CONSOLE_WORKFLOW_MATRIX.map((workflow)=>workflow.consoleView)
    };
    const rawTiles = [
        {
            title: "Control console",
            detail: `${CONSOLE_WORKFLOW_MATRIX.length} migrated workflows`,
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$cpu$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Cpu$3e$__["Cpu"],
            view: "console",
            apiSection: "meshapp.frontend.control_plane_api_client.v1",
            payload: consolePayload
        },
        {
            title: "Praxis MCP generator",
            detail: `Docker Dynamic MCP dry-run: ${praxis.certifiedTools} read-only / ${praxis.deniedTools} denied`,
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$sparkles$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Sparkles$3e$__["Sparkles"],
            view: "praxis",
            apiSection: "mesh.praxis",
            payload: mesh.praxis
        },
        {
            title: "Runtime readiness",
            detail: readModelSummary(readiness, "Read-only: readiness status unavailable"),
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$zap$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Zap$3e$__["Zap"],
            view: "gpu",
            apiSection: "mesh.readiness",
            payload: readiness
        },
        {
            title: "Run admission",
            detail: `${Array.isArray(runs.runs) ? runs.runs.length : 0} recent runs`,
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$play$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Play$3e$__["Play"],
            view: "evaluations",
            apiSection: "mesh.runs.runs",
            payload: runs
        },
        {
            title: "Connector status",
            detail: `${Object.keys(connectorRecords).length} connectors tracked`,
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$boxes$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Boxes$3e$__["Boxes"],
            view: "environments",
            apiSection: "mesh.connectors",
            payload: connectors
        },
        {
            title: "Orchestration topology",
            detail: readModelSummary(readiness.orchestration_topology || mesh.graph, "Read-only: topology profile unavailable"),
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$network$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Network$3e$__["Network"],
            view: "training",
            apiSection: "mesh.readiness.orchestration_topology || mesh.graph",
            payload: readiness.orchestration_topology || mesh.graph
        },
        {
            title: "Evidence packets",
            detail: readModelSummary(mesh.pilot_go_no_go, "Read-only: pilot packet unavailable"),
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$shield$2d$check$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__ShieldCheck$3e$__["ShieldCheck"],
            view: "evaluations",
            apiSection: "mesh.pilot_go_no_go",
            payload: mesh.pilot_go_no_go
        },
        {
            title: "Policy approvals",
            detail: `${Array.isArray(approvals.items) ? approvals.items.length : 0} pending`,
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$lock$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Lock$3e$__["Lock"],
            view: "evaluations",
            apiSection: "mesh.approvals.items",
            payload: approvals
        },
        {
            title: "Memory projection",
            detail: readModelSummary(mesh.memory?.graph, "Read-only: memory graph unavailable"),
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$database$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Database$3e$__["Database"],
            view: "inference",
            apiSection: "mesh.memory.graph",
            payload: mesh.memory?.graph
        },
        {
            title: "Settings parity",
            detail: "UI and CLI share validation",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$settings$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Settings$3e$__["Settings"],
            view: "settings",
            apiSection: "settings + settings_schema",
            payload: {
                settings: dashboard.settings,
                settings_schema: dashboard.settings_schema
            }
        },
        {
            title: "Operator setup",
            detail: `${buildOperatorSetupModel(dashboard).preferredAgents.length} preferred agent lanes`,
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$sliders$2d$horizontal$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__SlidersHorizontal$3e$__["SlidersHorizontal"],
            view: "operator-setup",
            apiSection: "operator_preferences_state",
            payload: dashboard.operator_preferences_state
        },
        {
            title: "Trust ladder",
            detail: `${Array.isArray(mesh.trust_ladder?.entries) ? mesh.trust_ladder.entries.length : 0} trust entries`,
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$shield$2d$check$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__ShieldCheck$3e$__["ShieldCheck"],
            view: "instances",
            apiSection: "mesh.trust_ladder.entries",
            payload: mesh.trust_ladder
        },
        {
            title: "Watchers",
            detail: readModelSummary(mesh.watchers, "Read-only: watcher state unavailable"),
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$activity$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Activity$3e$__["Activity"],
            view: "gpu",
            apiSection: "mesh.watchers",
            payload: mesh.watchers
        }
    ];
    return rawTiles.map((tile)=>{
        const state = dashboardSectionState(tile.payload);
        return {
            ...tile,
            state: state.state,
            stateReason: state.reason
        };
    });
}
function buildDashboardControlModel(dashboard) {
    const mesh = dashboard.mesh || {};
    const readiness = mesh.readiness || {};
    const runs = Array.isArray(mesh.runs?.runs) ? mesh.runs.runs : [];
    const approvals = Array.isArray(mesh.approvals?.items) ? mesh.approvals.items : [];
    const connectors = mesh.connectors?.connectors || mesh.connectors?.connector_certification || {};
    const connectorEntries = Object.entries(connectors);
    const pilot = mesh.pilot_go_no_go || {};
    const missingEvidence = Array.isArray(pilot.missing_evidence) ? pilot.missing_evidence.length : 0;
    const readinessStatus = readiness.status || (readiness.ready === true ? "ready" : readiness.ready === false ? "blocked" : "unknown");
    const activeRuns = runs.filter((run)=>![
            "completed",
            "failed",
            "cancelled"
        ].includes(String(run.status || "")));
    const connectorReady = connectorEntries.filter(([, value])=>String(value?.state || value?.status || "").includes("ready")).length;
    const killSwitch = mesh.kill_switch || {};
    const memoryGraph = mesh.memory?.graph || {};
    const topology = readiness.orchestration_topology || mesh.graph || {};
    return {
        readiness: {
            value: humanize(String(readinessStatus)),
            detail: readiness.blockers?.length ? `${readiness.blockers.length} blocker(s)` : readiness.detail || "Readiness snapshot from Mesh",
            tone: readinessStatus === "ready" || readiness.ready === true ? "good" : "warn"
        },
        runs: {
            value: String(activeRuns.length),
            detail: runs[0]?.scenario_key || `${runs.length} total run summary record(s)`,
            tone: activeRuns.length ? "warn" : "neutral"
        },
        approvals: {
            value: String(approvals.length),
            detail: approvals[0]?.blockers?.[0] || approvals[0]?.decision_type || "No pending approval queue item",
            tone: approvals.length ? "warn" : "good"
        },
        evidence: {
            value: missingEvidence ? `${missingEvidence} missing` : humanize(String(pilot.status || pilot.final_release_decision || "read-only")),
            detail: pilot.evidence_packet_id || pilot.reason || "Pilot packet and evidence posture from Mesh",
            tone: missingEvidence ? "warn" : "neutral"
        },
        recentRuns: runs.slice(0, 4).map((run)=>({
                id: String(run.run_id || run.id || run.scenario_key),
                label: String(run.scenario_key || "custom"),
                value: humanize(String(run.status || run.stage || "unknown")),
                detail: String(run.run_id || "run id unavailable")
            })),
        connectors: connectorEntries.slice(0, 5).map(([id, value])=>({
                id,
                label: String(value?.name || id),
                value: humanize(String(value?.state || value?.status || "unknown")),
                detail: String(value?.authority_posture || value?.detail || value?.credential_boundary?.credential_source || "Mesh connector certification")
            })),
        systemRows: [
            {
                id: "connector-total",
                label: "Connector matrix",
                value: `${connectorReady}/${connectorEntries.length}`,
                detail: "Ready connectors over tracked connectors",
                view: "environments"
            },
            {
                id: "topology",
                label: "Orchestration topology",
                value: humanize(String(topology.status || topology.state || topology.mode || "read-only")),
                detail: String(topology.detail || topology.degraded_reason || "Topology profile remains Mesh-owned"),
                view: "training"
            },
            {
                id: "memory",
                label: "Memory projection",
                value: humanize(String(memoryGraph.status || memoryGraph.state || "read-only")),
                detail: String(memoryGraph.detail || memoryGraph.reason || "Memory graph summary from Mesh read model"),
                view: "inference"
            },
            {
                id: "kill-switch",
                label: "Kill switch",
                value: humanize(String(killSwitch.status || killSwitch.state || (killSwitch.enabled === true ? "enabled" : "available"))),
                detail: String(killSwitch.reason || killSwitch.detail || "Emergency controls remain Mesh-owned"),
                view: "clusters"
            }
        ]
    };
}
function buildPraxisProductModel(dashboard) {
    const praxis = dashboard.mesh?.praxis || {};
    const summary = praxis.summary || {};
    const proof = praxis.p10_proof_packet || praxis.proof_packet || {};
    const readiness = proof.mcp_readiness || {};
    const runtime = praxis.pilot_runtime || {};
    const dockerBridge = runtime.docker_dynamic_mcp_bridge || {};
    const dockerManagementTools = Array.isArray(dockerBridge.management_tools) ? dockerBridge.management_tools : [];
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
        dockerDynamicMcpStatus: humanize(String(dockerBridge.status || "not_started")),
        dockerDynamicMcpGateway: String(dockerBridge.gateway_ref || "docker-mcp-gateway://current-session"),
        dockerDynamicMcpToolCount: String(dockerManagementTools.length),
        dockerDynamicMcpSession: dockerBridge.session_only === true && dockerBridge.profile_persisted === false ? "session-only, not profile-persisted" : "profile posture unavailable",
        runtimeStatus: humanize(String(runtime.status || readiness.status || "blocked")),
        managedRuntime: Boolean(runtime.managed_runtime_deployed),
        blockerCount: blockers.length,
        tools: tools.map((tool)=>{
            const result = String(tool.certification_result || tool.approval_posture || "candidate");
            return {
                id: String(tool.tool_id || tool.name),
                label: String(tool.name || tool.tool_id),
                value: humanize(result),
                detail: tool.readiness_blockers?.length ? `${tool.readiness_blockers.length} blocker(s)` : String(tool.mutation_class || "unknown"),
                method: String(tool.method || "GET"),
                path: String(tool.path || "/"),
                authScopes: Array.isArray(tool.allowed_scopes) ? tool.allowed_scopes.map(String) : Array.isArray(tool.auth_scope?.allowed_scopes) ? tool.auth_scope.allowed_scopes.map(String) : [],
                blockers: Array.isArray(tool.readiness_blockers) ? tool.readiness_blockers.map(String) : Array.isArray(tool.blockers) ? tool.blockers.map(String) : [],
                testPlan: Array.isArray(tool.test_plan) ? tool.test_plan.map(String) : [
                    `Validate ${String(tool.method || "GET")} ${String(tool.path || "/")} with redacted fixture input.`,
                    "Confirm dry-run call records side_effects_executed=false."
                ],
                tone: result === "read_only" || result === "staging_ready" ? "good" : result === "denied" ? "warn" : "neutral"
            };
        }),
        controls: controls.map((control)=>({
                id: String(control.control_id || control.label),
                label: String(control.label || control.control_id),
                value: humanize(String(control.state || "unknown")),
                detail: String(control.reason || (control.requires_mesh_approval ? "Requires Mesh approval" : "Dry-run control")),
                state: String(control.state || "unknown"),
                requiresMeshApproval: Boolean(control.requires_mesh_approval)
            }))
    };
}
function settingsParityRows(dashboard) {
    const scope = dashboard.scope.team ? `team:${dashboard.scope.team.id}` : `user:${dashboard.session.user.id}`;
    const operatorId = dashboard.session.user.email || dashboard.session.user.id;
    const mutableRows = Object.entries(dashboard.settings_schema).map(([key, schema])=>({
            key,
            label: titleize(key),
            value: dashboard.settings[key] ?? schema.default,
            description: schema.description,
            mutable: true,
            values: schema.values,
            uiMutationPath: "/api/operator/settings",
            cliPath: `python scripts/operator_config.py set --scope ${scope} --operator-id ${operatorId} --reason "<audit reason>" ${key}=...`
        }));
    const readonlyRows = [
        {
            key: "api_base_url",
            label: "API base URL",
            value: "Browser runtime target",
            description: "Read-only in UI. Change via frontend environment or deployment config.",
            mutable: false,
            readOnlyReason: "Product runtime target is deployment-owned, not operator settings state."
        },
        {
            key: "build_commit",
            label: "Build commit",
            value: dashboard.mesh.health?.commit || "unknown",
            description: "Read-only in UI. Change by building and deploying a new artifact.",
            mutable: false,
            readOnlyReason: "Build provenance is release metadata, not mutable operator preference."
        },
        {
            key: "state_backend",
            label: "State backend",
            value: dashboard.mesh.readiness?.state_backend || "RuntimeConfig-owned",
            description: "Read-only in UI. Change via environment or deployment config.",
            mutable: false,
            readOnlyReason: "Runtime persistence backend is owned by Mesh deployment configuration."
        },
        {
            key: "captcha_provider",
            label: "Captcha provider",
            value: "Auth config owned by environment",
            description: "Read-only in UI. Change through ignored env files or deployment secret manager.",
            mutable: false,
            readOnlyReason: "Auth provider secrets must not be written through the product dashboard."
        }
    ];
    return [
        ...mutableRows,
        ...readonlyRows
    ];
}
function listPreference(value) {
    if (Array.isArray(value)) return value.map(String).filter(Boolean);
    if (typeof value === "string") return value.split(",").map((item)=>item.trim()).filter(Boolean);
    return [];
}
function stringPreference(value, fallback = "") {
    if (typeof value === "boolean") return value ? "true" : "false";
    if (Array.isArray(value)) return value.join(", ");
    return String(value || fallback);
}
function booleanPreference(value) {
    if (typeof value === "boolean") return value;
    return [
        "true",
        "1",
        "yes",
        "required"
    ].includes(String(value || "").toLowerCase());
}
function buildOperatorSetupModel(dashboard) {
    const preferencesState = dashboard.operator_preferences_state || {};
    const preferences = preferencesState.operator_preferences || dashboard.operator_preferences || {};
    const schema = preferencesState.operator_preferences_schema || dashboard.operator_preferences_schema || {};
    const readiness = dashboard.mesh.readiness || {};
    const topology = readiness.orchestration_topology || dashboard.mesh.graph || {};
    const topologyProfile = topology.organization_profile || {};
    const providerPolicy = topology.model_provider_policy || {};
    const preferredAgents = listPreference(preferences.preferred_agents ?? schema.preferred_agents?.default);
    const pausePoints = listPreference(preferences.pause_points ?? schema.pause_points?.default);
    const modelProvider = stringPreference(preferences.model_provider ?? schema.model_provider?.default, "openai-compatible");
    const modelName = stringPreference(preferences.model_name ?? schema.model_name?.default, "MiniMax-M2.7");
    const scopeTeam = dashboard.scope?.team || null;
    const sessionUser = dashboard.session?.user || {
        id: "unknown",
        email: "unknown",
        display_name: "Unknown"
    };
    const sessionRoles = dashboard.session?.active_team?.roles || (scopeTeam?.roles ?? [
        "viewer",
        "launcher"
    ]);
    const scope = String(preferencesState.scope || (scopeTeam ? `team:${scopeTeam.id}` : `user:${sessionUser.id}`));
    return {
        stateSlice: String(preferencesState.state_slice || "mesh.operator-preferences.v1"),
        scope,
        operatorId: sessionUser.email || sessionUser.id,
        roles: sessionRoles,
        source: "operator_session",
        team: scopeTeam?.display_name || scopeTeam?.name || "Solo",
        agentFabricMode: stringPreference(preferences.agent_fabric_mode ?? schema.agent_fabric_mode?.default, "native"),
        preferredAgents,
        modelBinding: `${modelProvider}:${modelName}`,
        approvalPolicy: stringPreference(preferences.approval_policy ?? schema.approval_policy?.default, "approval_required"),
        pausePoints,
        target: {
            environment: stringPreference(preferences.target_environment ?? schema.target_environment?.default, "pilot"),
            namespace: stringPreference(preferences.target_namespace ?? schema.target_namespace?.default, "search"),
            service: stringPreference(preferences.target_service ?? schema.target_service?.default, "semantic-search"),
            lockRequired: booleanPreference(preferences.target_lock_required ?? schema.target_lock_required?.default)
        },
        runTemplate: stringPreference(preferences.run_template ?? schema.run_template?.default, "reth_peer_starvation"),
        topology: {
            active: String(topology.active_topology || topology.mode || topology.status || "centralized"),
            preferredAgents: Array.isArray(topologyProfile.preferred_agents) ? topologyProfile.preferred_agents.map(String) : [],
            allowedModels: Array.isArray(providerPolicy.allowed_models) ? providerPolicy.allowed_models.map((item)=>`${item.provider}:${item.model}`) : [],
            blockers: Array.isArray(topology.blockers) ? topology.blockers.map(String) : []
        }
    };
}
function buildRunPreflightModel(dashboard, selection) {
    const setup = buildOperatorSetupModel(dashboard);
    const readiness = dashboard.mesh.readiness || {};
    const connectors = dashboard.mesh.connectors?.connectors || dashboard.mesh.connectors?.connector_certification || {};
    const connectorScopes = Object.values(connectors).flatMap((connector)=>Array.isArray(connector?.allowed_scopes) ? connector.allowed_scopes : []).map(String);
    const uniqueScopes = Array.from(new Set(connectorScopes)).sort();
    const readinessBlockers = [
        ...Array.isArray(readiness.blockers) ? readiness.blockers.map(String) : [],
        ...setup.topology.blockers
    ];
    const operatorPresent = Boolean(setup.operatorId && setup.roles.length);
    return {
        operatorPresent,
        operatorId: setup.operatorId,
        roles: setup.roles,
        source: setup.source,
        team: setup.team,
        selectedTopology: setup.topology.active,
        selectedAgents: setup.preferredAgents,
        modelBinding: setup.modelBinding,
        pausePoints: setup.pausePoints,
        target: `${setup.target.environment}/${setup.target.namespace}/${setup.target.service}`,
        targetLock: selection?.requireTargetLock ?? setup.target.lockRequired ? "required" : "optional",
        connectorScopes: uniqueScopes.slice(0, 8),
        readiness: humanize(String(readiness.status || (readiness.ready === true ? "ready" : readiness.ready === false ? "blocked" : "unknown"))),
        blockers: operatorPresent ? readinessBlockers : [
            "operator_identity_missing",
            ...readinessBlockers
        ]
    };
}
function buildHardenedArenaProfileCards(registry) {
    return (registry?.profiles || []).map((profile)=>({
            id: profile.profile_id,
            title: profile.display_name,
            detail: profile.intended_use,
            state: profile.lifecycle_state,
            readiness: profile.readiness_posture,
            aiLane: profile.ai_lane,
            blockers: Array.isArray(profile.blockers) ? profile.blockers : [],
            components: Array.isArray(profile.components) ? profile.components.length : 0,
            proofGates: profile.proof_gates?.required || []
        }));
}
function HardenedArenaView({ setView }) {
    _s9();
    const [arenaState, setArenaState] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])({
        state: "loading"
    });
    const [selectedProfileId, setSelectedProfileId] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("solo_project_default");
    const [intendedUse, setIntendedUse] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("solo project / startup trial");
    const [compliancePosture, setCompliancePosture] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("baseline with DHI preferred inputs");
    const [packetState, setPacketState] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])({
        state: "empty",
        message: "No packet generated yet."
    });
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "HardenedArenaView.useEffect": ()=>{
            let mounted = true;
            Promise.all([
                __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].hardenedArenaProfiles(),
                __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].hardenedArenaCatalog()
            ]).then({
                "HardenedArenaView.useEffect": ([profiles, catalog])=>{
                    if (!mounted) return;
                    setArenaState({
                        state: "ready",
                        data: {
                            profiles,
                            catalog
                        }
                    });
                    if (profiles.profiles?.[0]?.profile_id) setSelectedProfileId({
                        "HardenedArenaView.useEffect": (current)=>current || profiles.profiles[0].profile_id
                    }["HardenedArenaView.useEffect"]);
                }
            }["HardenedArenaView.useEffect"]).catch({
                "HardenedArenaView.useEffect": (error)=>{
                    if (!mounted) return;
                    setArenaState((0, __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["loadStateFromError"])(error));
                }
            }["HardenedArenaView.useEffect"]);
            return ({
                "HardenedArenaView.useEffect": ()=>{
                    mounted = false;
                }
            })["HardenedArenaView.useEffect"];
        }
    }["HardenedArenaView.useEffect"], []);
    async function generatePacket() {
        if (!selectedProfileId || packetState.state === "loading") return;
        setPacketState({
            state: "loading"
        });
        try {
            const response = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].generateHardenedArenaPacket(selectedProfileId);
            setPacketState({
                state: "ready",
                data: response
            });
        } catch (error) {
            setPacketState((0, __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["loadStateFromError"])(error));
        }
    }
    if (arenaState.state !== "ready") {
        return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(LoadStatePanel, {
            state: arenaState,
            onRetry: ()=>{
                setArenaState({
                    state: "loading"
                });
                Promise.all([
                    __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].hardenedArenaProfiles(),
                    __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].hardenedArenaCatalog()
                ]).then(([profiles, catalog])=>{
                    setArenaState({
                        state: "ready",
                        data: {
                            profiles,
                            catalog
                        }
                    });
                    if (profiles.profiles?.[0]?.profile_id) {
                        setSelectedProfileId((current)=>current || profiles.profiles[0].profile_id);
                    }
                }).catch((error)=>setArenaState((0, __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["loadStateFromError"])(error)));
            }
        }, void 0, false, {
            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
            lineNumber: 2891,
            columnNumber: 7
        }, this);
    }
    const { profiles, catalog } = arenaState.data;
    const profileCards = buildHardenedArenaProfileCards(profiles);
    const selectedProfile = profiles.profiles.find((profile)=>profile.profile_id === selectedProfileId) || profiles.profiles[0];
    const packetCreate = packetState.state === "ready" ? packetState.data : null;
    const packet = packetCreate?.packet ?? null;
    const catalogImages = catalog.entries.filter((entry)=>entry.type === "image").length;
    const catalogCharts = catalog.entries.filter((entry)=>entry.type === "chart").length;
    const proofBlocked = packet?.readiness_posture?.target_validated === false;
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "content-stack",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Toolbar, {
                title: "Build Arena",
                detail: "Generate review-only Hardened Production Arena proof packets. This surface does not deploy, install, ingest secrets, or claim production readiness.",
                action: "Review readiness",
                onAction: ()=>setView("gpu")
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2919,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "stat-row",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Stat, {
                        label: "Profiles",
                        value: String(profiles.profiles.length),
                        detail: "Recipe profiles only"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2926,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Stat, {
                        label: "DHI catalog",
                        value: `${catalogImages} images / ${catalogCharts} charts`,
                        detail: "Catalog data only, no deployment claim"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2927,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Stat, {
                        label: "Readiness posture",
                        value: "Not deployed",
                        detail: "Target proof required before validation"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2928,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2925,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "form-card",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "form-grid two",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                                children: [
                                    "Target profile",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("select", {
                                        value: selectedProfileId,
                                        onChange: (event)=>setSelectedProfileId(event.target.value),
                                        children: profiles.profiles.map((profile)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                                                value: profile.profile_id,
                                                children: profile.display_name
                                            }, profile.profile_id, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 2935,
                                                columnNumber: 51
                                            }, this))
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2934,
                                        columnNumber: 13
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2932,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                                children: [
                                    "Intended use",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("select", {
                                        value: intendedUse,
                                        onChange: (event)=>setIntendedUse(event.target.value),
                                        children: [
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                                                children: "solo project / startup trial"
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 2941,
                                                columnNumber: 15
                                            }, this),
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                                                children: "internal lab rehearsal"
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 2942,
                                                columnNumber: 15
                                            }, this),
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                                                children: "enterprise on-prem rehearsal"
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 2943,
                                                columnNumber: 15
                                            }, this)
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2940,
                                        columnNumber: 13
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2938,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                                children: [
                                    "Compliance posture",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("select", {
                                        value: compliancePosture,
                                        onChange: (event)=>setCompliancePosture(event.target.value),
                                        children: [
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                                                children: "baseline with DHI preferred inputs"
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 2949,
                                                columnNumber: 15
                                            }, this),
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                                                children: "CIS-preferred review"
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 2950,
                                                columnNumber: 15
                                            }, this),
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                                                children: "FIPS/STIG blockers visible"
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 2951,
                                                columnNumber: 15
                                            }, this),
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                                                children: "customer-controlled image source"
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 2952,
                                                columnNumber: 15
                                            }, this)
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 2948,
                                        columnNumber: 13
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2946,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(FormRead, {
                                label: "Selected posture",
                                value: `${intendedUse}; ${compliancePosture}`
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2955,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2931,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "action-row",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                className: "primary-button",
                                type: "button",
                                onClick: generatePacket,
                                disabled: packetState.state === "loading",
                                children: "Generate packet"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2958,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                type: "button",
                                disabled: true,
                                title: "Intent preparation is review-only in this release",
                                children: "Prepare intent"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2959,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                className: "muted-inline",
                                children: "Review-only — no production deploy from this surface."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2962,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2957,
                        columnNumber: 9
                    }, this),
                    packetState.state === "error" || packetState.state === "forbidden" || packetState.state === "unauthorized" ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(EmptyInline, {
                        text: packetState.message
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2964,
                        columnNumber: 119
                    }, this) : null
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2930,
                columnNumber: 7
            }, this),
            selectedProfile ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "capability-grid two",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ReadModelCard, {
                        title: "Component graph",
                        payload: {
                            components: selectedProfile.components,
                            selected_profile: selectedProfile.profile_id
                        }
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2968,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ReadModelCard, {
                        title: "Authority boundaries",
                        payload: {
                            authority: selectedProfile.components.map((component)=>({
                                    component_id: component.component_id,
                                    boundary: component.authority_boundary,
                                    credential_class: component.credential_class,
                                    mutates_state: component.mutates_state
                                }))
                        }
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2969,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ReadModelCard, {
                        title: "Blockers",
                        payload: {
                            profile_blockers: selectedProfile.blockers,
                            source_blockers: selectedProfile.components.flatMap((component)=>component.source?.blockers || [])
                        }
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2970,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ReadModelCard, {
                        title: "Proof checklist",
                        payload: {
                            gates: selectedProfile.proof_gates.required,
                            target_validated_allowed: selectedProfile.proof_gates.target_validated_allowed
                        }
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2971,
                        columnNumber: 11
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2967,
                columnNumber: 9
            }, this) : null,
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(CardRows, {
                sections: [
                    {
                        title: "Profile registry",
                        count: profileCards.length,
                        cards: profileCards.map((card)=>({
                                id: card.id,
                                owner: "Hardened arena",
                                state: card.state,
                                title: card.title,
                                detail: card.detail,
                                blockers: card.blockers,
                                tags: [
                                    card.readiness,
                                    card.aiLane,
                                    `${card.components} components`
                                ],
                                version: "mesh.hardened_arena.profiles.v1"
                            }))
                    }
                ]
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2974,
                columnNumber: 7
            }, this),
            packet ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "form-card",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h3", {
                        children: "Export / review packet"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2977,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                        children: [
                            "Packet `",
                            packet.packet_id,
                            "` is stored for review. It says ",
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: packet.readiness_posture.status
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2978,
                                columnNumber: 72
                            }, this),
                            ", not deployed or production-ready."
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2978,
                        columnNumber: 11
                    }, this),
                    proofBlocked ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(EmptyInline, {
                        text: "Blocked proof state visible: target_validated remains false until observed target-specific proof exists."
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2979,
                        columnNumber: 27
                    }, this) : null,
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "capability-grid two",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ReadModelCard, {
                                title: "Generated packet",
                                payload: packet
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2981,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ReadModelCard, {
                                title: "Packet storage",
                                payload: {
                                    packet_path: packetCreate?.packet_path,
                                    stored_artifact: packetCreate?.stored_artifact,
                                    live_deployment_allowed: packetCreate?.live_deployment_allowed
                                }
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 2982,
                                columnNumber: 13
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 2980,
                        columnNumber: 11
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 2976,
                columnNumber: 9
            }, this) : null
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 2918,
        columnNumber: 5
    }, this);
}
_s9(HardenedArenaView, "NMUuoOfajW4zFNJuo5VLqJRjivQ=");
_c29 = HardenedArenaView;
function EnvironmentView({ dashboard, setView }) {
    _s10();
    const connectorPosture = operatorWorkflowPosture("connector");
    const connectors = dashboard.mesh.connectors?.connectors || dashboard.mesh.connectors?.connector_certification || {};
    const [query, setQuery] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [stateFilter, setStateFilter] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("all");
    const [domainFilter, setDomainFilter] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("all");
    const cards = Object.entries(connectors).map(([id, value])=>({
            id,
            owner: "Mesh",
            blockers: Array.isArray(value.blockers) ? value.blockers : [],
            state: String(value.state || value.status || "unknown"),
            domain: String(value.domain || value.credential_boundary?.credential_source || "Deployment"),
            title: value.name || id,
            detail: value.detail || value.authority_posture || "Connector certification state",
            tags: [
                value.state || "unknown",
                value.credential_boundary?.credential_source || "config"
            ],
            version: value.schema_version || "v1"
        }));
    const stateOptions = [
        "all",
        ...Array.from(new Set(cards.map((card)=>card.state))).sort()
    ];
    const domainOptions = [
        "all",
        ...Array.from(new Set(cards.map((card)=>card.domain))).sort()
    ];
    const loweredQuery = query.trim().toLowerCase();
    const filteredCards = cards.filter((card)=>{
        const matchesQuery = !loweredQuery || [
            card.id,
            card.title,
            card.detail,
            card.state,
            card.domain,
            ...card.tags
        ].join(" ").toLowerCase().includes(loweredQuery);
        const matchesState = stateFilter === "all" || card.state === stateFilter;
        const matchesDomain = domainFilter === "all" || card.domain === domainFilter;
        return matchesQuery && matchesState && matchesDomain;
    });
    const grouped = groupConnectorCards(filteredCards);
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "content-stack",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Toolbar, {
                title: "Connectors",
                detail: connectorPosture.reason,
                action: "Review Dashboard",
                onAction: ()=>setView("home")
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3020,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(SearchBar, {
                value: query,
                onChange: setQuery,
                placeholder: "Filter connectors by name, status, domain, blocker..."
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3026,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "filter-row",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                        children: [
                            "State",
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("select", {
                                value: stateFilter,
                                onChange: (event)=>setStateFilter(event.target.value),
                                children: stateOptions.map((state)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                                        value: state,
                                        children: humanize(state)
                                    }, state, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3031,
                                        columnNumber: 42
                                    }, this))
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3030,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3028,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                        children: [
                            "Domain",
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("select", {
                                value: domainFilter,
                                onChange: (event)=>setDomainFilter(event.target.value),
                                children: domainOptions.map((domain)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                                        value: domain,
                                        children: humanize(domain)
                                    }, domain, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3037,
                                        columnNumber: 44
                                    }, this))
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3036,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3034,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3027,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "connector-legend",
                children: [
                    "ready",
                    "staging-ready",
                    "read-only",
                    "config-only",
                    "blocked",
                    "stub",
                    "disconnected"
                ].map((state)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$circle$2d$dot$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__CircleDot$3e$__["CircleDot"], {
                                size: 10
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3043,
                                columnNumber: 29
                            }, this),
                            " ",
                            humanize(state)
                        ]
                    }, state, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3043,
                        columnNumber: 11
                    }, this))
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3041,
                columnNumber: 7
            }, this),
            filteredCards.length ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(CardRows, {
                sections: grouped
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3046,
                columnNumber: 31
            }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(EmptyInline, {
                text: "No connectors match the current filters."
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3046,
                columnNumber: 65
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 3019,
        columnNumber: 5
    }, this);
}
_s10(EnvironmentView, "nQEgN7Ki1XQBXe0GhevhbNw1X34=");
_c30 = EnvironmentView;
function groupConnectorCards(cards) {
    const groups = new Map();
    for (const card of cards){
        const key = `${humanize(card.state)} / ${card.domain}`;
        groups.set(key, [
            ...groups.get(key) || [],
            card
        ]);
    }
    return Array.from(groups.entries()).sort(([a], [b])=>a.localeCompare(b)).map(([title, groupCards])=>({
            title,
            count: groupCards.length,
            cards: groupCards
        }));
}
function EvaluationsView({ dashboard, setView, onDashboardRefresh }) {
    _s11();
    const launchPosture = operatorWorkflowPosture("launch");
    const runs = dashboard.mesh.runs?.runs || [];
    const [query, setQuery] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const active = runs.filter((run)=>![
            "completed",
            "failed",
            "cancelled"
        ].includes(run.status)).length;
    const failed = runs.filter((run)=>run.status === "failed").length;
    const traceSteps = evidenceTraceSteps(dashboard);
    const loweredQuery = query.trim().toLowerCase();
    const filteredRuns = runs.filter((run)=>{
        if (!loweredQuery) return true;
        return [
            run.run_id,
            run.id,
            run.scenario_key,
            run.status,
            run.stage,
            run.created_at,
            run.operator_id
        ].map((value)=>String(value || "")).join(" ").toLowerCase().includes(loweredQuery);
    });
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "content-stack",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Toolbar, {
                title: "Evaluations",
                detail: launchPosture.reason,
                action: "Review Dashboard",
                onAction: ()=>setView("home")
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3090,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(LaunchRunPanel, {
                dashboard: dashboard,
                onDashboardRefresh: onDashboardRefresh
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3096,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ApprovalQueuePanel, {
                dashboard: dashboard,
                onDashboardRefresh: onDashboardRefresh
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3097,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "stat-row",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Stat, {
                        label: "Active evals",
                        value: String(active),
                        detail: "Pending, running, or processing"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3099,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Stat, {
                        label: "Failed evals",
                        value: String(failed),
                        detail: "Failed or timed out evaluations"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3100,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Stat, {
                        label: "Total evals",
                        value: String(runs.length),
                        detail: "All evaluations in this account"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3101,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3098,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(TraceRail, {
                steps: traceSteps
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3103,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ProofDrilldownPanel, {
                dashboard: dashboard
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3104,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(SearchBar, {
                value: query,
                onChange: setQuery,
                placeholder: "Search by run, scenario, status, operator..."
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3105,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "data-table",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "table-head",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Name"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3107,
                                columnNumber: 37
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Scenario"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3107,
                                columnNumber: 54
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Status"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3107,
                                columnNumber: 75
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Created"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3107,
                                columnNumber: 94
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Created by"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3107,
                                columnNumber: 114
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3107,
                        columnNumber: 9
                    }, this),
                    filteredRuns.length ? filteredRuns.map((run)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                            className: "table-row",
                            children: [
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                    children: run.run_id
                                }, void 0, false, {
                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                    lineNumber: 3110,
                                    columnNumber: 13
                                }, this),
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                    children: run.scenario_key || "custom"
                                }, void 0, false, {
                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                    lineNumber: 3110,
                                    columnNumber: 38
                                }, this),
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                    children: run.status
                                }, void 0, false, {
                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                    lineNumber: 3110,
                                    columnNumber: 81
                                }, this),
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                    children: run.created_at
                                }, void 0, false, {
                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                    lineNumber: 3110,
                                    columnNumber: 106
                                }, this),
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                    children: run.operator_id || "Mesh"
                                }, void 0, false, {
                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                    lineNumber: 3110,
                                    columnNumber: 135
                                }, this)
                            ]
                        }, run.run_id, true, {
                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                            lineNumber: 3109,
                            columnNumber: 11
                        }, this)) : runs.length ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "empty-eval",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$search$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Search$3e$__["Search"], {
                                size: 24
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3113,
                                columnNumber: 39
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: "No matching evaluations"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3113,
                                columnNumber: 59
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                children: "Adjust the search terms to inspect run state returned by Mesh."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3113,
                                columnNumber: 99
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3113,
                        columnNumber: 11
                    }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "empty-eval",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$chart$2d$column$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__BarChart3$3e$__["BarChart3"], {
                                size: 24
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3115,
                                columnNumber: 39
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: "Run your first evaluation"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3115,
                                columnNumber: 62
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                children: "Use the launch form above. Mesh owns admission and policy."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3115,
                                columnNumber: 104
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3115,
                        columnNumber: 11
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3106,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 3089,
        columnNumber: 5
    }, this);
}
_s11(EvaluationsView, "HYX2QbDDdTtlu7GfoQbAPZOIM6k=");
_c31 = EvaluationsView;
function ApprovalQueuePanel({ dashboard, onDashboardRefresh }) {
    _s12();
    const queue = dashboard.mesh.approvals || {};
    const items = Array.isArray(queue.items) ? queue.items : [];
    const [reasonByRun, setReasonByRun] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])({});
    const [message, setMessage] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [busyCommand, setBusyCommand] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    async function runCommand(runId, command) {
        const reason = (reasonByRun[runId] || "").trim();
        if (command !== "cancel" && !reason) {
            setMessage("Approval action reason is required before product steering calls Mesh.");
            return;
        }
        setBusyCommand(`${runId}:${command}`);
        setMessage("");
        try {
            await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].steerRun(runId, {
                command,
                reason
            });
            await onDashboardRefresh();
            setMessage(`Mesh accepted ${command} for ${runId}.`);
        } catch (err) {
            setMessage(err instanceof Error ? err.message : "Approval command failed");
        } finally{
            setBusyCommand("");
        }
    }
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
        className: "approval-panel",
        "aria-label": "Approval queue",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "panel-heading",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Approval queue"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3152,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h3", {
                                children: "Mesh owns this decision"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3153,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                children: "Actions call `POST /api/runs/:id/steer` with Mesh role checks, command validation, and audit context."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3154,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3151,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                        children: queue.status || "empty"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3156,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3150,
                columnNumber: 7
            }, this),
            items.length ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "approval-list",
                children: items.map((item)=>{
                    const commands = approvalCommands(item.allowed_commands);
                    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("article", {
                        className: `approval-card ${item.approval_state || "pending"}`,
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: item.scenario_key || "custom"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3165,
                                        columnNumber: 19
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                        children: item.approval_state || "pending"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3166,
                                        columnNumber: 19
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                        children: item.run_id
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3167,
                                        columnNumber: 19
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3164,
                                columnNumber: 17
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                children: item.blockers?.length ? `Blocked by ${item.blockers.join(", ")}` : item.final_recommendation || "Awaiting Mesh-approved operator decision."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3169,
                                columnNumber: 17
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "approval-evidence-grid",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: [
                                            "Risk ",
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                                children: humanize(String(item.risk_tier || item.risk || "unknown"))
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 3171,
                                                columnNumber: 30
                                            }, this)
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3171,
                                        columnNumber: 19
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: [
                                            "Action ",
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                                children: humanize(String(item.proposed_action || item.decision_type || "review"))
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 3172,
                                                columnNumber: 32
                                            }, this)
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3172,
                                        columnNumber: 19
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: [
                                            "Evidence ",
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                                children: [
                                                    Array.isArray(item.evidence_refs) ? item.evidence_refs.length : 0,
                                                    " ref(s)"
                                                ]
                                            }, void 0, true, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 3173,
                                                columnNumber: 34
                                            }, this)
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3173,
                                        columnNumber: 19
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: [
                                            "Approver ",
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                                children: item.approver_role || "approver/admin"
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 3174,
                                                columnNumber: 34
                                            }, this)
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3174,
                                        columnNumber: 19
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: [
                                            "Rollback ",
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                                children: item.rollback_authority || item.rollback_ref || "Mesh-owned"
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 3175,
                                                columnNumber: 34
                                            }, this)
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3175,
                                        columnNumber: 19
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: [
                                            "Expires ",
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                                children: item.expires_at || item.approval_expires_at || "policy default"
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 3176,
                                                columnNumber: 33
                                            }, this)
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3176,
                                        columnNumber: 19
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3170,
                                columnNumber: 17
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                                children: [
                                    "Action reason",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                        value: reasonByRun[item.run_id] || "",
                                        onChange: (event)=>setReasonByRun({
                                                ...reasonByRun,
                                                [item.run_id]: event.target.value
                                            }),
                                        placeholder: "why this approval action is correct"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3180,
                                        columnNumber: 19
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3178,
                                columnNumber: 17
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "approval-actions",
                                children: commands.map((command)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                        type: "button",
                                        onClick: ()=>runCommand(item.run_id, command),
                                        disabled: busyCommand === `${item.run_id}:${command}`,
                                        children: humanize(command)
                                    }, command, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3188,
                                        columnNumber: 21
                                    }, this))
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3186,
                                columnNumber: 17
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: (item.evidence_refs || []).slice(0, 3).join(" | ")
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3198,
                                columnNumber: 17
                            }, this)
                        ]
                    }, item.queue_id || item.run_id, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3163,
                        columnNumber: 15
                    }, this);
                })
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3159,
                columnNumber: 9
            }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(EmptyInline, {
                text: "No approval queue items returned by Mesh."
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3203,
                columnNumber: 11
            }, this),
            message ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: message.startsWith("Mesh accepted") ? "product-alert success" : "auth-error",
                children: message
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3204,
                columnNumber: 18
            }, this) : null
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 3149,
        columnNumber: 5
    }, this);
}
_s12(ApprovalQueuePanel, "ABITr4eVs8wn13wcLvEHpQwCRw4=");
_c32 = ApprovalQueuePanel;
function approvalCommands(raw) {
    const allowed = Array.isArray(raw) ? raw.map(String) : [];
    return [
        "approve",
        "resume",
        "explain_blockers",
        "override_decision",
        "cancel"
    ].filter((command)=>allowed.includes(command));
}
const SCENARIO_PICKER = [
    {
        key: "reth_peer_starvation",
        label: "Reth peer starvation",
        detail: "Exercise peer loss, degraded sync signal, evidence collection, and bounded remediation."
    },
    {
        key: "reth_sync_stalled_disk_pressure",
        label: "Reth disk pressure stall",
        detail: "Rehearse stalled sync diagnosis against disk-pressure evidence and safe remediation gates."
    },
    {
        key: "kubernetes_crashloop_patch",
        label: "Kubernetes crashloop patch",
        detail: "Check workload evidence, ownership, approval, and patch safety before cluster-facing action."
    },
    {
        key: "search_latency_regression",
        label: "Search latency regression",
        detail: "Validate service-latency triage, RCA evidence, and advisory remediation boundaries."
    }
];
const AUDIT_REASON_TEMPLATES = [
    "Pilot dry-run: verify readiness and proof continuity before partner invite.",
    "Partner review: explain blockers without granting production authority.",
    "Regression rehearsal: confirm Mesh admission, approval, and evidence paths."
];
function ProofDrilldownPanel({ dashboard }) {
    _s13();
    const runs = dashboard.mesh.runs?.runs || [];
    const [selectedRunId, setSelectedRunId] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(String(runs[0]?.run_id || ""));
    const [proof, setProof] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])({
        status: "idle",
        runId: "",
        message: "",
        payloads: {}
    });
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "ProofDrilldownPanel.useEffect": ()=>{
            if (!selectedRunId && runs[0]?.run_id) setSelectedRunId(String(runs[0].run_id));
        }
    }["ProofDrilldownPanel.useEffect"], [
        runs,
        selectedRunId
    ]);
    async function loadProof() {
        if (!selectedRunId) {
            setProof({
                status: "error",
                runId: "",
                message: "Select a run before loading proof views.",
                payloads: {}
            });
            return;
        }
        setProof({
            status: "loading",
            runId: selectedRunId,
            message: "Loading Mesh proof views.",
            payloads: {}
        });
        const loaders = {
            detail: __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].runDetail(selectedRunId),
            events: __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].runEvents(selectedRunId),
            evidenceGraph: __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].evidenceGraph(selectedRunId),
            rcaTrace: __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].scenarioAnalysis(selectedRunId),
            merkle: __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].merkle(selectedRunId),
            timelineProof: __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].timelineProof(selectedRunId),
            exportPackage: __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].exportRun(selectedRunId)
        };
        const entries = await Promise.all(Object.entries(loaders).map(async ([key, promise])=>{
            try {
                return [
                    key,
                    {
                        state: "ready",
                        payload: await promise
                    }
                ];
            } catch (err) {
                return [
                    key,
                    {
                        state: "blocked",
                        error: err instanceof Error ? err.message : "unavailable"
                    }
                ];
            }
        }));
        setProof({
            status: "ready",
            runId: selectedRunId,
            message: "Loaded read-only Mesh proof views. Mesh owns evidence, RCA, export, and decision records.",
            payloads: Object.fromEntries(entries)
        });
    }
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
        className: "proof-panel",
        "aria-label": "Proof packet and evidence views",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "panel-heading",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Evidence graph / proof packet / RCA trace / export"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3277,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h3", {
                                children: "Read-only Mesh proof views"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3278,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                children: "Every drill-in uses existing Mesh proof endpoints. The product shell cannot rewrite evidence or approve decisions from these views."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3279,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3276,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        type: "button",
                        onClick: loadProof,
                        disabled: proof.status === "loading" || !runs.length,
                        children: proof.status === "loading" ? "Loading" : "Load proof views"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3281,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3275,
                columnNumber: 7
            }, this),
            runs.length ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                className: "proof-run-select",
                children: [
                    "Run",
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("select", {
                        value: selectedRunId,
                        onChange: (event)=>setSelectedRunId(event.target.value),
                        children: runs.map((run)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                                value: run.run_id,
                                children: [
                                    run.scenario_key || "custom",
                                    " / ",
                                    run.run_id
                                ]
                            }, run.run_id, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3289,
                                columnNumber: 37
                            }, this))
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3288,
                        columnNumber: 11
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3286,
                columnNumber: 9
            }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(EmptyInline, {
                text: "No run summaries available for proof drill-in."
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3292,
                columnNumber: 11
            }, this),
            proof.message ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: proof.status === "error" ? "auth-error" : "product-alert success",
                children: proof.message
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3293,
                columnNumber: 24
            }, this) : null,
            proof.status === "ready" ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["Fragment"], {
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(RunWorkbenchSummary, {
                        model: buildRunWorkbenchModel(proof.payloads)
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3296,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(AgentFabricObservability, {
                        attempts: buildAgentFabricObservability(proof.payloads)
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3297,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "proof-grid",
                        children: Object.entries(proof.payloads).map(([key, value])=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ReadModelCard, {
                                title: humanize(key),
                                payload: value
                            }, key, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3300,
                                columnNumber: 15
                            }, this))
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3298,
                        columnNumber: 11
                    }, this)
                ]
            }, void 0, true) : null
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 3274,
        columnNumber: 5
    }, this);
}
_s13(ProofDrilldownPanel, "KxtCq6FuwbQC8g8+kPS61o6Y/Nk=");
_c33 = ProofDrilldownPanel;
function AgentFabricObservability({ attempts }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
        className: "run-workbench",
        "aria-label": "Agent fabric observability",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "panel-title",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$network$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Network$3e$__["Network"], {
                        size: 15
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3312,
                        columnNumber: 36
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        children: "meshapp.agent_fabric_observability.v1"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3312,
                        columnNumber: 57
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3312,
                columnNumber: 7
            }, this),
            attempts.length ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "preflight-grid",
                children: attempts.map((attempt)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: [
                                    attempt.agent,
                                    " / ",
                                    attempt.adapter
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3317,
                                columnNumber: 15
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: humanize(attempt.status)
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3318,
                                columnNumber: 15
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: [
                                    attempt.harness,
                                    " / ",
                                    attempt.events,
                                    " event(s) / ",
                                    attempt.tools,
                                    " tool call(s)"
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3319,
                                columnNumber: 15
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: [
                                    attempt.changedFiles,
                                    " changed file(s) / ",
                                    attempt.tests,
                                    " test result(s)"
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3320,
                                columnNumber: 15
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: [
                                    "egress: ",
                                    attempt.egress
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3321,
                                columnNumber: 15
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: [
                                    "release: ",
                                    attempt.release
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3322,
                                columnNumber: 15
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: [
                                    "authority: ",
                                    attempt.authority
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3323,
                                columnNumber: 15
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: [
                                    "risk: ",
                                    attempt.riskFlags.length ? attempt.riskFlags.join(", ") : "none"
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3324,
                                columnNumber: 15
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: [
                                    "proposal: ",
                                    attempt.output
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3325,
                                columnNumber: 15
                            }, this)
                        ]
                    }, attempt.key, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3316,
                        columnNumber: 13
                    }, this))
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3314,
                columnNumber: 9
            }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(EmptyInline, {
                text: "No durable agent attempt threads were projected for this run."
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3330,
                columnNumber: 9
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 3311,
        columnNumber: 5
    }, this);
}
_c34 = AgentFabricObservability;
function RunWorkbenchSummary({ model }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
        className: "run-workbench",
        "aria-label": "Run workbench",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "panel-title",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$activity$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Activity$3e$__["Activity"], {
                        size: 15
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3339,
                        columnNumber: 36
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        children: "meshapp.run-workbench.v1"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3339,
                        columnNumber: 58
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3339,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "preflight-grid",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Run"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3341,
                                columnNumber: 14
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: model.runId || "selected run"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3341,
                                columnNumber: 30
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: [
                                    model.currentStage,
                                    " / ",
                                    model.status
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3341,
                                columnNumber: 78
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3341,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Operator"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3342,
                                columnNumber: 14
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: model.operator
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3342,
                                columnNumber: 35
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: "Launcher or Mesh-owned system context"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3342,
                                columnNumber: 68
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3342,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Evidence"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3343,
                                columnNumber: 14
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: model.evidenceSummary
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3343,
                                columnNumber: 35
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: [
                                    model.events,
                                    " event(s) loaded"
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3343,
                                columnNumber: 75
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3343,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Decision"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3344,
                                columnNumber: 14
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: humanize(model.decisionSummary)
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3344,
                                columnNumber: 35
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: model.nextAction
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3344,
                                columnNumber: 85
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3344,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Agent mesh"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3345,
                                columnNumber: 14
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: model.agentSummary
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3345,
                                columnNumber: 37
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: "Review lane outputs in detail payload."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3345,
                                columnNumber: 74
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3345,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Blockers"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3346,
                                columnNumber: 14
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: model.blockers.length ? model.blockers.join(", ") : "none"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3346,
                                columnNumber: 35
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: "Evidence translation, not authority replacement."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3346,
                                columnNumber: 112
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3346,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3340,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 3338,
        columnNumber: 5
    }, this);
}
_c35 = RunWorkbenchSummary;
function LaunchRunPanel({ dashboard, onDashboardRefresh }) {
    _s14();
    const setup = buildOperatorSetupModel(dashboard);
    const operatorDefaultTemplate = String(dashboard.operator_preferences_schema?.run_template?.default || "reth_peer_starvation");
    const settingsDefaultScenario = dashboard.settings.default_run_scenario || "";
    const configuredDefaultScenario = setup.runTemplate && setup.runTemplate !== operatorDefaultTemplate ? setup.runTemplate : settingsDefaultScenario || setup.runTemplate || "reth_peer_starvation";
    const defaultScenarioKnown = SCENARIO_PICKER.some((scenario)=>scenario.key === configuredDefaultScenario);
    const preferredOrchestration = [
        "native",
        "hermes",
        "goose",
        "auto"
    ].includes(setup.agentFabricMode) ? setup.agentFabricMode : dashboard.settings.default_orchestration_mode || "auto";
    const [scenarioKey, setScenarioKey] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(defaultScenarioKnown ? configuredDefaultScenario : "reth_peer_starvation");
    const [evaluationMode, setEvaluationMode] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(dashboard.settings.default_evaluation_mode || "native");
    const [orchestrationMode, setOrchestrationMode] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(String(preferredOrchestration));
    const [steeringMode, setSteeringMode] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(setup.approvalPolicy === "interruptible_auto" ? "interruptible_auto" : dashboard.settings.default_steering_mode || "approval_gate");
    const [auditReason, setAuditReason] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [requireTargetLock, setRequireTargetLock] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(setup.target.lockRequired || dashboard.settings.default_target_lock === "required");
    const [result, setResult] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(null);
    const [message, setMessage] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [submitting, setSubmitting] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(false);
    const preflight = buildRunPreflightModel(dashboard, {
        scenarioKey,
        orchestrationMode,
        steeringMode,
        requireTargetLock
    });
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
            const response = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].createRun({
                scenario_key: scenarioKey,
                audit_reason: cleanedReason,
                evaluation_mode: evaluationMode,
                orchestration_mode: orchestrationMode,
                steering_mode: steeringMode,
                require_target_lock: requireTargetLock,
                pause_points: setup.pausePoints,
                simulation_context: {
                    state_slice: "meshapp.run-preflight.v1",
                    operator_preferences_ref: setup.stateSlice,
                    preferred_agents: setup.preferredAgents,
                    model_binding: setup.modelBinding,
                    target: setup.target
                }
            });
            setResult(response);
            await onDashboardRefresh();
            setAuditReason("");
            const admission = runAdmission(response);
            setMessage(admission?.decision === "blocked" ? "Mesh blocked this run admission." : "Mesh admitted this run.");
        } catch (err) {
            setMessage(err instanceof Error ? err.message : "Run launch failed");
        } finally{
            setSubmitting(false);
        }
    }
    const admission = result ? runAdmission(result) : null;
    const blockers = admission?.blockers || [];
    const selectedScenario = SCENARIO_PICKER.find((scenario)=>scenario.key === scenarioKey) || SCENARIO_PICKER[0];
    const messageClass = message.startsWith("Mesh admitted") ? "product-alert success" : message.startsWith("Mesh blocked") ? "product-alert warn" : "auth-error";
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
        className: "launch-panel",
        "aria-label": "New Evaluation / Launch Run",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "launch-heading",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "New Evaluation / Launch Run"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3424,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h3", {
                                children: "Mesh-owned run admission"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3425,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                children: "Product launch calls `POST /api/runs`; Mesh records operator context, audit reason, ownership boundary, policy, and admission blockers."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3426,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3423,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        className: "primary-button",
                        type: "button",
                        onClick: launchRun,
                        disabled: submitting,
                        children: submitting ? "Launching" : "Launch run"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3428,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3422,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "launch-grid",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                        children: [
                            "Scenario",
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("select", {
                                value: scenarioKey,
                                onChange: (event)=>setScenarioKey(event.target.value),
                                children: SCENARIO_PICKER.map((scenario)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                                        value: scenario.key,
                                        children: scenario.label
                                    }, scenario.key, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3436,
                                        columnNumber: 48
                                    }, this))
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3435,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: selectedScenario.detail
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3438,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3433,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                        children: [
                            "Evaluation",
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("select", {
                                value: evaluationMode,
                                onChange: (event)=>setEvaluationMode(event.target.value),
                                children: (dashboard.settings_schema.default_evaluation_mode?.values || [
                                    "native",
                                    "promptfoo"
                                ]).map((value)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                                        value: value,
                                        children: value
                                    }, value, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3443,
                                        columnNumber: 116
                                    }, this))
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3442,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3440,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                        children: [
                            "Orchestration",
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("select", {
                                value: orchestrationMode,
                                onChange: (event)=>setOrchestrationMode(event.target.value),
                                children: (dashboard.settings_schema.default_orchestration_mode?.values || [
                                    "native",
                                    "hermes",
                                    "goose",
                                    "auto"
                                ]).map((value)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                                        value: value,
                                        children: value
                                    }, value, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3449,
                                        columnNumber: 133
                                    }, this))
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3448,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3446,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                        children: [
                            "Steering",
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("select", {
                                value: steeringMode,
                                onChange: (event)=>setSteeringMode(event.target.value),
                                children: (dashboard.settings_schema.default_steering_mode?.values || [
                                    "approval_gate",
                                    "interruptible_auto"
                                ]).map((value)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                                        value: value,
                                        children: value
                                    }, value, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3455,
                                        columnNumber: 130
                                    }, this))
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3454,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3452,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                        className: "launch-reason",
                        children: [
                            "Audit reason",
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                value: auditReason,
                                onChange: (event)=>setAuditReason(event.target.value),
                                placeholder: "why this evaluation is being launched"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3460,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3458,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "audit-template-row",
                        children: AUDIT_REASON_TEMPLATES.map((template)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                type: "button",
                                onClick: ()=>setAuditReason(template),
                                children: template
                            }, template, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3463,
                                columnNumber: 53
                            }, this))
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3462,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                        className: "toggle-row",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                type: "checkbox",
                                checked: requireTargetLock,
                                onChange: (event)=>setRequireTargetLock(event.target.checked)
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3466,
                                columnNumber: 11
                            }, this),
                            "Require target lock"
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3465,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3432,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(RunPreflightPanel, {
                preflight: preflight,
                scenarioKey: scenarioKey,
                orchestrationMode: orchestrationMode,
                steeringMode: steeringMode
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3470,
                columnNumber: 7
            }, this),
            message ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: messageClass,
                children: message
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3471,
                columnNumber: 18
            }, this) : null,
            result ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: `admission-result ${admission?.decision === "blocked" ? "blocked" : "ready"}`,
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        children: admission?.schema_version || "mesh.run_admission.v1"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3474,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                        children: admission?.decision || result.status || result.stage
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3475,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                        children: result.run_id
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3476,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                        children: [
                            "Operator: ",
                            result.artifacts?.operator_audit?.operator_id || preflight.operatorId,
                            " / ",
                            result.artifacts?.operator_audit?.state_slice || "meshapp.run-admission-launch.v1"
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3477,
                        columnNumber: 11
                    }, this),
                    blockers.length ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                        children: [
                            "Blocked by: ",
                            blockers.join(", ")
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3478,
                        columnNumber: 30
                    }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                        children: [
                            "Queue depth: ",
                            admission?.queue?.current_depth ?? 0,
                            " / ",
                            admission?.queue?.max_size ?? "unknown"
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3478,
                        columnNumber: 73
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        type: "button",
                        onClick: ()=>setAuditReason(`Follow-up on ${result.run_id}: review Mesh proof and admission outcome.`),
                        children: "Prepare follow-up reason"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3479,
                        columnNumber: 11
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3473,
                columnNumber: 9
            }, this) : null
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 3421,
        columnNumber: 5
    }, this);
}
_s14(LaunchRunPanel, "CzXxXJnqvmxh1O4VWjQ2b8nWoDo=");
_c36 = LaunchRunPanel;
function RunPreflightPanel({ preflight, scenarioKey, orchestrationMode, steeringMode }) {
    const rows = [
        {
            label: "Operator",
            value: preflight.operatorId,
            detail: `${preflight.source} / ${preflight.roles.join(", ")}`
        },
        {
            label: "Team",
            value: preflight.team,
            detail: preflight.operatorPresent ? "Identity present for Mesh role checks" : "Mesh will reject missing identity"
        },
        {
            label: "Topology",
            value: preflight.selectedTopology,
            detail: `${preflight.selectedAgents.join(", ") || "no preferred agents"} / ${preflight.modelBinding}`
        },
        {
            label: "Target",
            value: preflight.target,
            detail: `target lock ${preflight.targetLock}`
        },
        {
            label: "Run mode",
            value: scenarioKey,
            detail: `${orchestrationMode} / ${steeringMode}`
        },
        {
            label: "Readiness",
            value: preflight.readiness,
            detail: preflight.blockers.length ? preflight.blockers.join(", ") : "No preflight blockers surfaced"
        }
    ];
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
        className: preflight.blockers.length ? "run-preflight blocked" : "run-preflight ready",
        "aria-label": "Run preflight",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "panel-title",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$shield$2d$check$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__ShieldCheck$3e$__["ShieldCheck"], {
                        size: 15
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3507,
                        columnNumber: 36
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        children: "meshapp.run-preflight.v1"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3507,
                        columnNumber: 61
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3507,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "preflight-grid",
                children: rows.map((row)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: row.label
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3511,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: humanize(row.value)
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3512,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: row.detail
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3513,
                                columnNumber: 13
                            }, this)
                        ]
                    }, row.label, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3510,
                        columnNumber: 11
                    }, this))
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3508,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                children: [
                    "Connector scopes: ",
                    preflight.connectorScopes.length ? preflight.connectorScopes.join(", ") : "no connector scopes returned"
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3517,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 3506,
        columnNumber: 5
    }, this);
}
_c37 = RunPreflightPanel;
function buildRunWorkbenchModel(payloads) {
    const detail = payloads.detail?.payload || payloads.detail || {};
    const eventsPayload = payloads.events?.payload || payloads.events || {};
    const exportPayload = payloads.exportPackage?.payload || payloads.exportPackage || {};
    const artifacts = detail.artifacts || exportPayload.artifacts || {};
    const admission = artifacts.run_admission || detail.artifacts?.run_admission || {};
    const operator = artifacts.operator || detail.artifacts?.operator || {};
    const decision = artifacts.decision || exportPayload.decision_record || {};
    const evaluation = artifacts.evaluation || exportPayload.evaluation_record || {};
    const agentTasks = Array.isArray(artifacts.agent_tasks) ? artifacts.agent_tasks : [];
    const events = Array.isArray(detail.events) ? detail.events : Array.isArray(eventsPayload.events) ? eventsPayload.events : [];
    const blockers = [
        ...Array.isArray(admission.blockers) ? admission.blockers.map(String) : [],
        ...Array.isArray(evaluation.blocking_reasons) ? evaluation.blocking_reasons.map(String) : []
    ];
    const status = String(detail.status || "unknown");
    const stage = String(detail.stage || "unknown");
    const nextAction = blockers.length ? "Resolve blockers or ask Mesh to explain blockers." : status === "awaiting_operator" || stage === "awaiting_operator" ? "Approve, resume, cancel, or hand off through Mesh steering." : [
        "completed",
        "failed",
        "cancelled"
    ].includes(status) ? "Export proof package and review postmortem evidence." : "Watch events and wait for the next Mesh pause point.";
    return {
        runId: String(detail.run_id || exportPayload.run_id || ""),
        currentStage: stage,
        status,
        nextAction,
        operator: String(operator.operator_id || detail.artifacts?.operator_audit?.operator_id || "Mesh"),
        evidenceSummary: blockers.length ? `${blockers.length} blocker(s) require attention` : "Evidence, Merkle, timeline, and export endpoints loaded.",
        decisionSummary: String(decision.decision_type || decision.final_recommendation || admission.decision || "No decision artifact yet."),
        agentSummary: agentTasks.length ? `${agentTasks.length} agent task(s) recorded` : "No agent task artifact returned for this run.",
        blockers,
        events: events.length
    };
}
function buildAgentFabricObservability(payloads) {
    const detail = payloads.detail?.payload || payloads.detail || {};
    const eventsPayload = payloads.events?.payload || payloads.events || {};
    const exportPayload = payloads.exportPackage?.payload || payloads.exportPackage || {};
    const artifacts = detail.artifacts || exportPayload.artifacts || {};
    const eventAttempts = collectAttemptThreads(Array.isArray(detail.events) ? detail.events : []);
    const loadedEventAttempts = collectAttemptThreads(Array.isArray(eventsPayload.events) ? eventsPayload.events : []);
    const taskAttempts = collectTaskAttemptThreads(Array.isArray(artifacts.agent_tasks) ? artifacts.agent_tasks : []);
    const byKey = new Map();
    [
        ...eventAttempts,
        ...loadedEventAttempts,
        ...taskAttempts
    ].forEach((attempt)=>{
        byKey.set(attempt.key, attempt);
    });
    return Array.from(byKey.values());
}
function collectAttemptThreads(events) {
    return events.flatMap((event)=>{
        const threads = event?.payload?.attempt_threads;
        return Array.isArray(threads) ? threads.map(agentAttemptViewFromThread).filter(isAgentFabricAttemptView) : [];
    });
}
function collectTaskAttemptThreads(tasks) {
    return tasks.flatMap((task)=>{
        const attempts = Array.isArray(task?.attempts) ? task.attempts : [];
        return attempts.map((attempt)=>{
            const thread = attempt?.output?.thread;
            return thread && typeof thread === "object" ? agentAttemptViewFromThread({
                ...thread,
                agent: attempt.agent,
                adapter: attempt.adapter
            }) : null;
        }).filter(isAgentFabricAttemptView);
    });
}
function isAgentFabricAttemptView(value) {
    return value !== null;
}
function agentAttemptViewFromThread(thread) {
    if (!thread || typeof thread !== "object") return null;
    const request = thread.request && typeof thread.request === "object" ? thread.request : {};
    const credentialPolicy = request.credential_policy && typeof request.credential_policy === "object" ? request.credential_policy : {};
    const release = thread.release_status && typeof thread.release_status === "object" ? thread.release_status : {};
    const authority = thread.authority && typeof thread.authority === "object" ? thread.authority : {};
    const output = thread.output && typeof thread.output === "object" ? thread.output : {};
    const eventCount = Number(thread.event_count ?? (Array.isArray(thread.events) ? thread.events.length : 0));
    return {
        key: String(thread.attempt_id || thread.thread_id || `${thread.agent || "agent"}:${thread.adapter || "adapter"}`),
        agent: String(thread.agent || "agent"),
        adapter: String(thread.adapter || "adapter"),
        status: String(thread.status || "unknown"),
        harness: String(thread.harness || request.harness || "default"),
        events: Number.isFinite(eventCount) ? eventCount : 0,
        tools: Array.isArray(thread.tool_calls) ? thread.tool_calls.length : 0,
        changedFiles: Array.isArray(thread.changed_files) ? thread.changed_files.length : 0,
        tests: Array.isArray(thread.test_results) ? thread.test_results.length : 0,
        riskFlags: Array.isArray(thread.risk_flags) ? thread.risk_flags.map(String) : [],
        release: release.released === true ? "released" : release.released === false ? "not released" : "not reported",
        egress: credentialPolicy.sandbox_receives_placeholder_only === true && credentialPolicy.raw_secret_in_sandbox === false ? "placeholder-only" : "not proven",
        authority: authority.mesh_control_plane_authoritative === true && authority.agent_thread_authoritative === false ? "Mesh approves and executes" : "authority not proven",
        output: String(output.summary || output.result_text || output.execution_id || "proposal metadata recorded")
    };
}
function runAdmission(run) {
    return run.artifacts?.run_admission || null;
}
function evidenceTraceSteps(dashboard) {
    const runs = dashboard.mesh.runs?.runs || [];
    const latestRun = runs[0];
    const approvals = dashboard.mesh.approvals?.items || [];
    const pilot = dashboard.mesh.pilot_go_no_go || {};
    const missingEvidence = Array.isArray(pilot.missing_evidence) ? pilot.missing_evidence.length : 0;
    return [
        {
            label: "Signal",
            detail: latestRun?.scenario_key || "No active run signal in the dashboard read model.",
            authority: "Mesh run state"
        },
        {
            label: "Evidence",
            detail: missingEvidence ? `${missingEvidence} missing proof(s) reported by Mesh.` : "Evidence packets remain Mesh-owned read models.",
            authority: "Mesh evidence artifacts"
        },
        {
            label: "Policy",
            detail: approvals.length ? `${approvals.length} approval gate(s) pending.` : "No pending approval gate in the product read model.",
            authority: "Mesh policy and approvals"
        },
        {
            label: "Decision",
            detail: latestRun?.status ? `Latest run status: ${latestRun.status}.` : "Awaiting a Mesh decision/evaluation record.",
            authority: "Mesh decision record"
        }
    ];
}
function TraceRail({ steps }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
        className: "trace-rail",
        "aria-label": "Signal to decision trace",
        children: steps.map((step)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "trace-step",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        children: step.label
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3667,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                        children: step.detail
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3668,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                        children: step.authority
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3669,
                        columnNumber: 11
                    }, this)
                ]
            }, step.label, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3666,
                columnNumber: 9
            }, this))
    }, void 0, false, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 3664,
        columnNumber: 5
    }, this);
}
_c38 = TraceRail;
function TeamSettingsView({ session, dashboard, onDashboardRefresh, onSession, onLogout, loggingOut }) {
    _s15();
    const team = session.active_team;
    const [teamName, setTeamName] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [inviteEmails, setInviteEmails] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [profileName, setProfileName] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(team?.name || "");
    const [profileDisplayName, setProfileDisplayName] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(team?.display_name || "");
    const [teamMessage, setTeamMessage] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [creatingTeam, setCreatingTeam] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(false);
    const [savingTeam, setSavingTeam] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(false);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "TeamSettingsView.useEffect": ()=>{
            setProfileName(team?.name || "");
            setProfileDisplayName(team?.display_name || "");
        }
    }["TeamSettingsView.useEffect"], [
        team?.id,
        team?.name,
        team?.display_name
    ]);
    async function createTeamFromSettings() {
        const name = teamName.trim();
        if (!name) {
            setTeamMessage("Team name is required.");
            return;
        }
        setCreatingTeam(true);
        setTeamMessage("");
        try {
            const members = inviteEmails.split(",").map((email)=>email.trim()).filter(Boolean).map((email)=>({
                    email,
                    role: "viewer"
                }));
            const payload = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].createTeam({
                name,
                members
            });
            onSession(payload);
            await onDashboardRefresh();
            setTeamName("");
            setInviteEmails("");
            setTeamMessage(`Created team ${payload.active_team?.name || name}.`);
        } catch (err) {
            setTeamMessage(err instanceof Error ? err.message : "Team creation failed.");
        } finally{
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
            const payload = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].updateTeam({
                team_id: team.id,
                name,
                display_name: profileDisplayName.trim()
            });
            onSession(payload);
            await onDashboardRefresh();
            setTeamMessage(`Saved team profile for ${payload.active_team?.name || name}.`);
        } catch (err) {
            setTeamMessage(err instanceof Error ? err.message : "Team profile update failed.");
        } finally{
            setSavingTeam(false);
        }
    }
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "settings-layout",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "profile-panel",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h2", {
                        children: "Team Settings"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3752,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                        children: team ? "Review team profile and preferences for the active dashboard scope." : "Create a team when you are ready to invite partners or separate this browser from solo mode."
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3753,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "avatar-disc",
                        children: team?.name?.[0] || session.user.display_name[0]
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3754,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(FormRead, {
                        label: "ID",
                        value: team?.id || session.user.id
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3755,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(FormRead, {
                        label: "Email",
                        value: session.user.email
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3756,
                        columnNumber: 9
                    }, this),
                    team ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "create-team-panel",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h3", {
                                children: "Team profile"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3759,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                                children: [
                                    "Team name",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                        value: profileName,
                                        onChange: (event)=>setProfileName(event.target.value)
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3762,
                                        columnNumber: 15
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3760,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                                children: [
                                    "Display name",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                        value: profileDisplayName,
                                        onChange: (event)=>setProfileDisplayName(event.target.value)
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3766,
                                        columnNumber: 15
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3764,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(FormRead, {
                                label: "Slug",
                                value: team.slug
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3768,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(FormRead, {
                                label: "Your role",
                                value: team.role
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3769,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                className: "primary-button",
                                type: "button",
                                onClick: saveTeamProfile,
                                disabled: savingTeam,
                                children: savingTeam ? "Saving" : "Save team profile"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3770,
                                columnNumber: 13
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3758,
                        columnNumber: 11
                    }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "create-team-panel",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h3", {
                                children: "Create team"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3774,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                                children: [
                                    "Team name",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                        value: teamName,
                                        onChange: (event)=>setTeamName(event.target.value),
                                        placeholder: `${session.user.display_name || "Operator"}'s team`
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3777,
                                        columnNumber: 15
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3775,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                                children: [
                                    "Invite members",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                        value: inviteEmails,
                                        onChange: (event)=>setInviteEmails(event.target.value),
                                        placeholder: "colleague@company.com, sre@company.com"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3781,
                                        columnNumber: 15
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3779,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                className: "primary-button",
                                type: "button",
                                onClick: createTeamFromSettings,
                                disabled: creatingTeam,
                                children: creatingTeam ? "Creating" : "Create team"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3783,
                                columnNumber: 13
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3773,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(FormRead, {
                        label: "Authority boundary",
                        value: "Mesh operator dashboard. Runtime authority remains with Mesh.",
                        large: true
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3786,
                        columnNumber: 9
                    }, this),
                    teamMessage ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: teamMessage.startsWith("Created") || teamMessage.startsWith("Saved") ? "product-alert success inline" : "auth-error compact",
                        children: teamMessage
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3787,
                        columnNumber: 24
                    }, this) : null,
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "button-row",
                        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                            type: "button",
                            onClick: onLogout,
                            disabled: loggingOut,
                            children: loggingOut ? "Logging out" : "Log out"
                        }, void 0, false, {
                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                            lineNumber: 3789,
                            columnNumber: 11
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3788,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3751,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(SettingsView, {
                dashboard: dashboard,
                compact: true,
                onDashboardRefresh: onDashboardRefresh
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3792,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 3750,
        columnNumber: 5
    }, this);
}
_s15(TeamSettingsView, "g0rAdmU8OcKnoJi8BCZopGuvxv4=");
_c39 = TeamSettingsView;
const MEMBER_ROLES = [
    "viewer",
    "launcher",
    "approver",
    "admin"
];
function MembersView({ session, setView, onSession, onDashboardRefresh }) {
    _s16();
    const team = session.active_team;
    const members = team?.members || [
        {
            email: session.user.email,
            role: "owner",
            status: "active"
        }
    ];
    const [inviteEmails, setInviteEmails] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [inviteRole, setInviteRole] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("viewer");
    const [message, setMessage] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [saving, setSaving] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(false);
    async function saveMembers() {
        if (!team) {
            setMessage("Create a team before inviting members.");
            return;
        }
        const emails = inviteEmails.split(",").map((email)=>email.trim()).filter(Boolean);
        if (!emails.length) {
            setMessage("At least one member email is required.");
            return;
        }
        setSaving(true);
        setMessage("");
        try {
            const payload = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].upsertTeamMembers({
                team_id: team.id,
                members: emails.map((email)=>({
                        email,
                        role: inviteRole
                    }))
            });
            onSession(payload);
            await onDashboardRefresh();
            setInviteEmails("");
            setMessage(`Saved ${emails.length} member update(s) for ${payload.active_team?.name || team.name}.`);
        } catch (err) {
            setMessage(err instanceof Error ? err.message : "Member update failed.");
        } finally{
            setSaving(false);
        }
    }
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "content-stack",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Toolbar, {
                title: "Members",
                detail: "Team roles map into Mesh operator roles for protected actions.",
                action: "Manage Team",
                onAction: ()=>setView("team")
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3847,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "member-config-panel",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h3", {
                                children: team ? "Invite or update members" : "Team required"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3850,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                children: team ? "Add comma-separated emails, choose the Mesh role mapping, and save through the team-tenancy state slice." : "Solo mode has only the current operator. Create a team before inviting partners."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3851,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3849,
                        columnNumber: 9
                    }, this),
                    team ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "member-config-grid",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                                children: [
                                    "Emails",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                        value: inviteEmails,
                                        onChange: (event)=>setInviteEmails(event.target.value),
                                        placeholder: "viewer@company.com, approver@company.com"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3857,
                                        columnNumber: 15
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3855,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                                children: [
                                    "Role",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("select", {
                                        value: inviteRole,
                                        onChange: (event)=>setInviteRole(event.target.value),
                                        children: MEMBER_ROLES.map((role)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                                                value: role,
                                                children: humanize(role)
                                            }, role, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 3862,
                                                columnNumber: 45
                                            }, this))
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3861,
                                        columnNumber: 15
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3859,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                className: "primary-button",
                                type: "button",
                                onClick: saveMembers,
                                disabled: saving,
                                children: saving ? "Saving" : "Save members"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3865,
                                columnNumber: 13
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3854,
                        columnNumber: 11
                    }, this) : null,
                    message ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: message.startsWith("Saved") ? "product-alert success inline" : "auth-error compact",
                        children: message
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3868,
                        columnNumber: 20
                    }, this) : null
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3848,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "data-table compact",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "table-head",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Email"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3871,
                                columnNumber: 37
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Role"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3871,
                                columnNumber: 55
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Status"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3871,
                                columnNumber: 72
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3871,
                        columnNumber: 9
                    }, this),
                    members.map((member)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                            className: "table-row",
                            children: [
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                    children: member.email
                                }, void 0, false, {
                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                    lineNumber: 3872,
                                    columnNumber: 80
                                }, this),
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                    children: member.role
                                }, void 0, false, {
                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                    lineNumber: 3872,
                                    columnNumber: 107
                                }, this),
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                    children: member.status
                                }, void 0, false, {
                                    fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                    lineNumber: 3872,
                                    columnNumber: 133
                                }, this)
                            ]
                        }, member.email, true, {
                            fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                            lineNumber: 3872,
                            columnNumber: 34
                        }, this))
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3870,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 3846,
        columnNumber: 5
    }, this);
}
_s16(MembersView, "QD1dMQaOmt2z3a9Ma+87hSganGI=");
_c40 = MembersView;
function OperatorSetupView({ dashboard, onDashboardRefresh, setView }) {
    _s17();
    const model = buildOperatorSetupModel(dashboard);
    const schema = dashboard.operator_preferences_state?.operator_preferences_schema || dashboard.operator_preferences_schema || {};
    const [draft, setDraft] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])({});
    const [reason, setReason] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [message, setMessage] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [saving, setSaving] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(false);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "OperatorSetupView.useEffect": ()=>{
            setDraft({
                ...dashboard.operator_preferences_state?.operator_preferences || dashboard.operator_preferences || {}
            });
        }
    }["OperatorSetupView.useEffect"], [
        dashboard
    ]);
    function updateDraft(key, value) {
        setDraft({
            ...draft,
            [key]: value
        });
    }
    async function savePreferences() {
        const cleanedReason = reason.trim();
        if (!cleanedReason) {
            setMessage("Audit reason is required before operator preferences can be saved.");
            return;
        }
        setSaving(true);
        setMessage("");
        try {
            const response = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].updateOperatorPreferences(dashboard.scope.team?.id || null, draft, cleanedReason);
            setDraft(response.operator_preferences);
            setReason("");
            await onDashboardRefresh();
            setMessage(`Saved ${response.audit.fields.join(", ")} for ${response.audit.scope}.`);
        } catch (err) {
            setMessage(err instanceof Error ? err.message : "Operator preferences update failed");
        } finally{
            setSaving(false);
        }
    }
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "content-stack",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Toolbar, {
                title: "Operator Setup",
                detail: "Preferences mutate mesh.operator-preferences.v1. Mesh still owns topology resolution, connector certification, approval, and actuation.",
                action: "Launch Run",
                onAction: ()=>setView("evaluations")
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3925,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "operator-setup-summary",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ConfigPostureCard, {
                        title: "Operator",
                        value: model.operatorId,
                        state: "ready",
                        detail: `${model.source} / ${model.roles.join(", ") || "no roles"}`
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3932,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ConfigPostureCard, {
                        title: "Team scope",
                        value: model.team,
                        state: "ready",
                        detail: model.scope
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3933,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ConfigPostureCard, {
                        title: "Agent fabric",
                        value: model.agentFabricMode,
                        state: "ready",
                        detail: `${model.preferredAgents.length} preferred lane(s)`
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3934,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ConfigPostureCard, {
                        title: "Model binding",
                        value: model.modelBinding,
                        state: "ready",
                        detail: "Preference only; deployment secrets stay out of product state."
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3935,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ConfigPostureCard, {
                        title: "Approval policy",
                        value: model.approvalPolicy,
                        state: model.approvalPolicy === "approval_required" ? "ready" : "config-only",
                        detail: `${model.pausePoints.length} pause point(s)`
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3936,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ConfigPostureCard, {
                        title: "Target",
                        value: `${model.target.namespace}/${model.target.service}`,
                        state: model.target.lockRequired ? "ready" : "config-only",
                        detail: `${model.target.environment}; lock ${model.target.lockRequired ? "required" : "optional"}`
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3937,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3931,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "operator-setup-editor",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "panel-heading",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        children: model.stateSlice
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3942,
                                        columnNumber: 13
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h3", {
                                        children: "Governed setup editor"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3943,
                                        columnNumber: 13
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                        children: "These preferences are stamped into preflight context and launch payloads. Runtime env vars and Mesh policy can still narrow actual lanes."
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3944,
                                        columnNumber: 13
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3941,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                className: "primary-button",
                                type: "button",
                                onClick: savePreferences,
                                disabled: saving,
                                children: saving ? "Saving" : "Save setup"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3946,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3940,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "setting-grid operator-grid",
                        children: Object.entries(schema).map(([key, item])=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(OperatorPreferenceField, {
                                name: key,
                                schema: item,
                                value: draft[key] ?? item.default,
                                onChange: (value)=>updateDraft(key, value)
                            }, key, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3950,
                                columnNumber: 13
                            }, this))
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3948,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "settings-save-row",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                                children: [
                                    "Audit reason",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                        value: reason,
                                        onChange: (event)=>setReason(event.target.value),
                                        placeholder: "why this operator setup change is required"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 3962,
                                        columnNumber: 13
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3960,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                className: "primary-button",
                                type: "button",
                                onClick: savePreferences,
                                disabled: saving,
                                children: saving ? "Saving" : "Save setup"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3964,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3959,
                        columnNumber: 9
                    }, this),
                    message ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: message.startsWith("Saved") ? "product-alert success" : "auth-error",
                        children: message
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3966,
                        columnNumber: 20
                    }, this) : null
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3939,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "operator-topology-panel",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "mesh.orchestration_topology_profile.v1"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3970,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: humanize(model.topology.active)
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3971,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: model.topology.blockers.length ? model.topology.blockers.join(", ") : "No topology blockers in the dashboard read model."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3972,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3969,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Preferred profile agents"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3975,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: model.topology.preferredAgents.slice(0, 6).join(", ") || "unavailable"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3976,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: "Runtime filter can still remove lanes before attempts are collected."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3977,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3974,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "Allowed model policy"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3980,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: model.topology.allowedModels.slice(0, 3).join(", ") || "unavailable"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3981,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: "Provider secrets remain deployment-owned."
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 3982,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 3979,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 3968,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 3924,
        columnNumber: 5
    }, this);
}
_s17(OperatorSetupView, "pgkT56bXLAJg1am7fSuN1lflQL8=");
_c41 = OperatorSetupView;
function OperatorPreferenceField({ name, schema, value, onChange }) {
    const values = schema.values || [];
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "setting-card",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                children: titleize(name)
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4003,
                columnNumber: 7
            }, this),
            schema.kind === "enum" ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("select", {
                value: String(value),
                onChange: (event)=>onChange(event.target.value),
                children: values.map((option)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                        value: option,
                        children: humanize(option)
                    }, option, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 4006,
                        columnNumber: 35
                    }, this))
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4005,
                columnNumber: 9
            }, this) : schema.kind === "multi" ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "preference-checkboxes",
                children: values.map((option)=>{
                    const checked = listPreference(value).includes(option);
                    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                type: "checkbox",
                                checked: checked,
                                onChange: (event)=>{
                                    const current = new Set(listPreference(value));
                                    if (event.target.checked) current.add(option);
                                    else current.delete(option);
                                    onChange(Array.from(current).sort());
                                }
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4014,
                                columnNumber: 17
                            }, this),
                            humanize(option)
                        ]
                    }, option, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 4013,
                        columnNumber: 15
                    }, this);
                })
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4009,
                columnNumber: 9
            }, this) : schema.kind === "boolean" ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                className: "toggle-row inline",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                        type: "checkbox",
                        checked: booleanPreference(value),
                        onChange: (event)=>onChange(event.target.checked)
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 4031,
                        columnNumber: 11
                    }, this),
                    booleanPreference(value) ? "Required" : "Optional"
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4030,
                columnNumber: 9
            }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                value: String(value || ""),
                onChange: (event)=>onChange(event.target.value)
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4035,
                columnNumber: 9
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                children: schema.description
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4037,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 4002,
        columnNumber: 5
    }, this);
}
_c42 = OperatorPreferenceField;
function buildKeysReadinessRows(authConfig, dashboard) {
    const readiness = dashboard.mesh.readiness || {};
    const connectors = dashboard.mesh.connectors?.connectors || dashboard.mesh.connectors?.connector_certification || {};
    const connectorRows = Object.entries(connectors).slice(0, 6).map(([id, connector])=>({
            title: `Connector: ${connector.display_name || connector.name || id}`,
            value: String(connector.state || connector.status || "unknown"),
            state: String(connector.state || connector.status || "read-only"),
            detail: `${connector.authority_posture || "Mesh-certified connector"} / scopes ${(connector.allowed_scopes || []).slice(0, 4).join(", ") || "none"} / ${connector.credential_boundary?.credential_mode || connector.credential_policy || "credential boundary unavailable"}`
        }));
    const setup = buildOperatorSetupModel(dashboard);
    const rows = authConfig ? [
        {
            title: "Auth mode",
            value: authConfig.auth_mode,
            state: authConfig.auth_mode === "app_session" ? "ready" : "read-only",
            detail: "Configured by MESH_AUTH_MODE. Product app sessions scope dashboard access; proxy-header ingress remains deployment-owned."
        },
        {
            title: "Password signup",
            value: authConfig.signup_enabled && authConfig.password_auth_enabled ? "enabled" : "disabled",
            state: authConfig.signup_enabled && authConfig.password_auth_enabled ? "ready" : "blocked",
            detail: "Controlled by MESH_SIGNUP_ENABLED and MESH_PASSWORD_AUTH_ENABLED."
        },
        {
            title: "Invite gate",
            value: authConfig.invite.configured ? authConfig.invite.required ? "code required" : "allowlist" : "open local mode",
            state: authConfig.invite.configured ? "ready" : "config-only",
            detail: "Controlled by MESH_AUTH_INVITE_ALLOWLIST and MESH_AUTH_INVITE_CODES; raw invite codes stay outside product state."
        },
        {
            title: "Captcha",
            value: authConfig.captcha.dev_bypass_enabled ? "dev bypass" : authConfig.captcha.configured ? authConfig.captcha.provider : "not configured",
            state: authConfig.captcha.configured || authConfig.captcha.dev_bypass_enabled ? "ready" : "blocked",
            detail: "Controlled by MESH_CAPTCHA_PROVIDER, MESH_CAPTCHA_SITE_KEY, and MESH_CAPTCHA_SECRET_KEY. Browser tokens are never stored."
        },
        {
            title: "Google OAuth",
            value: authConfig.oauth.google.configured ? "configured" : "not configured",
            state: authConfig.oauth.google.configured ? "ready" : "blocked",
            detail: "Requires client id, client secret, and redirect URL. The product shell only starts the provider flow."
        },
        {
            title: "GitHub OAuth",
            value: authConfig.oauth.github.configured ? "configured" : "not configured",
            state: authConfig.oauth.github.configured ? "ready" : "blocked",
            detail: "Requires client id, client secret, and redirect URL. Tokens never enter the dashboard read model."
        }
    ] : [
        {
            title: "Auth config",
            value: "unavailable",
            state: "blocked",
            detail: (0, __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["backendUnavailableMessage"])()
        }
    ];
    const deploymentRows = [
        {
            title: "Model route",
            value: setup.modelBinding,
            state: "read-only",
            detail: "Provider route preference is stored in mesh.operator-preferences.v1; raw provider keys remain deployment-owned."
        },
        {
            title: "Agent fabric",
            value: setup.agentFabricMode,
            state: "config-only",
            detail: `Preferred agents: ${setup.preferredAgents.join(", ") || "none"}. Runtime config can still narrow lanes.`
        },
        {
            title: "State backend",
            value: String(readiness.state_backend || "RuntimeConfig-owned"),
            state: readiness.state_backend ? "ready" : "read-only",
            detail: "Runtime persistence is deployment config, not a product-secret setting."
        },
        {
            title: "Build commit",
            value: String(dashboard.mesh.health?.commit || "unknown"),
            state: dashboard.mesh.health?.commit ? "ready" : "read-only",
            detail: "Build provenance changes only when a new artifact is deployed."
        },
        {
            title: "Settings scope",
            value: dashboard.scope.kind === "team" ? `team:${dashboard.scope.team?.id}` : `user:${dashboard.session.user.id}`,
            state: "ready",
            detail: "Defaults on the Settings page mutate mesh-settings-control with an audit reason."
        }
    ];
    return [
        ...rows,
        ...deploymentRows,
        ...connectorRows
    ];
}
function KeysView({ authConfig, dashboard, setView }) {
    const rows = buildKeysReadinessRows(authConfig, dashboard);
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "content-stack",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Toolbar, {
                title: "Keys & Secrets",
                detail: "Provider secrets are deployment-owned. This page shows configuration posture and exact ownership without exposing raw values.",
                action: "Open Settings",
                onAction: ()=>setView("settings")
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4137,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "keys-posture-grid",
                children: rows.map((row)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ConfigPostureCard, {
                        ...row
                    }, row.title, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 4144,
                        columnNumber: 28
                    }, this))
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4143,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "keys-env-panel",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h3", {
                        children: "Deployment-owned variables"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 4147,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "env-var-grid",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                children: "MESH_GOOGLE_OAUTH_CLIENT_ID"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4149,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                children: "MESH_GOOGLE_OAUTH_CLIENT_SECRET"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4150,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                children: "MESH_GOOGLE_OAUTH_REDIRECT_URL"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4151,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                children: "MESH_GITHUB_OAUTH_CLIENT_ID"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4152,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                children: "MESH_GITHUB_OAUTH_CLIENT_SECRET"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4153,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                children: "MESH_GITHUB_OAUTH_REDIRECT_URL"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4154,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                children: "MESH_CAPTCHA_PROVIDER"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4155,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                children: "MESH_CAPTCHA_SITE_KEY"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4156,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                children: "MESH_CAPTCHA_SECRET_KEY"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4157,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                children: "MESH_AUTH_INVITE_ALLOWLIST"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4158,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                children: "MESH_AUTH_INVITE_CODES"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4159,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                children: "MESH_AUTH_PRODUCT_REDIRECT_URL"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4160,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 4148,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4146,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 4136,
        columnNumber: 5
    }, this);
}
_c43 = KeysView;
function ConfigPostureCard({ title, value, detail, state }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("article", {
        className: `config-posture-card ${state}`,
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                children: title
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4170,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                children: humanize(value)
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4171,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                children: detail
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4172,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(SensitivityBadges, {
                badges: sensitivityBadgesForSource(title.toLowerCase().includes("auth") || title.toLowerCase().includes("oauth") || title.toLowerCase().includes("captcha") || title.toLowerCase().includes("invite") ? "auth-provider-proof.v1" : "mesh-settings-control")
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4173,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 4169,
        columnNumber: 5
    }, this);
}
_c44 = ConfigPostureCard;
function SettingsView({ dashboard, compact = false, onDashboardRefresh }) {
    _s18();
    const settingsPosture = operatorWorkflowPosture("settings");
    const [draft, setDraft] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])({});
    const [reason, setReason] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [message, setMessage] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])("");
    const [saving, setSaving] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useState"])(false);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$index$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["useEffect"])({
        "SettingsView.useEffect": ()=>{
            const next = {};
            Object.entries(dashboard.settings_schema).forEach({
                "SettingsView.useEffect": ([key, schema])=>{
                    next[key] = dashboard.settings[key] || schema.default;
                }
            }["SettingsView.useEffect"]);
            setDraft(next);
        }
    }["SettingsView.useEffect"], [
        dashboard
    ]);
    async function saveSettings() {
        const cleanedReason = reason.trim();
        if (!cleanedReason) {
            setMessage("Audit reason is required before settings can be saved.");
            return;
        }
        setSaving(true);
        setMessage("");
        try {
            const response = await __TURBOPACK__imported__module__$5b$project$5d2f$meshapp$2f$frontend$2f$src$2f$product$2f$api$2e$ts__$5b$app$2d$client$5d$__$28$ecmascript$29$__["productApi"].updateSettings(dashboard.scope.team?.id || null, draft, cleanedReason);
            setDraft(response.settings);
            setReason("");
            await onDashboardRefresh?.();
            setMessage(`Saved ${response.audit.fields.join(", ")} for ${response.audit.scope}.`);
        } catch (err) {
            setMessage(err instanceof Error ? err.message : "Settings update failed");
        } finally{
            setSaving(false);
        }
    }
    const parityRows = settingsParityRows({
        ...dashboard,
        settings: {
            ...dashboard.settings,
            ...draft
        }
    });
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
        className: compact ? "settings-panel compact" : "settings-panel",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h2", {
                children: "Settings"
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4225,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                children: [
                    settingsPosture.reason,
                    " Mesh runtime-critical values are read-only and deployment-owned."
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4226,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "setting-grid",
                children: parityRows.map((row)=>row.mutable ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "setting-card",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: row.label
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4230,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("select", {
                                value: draft[row.key] || row.value,
                                onChange: (event)=>setDraft({
                                        ...draft,
                                        [row.key]: event.target.value
                                    }),
                                children: (row.values || []).map((value)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("option", {
                                        value: value,
                                        children: value
                                    }, value, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 4232,
                                        columnNumber: 50
                                    }, this))
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4231,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                children: row.description
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4234,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("details", {
                                className: "setting-advanced",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("summary", {
                                        children: "Advanced"
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 4236,
                                        columnNumber: 15
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                        children: row.uiMutationPath
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 4237,
                                        columnNumber: 15
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("code", {
                                        children: row.cliPath
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 4238,
                                        columnNumber: 15
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4235,
                                columnNumber: 13
                            }, this)
                        ]
                    }, row.key, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 4229,
                        columnNumber: 11
                    }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "setting-card readonly",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: row.label
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4243,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                children: row.value
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4243,
                                columnNumber: 37
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                children: row.description
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4243,
                                columnNumber: 65
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                children: row.readOnlyReason
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4243,
                                columnNumber: 89
                            }, this)
                        ]
                    }, row.key, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 4242,
                        columnNumber: 11
                    }, this))
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4227,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "settings-save-row",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                        children: [
                            "Audit reason",
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                value: reason,
                                onChange: (event)=>setReason(event.target.value),
                                placeholder: "why this settings change is required"
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4250,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 4248,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        className: "primary-button",
                        type: "button",
                        onClick: saveSettings,
                        disabled: saving,
                        children: saving ? "Saving" : "Save settings"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 4252,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4247,
                columnNumber: 7
            }, this),
            message ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: message.startsWith("Saved") ? "product-alert success" : "auth-error",
                children: message
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4254,
                columnNumber: 18
            }, this) : null
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 4224,
        columnNumber: 5
    }, this);
}
_s18(SettingsView, "pgkT56bXLAJg1am7fSuN1lflQL8=");
_c45 = SettingsView;
function CapabilityView({ view, dashboard, setView }) {
    const workflowPosture = operatorWorkflowPosture(workflowForView(view));
    const page = runtimeProductPage(view, dashboard);
    const allEmpty = page.cards.every((card)=>{
        const payload = readModelCardPayload(card.title, card.payload);
        return payload?.state === "empty" || payload && typeof payload === "object" && Object.keys(payload).length <= 2;
    });
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "content-stack",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(Toolbar, {
                title: page.title,
                detail: page.detail || workflowPosture.reason,
                action: "Review Dashboard",
                onAction: ()=>setView("home")
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4268,
                columnNumber: 7
            }, this),
            allEmpty ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                className: "capability-readonly-banner",
                role: "status",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$triangle$2d$alert$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__AlertTriangle$3e$__["AlertTriangle"], {
                        size: 16,
                        "aria-hidden": "true"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 4276,
                        columnNumber: 11
                    }, this),
                    "Mesh has not published data for these read models in your current scope. Use Advanced Console for full operator workflows, or confirm the control plane is reachable."
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4275,
                columnNumber: 9
            }, this) : null,
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "capability-grid two",
                children: page.cards.map((card)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(ReadModelCard, {
                        title: card.title,
                        payload: card.payload
                    }, card.title, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 4281,
                        columnNumber: 35
                    }, this))
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4280,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 4267,
        columnNumber: 5
    }, this);
}
_c46 = CapabilityView;
function runtimeProductPage(view, dashboard) {
    const mesh = dashboard.mesh || {};
    const readiness = mesh.readiness || {};
    if (view === "training") {
        return {
            title: "Topology",
            detail: "Topology is a Mesh-owned read model. Product navigation shows the profile and graph without using the legacy tab shortcut.",
            cards: [
                {
                    title: "Orchestration topology",
                    payload: readiness.orchestration_topology || mesh.graph
                },
                {
                    title: "Runtime graph",
                    payload: mesh.graph
                },
                {
                    title: "Connector matrix",
                    payload: mesh.connectors
                },
                {
                    title: "Read model authority",
                    payload: mesh.read_model
                }
            ]
        };
    }
    if (view === "inference") {
        return {
            title: "Memory Projection",
            detail: "Memory projection is surfaced as a read model; Mesh owns corpus projection, active memory, and graph persistence.",
            cards: [
                {
                    title: "Memory graph",
                    payload: mesh.memory?.graph
                },
                {
                    title: "Active memory",
                    payload: mesh.memory?.active
                },
                {
                    title: "Trust ladder",
                    payload: mesh.trust_ladder
                },
                {
                    title: "Readiness",
                    payload: readiness
                }
            ]
        };
    }
    if (view === "gpu") {
        return {
            title: "Readiness",
            detail: "Readiness stays Mesh-owned. Product cards show blockers and degraded backend state without granting remediation authority.",
            cards: [
                {
                    title: "Runtime readiness",
                    payload: readiness
                },
                {
                    title: "Watchers",
                    payload: mesh.watchers
                },
                {
                    title: "Kill switch",
                    payload: mesh.kill_switch
                },
                {
                    title: "Connector certification",
                    payload: mesh.connectors
                }
            ]
        };
    }
    if (view === "clusters") {
        return {
            title: "Kill Switch",
            detail: "Kill switch mutation remains a Mesh admin API. This page exposes state and blocked reasons only.",
            cards: [
                {
                    title: "Kill switch",
                    payload: mesh.kill_switch
                },
                {
                    title: "Policy state",
                    payload: mesh.approvals
                },
                {
                    title: "Readiness",
                    payload: readiness
                },
                {
                    title: "Pilot go/no-go",
                    payload: mesh.pilot_go_no_go
                }
            ]
        };
    }
    if (view === "instances") {
        return {
            title: "Policy State",
            detail: "Policy state combines approval queue, trust ladder, pilot packet, and evidence posture. Mesh owns decisions.",
            cards: [
                {
                    title: "Approval queue",
                    payload: mesh.approvals
                },
                {
                    title: "Trust ladder",
                    payload: mesh.trust_ladder
                },
                {
                    title: "Pilot proof packet",
                    payload: mesh.pilot_go_no_go
                },
                {
                    title: "Read model authority",
                    payload: mesh.read_model
                }
            ]
        };
    }
    if (view === "keys") {
        return {
            title: "Keys & Secrets",
            detail: "Secrets and provider configuration stay read-only in the product shell; local values must stay in ignored env files.",
            cards: [
                {
                    title: "Auth provider posture",
                    payload: {
                        state: "read-only",
                        reason: "Configured through ignored env or deployment secret manager."
                    }
                },
                {
                    title: "Build health",
                    payload: mesh.health
                },
                {
                    title: "Runtime config state",
                    payload: readiness
                },
                {
                    title: "Settings parity",
                    payload: dashboard.settings_schema
                }
            ]
        };
    }
    return {
        title: view,
        detail: "Product-native read model page.",
        cards: [
            {
                title: "Runtime readiness",
                payload: readiness
            },
            {
                title: "Policy state",
                payload: mesh.approvals
            },
            {
                title: "Connector proof",
                payload: mesh.connectors
            },
            {
                title: "Memory projection",
                payload: mesh.memory
            }
        ]
    };
}
function workflowForView(view) {
    if (isConsoleProductView(view)) return workflowForView(consoleWorkflowForView(view).productFallback);
    if (view === "keys" || view === "settings" || view === "operator-setup") return "settings";
    if (view === "environments") return "connector";
    if (view === "hardened-arena") return "launch";
    if (view === "evaluations") return "launch";
    if (view === "training" || view === "inference" || view === "gpu" || view === "clusters" || view === "instances") return "readiness";
    return "evidence";
}
function defaultLensForSession(session) {
    const roles = [
        session.active_team?.role,
        ...session.active_team?.roles || []
    ].map((role)=>String(role || "").toLowerCase());
    if (roles.some((role)=>role.includes("security") || role.includes("admin"))) return "security";
    if (roles.some((role)=>role.includes("approver"))) return "approver";
    if (roles.some((role)=>role.includes("viewer") || role.includes("partner"))) return "partner-review";
    return "operator";
}
function lensStorageKey(session) {
    return `mesh.product.lens.${session.active_team?.id || `solo.${session.user.id}`}`;
}
function isLensKey(value) {
    return value === "operator" || value === "approver" || value === "security" || value === "partner-review";
}
function orderDashboardInsights(insights, lens) {
    const lensPriority = {
        operator: [
            "readiness",
            "run",
            "operator",
            "praxis",
            "connector",
            "settings",
            "proof",
            "approval",
            "auth"
        ],
        approver: [
            "approval",
            "proof",
            "readiness",
            "run",
            "operator",
            "settings",
            "connector",
            "auth",
            "praxis"
        ],
        security: [
            "auth",
            "connector",
            "proof",
            "readiness",
            "operator",
            "settings",
            "approval",
            "run",
            "praxis"
        ],
        "partner-review": [
            "proof",
            "readiness",
            "auth",
            "connector",
            "praxis",
            "run",
            "approval",
            "operator",
            "settings"
        ]
    };
    return [
        ...insights
    ].sort((a, b)=>{
        const severityDelta = severityRank(b.severity) - severityRank(a.severity);
        if (severityDelta !== 0) return severityDelta;
        const aLens = lensPriority[lens].findIndex((key)=>a.id.includes(key) || a.sourcePath.includes(key));
        const bLens = lensPriority[lens].findIndex((key)=>b.id.includes(key) || b.sourcePath.includes(key));
        const lensDelta = (aLens === -1 ? 99 : aLens) - (bLens === -1 ? 99 : bLens);
        if (lensDelta !== 0) return lensDelta;
        return b.confidence - a.confidence;
    });
}
function orderDashboardTiles(cards, lens) {
    const priority = {
        operator: [
            "Run admission",
            "Operator setup",
            "Runtime readiness",
            "Praxis MCP generator",
            "Connector status",
            "Evidence packets",
            "Settings parity"
        ],
        approver: [
            "Policy approvals",
            "Evidence packets",
            "Runtime readiness",
            "Run admission",
            "Trust ladder",
            "Settings parity"
        ],
        security: [
            "Connector status",
            "Runtime readiness",
            "Evidence packets",
            "Operator setup",
            "Settings parity",
            "Watchers",
            "Policy approvals"
        ],
        "partner-review": [
            "Evidence packets",
            "Runtime readiness",
            "Connector status",
            "Praxis MCP generator",
            "Policy approvals",
            "Settings parity"
        ]
    };
    return [
        ...cards
    ].sort((a, b)=>{
        const blockerDelta = surfaceRank(b.state) - surfaceRank(a.state);
        if (blockerDelta !== 0) return blockerDelta;
        const aIndex = priority[lens].indexOf(a.title);
        const bIndex = priority[lens].indexOf(b.title);
        return (aIndex === -1 ? 99 : aIndex) - (bIndex === -1 ? 99 : bIndex);
    });
}
function buildDashboardInsights(dashboard, authConfig) {
    const mesh = dashboard.mesh || {};
    const readiness = mesh.readiness || {};
    const pilot = mesh.pilot_go_no_go || {};
    const runs = Array.isArray(mesh.runs?.runs) ? mesh.runs.runs : [];
    const approvals = Array.isArray(mesh.approvals?.items) ? mesh.approvals.items : [];
    const connectorRecords = mesh.connectors?.connectors || mesh.connectors?.connector_certification || {};
    const connectorEntries = Object.entries(connectorRecords);
    const praxis = buildPraxisProductModel(dashboard);
    const insights = [];
    const readinessBlockers = Array.isArray(readiness.blockers) ? readiness.blockers : [];
    const missingEvidence = Array.isArray(pilot.missing_evidence) ? pilot.missing_evidence : [];
    const failedRuns = runs.filter((run)=>String(run.status || "").toLowerCase() === "failed");
    const degradedConnectors = connectorEntries.filter(([, value])=>!String(value?.state || value?.status || "").toLowerCase().includes("ready"));
    if (readiness.ready === false || readinessBlockers.length || String(readiness.status || "").toLowerCase().includes("blocked")) {
        insights.push({
            id: "readiness-blockers",
            title: "Readiness is blocked",
            severity: "critical",
            confidence: 0.96,
            sourcePath: "mesh.readiness.blockers",
            authority: "Mesh readiness read model",
            why: `${readinessBlockers.length || 1} readiness blocker(s) are stopping a clean operator handoff.`,
            actionLabel: "Review proof",
            actionView: "gpu",
            badges: sensitivityBadgesForSource("mesh.readiness.blockers")
        });
    }
    if (missingEvidence.length) {
        insights.push({
            id: "proof-gaps",
            title: "Proof packet has gaps",
            severity: "warning",
            confidence: 0.93,
            sourcePath: "mesh.pilot_go_no_go.missing_evidence",
            authority: "Mesh evidence packet",
            why: `${missingEvidence.slice(0, 3).map((item)=>humanize(String(item))).join(", ")} ${missingEvidence.length > 3 ? "and more " : ""}must be resolved before review.`,
            actionLabel: "Review proof",
            actionView: "evaluations",
            badges: sensitivityBadgesForSource("mesh.pilot_go_no_go.missing_evidence")
        });
    }
    if (approvals.length) {
        insights.push({
            id: "pending-approvals",
            title: "Approval queue needs attention",
            severity: "warning",
            confidence: 0.9,
            sourcePath: "mesh.approvals.items",
            authority: "Mesh policy and approvals",
            why: `${approvals.length} pending approval item(s) require an audited operator reason before steering.`,
            actionLabel: "Review proof",
            actionView: "evaluations",
            badges: sensitivityBadgesForSource("mesh.approvals.items")
        });
    }
    if (failedRuns.length) {
        insights.push({
            id: "failed-runs",
            title: "Recent runs failed",
            severity: "warning",
            confidence: 0.88,
            sourcePath: "mesh.runs.runs",
            authority: "Mesh run state",
            why: `${failedRuns.length} failed run(s) should be inspected for evidence, RCA, and admission blockers.`,
            actionLabel: "Review proof",
            actionView: "evaluations",
            badges: sensitivityBadgesForSource("mesh.runs.runs")
        });
    } else if (!runs.length) {
        insights.push({
            id: "launch-first-run",
            title: "No run evidence yet",
            severity: "info",
            confidence: 0.82,
            sourcePath: "mesh.runs.runs",
            authority: "Mesh run state",
            why: "Launch a sandbox scenario so readiness, evidence, and approval views have a current Mesh-owned record.",
            actionLabel: "Launch run",
            actionView: "evaluations",
            badges: sensitivityBadgesForSource("mesh.runs.runs")
        });
    }
    if (degradedConnectors.length) {
        insights.push({
            id: "connector-posture",
            title: "Connector posture is degraded",
            severity: "warning",
            confidence: 0.86,
            sourcePath: "mesh.connectors.connectors",
            authority: "Mesh connector certification",
            why: `${degradedConnectors.length} connector(s) are not reporting a ready certification posture.`,
            actionLabel: "Open Connectors",
            actionView: "environments",
            badges: sensitivityBadgesForSource("mesh.connectors.connectors")
        });
    }
    if (Number(praxis.sourcePackets) === 0) {
        insights.push({
            id: "praxis-source",
            title: "Praxis source is missing",
            severity: "info",
            confidence: 0.78,
            sourcePath: "mesh.praxis.source_bundle",
            authority: "Mesh Praxis read model",
            why: "Import redacted OpenAPI, SOP, Postman, or traffic references before generating and certifying tools.",
            actionLabel: "Import source",
            actionView: "praxis",
            badges: sensitivityBadgesForSource("mesh.praxis.source_bundle")
        });
    }
    const authBlocked = !authConfig || !authConfig.captcha.configured || !authConfig.invite.configured || !authConfig.oauth.google.configured && !authConfig.oauth.github.configured;
    if (authBlocked) {
        insights.push({
            id: "auth-provider-posture",
            title: "Provider posture needs review",
            severity: "warning",
            confidence: authConfig ? 0.84 : 0.91,
            sourcePath: "auth-provider-proof.v1",
            authority: "Deployment-owned auth config",
            why: "Signup, captcha, invite, or OAuth posture is incomplete or unavailable in the read-only provider proof.",
            actionLabel: "Open Keys",
            actionView: "keys",
            badges: sensitivityBadgesForSource("auth-provider-proof.v1")
        });
    }
    if (dashboard.settings.default_steering_mode !== "approval_gate") {
        insights.push({
            id: "settings-defaults",
            title: "Settings default weakens review posture",
            severity: "info",
            confidence: 0.76,
            sourcePath: "mesh-settings-control.default_steering_mode",
            authority: "Mesh settings control",
            why: "Approval gate is the safest product default for partner-facing or security-sensitive launches.",
            actionLabel: "Open Settings",
            actionView: "settings",
            badges: sensitivityBadgesForSource("mesh-settings-control.default_steering_mode")
        });
    }
    if (!insights.length) {
        insights.push({
            id: "dashboard-clear",
            title: "No immediate blockers surfaced",
            severity: "success",
            confidence: 0.7,
            sourcePath: "mesh-dashboard-read-model",
            authority: "Mesh dashboard read model",
            why: "The dashboard did not report blockers, proof gaps, pending approvals, failed runs, or degraded connectors.",
            actionLabel: "Launch run",
            actionView: "evaluations",
            badges: sensitivityBadgesForSource("mesh-dashboard-read-model")
        });
    }
    return orderDashboardInsights(insights, "operator");
}
function askMesh(query, dashboard, authConfig) {
    const normalized = query.trim().toLowerCase();
    const mesh = dashboard.mesh || {};
    const runs = Array.isArray(mesh.runs?.runs) ? mesh.runs.runs : [];
    const failedRuns = runs.filter((run)=>String(run.status || "").toLowerCase() === "failed");
    const approvals = Array.isArray(mesh.approvals?.items) ? mesh.approvals.items : [];
    const readiness = mesh.readiness || {};
    const readinessBlockers = Array.isArray(readiness.blockers) ? readiness.blockers : [];
    const pilot = mesh.pilot_go_no_go || {};
    const missingEvidence = Array.isArray(pilot.missing_evidence) ? pilot.missing_evidence : [];
    const connectors = Object.entries(mesh.connectors?.connectors || mesh.connectors?.connector_certification || {});
    const connectorNotReady = connectors.filter(([, value])=>!String(value?.state || value?.status || "").toLowerCase().includes("ready"));
    const setup = buildOperatorSetupModel(dashboard);
    const suggestions = [
        "why blocked",
        "latest runs",
        "failed runs",
        "pending approvals",
        "operator setup",
        "agent preferences",
        "connector readiness",
        "proof gaps",
        "auth posture",
        "settings defaults"
    ];
    if (normalized.includes("block") || normalized.includes("why")) {
        const blockers = [
            ...readinessBlockers,
            ...missingEvidence
        ].map((item)=>humanize(String(item)));
        return {
            query,
            intent: "blockers",
            supported: true,
            answer: blockers.length ? `Mesh reports ${blockers.length} blocker(s): ${blockers.slice(0, 4).join(", ")}.` : "Mesh does not report readiness blockers or missing proof in this dashboard payload.",
            sourcePath: "mesh.readiness.blockers + mesh.pilot_go_no_go.missing_evidence",
            targetView: missingEvidence.length ? "evaluations" : "gpu",
            filters: blockers.slice(0, 4),
            suggestions
        };
    }
    if (normalized.includes("latest") || normalized.includes("recent")) {
        const latest = runs[0];
        return {
            query,
            intent: "latest runs",
            supported: true,
            answer: latest ? `Latest run ${latest.run_id || latest.id || "unknown"} is ${humanize(String(latest.status || latest.stage || "unknown"))} for ${latest.scenario_key || "custom scenario"}.` : "No run summaries are present in this dashboard payload.",
            sourcePath: "mesh.runs.runs[0]",
            targetView: "evaluations",
            filters: latest ? [
                String(latest.run_id || latest.id || ""),
                String(latest.status || "")
            ] : [],
            suggestions
        };
    }
    if (normalized.includes("fail")) {
        return {
            query,
            intent: "failed runs",
            supported: true,
            answer: failedRuns.length ? `${failedRuns.length} failed run(s): ${failedRuns.slice(0, 3).map((run)=>run.run_id || run.id).join(", ")}.` : "No failed runs are present in the dashboard read model.",
            sourcePath: "mesh.runs.runs",
            targetView: "evaluations",
            filters: failedRuns.map((run)=>String(run.run_id || run.id || "failed")).slice(0, 4),
            suggestions
        };
    }
    if (normalized.includes("approval")) {
        return {
            query,
            intent: "pending approvals",
            supported: true,
            answer: approvals.length ? `${approvals.length} pending approval item(s) require Mesh steering commands with an audit reason.` : "No pending approval queue items are present.",
            sourcePath: "mesh.approvals.items",
            targetView: "evaluations",
            filters: approvals.map((item)=>String(item.run_id || item.queue_id || "approval")).slice(0, 4),
            suggestions
        };
    }
    if (normalized.includes("connector") || normalized.includes("integration")) {
        return {
            query,
            intent: "connector readiness",
            supported: true,
            answer: connectorNotReady.length ? `${connectorNotReady.length}/${connectors.length} connector(s) are not ready.` : `${connectors.length} connector(s) are reporting ready or no connector blockers were returned.`,
            sourcePath: "mesh.connectors.connectors",
            targetView: "environments",
            filters: connectorNotReady.map(([id])=>id).slice(0, 4),
            suggestions
        };
    }
    if (normalized.includes("operator") || normalized.includes("agent preference") || normalized.includes("agent setup") || normalized.includes("agent preferences")) {
        return {
            query,
            intent: "operator setup",
            supported: true,
            answer: `${setup.operatorId} is using ${setup.agentFabricMode} with ${setup.preferredAgents.join(", ") || "no preferred agents"} and model ${setup.modelBinding}. Target is ${setup.target.environment}/${setup.target.namespace}/${setup.target.service}.`,
            sourcePath: "operator_preferences_state",
            targetView: "operator-setup",
            filters: [
                setup.agentFabricMode,
                ...setup.preferredAgents
            ].filter(Boolean),
            suggestions
        };
    }
    if (normalized.includes("proof") || normalized.includes("evidence")) {
        return {
            query,
            intent: "proof gaps",
            supported: true,
            answer: missingEvidence.length ? `${missingEvidence.length} proof gap(s): ${missingEvidence.slice(0, 4).map((item)=>humanize(String(item))).join(", ")}.` : "No missing evidence is present in the pilot go/no-go read model.",
            sourcePath: "mesh.pilot_go_no_go.missing_evidence",
            targetView: "evaluations",
            filters: missingEvidence.slice(0, 4).map(String),
            suggestions
        };
    }
    if (normalized.includes("auth") || normalized.includes("provider") || normalized.includes("key") || normalized.includes("secret")) {
        const configured = authConfig ? [
            authConfig.captcha.configured || authConfig.captcha.dev_bypass_enabled ? "captcha configured" : "captcha blocked",
            authConfig.invite.configured ? "invite configured" : "invite not configured",
            authConfig.oauth.google.configured ? "google oauth configured" : "google oauth not configured",
            authConfig.oauth.github.configured ? "github oauth configured" : "github oauth not configured"
        ] : [
            "auth config unavailable"
        ];
        return {
            query,
            intent: "auth/provider posture",
            supported: true,
            answer: configured.join("; "),
            sourcePath: "auth-provider-proof.v1",
            targetView: "keys",
            filters: configured,
            suggestions
        };
    }
    if (normalized.includes("setting") || normalized.includes("default")) {
        const defaults = Object.entries(dashboard.settings).map(([key, value])=>`${humanize(key)}: ${value}`);
        return {
            query,
            intent: "settings defaults",
            supported: true,
            answer: defaults.length ? defaults.slice(0, 4).join("; ") : "No operator settings are present in this dashboard payload.",
            sourcePath: "mesh-settings-control",
            targetView: "settings",
            filters: defaults.slice(0, 4),
            suggestions
        };
    }
    return {
        query,
        intent: "unsupported",
        supported: false,
        answer: "Ask Mesh V1 supports deterministic prompts for blockers, runs, approvals, operator setup, connectors, proof, auth posture, and settings defaults.",
        sourcePath: "ui-product-shell.ask_mesh.v1",
        targetView: "home",
        filters: [],
        suggestions
    };
}
function sensitivityBadgesForSource(sourcePath) {
    const normalized = sourcePath.toLowerCase();
    const badges = normalized.includes("auth") || normalized.includes("key") || normalized.includes("secret") || normalized.includes("captcha") || normalized.includes("oauth") || normalized.includes("invite") ? [
        "Read-only",
        "Deployment-owned",
        "Sensitive",
        "Redacted"
    ] : normalized.includes("approval") || normalized.includes("proof") || normalized.includes("evidence") || normalized.includes("settings") || normalized.includes("preference") ? [
        "Read-only",
        "Mesh-owned",
        "Audit required"
    ] : [
        "Read-only",
        "Mesh-owned"
    ];
    if (normalized.includes("connector")) badges.push("Sensitive");
    return Array.from(new Set(badges));
}
function sourceLineage(sourcePath, payload, fallbackAuthority) {
    const authority = String(payload?.authority || payload?.authority_posture || payload?.source_authority || fallbackAuthority);
    const timestamp = payload?.updated_at || payload?.last_updated || payload?.timestamp || payload?.created_at;
    const degraded = payload?.degraded_reason || payload?.error || (timestamp ? "" : "freshness missing");
    return {
        sourcePath,
        authority,
        timestamp: timestamp ? String(timestamp) : undefined,
        degraded: degraded ? String(degraded) : undefined
    };
}
function badgeToneClass(badge) {
    if (badge === "Sensitive" || badge === "Audit required") return "warn";
    if (badge === "Deployment-owned" || badge === "Redacted") return "info";
    return "neutral";
}
function severityRank(severity) {
    if (severity === "critical") return 4;
    if (severity === "warning") return 3;
    if (severity === "info") return 2;
    return 1;
}
function surfaceRank(state) {
    if (state === "blocked" || state === "degraded" || state === "backend-unavailable" || state === "unauthorized") return 2;
    if (state === "empty") return 1;
    return 0;
}
function ReadModelCard({ title, payload }) {
    const displayPayload = readModelCardPayload(title, payload);
    const display = readModelDisplay(displayPayload);
    const isEmpty = displayPayload?.state === "empty" || display.state === "empty";
    const sourcePath = `mesh.${title.toLowerCase().replaceAll(" ", "_")}`;
    const lineage = sourceLineage(sourcePath, displayPayload, "Mesh read model");
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
        className: `read-model-card ${display.state} ${isEmpty ? "empty" : ""}`,
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$circle$2d$dot$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__CircleDot$3e$__["CircleDot"], {
                size: 15
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4796,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                children: title
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4797,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                children: humanize(display.status)
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4798,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                children: display.summary
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4799,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(SensitivityBadges, {
                badges: sensitivityBadgesForSource(sourcePath)
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4800,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(SourceLine, {
                ...lineage
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4801,
                columnNumber: 7
            }, this),
            isEmpty ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                className: "read-model-empty-hint",
                children: "Nothing to show here yet. This updates automatically as Mesh records activity for your team."
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4803,
                columnNumber: 9
            }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("details", {
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("summary", {
                        children: "Raw payload"
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 4806,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("pre", {
                        children: JSON.stringify(displayPayload, null, 2).slice(0, 720)
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 4807,
                        columnNumber: 11
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4805,
                columnNumber: 9
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 4795,
        columnNumber: 5
    }, this);
}
_c47 = ReadModelCard;
function SensitivityBadges({ badges }) {
    const uniqueBadges = Array.from(new Set(badges));
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "sensitivity-badges",
        children: uniqueBadges.map((badge)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                className: badgeToneClass(badge),
                children: badge
            }, badge, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4818,
                columnNumber: 36
            }, this))
    }, void 0, false, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 4817,
        columnNumber: 5
    }, this);
}
_c48 = SensitivityBadges;
function SourceLine({ sourcePath, authority, timestamp, degraded }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
        className: "source-line",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                children: sourcePath
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4826,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                children: authority
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4827,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                children: timestamp || "timestamp unavailable"
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4828,
                columnNumber: 7
            }, this),
            degraded ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                children: degraded
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4829,
                columnNumber: 19
            }, this) : null
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 4825,
        columnNumber: 5
    }, this);
}
_c49 = SourceLine;
function readModelDisplay(payload) {
    const status = String(payload?.status || payload?.state || payload?.decision || "read-only");
    const sectionState = dashboardSectionState(payload).state;
    if (payload?.error) return {
        status,
        summary: String(payload.error),
        state: "degraded"
    };
    if (payload?.reason) return {
        status,
        summary: String(payload.reason),
        state: sectionState
    };
    if (payload?.detail) return {
        status,
        summary: String(payload.detail),
        state: sectionState
    };
    if (payload?.degraded_reason) return {
        status,
        summary: String(payload.degraded_reason),
        state: sectionState
    };
    if (Array.isArray(payload?.blockers) && payload.blockers.length) return {
        status,
        summary: `${payload.blockers.length} blocker(s): ${payload.blockers.slice(0, 3).join(", ")}`,
        state: "blocked"
    };
    const keys = payload && typeof payload === "object" ? Object.keys(payload) : [];
    return {
        status,
        summary: keys.length ? `Mesh returned ${keys.length} field(s) for this read model.` : "No payload is available for this read model yet.",
        state: sectionState
    };
}
function readModelSummary(payload, emptyReason) {
    if (payload?.error) return `Unavailable: ${payload.error}`;
    if (payload?.status) return String(payload.status);
    if (payload?.state) return String(payload.state);
    return emptyReason;
}
function readModelCardPayload(title, payload) {
    if (payload && Object.keys(payload).length > 0) return payload;
    return {
        state: "empty",
        reason: `${title} read model returned no payload. This product surface is read-only until Mesh exposes data.`
    };
}
function humanize(value) {
    return value.replaceAll("_", " ").replaceAll("-", " ");
}
function titleize(value) {
    return humanize(value).replace(/\b\w/g, (letter)=>letter.toUpperCase());
}
function Toolbar({ title, detail, action, onAction }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "toolbar",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h2", {
                        children: title
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 4886,
                        columnNumber: 12
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                        children: detail
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 4886,
                        columnNumber: 28
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4886,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                className: "primary-button",
                type: "button",
                onClick: onAction,
                disabled: !onAction,
                children: action
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4887,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 4885,
        columnNumber: 5
    }, this);
}
_c50 = Toolbar;
function SearchBar({ placeholder = "Search by name, author, description, tags...", value, onChange }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
        className: "search-bar",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$search$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__Search$3e$__["Search"], {
                size: 16
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4903,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                placeholder: placeholder,
                value: value ?? "",
                onChange: (event)=>onChange?.(event.target.value)
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4904,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 4902,
        columnNumber: 5
    }, this);
}
_c51 = SearchBar;
function SectionLabel({ label }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h3", {
        className: "section-label",
        children: label
    }, void 0, false, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 4910,
        columnNumber: 10
    }, this);
}
_c52 = SectionLabel;
function CardRows({ sections }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["Fragment"], {
        children: sections.map((section)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                className: "card-section",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h3", {
                        children: [
                            section.title,
                            " ",
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: section.count
                            }, void 0, false, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4918,
                                columnNumber: 31
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 4918,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "environment-grid",
                        children: section.cards.map((card)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("article", {
                                className: "environment-card",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                        children: [
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                children: card.owner
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 4922,
                                                columnNumber: 22
                                            }, this),
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                children: card.state || card.tags?.[0] || "unknown"
                                            }, void 0, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 4922,
                                                columnNumber: 47
                                            }, this)
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 4922,
                                        columnNumber: 17
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("h4", {
                                        children: card.title
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 4923,
                                        columnNumber: 17
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                        children: card.detail
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 4924,
                                        columnNumber: 17
                                    }, this),
                                    card.blockers?.length ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                        className: "blocker-badges",
                                        children: card.blockers.map((blocker)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                children: [
                                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$lucide$2d$react$40$0$2e$562$2e$0_react$40$19$2e$2$2e$6$2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$triangle$2d$alert$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__$3c$export__default__as__AlertTriangle$3e$__["AlertTriangle"], {
                                                        size: 11
                                                    }, void 0, false, {
                                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                        lineNumber: 4927,
                                                        columnNumber: 81
                                                    }, this),
                                                    " ",
                                                    humanize(blocker)
                                                ]
                                            }, blocker, true, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 4927,
                                                columnNumber: 61
                                            }, this))
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 4926,
                                        columnNumber: 19
                                    }, this) : null,
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                        className: "tag-row",
                                        children: card.tags.map((tag)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                children: tag
                                            }, tag, false, {
                                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                                lineNumber: 4930,
                                                columnNumber: 74
                                            }, this))
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 4930,
                                        columnNumber: 17
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("small", {
                                        children: card.version
                                    }, void 0, false, {
                                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                        lineNumber: 4931,
                                        columnNumber: 17
                                    }, this)
                                ]
                            }, card.id, true, {
                                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                                lineNumber: 4921,
                                columnNumber: 15
                            }, this))
                    }, void 0, false, {
                        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                        lineNumber: 4919,
                        columnNumber: 11
                    }, this)
                ]
            }, section.title, true, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4917,
                columnNumber: 9
            }, this))
    }, void 0, false);
}
_c53 = CardRows;
function Stat({ label, value, detail }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "stat-card",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                children: label
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4942,
                columnNumber: 37
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                children: value
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4942,
                columnNumber: 57
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                children: detail
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4942,
                columnNumber: 81
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 4942,
        columnNumber: 10
    }, this);
}
_c54 = Stat;
function FormRead({ label, value, large = false }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
        className: large ? "form-read large" : "form-read",
        children: [
            label,
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f2e$pnpm$2f$next$40$16$2e$2$2e$6_$40$playwright$2b$test$40$1$2e$60$2e$0_react$2d$dom$40$19$2e$2$2e$6_react$40$19$2e$2$2e$6_$5f$react$40$19$2e$2$2e$6$2f$node_modules$2f$next$2f$dist$2f$compiled$2f$react$2f$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$client$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                children: value
            }, void 0, false, {
                fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
                lineNumber: 4946,
                columnNumber: 76
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/meshapp/frontend/src/product/ProductApp.tsx",
        lineNumber: 4946,
        columnNumber: 10
    }, this);
}
_c55 = FormRead;
var _c, _c1, _c2, _c3, _c4, _c5, _c6, _c7, _c8, _c9, _c10, _c11, _c12, _c13, _c14, _c15, _c16, _c17, _c18, _c19, _c20, _c21, _c22, _c23, _c24, _c25, _c26, _c27, _c28, _c29, _c30, _c31, _c32, _c33, _c34, _c35, _c36, _c37, _c38, _c39, _c40, _c41, _c42, _c43, _c44, _c45, _c46, _c47, _c48, _c49, _c50, _c51, _c52, _c53, _c54, _c55;
__turbopack_context__.k.register(_c, "BackendStatusChip");
__turbopack_context__.k.register(_c1, "ProductApp");
__turbopack_context__.k.register(_c2, "BootScreen");
__turbopack_context__.k.register(_c3, "BrandLogo");
__turbopack_context__.k.register(_c4, "AsciiFlowBackground");
__turbopack_context__.k.register(_c5, "AuthScreen");
__turbopack_context__.k.register(_c6, "CaptchaWidget");
__turbopack_context__.k.register(_c7, "TeamSetupScreen");
__turbopack_context__.k.register(_c8, "Sidebar");
__turbopack_context__.k.register(_c9, "Header");
__turbopack_context__.k.register(_c10, "LensSelector");
__turbopack_context__.k.register(_c11, "TeamSwitcher");
__turbopack_context__.k.register(_c12, "ContentRouter");
__turbopack_context__.k.register(_c13, "ConsoleWorkspace");
__turbopack_context__.k.register(_c14, "AgentFlowView");
__turbopack_context__.k.register(_c15, "LoadStatePanel");
__turbopack_context__.k.register(_c16, "HomeView");
__turbopack_context__.k.register(_c17, "InsightsPanel");
__turbopack_context__.k.register(_c18, "AskMeshPanel");
__turbopack_context__.k.register(_c19, "PraxisHomeModule");
__turbopack_context__.k.register(_c20, "PraxisStat");
__turbopack_context__.k.register(_c21, "PraxisFileInput");
__turbopack_context__.k.register(_c22, "PraxisView");
__turbopack_context__.k.register(_c23, "PraxisStepper");
__turbopack_context__.k.register(_c24, "PraxisJourney");
__turbopack_context__.k.register(_c25, "PraxisLane");
__turbopack_context__.k.register(_c26, "OperatorCommandCenter");
__turbopack_context__.k.register(_c27, "ConsoleMetric");
__turbopack_context__.k.register(_c28, "EmptyInline");
__turbopack_context__.k.register(_c29, "HardenedArenaView");
__turbopack_context__.k.register(_c30, "EnvironmentView");
__turbopack_context__.k.register(_c31, "EvaluationsView");
__turbopack_context__.k.register(_c32, "ApprovalQueuePanel");
__turbopack_context__.k.register(_c33, "ProofDrilldownPanel");
__turbopack_context__.k.register(_c34, "AgentFabricObservability");
__turbopack_context__.k.register(_c35, "RunWorkbenchSummary");
__turbopack_context__.k.register(_c36, "LaunchRunPanel");
__turbopack_context__.k.register(_c37, "RunPreflightPanel");
__turbopack_context__.k.register(_c38, "TraceRail");
__turbopack_context__.k.register(_c39, "TeamSettingsView");
__turbopack_context__.k.register(_c40, "MembersView");
__turbopack_context__.k.register(_c41, "OperatorSetupView");
__turbopack_context__.k.register(_c42, "OperatorPreferenceField");
__turbopack_context__.k.register(_c43, "KeysView");
__turbopack_context__.k.register(_c44, "ConfigPostureCard");
__turbopack_context__.k.register(_c45, "SettingsView");
__turbopack_context__.k.register(_c46, "CapabilityView");
__turbopack_context__.k.register(_c47, "ReadModelCard");
__turbopack_context__.k.register(_c48, "SensitivityBadges");
__turbopack_context__.k.register(_c49, "SourceLine");
__turbopack_context__.k.register(_c50, "Toolbar");
__turbopack_context__.k.register(_c51, "SearchBar");
__turbopack_context__.k.register(_c52, "SectionLabel");
__turbopack_context__.k.register(_c53, "CardRows");
__turbopack_context__.k.register(_c54, "Stat");
__turbopack_context__.k.register(_c55, "FormRead");
if (typeof globalThis.$RefreshHelpers$ === 'object' && globalThis.$RefreshHelpers !== null) {
    __turbopack_context__.k.registerExports(__turbopack_context__.m, globalThis.$RefreshHelpers$);
}
}),
]);

//# sourceMappingURL=meshapp_frontend_src_product_10vrttl._.js.map