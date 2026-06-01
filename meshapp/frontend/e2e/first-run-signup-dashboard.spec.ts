import { expect, test, type Locator, type Page, type TestInfo } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const pageIssues = new WeakMap<Page, string[]>();

test.beforeEach(async ({ page }) => {
  const issues: string[] = [];
  pageIssues.set(page, issues);
  page.on("console", (message) => {
    if ((message.type() === "error" || message.type() === "warning") && !isExpectedBrowserResourceStatus(message.text())) {
      issues.push(`console.${message.type()}: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => {
    issues.push(`pageerror: ${error.message}`);
  });
});

test.afterEach(async ({ page }) => {
  expect(pageIssues.get(page) ?? []).toEqual([]);
});

test("first-run signup creates a team and reaches the product dashboard", async ({ page }, testInfo) => {
  const email = testEmail(testInfo, "operator");
  const teamName = testLabel(testInfo, "E2E Operators");

  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Welcome" })).toBeVisible();
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();

  await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
  await page.getByLabel("Display name").fill("E2E Operator");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-42");
  await page.getByLabel("Confirm password").fill("correct-horse-42");
  await page.getByLabel(/I agree to use only redacted sources/).check();
  await expect(page.getByText("Local captcha bypass is active for development only.")).toBeVisible();
  await page.getByRole("button", { name: "Sign up" }).click();

  await expect(page.getByRole("heading", { name: "Create a team" })).toBeVisible();
  await page.getByLabel("Team name").fill(teamName);
  const dashboardResponse = page.waitForResponse((response) =>
    response.url().includes("/api/operator/dashboard") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Create team" }).click();
  const dashboard = await dashboardResponse;
  const dashboardPayload = await dashboard.json();
  expect(dashboardPayload.authority_boundary).toContain("Dashboard identity scopes the product read model.");

  await expect(page.locator(".partner-home-hero").getByText("Readiness", { exact: true })).toBeVisible();
  await expect(page.getByText(/Next step/)).toBeVisible();
  await expect(page.getByRole("navigation").getByRole("button", { name: "Connectors", exact: true })).toBeVisible();
  await expect(page.getByRole("navigation").getByRole("button", { name: "Evaluations", exact: true })).toBeVisible();
  await expect(page.getByRole("navigation").getByRole("button", { name: "Readiness", exact: true })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("team settings, member invites, provider posture, connector filters, and launch defaults work end to end", async ({ page }, testInfo) => {
  const email = testEmail(testInfo, "integrated");
  const teamName = testLabel(testInfo, "Integrated Product Operators");
  const memberEmail = testEmail(testInfo, "member");

  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Integrated E2E Operator");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-42");
  await page.getByLabel("Confirm password").fill("correct-horse-42");
  await page.getByLabel(/I agree to use only redacted sources/).check();
  await page.getByRole("button", { name: "Sign up" }).click();

  await expect(page.getByRole("heading", { name: "Create a team" })).toBeVisible();
  await page.getByLabel("Team name").fill(teamName);
  await page.getByRole("button", { name: "Create team" }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();

  await page.getByRole("navigation").getByRole("button", { name: "Team Settings" }).click();
  await expect(page.locator(".product-header h1", { hasText: "Team Settings" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await page.getByLabel("Display name").fill("Integrated Product Display");
  await page.getByRole("button", { name: "Save team profile" }).click();
  await expect(page.getByText(/Saved team profile/)).toBeVisible();
  await page.getByLabel("Display name").fill("");
  await page.getByRole("button", { name: "Save team profile" }).click();
  await expect(page.locator(".sidebar-footer").getByText(teamName)).toBeVisible();

  await page.getByRole("navigation").getByRole("button", { name: "Settings", exact: true }).click();
  const defaultScenarioSelect = page.locator(".setting-card", { hasText: "Default Run Scenario" }).locator("select");
  const defaultTargetLockSelect = page.locator(".setting-card", { hasText: "Default Target Lock" }).locator("select");
  await defaultScenarioSelect.selectOption("search_latency_regression");
  await expect(defaultScenarioSelect).toHaveValue("search_latency_regression");
  await defaultTargetLockSelect.selectOption("required");
  await expect(defaultTargetLockSelect).toHaveValue("required");
  await page.getByLabel("Audit reason").fill("e2e settings launch default proof");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByText(/Saved default_evaluation_mode/)).toBeVisible();

  await page.getByRole("navigation").getByRole("button", { name: "Evaluations" }).click();
  const launchRegion = page.getByRole("region", { name: "New Evaluation / Launch Run" });
  await expect(launchRegion.locator("select").first()).toHaveValue("search_latency_regression");
  await expect(launchRegion.getByLabel("Require target lock")).toBeChecked();
  await expect(launchRegion.getByText("meshapp.run-preflight.v1")).toBeVisible();
  const preflightRegion = launchRegion.getByRole("region", { name: "Run preflight" });
  await expect(preflightRegion.getByText("Operator", { exact: true })).toBeVisible();
  await expect(preflightRegion.getByText("Topology", { exact: true })).toBeVisible();
  await expect(preflightRegion.getByText("Target", { exact: true })).toBeVisible();
  await expect(preflightRegion.getByText(/Connector scopes:/)).toBeVisible();
  await launchRegion.getByLabel("Audit reason").fill("e2e launch uses saved defaults");
  await launchRegion.getByRole("button", { name: "Launch run" }).click();
  await expect(launchRegion.getByText("Mesh admitted this run.")).toBeVisible();
  await expect(launchRegion.getByText("mesh.run_admission.v1")).toBeVisible();
  const admittedRunId = await runIdFromRegion(launchRegion);
  await expect(page.locator(".data-table").getByText(admittedRunId)).toBeVisible();
  const proofRegion = page.getByRole("region", { name: "Proof packet and evidence views" });
  await proofRegion.getByRole("button", { name: "Load proof views" }).click();
  await expect(proofRegion.getByText("meshapp.run-workbench.v1")).toBeVisible();
  await expect(proofRegion.getByText("timelineProof", { exact: true })).toBeVisible();
  await expect(proofRegion.getByText("exportPackage", { exact: true })).toBeVisible();
  await expect(proofRegion.getByText("Agent mesh", { exact: true })).toBeVisible();

  await cancelRunThroughMesh(page, admittedRunId);

  await page.getByRole("navigation").getByRole("button", { name: "Members" }).click();
  await page.getByLabel("Emails").fill(memberEmail);
  await page.locator(".member-config-grid select").selectOption("approver");
  await page.getByRole("button", { name: "Save members" }).click();
  await expect(page.getByText(memberEmail)).toBeVisible();
  await expect(page.locator(".data-table.compact")).toContainText("approver");

  await page.getByRole("navigation").getByRole("button", { name: "Keys & Secrets" }).click();
  await expect(page.locator("code", { hasText: "MESH_GOOGLE_OAUTH_CLIENT_ID" })).toBeVisible();
  await expect(page.locator("code", { hasText: "MESH_CAPTCHA_SECRET_KEY" })).toBeVisible();
  await expect(page.locator("code", { hasText: "MESH_AUTH_INVITE_ALLOWLIST" })).toBeVisible();

  await page.getByRole("navigation").getByRole("button", { name: "Connectors", exact: true }).click();
  await page.getByPlaceholder("Filter connectors by name, status, domain, blocker...").fill("codex");
  await expect(page.locator(".environment-card h4", { hasText: "codex" })).toBeVisible();
  await expect(page.locator(".environment-card h4", { hasText: "hermes" })).toHaveCount(0);
});

test("product dashboard opens migrated console workflows in place", async ({ page }, testInfo) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Console E2E Operator");
  await page.getByLabel("Email address").fill(testEmail(testInfo, "console"));
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-42");
  await page.getByLabel("Confirm password").fill("correct-horse-42");
  await page.getByLabel(/I agree to use only redacted sources/).check();
  await page.getByRole("button", { name: "Sign up" }).click();
  await expect(page.getByRole("heading", { name: "Create a team" })).toBeVisible();
  await page.getByRole("button", { name: "Continue solo" }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();

  await page.locator(".product-sidebar nav").getByRole("button", { name: "Advanced Console", exact: true }).click();
  await page.locator(".product-sidebar nav").getByRole("button", { name: "Hermes", exact: true }).click();
  await expect(page.locator(".product-header h1", { hasText: "Hermes" })).toBeVisible();
  await expect(page.locator(".console-workspace-toolbar").getByText("Hermes chat, explanation, advisory context")).toBeVisible();
  await expect(page.locator(".console-workspace .mesh-session-rail")).toBeHidden();
  await expect(page.getByText("Hermes Status")).toBeVisible();

  await page.locator(".product-sidebar nav").getByRole("button", { name: "Evidence Runs" }).click();
  await expect(page.locator(".console-workspace-toolbar").getByText("Run timeline, delivery context, evidence graph")).toBeVisible();
  await expect(page.getByTestId("mesh-view-runs")).toBeVisible();
  await expect(page.getByRole("button", { name: "Delivery" })).toBeVisible();
});

test("product-native pages expose runtime read models without legacy shortcuts", async ({ page }, testInfo) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Product Native E2E Operator");
  await page.getByLabel("Email address").fill(testEmail(testInfo, "product-native"));
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-42");
  await page.getByLabel("Confirm password").fill("correct-horse-42");
  await page.getByLabel(/I agree to use only redacted sources/).check();
  await page.getByRole("button", { name: "Sign up" }).click();
  await expect(page.getByRole("heading", { name: "Create a team" })).toBeVisible();
  await page.getByRole("button", { name: "Continue solo" }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();

  const productPages = [
    { nav: "Topology", heading: "Topology", cards: ["Orchestration topology", "Runtime graph"] },
    { nav: "Memory Projection", heading: "Memory Projection", cards: ["Memory graph", "Active memory"] },
    { nav: "Readiness", heading: "Readiness", cards: ["Runtime readiness", "Watchers"] },
    { nav: "Kill Switch", heading: "Kill Switch", cards: ["Kill switch", "Pilot go/no-go"] },
    { nav: "Policy State", heading: "Policy State", cards: ["Approval queue", "Trust ladder"] },
    { nav: "Keys & Secrets", heading: "Keys & Secrets", cards: ["Auth mode", "Deployment-owned variables"] },
  ];

  for (const pageSpec of productPages) {
    await page.getByRole("navigation").getByRole("button", { name: pageSpec.nav, exact: true }).click();
    await expect(page.locator(".product-header h1", { hasText: pageSpec.heading })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    for (const card of pageSpec.cards) {
      await expect(page.getByText(card, { exact: true }).first()).toBeVisible();
    }
  }

  await page.getByRole("navigation").getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.locator(".product-header h1", { hasText: "Settings" })).toBeVisible();
  await expect(page.getByText("Default Evaluation Mode")).toBeVisible();
  await expect(page.getByLabel("Audit reason")).toBeVisible();

  await page.getByRole("navigation").getByRole("button", { name: "Team Settings", exact: true }).click();
  await expect(page.locator(".product-header h1", { hasText: "Team Settings" })).toBeVisible();
  await expect(page.locator(".product-header .breadcrumb-row", { hasText: "Solo dashboard" })).toBeVisible();

  await page.getByRole("navigation").getByRole("button", { name: "Evaluations", exact: true }).click();
  await expect(page.getByRole("region", { name: "New Evaluation / Launch Run" })).toBeVisible();
  await expect(page.getByText("Approval queue", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Proof packet and evidence views" }).getByText(/Evidence graph \/ proof packet/)).toBeVisible();
});

test("agent flow calls Mesh endpoints and keeps mutation preview draft-only", async ({ page }, testInfo) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Agent Flow E2E Operator");
  await page.getByLabel("Email address").fill(testEmail(testInfo, "agent-flow"));
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-42");
  await page.getByLabel("Confirm password").fill("correct-horse-42");
  await page.getByLabel(/I agree to use only redacted sources/).check();
  await page.getByRole("button", { name: "Sign up" }).click();
  await expect(page.getByRole("heading", { name: "Create a team" })).toBeVisible();
  await page.getByRole("button", { name: "Continue solo" }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();

  const livekitResponse = page.waitForResponse((response) =>
    response.url().includes("/api/operator/agent-flow/livekit-session") && response.status() === 200,
  );
  await page.getByRole("navigation").getByRole("button", { name: "Agent Flow" }).click();
  await livekitResponse;
  await expect(page.getByRole("heading", { name: "Agent Flow", exact: true })).toBeVisible();
  await expect(page.getByText("Draft-first composer")).toBeVisible();
  await expectNoHorizontalOverflow(page);

  const chatResponse = page.waitForResponse((response) =>
    response.url().includes("/api/operator/agent-flow/chat") && response.status() === 200,
  );
  await page.getByPlaceholder("Ask Harper to inspect blockers, evidence, approvals, or lifecycle state...").fill("Inspect blockers and draft a launch");
  await page.keyboard.press("Enter");
  await chatResponse;

  await expect(page.locator(".agent-flow-response-meta code", { hasText: "mesh.agent_flow.chat_response.v1" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Agent Flow mutation preview" })).toContainText("side_effects_executed=false");
  await expect(page.getByRole("region", { name: "Agent Flow mutation preview" })).toContainText("mesh.run_admission.v1");
  await expect(page.getByRole("region", { name: "Agent Flow mutation preview" }).getByText("Mutation preview", { exact: true })).toBeVisible();

  await expect(page.getByRole("button", { name: "Confirm draft" })).toBeDisabled();
  await page.getByLabel("Confirmation reason").fill("e2e confirms draft only");
  const confirmResponse = page.waitForResponse((response) =>
    response.url().includes("/api/operator/agent-flow/confirm-preview") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Confirm draft" }).click();
  await confirmResponse;
  await expect(page.locator(".agent-flow-confirmation").getByText("confirmation recorded")).toBeVisible();
  await expect(page.locator(".agent-flow-confirmation").getByText("side_effects_executed=false")).toBeVisible();
});

test("product Praxis import generates, dry-runs, audits, exports P10 proof, and revokes", async ({ page }, testInfo) => {
  const teamName = testLabel(testInfo, "Praxis E2E Operators");

  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Praxis E2E Operator");
  await page.getByLabel("Email address").fill(testEmail(testInfo, "praxis"));
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-42");
  await page.getByLabel("Confirm password").fill("correct-horse-42");
  await page.getByLabel(/I agree to use only redacted sources/).check();
  await page.getByRole("button", { name: "Sign up" }).click();

  await expect(page.getByRole("heading", { name: "Create a team" })).toBeVisible();
  await page.getByLabel("Team name").fill(teamName);
  await page.getByRole("button", { name: "Create team" }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();

  await page.getByRole("navigation").getByRole("button", { name: "Praxis" }).click();
  await expect(page.getByRole("heading", { name: "Praxis MCP Generator" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  const sourceImport = page.getByRole("region", { name: "Praxis source import" });
  await page.getByLabel("OpenAPI file").setInputFiles(praxisFixture("demo-openapi.redacted.json"));
  await page.getByLabel("Postman file").setInputFiles(praxisFixture("demo-postman.redacted.json"));
  await page.getByLabel("SOP Markdown file").setInputFiles(praxisFixture("demo-sop.redacted.md"));
  await page.getByLabel("Traffic refs file").setInputFiles(praxisFixture("demo-traffic-ref.redacted.json"));
  await page.getByLabel("Akto evidence file").setInputFiles(praxisFixture("demo-akto-results.json"));

  await sourceImport.getByRole("button", { name: "Generate Praxis contract" }).click();
  await expect(page.getByText(/Generated Praxis request/)).toBeVisible();
  await expect(page.getByText(/candidate .* blocker\(s\)/).first()).toBeVisible();

  await sourceImport.getByRole("button", { name: "Import" }).click();
  await expect(page.getByText(/Imported Akto evidence/)).toBeVisible();

  await sourceImport.getByRole("button", { name: "Certify" }).click();
  await expect(page.getByText(/Built certification binding/)).toBeVisible();
  await expect(sourceImport.getByRole("button", { name: "Start dry run", exact: true })).toBeVisible();

  await sourceImport.getByRole("button", { name: "Start dry run", exact: true }).click();
  await expect(page.getByText(/Started dry-run MCP endpoint/)).toBeVisible();

  await sourceImport.getByRole("button", { name: "Call read-only tool" }).click();
  await expect(page.getByText(/MCP tool call audited/)).toBeVisible();

  await sourceImport.getByRole("button", { name: "Revoke connector", exact: true }).click();
  await expect(page.getByText(/Revoked generated connector/)).toBeVisible();

  await sourceImport.getByRole("button", { name: "Export" }).click();
  await expect(page.getByText(/Exported P10 proof packet .* complete/)).toBeVisible();
  await expect(page.getByRole("region", { name: "Praxis generator workbench" })).toContainText("Managed runtime deployed: no");
  await expect(page.getByRole("button", { name: /Deploy managed pilot runtime/ })).toBeDisabled();
});

test("Build Arena generates review packets and intent bundles without deployment authority", async ({ page }, testInfo) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Arena E2E Operator");
  await page.getByLabel("Email address").fill(testEmail(testInfo, "arena"));
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-42");
  await page.getByLabel("Confirm password").fill("correct-horse-42");
  await page.getByLabel(/I agree to use only redacted sources/).check();
  await page.getByRole("button", { name: "Sign up" }).click();
  await expect(page.getByRole("heading", { name: "Create a team" })).toBeVisible();
  await page.getByRole("button", { name: "Continue solo" }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();

  await page.getByRole("navigation").getByRole("button", { name: "Build Arena" }).click();
  await expect(page.getByRole("heading", { name: "Build Arena" })).toBeVisible();
  await expectNoHorizontalOverflow(page);

  const packetResponse = page.waitForResponse((response) =>
    response.url().includes("/api/hardened-arena/packets") && response.status() === 201,
  );
  await page.getByRole("button", { name: "Generate packet" }).click();
  const packetPayload = await (await packetResponse).json();
  expect(packetPayload.live_deployment_allowed).toBe(false);
  expect(packetPayload.secret_ingestion_allowed).toBe(false);
  await expect(page.getByText("Export / review packet")).toBeVisible();
  await expect(page.getByText("Live deployment allowed").first()).toBeVisible();
  await expect(page.getByText("Secret ingestion allowed").first()).toBeVisible();
  await expect(page.getByText(/target_validated remains false/)).toBeVisible();

  const intentResponse = page.waitForResponse((response) =>
    response.url().includes("/api/hardened-arena/intents") && response.status() === 201,
  );
  await page.getByRole("button", { name: "Prepare intent" }).click();
  const intentPayload = await (await intentResponse).json();
  expect(intentPayload.live_deployment_allowed).toBe(false);
  expect(intentPayload.secret_ingestion_allowed).toBe(false);
  expect(intentPayload.kubeconfig_material_present).toBe(false);
  await expect(page.getByText("Intent review bundle")).toBeVisible();
  await expect(page.getByText("Kubeconfig material present")).toBeVisible();
  await expect(page.getByText(/mesh.hardened_arena.intent.v1/)).toBeVisible();
});

test("first-run signup can continue solo from a clean browser session", async ({ page }, testInfo) => {
  const email = testEmail(testInfo, "solo");
  const teamName = testLabel(testInfo, "Solo Upgrade Operators");
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Solo E2E Operator");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-42");
  await page.getByLabel("Confirm password").fill("correct-horse-42");
  await page.getByLabel(/I agree to use only redacted sources/).check();
  await expect(page.getByText("Local captcha bypass is active for development only.")).toBeVisible();
  await page.getByRole("button", { name: "Sign up" }).click();

  await expect(page.getByRole("heading", { name: "Create a team" })).toBeVisible();
  const dashboardResponse = page.waitForResponse((response) =>
    response.url().includes("/api/operator/dashboard") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Continue solo" }).click();
  await dashboardResponse;

  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();
  await expect(page.getByText(email)).toBeVisible();
  await expect(page.getByRole("button", { name: "Open Advanced Console" })).toBeVisible();

  await page.getByRole("navigation").getByRole("button", { name: "Team Settings" }).click();
  await expect(page.locator(".product-header h1", { hasText: "Team Settings" })).toBeVisible();
  await page.getByLabel("Team name").fill(teamName);
  await page.getByRole("button", { name: "Create team", exact: true }).click();
  await expect(page.locator(".sidebar-footer").getByText(teamName)).toBeVisible();

  await page.getByRole("navigation").getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.locator(".product-header h1", { hasText: "Settings" })).toBeVisible();
  await expect(page.getByText("Default Evaluation Mode")).toBeVisible();
});

test("login returns an existing operator to the dashboard", async ({ page }, testInfo) => {
  const email = testEmail(testInfo, "login");
  const password = "correct-horse-42";

  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Login E2E Operator");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Confirm password").fill(password);
  await page.getByLabel(/I agree to use only redacted sources/).check();
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.getByRole("button", { name: "Continue solo" }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("heading", { name: "Welcome" })).toBeVisible();

  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();
  await expect(page.getByText(email)).toBeVisible();
});

test("logout returns a clean browser session to sign-in", async ({ page }, testInfo) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Logout E2E Operator");
  await page.getByLabel("Email address").fill(testEmail(testInfo, "logout"));
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-42");
  await page.getByLabel("Confirm password").fill("correct-horse-42");
  await page.getByLabel(/I agree to use only redacted sources/).check();
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.getByRole("button", { name: "Continue solo" }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("heading", { name: "Welcome" })).toBeVisible();
  await expect
    .poll(async () => (await page.context().cookies()).some((cookie) => cookie.name === "mesh_session"))
    .toBe(false);
});

test("operator setup saves governed preferences with audit reason", async ({ page }, testInfo) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Setup E2E Operator");
  await page.getByLabel("Email address").fill(testEmail(testInfo, "setup"));
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-42");
  await page.getByLabel("Confirm password").fill("correct-horse-42");
  await page.getByLabel(/I agree to use only redacted sources/).check();
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.getByRole("button", { name: "Continue solo" }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();

  await page.getByRole("navigation").getByRole("button", { name: "Operator Setup", exact: true }).click();
  await expect(page.locator(".product-header h1", { hasText: "Operator Setup" })).toBeVisible();
  await page.getByPlaceholder("why this operator setup change is required").fill("e2e operator setup proof");
  await page.getByRole("button", { name: "Save setup" }).first().click();
  await expect(page.getByText(/^Saved /)).toBeVisible();
});

test("expired session clears cookie and recovers through login", async ({ page }, testInfo) => {
  const email = testEmail(testInfo, "expired-browser");
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Expired E2E Operator");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-42");
  await page.getByLabel("Confirm password").fill("correct-horse-42");
  await page.getByLabel(/I agree to use only redacted sources/).check();
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.getByRole("button", { name: "Continue solo" }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();

  expireSessionsForEmail(email);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Welcome" })).toBeVisible();
  await expect
    .poll(async () => (await page.context().cookies()).some((cookie) => cookie.name === "mesh_session"))
    .toBe(false);

  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password").fill("correct-horse-42");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();
  await expect(page.getByText(email)).toBeVisible();
});

function expireSessionsForEmail(email: string) {
  const identityPath = process.env.MESH_OPERATOR_IDENTITY_PATH;
  if (!identityPath) throw new Error("MESH_OPERATOR_IDENTITY_PATH is required for session-expiry proof");
  const data = JSON.parse(readFileSync(identityPath, "utf-8"));
  const userIds = new Set(
    Object.entries((data.users || {}) as Record<string, { email?: string }>)
      .filter(([, user]) => user.email === email)
      .map(([userId]) => userId),
  );
  for (const record of Object.values(data.sessions || {}) as Array<Record<string, unknown>>) {
    if (userIds.has(String(record.user_id))) {
      record.expires_at = "2000-01-01T00:00:00Z";
    }
  }
  writeFileSync(identityPath, `${JSON.stringify(data, null, 2)}\n`);
}

function praxisFixture(name: string) {
  return resolve(__dirname, "../../../fixtures/praxis", name);
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => {
    const root = document.scrollingElement ?? document.documentElement;
    return Math.max(0, root.scrollWidth - window.innerWidth);
  });
  expect(overflow).toBeLessThanOrEqual(1);
}

function testEmail(testInfo: TestInfo, prefix: string) {
  return `${slug([prefix, testInfo.project.name, String(testInfo.workerIndex), String(Date.now())])}@example.com`;
}

function testLabel(testInfo: TestInfo, label: string) {
  return `${label} ${slug([testInfo.project.name, String(testInfo.workerIndex), String(Date.now())])}`;
}

function slug(parts: string[]) {
  return parts.join("-").replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase();
}

function isExpectedBrowserResourceStatus(text: string) {
  return /^Failed to load resource: the server responded with a status of (401|404) \((Unauthorized|Not Found)\)$/.test(text);
}

async function runIdFromRegion(region: Locator) {
  const text = await region.textContent();
  const match = text?.match(/run_\d{8}T\d{6}_[a-f0-9]+/);
  if (!match) throw new Error("admitted run id not found");
  return match[0];
}

async function cancelRunThroughMesh(page: Page, runId: string) {
  const apiUrl = process.env.MESH_PRODUCT_E2E_API_URL;
  if (!apiUrl) throw new Error("MESH_PRODUCT_E2E_API_URL is required for run cleanup");
  await page.evaluate(
    async ({ apiUrl, runId }) => {
      const response = await fetch(`${apiUrl}/api/runs/${encodeURIComponent(runId)}/steer`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: "cancel", reason: "e2e releases target lock" }),
      });
      if (!response.ok) {
        throw new Error(`run cleanup failed: ${response.status} ${await response.text()}`);
      }
    },
    { apiUrl, runId },
  );
}
