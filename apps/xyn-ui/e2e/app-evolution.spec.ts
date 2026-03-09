import { expect, test, type Page } from "@playwright/test";

const INITIAL_BUILD_PROMPT =
  "Build a network inventory application for managing devices and locations. Include a simple chart showing devices by status.";
const EVOLUTION_PROMPT = "Add interfaces to devices and include a chart showing interfaces by status.";

async function artifactList(page: Page, workspaceId: string) {
  return page.evaluate(async (id) => {
    const response = await fetch(`/xyn/api/workspaces/${id}/artifacts`);
    return {
      status: response.status,
      body: await response.json(),
    };
  }, workspaceId);
}

async function ensureSiblingWorkbench(page: Page, siblingUrl: string) {
  await page.goto(siblingUrl);
  if (/\/auth\/login/.test(page.url())) {
    await page.getByRole("button", { name: /continue as admin/i }).click();
  }
  await page.waitForURL(/\/w\/[^/]+\/workbench/, { timeout: 30_000 });
}

test.describe("application evolution", () => {
  test("reuses the same sibling and materializes interfaces", async ({ page }) => {
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
    const siblingUrlBefore = page.url();
    const workspaceIdMatch = siblingUrlBefore.match(/\/w\/([^/]+)\//);
    expect(workspaceIdMatch).not.toBeNull();
    const siblingWorkspaceId = String(workspaceIdMatch?.[1] || "");

    const beforeArtifacts = await artifactList(page, siblingWorkspaceId);
    expect(beforeArtifacts.status).toBe(200);
    const beforeInstalledApps = Array.isArray(beforeArtifacts.body?.artifacts)
      ? beforeArtifacts.body.artifacts.filter((artifact: Record<string, unknown>) => String(artifact.slug || "") === "app.net-inventory")
      : [];
    expect(beforeInstalledApps).toHaveLength(1);

    await expect(page.locator("textarea").first()).toHaveValue(/Add/i, { timeout: 30_000 });
    await page.locator("textarea").first().fill(EVOLUTION_PROMPT);
    await page.getByRole("button", { name: /submit/i }).click();
    await expect(page.getByText(/Draft Ready/i)).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: /Create revision draft/i }).click();
    await expect(page.getByRole("button", { name: /Track build/i })).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: /Track build/i }).click();

    await expect(page.getByText("Application Definition")).toBeVisible({ timeout: 120_000 });
    await expect(page.getByText(/devices_by_status,\s*interfaces_by_status/i).first()).toBeVisible({ timeout: 30_000 });

    await ensureSiblingWorkbench(page, siblingUrlBefore);
    const siblingUrlAfter = page.url();
    expect(siblingUrlAfter).toBe(siblingUrlBefore);

    const afterArtifacts = await artifactList(page, siblingWorkspaceId);
    expect(afterArtifacts.status).toBe(200);
    const afterInstalledApps = Array.isArray(afterArtifacts.body?.artifacts)
      ? afterArtifacts.body.artifacts.filter((artifact: Record<string, unknown>) => String(artifact.slug || "") === "app.net-inventory")
      : [];
    expect(afterInstalledApps).toHaveLength(1);

    await expect
      .poll(
        async () =>
          page.evaluate(async () => {
            const response = await fetch("/xyn/api/palette/execute?workspace_slug=development", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ prompt: "show interfaces", workspace_slug: "development" }),
            });
            const text = await response.text();
            let body: Record<string, unknown> = {};
            try {
              body = JSON.parse(text);
            } catch {
              return { status: response.status, parseError: true, text };
            }
            return { status: response.status, text: String(body.text || ""), rows: Array.isArray(body.rows) ? body.rows.length : 0 };
          }),
        { timeout: 60_000, message: "Sibling runtime should eventually expose interfaces after the revision completes." },
      )
      .toMatchObject({ status: 200, text: "Found 1 interfaces.", rows: 1 });

    await expect
      .poll(
        async () =>
          page.evaluate(async () => {
            const response = await fetch("/xyn/api/palette/execute?workspace_slug=development", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ prompt: "show interfaces by status", workspace_slug: "development" }),
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
            };
          }),
        { timeout: 60_000, message: "Sibling runtime should eventually expose the interfaces-by-status report after the revision completes." },
      )
      .toMatchObject({
        status: 200,
        kind: "bar_chart",
        title: "Interfaces by Status",
        text: "Generated status chart for 1 interfaces.",
      });
  });
});
