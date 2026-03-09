import { expect, test, type Page } from "@playwright/test";

const INITIAL_BUILD_PROMPT =
  "Build a network inventory application for managing devices and locations. Include a simple chart showing devices by status.";

async function artifactList(page: Page, workspaceId: string) {
  return page.evaluate(async (id) => {
    const response = await fetch(`/xyn/api/workspaces/${id}/artifacts`);
    return {
      status: response.status,
      body: await response.json(),
    };
  }, workspaceId);
}

async function palettePrompt(page: Page, prompt: string) {
  return page.evaluate(async ({ prompt: nextPrompt }) => {
    const response = await fetch("/xyn/api/palette/execute?workspace_slug=development", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: nextPrompt, workspace_slug: "development" }),
    });
    const text = await response.text();
    let body: Record<string, unknown> = {};
    try {
      body = JSON.parse(text);
    } catch {
      return { status: response.status, parseError: true, text };
    }
    return {
      status: response.status,
      kind: String(body.kind || ""),
      title: String(body.title || ""),
      text: String(body.text || ""),
      rows: Array.isArray(body.rows) ? body.rows : [],
      meta: typeof body.meta === "object" && body.meta ? body.meta : {},
    };
  }, { prompt });
}

test.describe("generated app create flows", () => {
  test("supports data-driven create location and create device in the sibling app", async ({ page }) => {
    test.slow();

    await page.goto("http://localhost/auth/login");
    await page.getByRole("button", { name: /continue as admin/i }).click();
    await page.waitForURL(/\/w\//, { timeout: 30_000 });

    await page.locator("textarea").first().fill(INITIAL_BUILD_PROMPT);
    await page.getByRole("button", { name: /submit/i }).click();
    await expect(page.getByText(/Draft Ready/i)).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: /Create app intent draft/i }).click();
    await expect(page.getByText(/App intent draft created and submitted for processing\./i)).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: /Track build/i }).click();

    await expect(page.getByText("Application Definition")).toBeVisible({ timeout: 120_000 });
    const reviseLink = page.getByRole("link", { name: /revise application/i });
    await expect(reviseLink).toBeVisible({ timeout: 120_000 });

    await reviseLink.click();
    if (/\/auth\/login/.test(page.url())) {
      await page.getByRole("button", { name: /continue as admin/i }).click();
    }

    await page.waitForURL(/\/w\/[^/]+\/workbench/, { timeout: 60_000 });
    const siblingUrl = page.url();
    const workspaceIdMatch = siblingUrl.match(/\/w\/([^/]+)\//);
    expect(workspaceIdMatch).not.toBeNull();
    const siblingWorkspaceId = String(workspaceIdMatch?.[1] || "");

    const beforeArtifacts = await artifactList(page, siblingWorkspaceId);
    expect(beforeArtifacts.status).toBe(200);
    const installedApps = Array.isArray(beforeArtifacts.body?.artifacts)
      ? beforeArtifacts.body.artifacts.filter((artifact: Record<string, unknown>) => String(artifact.slug || "") === "app.net-inventory")
      : [];
    expect(installedApps).toHaveLength(1);

    await expect
      .poll(
        async () => palettePrompt(page, "create location"),
        { timeout: 60_000, message: "Sibling app should ask for required create-location fields." },
      )
      .toMatchObject({
        status: 200,
        kind: "text",
        text: expect.stringMatching(/provide: name, city/i),
      });

    await expect
      .poll(
        async () => palettePrompt(page, "create location named office in St. Louis MO USA"),
        { timeout: 60_000, message: "Sibling app should create a location from supplied values." },
      )
      .toMatchObject({
        status: 200,
        kind: "table",
        text: expect.stringMatching(/^Created 1 location:/),
      });

    await expect
      .poll(
        async () => palettePrompt(page, "show locations"),
        { timeout: 60_000, message: "Sibling app should show the created office location." },
      )
      .toMatchObject({
        status: 200,
        kind: "table",
      });

    await expect
      .poll(
        async () => palettePrompt(page, "create device named edge-router-1"),
        { timeout: 60_000, message: "Sibling app should create a device from supplied values." },
      )
      .toMatchObject({
        status: 200,
        kind: "table",
        text: expect.stringMatching(/^Created 1 device:/),
      });

    await expect
      .poll(
        async () => palettePrompt(page, "show devices"),
        { timeout: 60_000, message: "Sibling app should show the created device." },
      )
      .toMatchObject({
        status: 200,
        kind: "table",
      });

    const locationRows = await palettePrompt(page, "show locations");
    const deviceRows = await palettePrompt(page, "show devices");
    expect(Array.isArray(locationRows.rows)).toBe(true);
    expect(Array.isArray(deviceRows.rows)).toBe(true);
    expect(locationRows.rows.some((row: Record<string, unknown>) =>
      String(row.name || "") === "office"
      && String(row.city || "") === "St. Louis"
      && String(row.region || "") === "MO"
      && String(row.country || "") === "USA")).toBe(true);
    expect(deviceRows.rows.some((row: Record<string, unknown>) => String(row.name || "") === "edge-router-1")).toBe(true);

  });
});
