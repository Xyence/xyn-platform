import { expect, test, type Page } from "@playwright/test";

const BUILD_PROMPT =
  "Create a simple network inventory application with devices and locations. Devices should have hostname, ip_address, and status. Locations should have name and city. Devices belong to locations. Include one chart showing device count by status.";

async function shot(page: Page, name: string) {
  await page.screenshot({ path: `test-results/screenshots/${name}.png`, fullPage: true });
}

async function openPalette(page: Page) {
  const dialog = page.getByRole("dialog", { name: "Xyn Console" });
  if (await dialog.isVisible().catch(() => false)) {
    return;
  }
  const button = page.getByRole("button", { name: /Xyn \(⌘K \/ Ctrl\+K\)/i });
  await expect(button).toBeVisible();
  await button.click();
  await expect(dialog).toBeVisible();
}

async function submitPalettePrompt(page: Page, prompt: string) {
  await openPalette(page);
  const promptRegion = page.getByRole("region", { name: "Xyn prompt" });
  const input = promptRegion.getByPlaceholder("Describe what you want to create or change...");
  await expect(input).toBeVisible();
  await input.fill(prompt);
  await promptRegion.getByRole("button", { name: "Submit" }).click();
}

test.describe("demo golden path", () => {
  test("builds, tracks, traces, opens, queries, and shows artifacts through the UI", async ({ page, context }) => {
    await page.goto("/");

    const signInLink = page.getByRole("link", { name: /Sign in/i });
    if (await signInLink.isVisible().catch(() => false)) {
      await signInLink.click();
    }

    const devLogin = page.getByRole("button", { name: /Continue as Admin/i });
    if (await devLogin.isVisible().catch(() => false)) {
      await devLogin.click();
    }

    await expect(page.getByText("Xyn").first()).toBeVisible();
    await expect(page.getByRole("button", { name: /Xyn \(⌘K \/ Ctrl\+K\)/i })).toBeVisible();
    await expect(page.getByText(/Workspace Not Accessible/i)).toHaveCount(0);
    await shot(page, "01-home");

    await submitPalettePrompt(page, BUILD_PROMPT);
    await expect(page.getByText(/Draft Ready/i)).toBeVisible();
    await page.getByRole("button", { name: /Create draft/i }).click();
    await expect(page.getByText("App intent draft created and submitted for processing.")).toBeVisible();
    await shot(page, "02-draft-created");

    await page.getByRole("button", { name: "Track build" }).click();
    await expect(page.getByRole("heading", { name: "Draft Detail" }).first()).toBeVisible();
    await expect(page.getByText("Build Pipeline")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Execution Trace" })).toBeVisible();
    const buildStatusField = page.locator("section.card .detail-grid > div").filter({
      has: page.locator("strong", { hasText: "Build status" }),
    }).first();
    await expect(buildStatusField.locator("p")).toHaveText(/succeeded/i, { timeout: 120_000 });
    await expect(page.getByRole("button", { name: /View full execution note|Hide full execution note/i })).toBeVisible({
      timeout: 60_000,
    });
    await shot(page, "03-build-tracking");

    const runningAppLink = page.locator("section.card").filter({ has: page.getByText("Running app") }).getByRole("link").first();
    await expect(runningAppLink).toBeVisible({ timeout: 120_000 });
    const [appPage] = await Promise.all([
      context.waitForEvent("page"),
      runningAppLink.click(),
    ]);
    await appPage.waitForLoadState("domcontentloaded");
    await expect(appPage).toHaveURL(/\/docs$/);
    await expect.poll(() => appPage.title(), { timeout: 30_000 }).toMatch(/Swagger UI|OpenAPI|FastAPI/i);
    await shot(appPage, "04-running-app");
    await appPage.close();

    await submitPalettePrompt(page, "show devices");
    await expect(page.getByText(/seeded-device-1/i)).toBeVisible({ timeout: 60_000 });
    await shot(page, "05-show-devices");

    await submitPalettePrompt(page, "show artifacts of kind app_spec");
    await expect(page.getByText(/Artifacts/i).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/appspec\\.net-inventory|net-inventory/i).first()).toBeVisible({ timeout: 60_000 });
    await shot(page, "06-show-artifacts");
  });
});
