import { expect, test } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

test("first-run signup creates a team and reaches the product dashboard", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Welcome" })).toBeVisible();
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();

  await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
  await page.getByLabel("Display name").fill("E2E Operator");
  await page.getByLabel("Email address").fill(`operator-${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-42");
  await page.getByLabel("Confirm password").fill("correct-horse-42");
  await page.getByLabel(/I agree to use only redacted sources/).check();
  await expect(page.getByText("Local captcha bypass is active for development only.")).toBeVisible();
  await page.getByRole("button", { name: "Sign up" }).click();

  await expect(page.getByRole("heading", { name: "Create a team" })).toBeVisible();
  await page.getByLabel("Team name").fill("E2E Operators");
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
});

test("team settings, member invites, provider posture, connector filters, and launch defaults work end to end", async ({ page }) => {
  const stamp = Date.now();
  const email = `integrated-${stamp}@example.com`;
  const teamName = `Integrated Product Operators ${stamp}`;
  const memberEmail = `member-${stamp}@example.com`;

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
  await page.getByLabel("Display name").fill("Integrated Product Display");
  await page.getByRole("button", { name: "Save team profile" }).click();
  await expect(page.getByText(/Saved team profile/)).toBeVisible();
  await page.getByLabel("Display name").fill("");
  await page.getByRole("button", { name: "Save team profile" }).click();
  await expect(page.locator(".sidebar-footer").getByText(teamName)).toBeVisible();

  await page.getByRole("navigation").getByRole("button", { name: "Settings", exact: true }).click();
  await page.locator(".setting-card", { hasText: "Default Run Scenario" }).locator("select").selectOption("search_latency_regression");
  await page.locator(".setting-card", { hasText: "Default Target Lock" }).locator("select").selectOption("required");
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
  await expect(page.locator(".data-table").getByText("search_latency_regression")).toBeVisible();
  const proofRegion = page.getByRole("region", { name: "Proof packet and evidence views" });
  await proofRegion.getByRole("button", { name: "Load proof views" }).click();
  await expect(proofRegion.getByText("meshapp.run-workbench.v1")).toBeVisible();
  await expect(proofRegion.getByText("timelineProof", { exact: true })).toBeVisible();
  await expect(proofRegion.getByText("exportPackage", { exact: true })).toBeVisible();
  await expect(proofRegion.getByText("Agent mesh", { exact: true })).toBeVisible();

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

test("product dashboard opens migrated console workflows in place", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Console E2E Operator");
  await page.getByLabel("Email address").fill(`console-${Date.now()}@example.com`);
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

test("product-native pages expose runtime read models without legacy shortcuts", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Product Native E2E Operator");
  await page.getByLabel("Email address").fill(`product-native-${Date.now()}@example.com`);
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

test("agent flow calls Mesh endpoints and keeps mutation preview draft-only", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Agent Flow E2E Operator");
  await page.getByLabel("Email address").fill(`agent-flow-${Date.now()}@example.com`);
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

test("product Praxis import generates, dry-runs, audits, exports P10 proof, and revokes", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Praxis E2E Operator");
  await page.getByLabel("Email address").fill(`praxis-${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-42");
  await page.getByLabel("Confirm password").fill("correct-horse-42");
  await page.getByLabel(/I agree to use only redacted sources/).check();
  await page.getByRole("button", { name: "Sign up" }).click();

  await expect(page.getByRole("heading", { name: "Create a team" })).toBeVisible();
  await page.getByLabel("Team name").fill("Praxis E2E Operators");
  await page.getByRole("button", { name: "Create team" }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();

  await page.getByRole("navigation").getByRole("button", { name: "Praxis" }).click();
  await expect(page.getByRole("heading", { name: "Praxis MCP Generator" })).toBeVisible();
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
});

test("first-run signup can continue solo from a clean browser session", async ({ page }) => {
  const email = `solo-${Date.now()}@example.com`;
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
  await page.getByLabel("Team name").fill("Solo Upgrade Operators");
  await page.getByRole("button", { name: "Create team", exact: true }).click();
  await expect(page.locator(".sidebar-footer").getByText("Solo Upgrade Operators")).toBeVisible();

  await page.getByRole("navigation").getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.locator(".product-header h1", { hasText: "Settings" })).toBeVisible();
  await expect(page.getByText("Default Evaluation Mode")).toBeVisible();
});

test("login returns an existing operator to the dashboard", async ({ page }) => {
  const email = `login-${Date.now()}@example.com`;
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

  await page.getByTitle("Log out").click();
  await expect(page.getByRole("heading", { name: "Welcome" })).toBeVisible();

  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();
  await expect(page.getByText(email)).toBeVisible();
});

test("logout returns a clean browser session to sign-in", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Logout E2E Operator");
  await page.getByLabel("Email address").fill(`logout-${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-42");
  await page.getByLabel("Confirm password").fill("correct-horse-42");
  await page.getByLabel(/I agree to use only redacted sources/).check();
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.getByRole("button", { name: "Continue solo" }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();

  await page.getByTitle("Log out").click();
  await expect(page.getByRole("heading", { name: "Welcome" })).toBeVisible();
  await expect
    .poll(async () => (await page.context().cookies()).some((cookie) => cookie.name === "mesh_session"))
    .toBe(false);
});

test("build arena loads profiles and generates a review packet", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Arena E2E Operator");
  await page.getByLabel("Email address").fill(`arena-${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-42");
  await page.getByLabel("Confirm password").fill("correct-horse-42");
  await page.getByLabel(/I agree to use only redacted sources/).check();
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.getByRole("button", { name: "Continue solo" }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();

  await page.getByRole("navigation").getByRole("button", { name: "Build Arena" }).click();
  await expect(page.locator(".product-header h1", { hasText: "Build Arena" })).toBeVisible();
  await expect(page.getByText("Profile registry")).toBeVisible();
  await page.getByRole("button", { name: "Generate packet" }).click();
  await expect(page.getByText(/Export \/ review packet/)).toBeVisible();
  await expect(page.getByText(/stored for review/i)).toBeVisible();
});

test("operator setup saves governed preferences with audit reason", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Setup E2E Operator");
  await page.getByLabel("Email address").fill(`setup-${Date.now()}@example.com`);
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

test("expired session clears cookie and recovers through login", async ({ page }) => {
  const email = `expired-browser-${Date.now()}@example.com`;
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

  expireSessions();
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

function expireSessions() {
  const identityPath = process.env.MESH_OPERATOR_IDENTITY_PATH;
  if (!identityPath) throw new Error("MESH_OPERATOR_IDENTITY_PATH is required for session-expiry proof");
  const data = JSON.parse(readFileSync(identityPath, "utf-8"));
  for (const record of Object.values(data.sessions || {}) as Array<Record<string, unknown>>) {
    record.expires_at = "2000-01-01T00:00:00Z";
  }
  writeFileSync(identityPath, `${JSON.stringify(data, null, 2)}\n`);
}

function praxisFixture(name: string) {
  return resolve(__dirname, "../../../fixtures/praxis", name);
}
