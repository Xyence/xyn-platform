import { expect, test, type Page, type TestInfo } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";

const BUILD_PROMPT =
  'Create a simple network inventory application with devices and locations. Devices should have hostname, ip_address, and status. Locations should have name and city. Devices belong to locations. Include one chart showing device count by status.';

const STEP_SEQUENCE = [
  "open Xyn",
  "build network inventory app",
  "submit draft",
  "track build",
  "show execution trace",
  "open deployed app",
  "run palette command",
  "show artifacts",
] as const;

function stepFileName(index: number, label: string): string {
  const slug = label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `${String(index + 1).padStart(2, "0")}-${slug}.png`;
}

async function shot(page: Page, testInfo: TestInfo, index: number, label: string) {
  const target = testInfo.outputPath("screenshots", stepFileName(index, label));
  await fs.mkdir(path.dirname(target), { recursive: true });
  await page.screenshot({ path: target, fullPage: true });
  await testInfo.attach(`screenshot:${label}`, {
    path: target,
    contentType: "image/png",
  });
}

async function openPalette(page: Page) {
  const dialog = page.getByRole("dialog", { name: "Xyn Console" });
  if (await dialog.isVisible().catch(() => false)) return;
  const button = page.getByRole("button", { name: /Xyn \(⌘K \/ Ctrl\+K\)/i });
  await expect(button, "Palette launcher should be visible on the workbench.").toBeVisible();
  await button.click();
  await expect(dialog, "Palette dialog should open after clicking the launcher.").toBeVisible();
}

async function submitPalettePrompt(page: Page, prompt: string) {
  await openPalette(page);
  const promptRegion = page.getByRole("region", { name: "Xyn prompt" });
  const input = promptRegion.getByPlaceholder("Describe what you want to create or change...");
  await expect(input, "Palette prompt input should be visible.").toBeVisible();
  await input.fill(prompt);
  await promptRegion.getByRole("button", { name: "Submit" }).click();
}

function workbenchPanelCloseButton(page: Page) {
  return page.locator(".ems-panel-host .ems-panel-head").getByRole("button", { name: "Close" });
}

test.describe("demo golden path", () => {
  test("walks the demo path through the UI", async ({ page }, testInfo) => {
    const browserLogs: string[] = [];
    const pushLog = (line: string) => browserLogs.push(`${new Date().toISOString()} ${line}`);
    page.on("console", (message) => pushLog(`[console:${message.type()}] ${message.text()}`));
    page.on("pageerror", (error) => pushLog(`[pageerror] ${error.message}`));
    page.on("requestfailed", (request) => pushLog(`[requestfailed] ${request.method()} ${request.url()} :: ${request.failure()?.errorText || "unknown"}`));

    const flushLogs = async () => {
      const logPath = testInfo.outputPath("logs", "browser.log");
      await fs.mkdir(path.dirname(logPath), { recursive: true });
      await fs.writeFile(logPath, `${browserLogs.join("\n")}\n`, "utf-8");
      await testInfo.attach("browser-log", { path: logPath, contentType: "text/plain" });
    };

    try {
      await test.step(STEP_SEQUENCE[0], async () => {
        await page.goto("/");

        const signInLink = page.getByRole("link", { name: /Sign in/i });
        if (await signInLink.isVisible().catch(() => false)) {
          await signInLink.click();
        }

        const devLogin = page.getByRole("button", { name: /Continue as Admin/i });
        if (await devLogin.isVisible().catch(() => false)) {
          await devLogin.click();
        }

        await expect(page.getByText("Xyn").first(), "Xyn branding should be visible after login.").toBeVisible();
        await expect(page.getByRole("button", { name: /Xyn \(⌘K \/ Ctrl\+K\)/i }), "Palette launcher should be visible.").toBeVisible();
        await expect(page.getByText(/Workspace Not Accessible/i), "Demo path must not land in an inaccessible workspace.").toHaveCount(0);
        const capabilityCount = page.locator(".workbench-capabilities-count");
        await expect(capabilityCount, "Capabilities count should be visible for the active workspace.").toBeVisible();
        await expect
          .poll(
            async () => Number.parseInt((await capabilityCount.textContent()) || "0", 10),
            { message: "Capabilities count should reflect installed runtime capabilities." },
          )
          .toBeGreaterThan(0);
        await page.getByRole("button", { name: /List artifacts/i }).click();
        await expect(page.getByText(/Artifacts/i).first(), "Artifacts panel should open from the landing view.").toBeVisible();
        for (const slug of [
          "ems",
          "hello-app",
          "articles-tour",
          "platform-build-tour",
          "deploy-subscriber-notes",
          "subscriber-notes-walkthrough",
        ]) {
          await expect(page.getByText(new RegExp(`^${slug}$`, "i")), `Fresh install should not list legacy artifact ${slug}.`).toHaveCount(0);
        }
        await workbenchPanelCloseButton(page).click();
        await shot(page, testInfo, 0, STEP_SEQUENCE[0]);
      });

      await test.step(STEP_SEQUENCE[1], async () => {
        await submitPalettePrompt(page, BUILD_PROMPT);
        await expect(page.getByText(/Draft Ready/i), "Build prompt should resolve to a draft-ready state.").toBeVisible();
        await shot(page, testInfo, 1, STEP_SEQUENCE[1]);
      });

      await test.step(STEP_SEQUENCE[2], async () => {
        await page.getByRole("button", { name: /Create draft/i }).click();
        await expect(
          page.getByText("App intent draft created and submitted for processing."),
          "Draft submission confirmation should be visible.",
        ).toBeVisible();
        await shot(page, testInfo, 2, STEP_SEQUENCE[2]);
      });

      await test.step(STEP_SEQUENCE[3], async () => {
        await page.getByRole("button", { name: "Track build" }).click();
        await expect(page.locator("h2").filter({ hasText: /^Draft Detail$/ }), "Draft detail page should open.").toBeVisible();
        await expect(page.getByText("Build Pipeline"), "Build pipeline section should be visible.").toBeVisible();
        const buildStatusField = page.locator("section.card .detail-grid > div").filter({
          has: page.locator("strong", { hasText: "Build status" }),
        }).first();
        await expect(buildStatusField.locator("p"), "Build status should reach succeeded for the demo draft.").toHaveText(/succeeded/i, {
          timeout: 120_000,
        });
        await shot(page, testInfo, 3, STEP_SEQUENCE[3]);
      });

      await test.step(STEP_SEQUENCE[4], async () => {
        await expect(page.getByRole("heading", { name: "Execution Trace" }), "Execution Trace heading should be visible.").toBeVisible();
        const expand = page.getByRole("button", { name: /View full execution note|Hide full execution note/i });
        await expect(expand, "Execution note expand control should be visible.").toBeVisible({ timeout: 60_000 });
        if (/view full execution note/i.test((await expand.textContent()) || "")) {
          await expand.click();
        }
        await expect(page.getByText("Findings", { exact: true }), "Execution trace findings section should be visible.").toBeVisible();
        await expect(page.getByText("Validation", { exact: true }), "Execution trace validation section should be visible.").toBeVisible();
        await shot(page, testInfo, 4, STEP_SEQUENCE[4]);
      });

      await test.step(STEP_SEQUENCE[5], async () => {
        await expect(
          page.getByText(/Installed in Xyn/i),
          "Draft detail should explain that the capability is installed into the Xyn shell.",
        ).toBeVisible();
        await expect(page.getByRole("heading", { name: "Installed Capability" }), "Installed capability card should be visible.").toBeVisible();
        await expect(page.getByText(/Network Inventory|net-inventory/i).first(), "Installed capability should identify the deployed app.").toBeVisible();
        await expect(
          page.locator("code").filter({ hasText: /^show devices by status$/i }),
          "Installed capability should advertise palette-driven report usage.",
        ).toBeVisible();
        await shot(page, testInfo, 5, STEP_SEQUENCE[5]);
      });

      await test.step(STEP_SEQUENCE[6], async () => {
        await submitPalettePrompt(page, "show devices");
        await expect(page.getByText(/seeded-device-1/i), "Palette should show seeded device data.").toBeVisible({ timeout: 60_000 });
        await submitPalettePrompt(page, "show locations");
        await expect(page.getByText(/seeded-location-1/i), "Palette should show seeded location data.").toBeVisible({ timeout: 60_000 });
        await submitPalettePrompt(page, "create device");
        await expect(page.getByText(/Created 1 device/i), "Palette should confirm device creation.").toBeVisible({ timeout: 60_000 });
        await expect(page.getByText(/demo-device-/i), "Created device should be visible in the palette result.").toBeVisible({ timeout: 60_000 });
        await submitPalettePrompt(page, "show devices by status");
        await expect(page.getByText(/Devices by status/i), "Palette should surface a devices-by-status report.").toBeVisible({ timeout: 60_000 });
        await expect(page.getByText(/online/i).first(), "Devices-by-status report should include at least one status bucket.").toBeVisible();
        await shot(page, testInfo, 6, STEP_SEQUENCE[6]);
      });

      await test.step(STEP_SEQUENCE[7], async () => {
        await page.getByRole("button", { name: /View generated artifacts/i }).click();
        await expect(page.getByText(/Artifacts/i).first(), "Artifacts panel should open.").toBeVisible({ timeout: 30_000 });
        await expect(page.getByText(/appspec\.net-inventory|net-inventory/i).first(), "Generated app_spec artifact should be visible.").toBeVisible({
          timeout: 60_000,
        });
        await shot(page, testInfo, 7, STEP_SEQUENCE[7]);
      });
    } finally {
      await flushLogs();
    }
  });
});
