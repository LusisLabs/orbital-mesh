import { expect, test } from "@playwright/test";

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
  await expect(page.getByRole("button", { name: "Environments Hub" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Evaluations" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Runtime readiness ready/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Orchestration topology Read-only:/ })).toBeVisible();
});
