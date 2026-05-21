#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "operator-product-app.md"
INGRESS_DOC_PATH = REPO_ROOT / "docs" / "authenticated-ingress.md"
PRODUCT_TYPES_PATH = REPO_ROOT / "meshapp" / "frontend" / "src" / "product" / "types.ts"
PRODUCT_APP_PATH = REPO_ROOT / "meshapp" / "frontend" / "src" / "product" / "ProductApp.tsx"
PRODUCT_API_PATH = REPO_ROOT / "meshapp" / "frontend" / "src" / "product" / "api.ts"
PRODUCT_E2E_PATH = REPO_ROOT / "meshapp" / "frontend" / "e2e" / "first-run-signup-dashboard.spec.ts"
PRODUCT_PLAYWRIGHT_CONFIG_PATH = REPO_ROOT / "meshapp" / "frontend" / "playwright.config.ts"
PRODUCT_PACKAGE_PATH = REPO_ROOT / "meshapp" / "frontend" / "package.json"
CONTROL_PLANE_PATH = REPO_ROOT / "control_plane_server.py"
IDENTITY_PATH = REPO_ROOT / "shared" / "mesh_runtime" / "operator_identity.py"
PRODUCT_CONTRACTS_PATH = REPO_ROOT / "shared" / "mesh_runtime" / "operator_product_contracts.py"
PRODUCT_SCHEMA_PATH = REPO_ROOT / "shared" / "mesh_runtime" / "schemas" / "operator-product.schema.json"
HTTP_TEST_PATH = REPO_ROOT / "tests" / "test_operator_auth_http.py"
AUTH_PROVIDER_SMOKE_TEST_PATH = REPO_ROOT / "tests" / "test_operator_auth_provider_smoke.py"
IDENTITY_TEST_PATH = REPO_ROOT / "tests" / "test_operator_identity.py"
CONFIG_TEST_PATH = REPO_ROOT / "tests" / "test_mesh_runtime_config.py"
INGRESS_DEPLOYMENT_TEST_PATH = REPO_ROOT / "tests" / "test_authenticated_ingress_deployment.py"
PRODUCT_CONTRACT_TEST_PATH = REPO_ROOT / "tests" / "test_operator_product_contracts.py"
PRODUCT_E2E_SCRIPT_PATH = REPO_ROOT / "scripts" / "operator_product_e2e.py"
AUTH_PROVIDER_SMOKE_PATH = REPO_ROOT / "scripts" / "operator_auth_provider_smoke.py"
AUTH_PROVIDER_CAPTURE_PATH = REPO_ROOT / "scripts" / "operator_auth_live_provider_capture.py"
PRODUCT_GOAL_AUDIT_PATH = REPO_ROOT / "scripts" / "operator_product_goal_audit.py"
PRODUCT_CONTRACT_GENERATOR_PATH = REPO_ROOT / "scripts" / "generate_operator_product_contracts.py"
PACKAGE_PATH = REPO_ROOT / "package.json"

REQUIRED_DOC_MARKERS = [
    "## P0 Web-To-Meshapp Parity Inventory",
    "## Product Workflow Authority Matrix",
    "Product-native workflow posture",
    "Evidence, approval, and RCA trace posture",
    "## Deployment And Ingress Matrix",
    "P8 deployment fail-closed checks",
    "## Browser E2E And Contract Drift Guard",
    "## Evidence Binder",
    "State slice: `ui-product-shell`",
    "`auth-identity`",
    "`mesh-dashboard-read-model`",
    "`mesh-settings-control`",
    "`meshapp.praxis-product-home.v1`",
    "`praxis.managed-dry-run-runtime.v1`",
    "Akto evidence is advisory security evidence and cannot grant production authority.",
    "ACP remains a supervised session surface and cannot grant runtime authority.",
    "State slices: `auth state`, `API route`, `persisted artifact`",
    "| Local development |",
    "| Local provider smoke |",
    "| Staging |",
    "| Pilot |",
    "Signup/OAuth fail closed when provider credentials are incomplete.",
    "Audit, approval, readiness, evidence, and run state stay Mesh-owned",
    "Mesh remains owner of readiness, approvals, evidence, run state, connectors, memory, and pilot packets.",
    "`pnpm run test:product:e2e`",
    "`pnpm run test:auth-provider:smoke`",
    "`pnpm run test:auth-provider:live`",
    "`pnpm run auth-provider:live-template`",
    "`pnpm run auth-provider:live-preflight`",
    "`pnpm run auth-provider:live-stack-smoke`",
    "`pnpm run auth-provider:reuse-stack-smoke`",
    "`pnpm run auth-provider:checkpoint`",
    "`pnpm run auth-provider:live-attempt`",
    "`pnpm run auth-provider:reuse-attempt`",
    "`pnpm run auth-provider:live-capture`",
    "`pnpm run auth-provider:live-stack`",
    "`pnpm run auth-provider:reuse-stack`",
    "`pnpm run verify:operator-goal`",
    "--reuse-local-stack",
    "stack_mode",
    "MESH_AUTH_PRODUCT_REDIRECT_URL",
    "mesh.operator_auth_provider_live_proof.v1",
    "mesh.operator_auth_runtime_evidence.v1",
    "mesh.operator_product_goal_audit.v1",
    "runtime_auth_evidence",
    "auth_events",
    "live-provider-proof.json",
    "`scripts/generate_operator_product_contracts.py --check`",
    "`shared/mesh_runtime/schemas/operator-product.schema.json`",
]

REQUIRED_INGRESS_DOC_MARKERS = [
    "must not expose the raw HTTP service to external clients",
    "does not replace the Mesh control plane authority",
    "Staging and pilot readiness require `MESH_AUTHENTICATED_INGRESS_PROOF_PATH`",
    "stripping any client-supplied `X-Mesh-Operator`, `X-Mesh-Roles`",
    "raw Mesh service is not publicly reachable",
    "raw_secret_material_present: false",
]

REQUIRED_PARITY_ROWS = [
    "`web/index.html`",
    "`web/src/main.tsx`",
    "`web/src/App.tsx`",
    "`web/src/api.ts`",
    "`web/src/types.ts`",
    "`web/src/index.css`",
    "`web/src/components/AmbientAsciiSignal.tsx`",
    "`web/src/components/Inspector.tsx`",
    "`web/src/components/Toaster.tsx`",
    "`web/src/components/rca/*`",
    "`web/src/lib/asciiSignal.ts`",
    "`web/src/lib/format.ts`",
    "`web/src/lib/labyrinth.ts`",
    "`web/src/lib/runGraph.ts`",
    "`web/branding/logo.svg`",
    "`web/e2e/operator-ui.spec.ts`",
    "`web/dist/*`",
    "`web/node_modules/*`, `web/package-lock.json`",
]

REQUIRED_PRODUCT_API_PATHS = [
    '"/api/auth/config"',
    '"/api/auth/me"',
    '"/api/auth/signup"',
    '"/api/auth/login"',
    '"/api/auth/logout"',
    '"/api/auth/team"',
    '"/api/auth/switch-team"',
    "/api/operator/dashboard",
    '"/api/operator/settings"',
    'from "./types"',
]

REQUIRED_CONTROL_PLANE_PATHS = [
    '"/api/auth/config"',
    '"/api/auth/oauth/google/start"',
    '"/api/auth/oauth/github/start"',
    '"/api/auth/oauth/google/callback"',
    '"/api/auth/oauth/github/callback"',
    "auth_product_redirect_url",
    "_auth_callback_redirect",
    '"/api/operator/dashboard"',
    '"/api/operator/settings"',
    "build_praxis_product_dashboard",
]

REQUIRED_PRODUCT_UI_MARKERS = [
    "OperatorCommandCenter",
    "buildDashboardControlModel",
    "Mesh Control Summary",
    "PraxisHomeModule",
    "PraxisView",
    "buildPraxisProductModel",
    "praxis.managed-dry-run-runtime.v1",
    "backendUnavailableMessage",
    "CaptchaWidget",
    "TeamSetupScreen",
    "TeamSwitcher",
    "operatorWorkflowPosture",
    "evidenceTraceSteps",
    "ReadModelCard",
    "readModelCardPayload",
    "settingsParityRows",
    "SettingsView",
    "Audit reason",
    "Mesh controls policy",
]

REQUIRED_TEST_MARKERS = [
    "test_logout_login_and_dashboard_recovery",
    "test_dashboard_read_model_degrades_failed_sections_explicitly",
    "test_team_isolation_and_scoped_settings_are_forbidden_for_non_member",
    "test_operator_settings_requires_reason_and_writes_shared_audit",
    "test_oauth_start_urls_and_callback_failures_are_clear",
    "test_oauth_callback_redirects_to_configured_local_product_url",
    "test_oauth_callback_rejects_unallowed_product_redirect_url",
    "test_oauth_callback_allows_configured_auth_origin",
    "test_oauth_start_routes_fail_closed_without_provider_config",
    "test_live_provider_proof_completes_only_with_clean_browser_evidence",
    "test_live_provider_proof_rejects_raw_secret_fields",
    "test_runtime_auth_evidence_completes_from_redacted_identity_events",
    "test_complete_live_proof_requires_runtime_auth_evidence",
    "test_live_capture_builds_complete_redacted_proof_from_runtime_events",
    "test_live_stack_env_uses_default_identity_path_and_redacts_secret_values",
    "test_live_capture_preflight_blocks_redirect_mismatch_without_secret_material",
    "test_live_capture_preflight_blocks_missing_product_redirect_and_nondefault_identity",
    "test_live_capture_preflight_ready_when_redirects_and_hcaptcha_match",
    "test_live_stack_smoke_artifacts_are_redacted_and_do_not_claim_provider_completion",
    "test_managed_stack_fails_closed_when_requested_port_is_already_in_use",
    "test_auth_checkpoint_binds_local_evidence_without_claiming_live_provider_completion",
    "test_auth_checkpoint_points_reused_stack_evidence_to_reuse_stack_command",
    "test_live_capture_attempt_records_missing_components_without_secret_material",
    "test_blocked_attempt_exit_code_is_allowed_only_for_clean_local_evidence",
    "test_auth_provider_runtime_evidence_records_redacted_provider_sessions",
    "test_goal_audit_blocks_only_on_external_provider_proof_when_local_markers_exist",
    "test_goal_audit_accepts_explicit_reused_local_stack_provenance",
    "test_goal_audit_completes_when_live_provider_proof_is_complete",
    "test_goal_audit_fails_local_when_complete_readiness_has_stale_blocked_checkpoint",
    "test_goal_audit_fails_local_when_auth_live_preflight_is_not_ready",
    "test_goal_audit_fails_local_when_auth_live_stack_smoke_is_not_ready",
    "test_goal_audit_fails_local_when_auth_live_stack_smoke_has_ambiguous_stack_provenance",
    "test_goal_audit_fails_local_when_auth_checkpoint_is_not_bound",
    "test_goal_audit_fails_local_when_auth_checkpoint_attempt_binding_is_stale",
    "test_goal_audit_fails_local_when_auth_checkpoint_evidence_timestamps_are_stale",
    "test_goal_audit_fails_local_when_auth_checkpoint_next_command_is_stale",
    "test_goal_audit_fails_local_when_auth_live_capture_attempt_is_not_bound",
    "test_goal_audit_fails_local_when_dashboard_backend_section_contract_marker_is_missing",
    "test_captcha_missing_provider_secret_fails_closed",
    "test_non_local_app_session_signup_requires_captcha_provider",
    "test_non_local_app_session_signup_accepts_complete_captcha_provider",
    "test_authenticated_ingress_deployment_blocks_wrong_expected_environment",
    "test_staging_readiness_requires_deployed_ingress_proof",
    "test_missing_authenticated_ingress_deployment_proof_reports_required_evidence",
    "test_team_dashboard_access_denied_for_non_member",
    "test_expired_session_is_rejected_and_removed",
    "test_oauth_authorize_url_requires_complete_provider_config",
    "test_product_auth_dashboard_and_settings_responses_match_schema",
    "test_operator_dashboard_exposes_every_product_home_section",
]

REQUIRED_PRODUCT_E2E_MARKERS = [
    "first-run signup creates a team and reaches the product dashboard",
    "Create your account",
    "Local captcha bypass is active for development only.",
    "/api/operator/dashboard",
    "Dashboard identity scopes the product read model.",
    "team settings, member invites, provider posture, connector filters, and launch defaults work end to end",
    "Save settings",
    "Save members",
    "Mesh admitted this run.",
    "MESH_CAPTCHA_SECRET_KEY",
]

REQUIRED_PRODUCT_TYPE_MARKERS = [
    "Generated by scripts/generate_operator_product_contracts.py",
    "AuthConfig",
    "DashboardPayload",
    "SettingsUpdateResponse",
    "settings_schema",
]

REQUIRED_PRODUCT_CONTRACT_MARKERS = [
    "operator_product_schema",
    "dashboard_mesh",
    "degraded_reason",
    "render_typescript_types",
    "settings_update_response",
    "DashboardPayload",
    "SettingsUpdateResponse",
]


def main() -> int:
    try:
        _require_files()
        doc_text = DOC_PATH.read_text(encoding="utf-8")
        ingress_doc_text = INGRESS_DOC_PATH.read_text(encoding="utf-8")
        product_types = PRODUCT_TYPES_PATH.read_text(encoding="utf-8")
        product_app = PRODUCT_APP_PATH.read_text(encoding="utf-8")
        product_api = PRODUCT_API_PATH.read_text(encoding="utf-8")
        product_e2e = PRODUCT_E2E_PATH.read_text(encoding="utf-8")
        product_e2e_script = PRODUCT_E2E_SCRIPT_PATH.read_text(encoding="utf-8")
        product_contracts = PRODUCT_CONTRACTS_PATH.read_text(encoding="utf-8")
        control_plane = CONTROL_PLANE_PATH.read_text(encoding="utf-8")
        identity = IDENTITY_PATH.read_text(encoding="utf-8")
        tests = "\n".join(
            [
                HTTP_TEST_PATH.read_text(encoding="utf-8"),
                AUTH_PROVIDER_SMOKE_TEST_PATH.read_text(encoding="utf-8"),
                (REPO_ROOT / "tests" / "test_operator_product_goal_audit.py").read_text(encoding="utf-8"),
                IDENTITY_TEST_PATH.read_text(encoding="utf-8"),
                CONFIG_TEST_PATH.read_text(encoding="utf-8"),
                INGRESS_DEPLOYMENT_TEST_PATH.read_text(encoding="utf-8"),
                PRODUCT_CONTRACT_TEST_PATH.read_text(encoding="utf-8"),
            ]
        )
        package = json.loads(PACKAGE_PATH.read_text(encoding="utf-8"))
        product_package = json.loads(PRODUCT_PACKAGE_PATH.read_text(encoding="utf-8"))

        _require_markers("docs/operator-product-app.md", doc_text, REQUIRED_DOC_MARKERS + REQUIRED_PARITY_ROWS)
        _require_markers("docs/authenticated-ingress.md", ingress_doc_text, REQUIRED_INGRESS_DOC_MARKERS)
        _require_markers("meshapp/frontend/src/product/types.ts", product_types, REQUIRED_PRODUCT_TYPE_MARKERS)
        _require_markers("shared/mesh_runtime/operator_product_contracts.py", product_contracts, REQUIRED_PRODUCT_CONTRACT_MARKERS)
        _require_markers("meshapp/frontend/src/product/ProductApp.tsx", product_app, REQUIRED_PRODUCT_UI_MARKERS)
        _require_markers("meshapp/frontend/src/product/api.ts", product_api, REQUIRED_PRODUCT_API_PATHS)
        _require_markers("meshapp/frontend/e2e/first-run-signup-dashboard.spec.ts", product_e2e, REQUIRED_PRODUCT_E2E_MARKERS)
        _require_no_forbidden_terms("scripts/operator_product_e2e.py", product_e2e_script, ["npm", "tail"])
        _require_no_forbidden_terms("meshapp/frontend/e2e/first-run-signup-dashboard.spec.ts", product_e2e, ["npm", "tail"])
        _require_markers("control_plane_server.py", control_plane, REQUIRED_CONTROL_PLANE_PATHS)
        _require_markers(
            "shared/mesh_runtime/operator_identity.py",
            identity,
            [
                "SETTINGS_SCHEMA",
                "verify_captcha",
                "oauth_authorize_url",
                "operator_context_from_session",
                "write_settings_audit",
                "auth_events",
                "auth_provider_evidence",
                "mesh.operator_auth_runtime_evidence.v1",
            ],
        )
        _require_markers("operator product focused tests", tests, REQUIRED_TEST_MARKERS)
        _require_package_wiring(package, product_package)
    except (OSError, json.JSONDecodeError, AssertionError) as exc:
        print(f"Operator product buildout verification failed: {exc}", file=sys.stderr)
        return 1
    print("Operator product buildout verification passed")
    return 0


def _require_files() -> None:
    for path in [
        DOC_PATH,
        PRODUCT_TYPES_PATH,
        PRODUCT_APP_PATH,
        PRODUCT_API_PATH,
        PRODUCT_E2E_PATH,
        PRODUCT_PLAYWRIGHT_CONFIG_PATH,
        PRODUCT_PACKAGE_PATH,
        CONTROL_PLANE_PATH,
        IDENTITY_PATH,
        PRODUCT_CONTRACTS_PATH,
        PRODUCT_SCHEMA_PATH,
        HTTP_TEST_PATH,
        AUTH_PROVIDER_SMOKE_TEST_PATH,
        IDENTITY_TEST_PATH,
        CONFIG_TEST_PATH,
        INGRESS_DEPLOYMENT_TEST_PATH,
        PRODUCT_CONTRACT_TEST_PATH,
        PRODUCT_E2E_SCRIPT_PATH,
        AUTH_PROVIDER_SMOKE_PATH,
        AUTH_PROVIDER_CAPTURE_PATH,
        PRODUCT_GOAL_AUDIT_PATH,
        PRODUCT_CONTRACT_GENERATOR_PATH,
        INGRESS_DOC_PATH,
        PACKAGE_PATH,
    ]:
        if not path.exists():
            raise AssertionError(f"missing required artifact: {path.relative_to(REPO_ROOT)}")


def _require_markers(label: str, text: str, markers: list[str]) -> None:
    missing = [marker for marker in markers if marker not in text]
    if missing:
        raise AssertionError(f"{label} missing markers: {', '.join(missing)}")


def _require_no_forbidden_terms(label: str, text: str, forbidden_terms: list[str]) -> None:
    forbidden = [
        term for term in forbidden_terms
        if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(term)}(?![A-Za-z0-9_-])", text)
    ]
    if forbidden:
        raise AssertionError(f"{label} contains forbidden terms: {', '.join(forbidden)}")


def _require_package_wiring(package: dict[str, object], product_package: dict[str, object]) -> None:
    scripts = package.get("scripts")
    if not isinstance(scripts, dict):
        raise AssertionError("package.json missing scripts object")
    product_scripts = product_package.get("scripts")
    if not isinstance(product_scripts, dict):
        raise AssertionError("meshapp/frontend/package.json missing scripts object")
    verify_contracts = str(scripts.get("verify:contracts") or "")
    verify_full = str(scripts.get("verify:full") or "")
    test_focused = str(scripts.get("test:focused") or "")
    product_e2e = str(scripts.get("test:product:e2e") or "")
    auth_provider_smoke = str(scripts.get("test:auth-provider:smoke") or "")
    auth_provider_live = str(scripts.get("test:auth-provider:live") or "")
    auth_provider_template = str(scripts.get("auth-provider:live-template") or "")
    auth_provider_preflight = str(scripts.get("auth-provider:live-preflight") or "")
    auth_provider_stack_smoke = str(scripts.get("auth-provider:live-stack-smoke") or "")
    auth_provider_reuse_stack_smoke = str(scripts.get("auth-provider:reuse-stack-smoke") or "")
    auth_provider_checkpoint = str(scripts.get("auth-provider:checkpoint") or "")
    auth_provider_attempt = str(scripts.get("auth-provider:live-attempt") or "")
    auth_provider_reuse_attempt = str(scripts.get("auth-provider:reuse-attempt") or "")
    auth_provider_capture = str(scripts.get("auth-provider:live-capture") or "")
    auth_provider_stack = str(scripts.get("auth-provider:live-stack") or "")
    auth_provider_reuse_stack = str(scripts.get("auth-provider:reuse-stack") or "")
    operator_goal = str(scripts.get("verify:operator-goal") or "")
    lint_fast = str(scripts.get("lint:fast") or "")
    meshapp_e2e = str(product_scripts.get("test:e2e") or "")
    if "scripts/verify_operator_product_buildout.py" not in verify_contracts:
        raise AssertionError("verify:contracts must run scripts/verify_operator_product_buildout.py")
    if "scripts/generate_operator_product_contracts.py --check" not in verify_contracts:
        raise AssertionError("verify:contracts must check operator product contracts")
    if "shared/mesh_runtime/schemas/operator-product.schema.json" not in verify_contracts:
        raise AssertionError("verify:contracts must json-check operator product schema")
    if "tests.test_operator_product_contracts" not in test_focused:
        raise AssertionError("test:focused must run operator product contract tests")
    if "tests.test_operator_auth_provider_smoke" not in test_focused:
        raise AssertionError("test:focused must run operator auth provider smoke tests")
    if "tests.test_operator_product_goal_audit" not in test_focused:
        raise AssertionError("test:focused must run operator product goal audit tests")
    if "pnpm --dir meshapp/frontend run test" not in test_focused:
        raise AssertionError("test:focused must run meshapp Vitest")
    if "scripts/operator_product_e2e.py" not in product_e2e:
        raise AssertionError("test:product:e2e must run scripts/operator_product_e2e.py")
    if "scripts/operator_auth_provider_smoke.py" not in auth_provider_smoke:
        raise AssertionError("test:auth-provider:smoke must run scripts/operator_auth_provider_smoke.py")
    if "scripts/operator_auth_provider_smoke.py --require-live" not in auth_provider_live:
        raise AssertionError("test:auth-provider:live must run scripts/operator_auth_provider_smoke.py --require-live")
    if "scripts/operator_auth_provider_smoke.py --print-live-proof-template" not in auth_provider_template:
        raise AssertionError("auth-provider:live-template must print the redacted live proof template")
    if "scripts/operator_auth_live_provider_capture.py --preflight-only" not in auth_provider_preflight:
        raise AssertionError("auth-provider:live-preflight must run preflight-only capture")
    if "scripts/operator_auth_live_provider_capture.py --stack-smoke-only" not in auth_provider_stack_smoke:
        raise AssertionError("auth-provider:live-stack-smoke must run managed local stack smoke")
    if "scripts/operator_auth_live_provider_capture.py --stack-smoke-only --reuse-local-stack" not in auth_provider_reuse_stack_smoke:
        raise AssertionError("auth-provider:reuse-stack-smoke must run explicit reused local stack smoke")
    if "scripts/operator_auth_live_provider_capture.py --checkpoint-only" not in auth_provider_checkpoint:
        raise AssertionError("auth-provider:checkpoint must write the auth checkpoint")
    if "scripts/operator_auth_live_provider_capture.py --manage-local-stack --timeout-seconds 300 --allow-blocked-attempt" not in auth_provider_attempt:
        raise AssertionError("auth-provider:live-attempt must run a bounded managed local stack capture")
    if "scripts/operator_auth_live_provider_capture.py --reuse-local-stack --timeout-seconds 300 --allow-blocked-attempt" not in auth_provider_reuse_attempt:
        raise AssertionError("auth-provider:reuse-attempt must run a bounded explicit reused local stack capture")
    if "scripts/operator_auth_live_provider_capture.py" not in auth_provider_capture:
        raise AssertionError("auth-provider:live-capture must run scripts/operator_auth_live_provider_capture.py")
    if "scripts/operator_auth_live_provider_capture.py --manage-local-stack" not in auth_provider_stack:
        raise AssertionError("auth-provider:live-stack must run managed local stack capture")
    if "scripts/operator_auth_live_provider_capture.py --reuse-local-stack" not in auth_provider_reuse_stack:
        raise AssertionError("auth-provider:reuse-stack must run explicit reused local stack capture")
    if "scripts/operator_product_goal_audit.py" not in operator_goal:
        raise AssertionError("verify:operator-goal must run scripts/operator_product_goal_audit.py")
    if "pnpm run verify:contracts" not in verify_full:
        raise AssertionError("verify:full must include verify:contracts")
    if "pnpm run test:product:e2e" not in verify_full:
        raise AssertionError("verify:full must include product browser e2e")
    if "shared/mesh_runtime/operator_identity.py" not in lint_fast:
        raise AssertionError("lint:fast must py_compile operator identity")
    if "shared/mesh_runtime/operator_product_contracts.py" not in lint_fast:
        raise AssertionError("lint:fast must py_compile operator product contracts")
    if "scripts/operator_product_goal_audit.py" not in lint_fast:
        raise AssertionError("lint:fast must py_compile operator product goal audit")
    if "scripts/operator_auth_live_provider_capture.py" not in lint_fast:
        raise AssertionError("lint:fast must py_compile operator auth live provider capture")
    if "playwright test --config playwright.config.ts" not in meshapp_e2e:
        raise AssertionError("meshapp test:e2e must run the product Playwright config")
    if "npm" in meshapp_e2e or "tail" in meshapp_e2e:
        raise AssertionError("meshapp test:e2e must not use npm or tail")


if __name__ == "__main__":
    raise SystemExit(main())
