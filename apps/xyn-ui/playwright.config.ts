import { defineConfig } from "@playwright/test";

const baseURL = process.env.XYN_UI_BASE_URL || "http://localhost";
const outputDir = process.env.PLAYWRIGHT_OUTPUT_DIR || "test-results";
const reportDir = process.env.PLAYWRIGHT_REPORT_DIR || "playwright-report";

export default defineConfig({
  testDir: "./e2e",
  timeout: 10 * 60 * 1000,
  expect: {
    timeout: 30_000,
  },
  fullyParallel: false,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: reportDir }]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    viewport: { width: 1600, height: 1100 },
  },
  outputDir,
});
