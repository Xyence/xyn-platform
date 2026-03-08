import { expect, test, type BrowserContext, type Page } from "@playwright/test";

const BUILD_PROMPT =
  "Build a new app. It is a network inventory application for managing devices, interfaces, IP addresses, and locations per workspace. Start with devices and locations only. Add one chart that shows devices by status.";

async function loginIfNeeded(page: Page, options?: { preserveCurrentUrl?: boolean }) {
  if (!options?.preserveCurrentUrl) {
    await page.goto("/");
  }
  const signInLink = page.getByRole("link", { name: /Sign in/i });
  if (await signInLink.isVisible().catch(() => false)) {
    await signInLink.click();
  }
  const devLogin = page.getByRole("button", { name: /Continue as Admin/i });
  if (await devLogin.isVisible().catch(() => false)) {
    await devLogin.click();
  }
  await expect(page.getByRole("button", { name: /Xyn \(⌘K \/ Ctrl\+K\)/i })).toBeVisible();
}

async function openPalette(page: Page) {
  const dialog = page.getByRole("dialog", { name: "Xyn Console" });
  if (await dialog.isVisible().catch(() => false)) return;
  await page.getByRole("button", { name: /Xyn \(⌘K \/ Ctrl\+K\)/i }).click();
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

async function buildNetworkInventory(page: Page) {
  await submitPalettePrompt(page, BUILD_PROMPT);
  await expect(page.getByText(/Draft Ready/i)).toBeVisible();
  await page.getByRole("button", { name: /Create draft/i }).click();
  await expect(page.getByText("App intent draft created and submitted for processing.")).toBeVisible();
  await page.getByRole("button", { name: "Track build" }).click();
  await expect(page.locator("h2").filter({ hasText: /^Draft Detail$/ })).toBeVisible();
  const buildStatusField = page.locator("section.card .detail-grid > div").filter({
    has: page.locator("strong", { hasText: "Build status" }),
  }).first();
  await expect(buildStatusField.locator("p")).toHaveText(/succeeded/i, { timeout: 120_000 });
}

async function waitForNewPage(context: BrowserContext, trigger: () => Promise<void>) {
  const popupPromise = context.waitForEvent("page");
  await trigger();
  const popup = await popupPromise;
  await popup.waitForLoadState("domcontentloaded");
  return popup;
}

test.describe("platform settings and sibling install", () => {
  test("platform settings stays inside workbench navigation and palette submissions still work", async ({ page }) => {
    await loginIfNeeded(page);
    await submitPalettePrompt(page, "Open platform settings");
    await expect(page.getByRole("heading", { name: "Platform Settings", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Clear panel" })).toBeVisible();
    await submitPalettePrompt(page, "List artifacts");
    await expect(page.getByText(/Artifacts/i).first()).toBeVisible();
  });

  test("sibling Xyn shows installed network inventory capability and artifact", async ({ page, context }) => {
    await loginIfNeeded(page);
    await buildNetworkInventory(page);

    const siblingPage = await waitForNewPage(context, async () => {
      await page.getByRole("link", { name: "Open sibling Xyn" }).click();
    });

    await loginIfNeeded(siblingPage, { preserveCurrentUrl: true });
    const capabilityCount = siblingPage.locator(".workbench-capabilities-count");
    await expect(capabilityCount).toBeVisible();
    await expect
      .poll(async () => Number.parseInt((await capabilityCount.textContent()) || "0", 10), {
        message: "Sibling Xyn capability count should include the installed Network Inventory capability.",
      })
      .toBeGreaterThan(2);

    await siblingPage.getByRole("button", { name: /List artifacts/i }).click();
    await expect(siblingPage.getByText(/Artifacts/i).first()).toBeVisible();
    await expect(siblingPage.getByText(/Network Inventory|net-inventory/i).first()).toBeVisible({ timeout: 60_000 });
  });
});
