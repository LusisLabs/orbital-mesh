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
  await page.getByLabel("Password").fill("correct-horse-42");
  await expect(page.getByText("Local captcha bypass is active for development only.")).toBeVisible();
  await page.getByRole("button", { name: "Sign up" }).click();

  await expect(page.getByRole("heading", { name: "Create a team" })).toBeVisible();
  await page.getByLabel("Team name").fill("E2E Operators");
  const dashboardResponse = page.waitForResponse((response) =>
    response.url().includes("/api/operator/dashboard") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Create team" }).click();
  await dashboardResponse;

  await expect(page.getByText("Dashboard identity scopes the product read model.")).toBeVisible();
  await expect(page.getByText("Mesh remains the authority for policy, approvals, run state, readiness, evidence, and actuation.")).toBeVisible();
  await expect(page.getByRole("navigation").getByRole("button", { name: "Connector Status", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Evaluations" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Runtime readiness ready/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Orchestration topology ready/ })).toBeVisible();
});

test("product dashboard opens migrated console workflows in place", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Console E2E Operator");
  await page.getByLabel("Email address").fill(`console-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("correct-horse-42");
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.getByRole("button", { name: "Continue solo" }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();

  await page.locator(".product-sidebar nav").getByRole("button", { name: "Hermes" }).click();
  await expect(page.getByRole("heading", { name: "Control Console" })).toBeVisible();
  await expect(page.getByText("Hermes chat, explanation, advisory context")).toBeVisible();
  await expect(page.locator(".console-workspace .mesh-session-rail")).toBeHidden();
  await expect(page.getByText("Hermes Status")).toBeVisible();

  await page.locator(".product-sidebar nav").getByRole("button", { name: "Evidence Runs" }).click();
  await expect(page.getByText("Run timeline, delivery context, evidence graph")).toBeVisible();
  await expect(page.getByTestId("mesh-view-runs")).toBeVisible();
  await expect(page.getByRole("button", { name: "Delivery" })).toBeVisible();
});

test("product Praxis import generates, dry-runs, audits, exports P10 proof, and revokes", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Praxis E2E Operator");
  await page.getByLabel("Email address").fill(`praxis-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("correct-horse-42");
  await page.getByRole("button", { name: "Sign up" }).click();

  await expect(page.getByRole("heading", { name: "Create a team" })).toBeVisible();
  await page.getByLabel("Team name").fill("Praxis E2E Operators");
  await page.getByRole("button", { name: "Create team" }).click();
  await expect(page.getByRole("heading", { name: "Praxis E2E Operators" })).toBeVisible();

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

  await sourceImport.getByRole("button", { name: "Import Akto evidence" }).click();
  await expect(page.getByText(/Imported Akto evidence/)).toBeVisible();

  await sourceImport.getByRole("button", { name: "Build certification binding" }).click();
  await expect(page.getByText(/Built certification binding/)).toBeVisible();
  await expect(page.getByRole("button", { name: /Start dry-run MCP endpoint ready/ })).toBeVisible();

  await sourceImport.getByRole("button", { name: "Start dry-run MCP endpoint", exact: true }).click();
  await expect(page.getByText(/Started dry-run MCP endpoint/)).toBeVisible();

  await sourceImport.getByRole("button", { name: "Call read-only MCP tool" }).click();
  await expect(page.getByText(/MCP tool call audited/)).toBeVisible();

  await sourceImport.getByRole("button", { name: "Revoke generated connector", exact: true }).click();
  await expect(page.getByText(/Revoked generated connector/)).toBeVisible();

  await sourceImport.getByRole("button", { name: "Export P10 proof" }).click();
  await expect(page.getByText(/Exported P10 proof packet .* complete/)).toBeVisible();
});

test("first-run signup can continue solo from a clean browser session", async ({ page }) => {
  const email = `solo-${Date.now()}@example.com`;
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Solo E2E Operator");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password").fill("correct-horse-42");
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
  await expect(page.getByRole("button", { name: /Settings parity ready/ })).toBeVisible();
});

test("logout returns a clean browser session to sign-in", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Logout E2E Operator");
  await page.getByLabel("Email address").fill(`logout-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("correct-horse-42");
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.getByRole("button", { name: "Continue solo" }).click();
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();

  await page.getByTitle("Log out").click();
  await expect(page.getByRole("heading", { name: "Welcome" })).toBeVisible();
  await expect
    .poll(async () => (await page.context().cookies()).some((cookie) => cookie.name === "mesh_session"))
    .toBe(false);
});

test("expired session clears cookie and recovers through login", async ({ page }) => {
  const email = `expired-browser-${Date.now()}@example.com`;
  await page.goto("/");
  await page.getByRole("button", { name: "Need an account? Sign up" }).click();
  await page.getByLabel("Display name").fill("Expired E2E Operator");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password").fill("correct-horse-42");
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
