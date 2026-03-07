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

test.describe("demo golden path", () => {
  test("walks the demo path through the UI", async ({ page, context }, testInfo) => {
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
        await expect(page.getByRole("heading", { name: "Draft Detail" }).first(), "Draft detail page should open.").toBeVisible();
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
        const runningAppLink = page.getByRole("link", { name: "Open deployed app" });
        await expect(runningAppLink, "Open deployed app CTA should be visible on draft detail.").toBeVisible({ timeout: 120_000 });
        await expect(
          page.getByText(/FastAPI docs route|visible application entrypoint/i),
          "Draft detail should explain the current deployed app entrypoint.",
        ).toBeVisible();
        const [appPage] = await Promise.all([context.waitForEvent("page"), runningAppLink.click()]);
        await appPage.waitForLoadState("domcontentloaded");
        await expect(appPage, "Running app should open in a new tab.").toHaveURL(/\/docs$/);
        await expect.poll(() => appPage.title(), { timeout: 30_000 }).toMatch(/Swagger UI|OpenAPI|FastAPI/i);
        await shot(appPage, testInfo, 5, STEP_SEQUENCE[5]);
        await appPage.close();
      });

      await test.step(STEP_SEQUENCE[6], async () => {
        await submitPalettePrompt(page, "show devices");
        await expect(page.getByText(/seeded-device-1/i), "Palette should show seeded device data.").toBeVisible({ timeout: 60_000 });
        await shot(page, testInfo, 6, STEP_SEQUENCE[6]);
      });

      await test.step(STEP_SEQUENCE[7], async () => {
        await submitPalettePrompt(page, "show artifacts of kind app_spec");
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
