import { defineConfig, devices, type LaunchOptions } from "@playwright/test";

const launchOptions: LaunchOptions = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
  ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
  : {};

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  workers: 1,
  expect: {
    timeout: 12_000,
  },
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    baseURL: process.env.MESH_PRODUCT_E2E_BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium-product",
      use: {
        ...devices["Desktop Chrome"],
        channel: undefined,
        launchOptions,
        viewport: { width: 1440, height: 920 },
      },
    },
    {
      name: "chromium-product-mobile",
      use: {
        ...devices["Pixel 7"],
        channel: undefined,
        launchOptions,
      },
    },
  ],
});
