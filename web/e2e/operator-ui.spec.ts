import { expect, type Page, test } from "@playwright/test";

function targetUrl(): string {
  const target = process.env.MESH_E2E_BASE_URL;
  expect(target, "MESH_E2E_BASE_URL must be set by scripts/e2e_ui_operator.sh").toBeTruthy();
  return target!;
}

async function openFixture(page: Page) {
  await page.goto(targetUrl());
  await expect(page.getByRole("heading", { name: "Purna Console" })).toBeVisible();
  await expect(page.getByText("Connection Failed")).toHaveCount(0);
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflowing = await page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    return Array.from(document.querySelectorAll("body *")).filter((el) => {
      if (el.closest(".react-flow")) return false;
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return false;
      return rect.left < -2 || rect.right > width + 2;
    }).slice(0, 5).map((el) => ({
      tag: el.tagName,
      className: String((el as HTMLElement).className),
      text: (el.textContent ?? "").slice(0, 80),
    }));
  });
  expect(overflowing).toEqual([]);
}

test("applies the Purna Labs Nebula kit end to end", async ({ page }) => {
  await openFixture(page);

  await expect(page.getByText("Purna Labs OS")).toBeVisible();
  await expect(page.getByText("Purna Labs desktop")).toBeVisible();
  await expect(page.getByText(/Lusis/i)).toHaveCount(0);

  const tokens = await page.evaluate(() => {
    const styles = getComputedStyle(document.documentElement);
    const activeNav = document.querySelector(".mesh-nav-item.active");
    const primaryAction = document.querySelector(".action-button.primary");

    return {
      accent: styles.getPropertyValue("--accent").trim(),
      bg: styles.getPropertyValue("--bg").trim(),
      good: styles.getPropertyValue("--accent-good").trim(),
      meshBlue: styles.getPropertyValue("--mesh-blue").trim(),
      meshPurple: styles.getPropertyValue("--mesh-purple").trim(),
      navAccent: activeNav ? getComputedStyle(activeNav).boxShadow : "",
      primaryBorder: primaryAction ? getComputedStyle(primaryAction).borderColor : "",
    };
  });

  expect(tokens).toMatchObject({
    accent: "#3e79bd",
    bg: "#0b1020",
    good: "#20a77c",
    meshBlue: "#3e79bd",
    meshPurple: "#6d33ab",
  });
  expect(tokens.navAccent).toContain("62, 121, 189");
  expect(tokens.primaryBorder).toBe("rgba(62, 121, 189, 0.52)");
});

test("loads the Purna console with overview as the default page", async ({ page }) => {
  await openFixture(page);

  await expect(page.getByRole("heading", { name: "Purna Console" })).toBeVisible();
  await expect(page.getByTestId("mesh-view-overview")).toBeVisible();
  await expect(page.getByTestId("mesh-primary-nav").getByRole("button", { name: "Overview" })).toHaveClass(/active/);
  await expect(page.locator(".react-flow")).toHaveCount(0);
  await expect(page.getByText("Labyrinth")).toHaveCount(0);
  await expect(page.getByText("Journey Index")).toHaveCount(0);
  await expect(page.getByText("Guideposts")).toHaveCount(0);
  await expect(page.getByText("Run Sessions")).toHaveCount(0);
});

test("exposes secondary control-plane, Hermes, agents, and integrations pages", async ({ page }) => {
  await openFixture(page);

  const nav = page.getByTestId("mesh-primary-nav");
  await nav.getByRole("button", { name: "Control Plane" }).click();
  await expect(page.getByTestId("mesh-view-control-plane")).toBeVisible();
  await expect(page.getByText("Control plane diagnostics")).toBeVisible();

  await nav.getByRole("button", { name: "Hermes" }).click();
  await expect(page.getByTestId("mesh-view-hermes")).toBeVisible();
  await expect(page.getByText("Hermes Status")).toBeVisible();

  await nav.getByRole("button", { name: "Agents" }).click();
  await expect(page.getByTestId("agents-grid")).toBeVisible();
  await expect(page.getByText("Hermes").first()).toBeVisible();
  await expect(page.getByText("Goose").first()).toBeVisible();
  await expect(page.getByText("Custom HTTP Agent")).toBeVisible();

  await nav.getByRole("button", { name: "Integrations" }).click();
  await expect(page.getByTestId("integrations-grid")).toBeVisible();
  await expect(page.getByText("Web3")).toBeVisible();
  await expect(page.getByText("Web2 Production")).toBeVisible();
  await expect(page.getByText("Development")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Operations" })).toBeVisible();
});

test("keeps run detail topology secondary while preserving canvas modes", async ({ page }) => {
  await openFixture(page);

  await page.getByTestId("mesh-primary-nav").getByRole("button", { name: "Runs" }).click();
  await expect(page.getByTestId("mesh-view-runs")).toBeVisible();
  await expect(page.getByTestId("run-detail-view")).toBeVisible();
  await page.getByRole("button", { name: "Topology" }).click();

  const overviewTab = page.getByTitle("Overview canvas");
  await expect(overviewTab).toBeVisible();
  for (const mode of ["Overview", "Run Flow", "Evidence", "Signal", "Merkle", "Artifacts"]) {
    const tab = page.getByTitle(`${mode} canvas`);
    const unavailable = page.getByTitle(`${mode} unavailable for this run`);
    if (await tab.count()) {
      await expect(tab).toBeVisible();
      await tab.click();
      await expect(page.locator(".react-flow__node").first()).toBeVisible();
    } else {
      await expect(unavailable).toBeVisible();
      await expect(unavailable).toBeDisabled();
    }
  }
});

test("submits operator note and Hermes chat through steering", async ({ page }) => {
  const apiUrl = process.env.MESH_E2E_API_URL;
  expect(apiUrl, "MESH_E2E_API_URL must be set by scripts/e2e_ui_operator.sh").toBeTruthy();
  const runResponse = await page.request.post(`${apiUrl}/api/runs`, {
    data: {
      scenario_key: "search_latency_regression",
      evaluation_mode: "native",
      orchestration_mode: "native",
      steering_mode: "interruptible_auto",
      pause_points: [],
    },
  });
  await expect(runResponse.status()).toBeLessThan(400);
  const run = await runResponse.json() as { run_id: string };
  const webUrl = new URL(targetUrl());
  await page.goto(`${webUrl.origin}/?server=${apiUrl}&run=${run.run_id}`);

  await page.getByRole("button", { name: "Context", exact: true }).click();
  await page.getByTestId("mesh-context-drawer").getByRole("button", { name: "Steering" }).click();
  await expect(page.getByText("Steering Context")).toBeVisible();
  await page.getByPlaceholder(/operator note|note for/i).fill("E2E operator note from professional console");
  const noteResponse = page.waitForResponse((response) =>
    response.url().includes(`/api/runs/${run.run_id}/steer`) &&
    response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Attach" }).click();
  await expect((await noteResponse).status()).toBeLessThan(400);

  await page.getByTestId("mesh-primary-nav").getByRole("button", { name: "Hermes" }).click();
  await expect(page.getByTestId("mesh-context-drawer")).toHaveCount(0);
  await page.getByPlaceholder(/Ask Hermes/i).fill("Summarize the current blocker and safest next action.");
  const hermesResponse = page.waitForResponse((response) =>
    response.url().includes(`/api/runs/${run.run_id}/steer`) &&
    response.request().method() === "POST",
  );
  await page.getByTestId("mesh-view-hermes").getByRole("button", { name: "Send" }).click();
  await expect((await hermesResponse).status()).toBeLessThan(500);
});

test("keeps the Purna shell usable on mobile", async ({ page }) => {
  await openFixture(page);

  await expect(page.getByRole("heading", { name: "Purna Console" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Context", exact: true })).toBeVisible();
  await expect(page.getByTestId("mesh-primary-nav")).toBeVisible();
  await expect(page.getByTestId("mesh-view-overview")).toBeVisible();
  await expectNoHorizontalOverflow(page);
});
