import { beforeEach, describe, expect, it } from "vitest";
import { buildUiActionFromPrompt, resolveDirectPanelOpenParams, resolvePanelCommand } from "./XynConsoleCore";

describe("resolveDirectPanelOpenParams", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("keeps non-composer panel params unchanged", () => {
    expect(
      resolveDirectPanelOpenParams(
        { panelKey: "artifact_detail", params: { slug: "core.authn-jwt" } },
        "ws-1",
      )
    ).toEqual({ slug: "core.authn-jwt" });
  });

  it("injects workspace context for campaign list open params", () => {
    expect(
      resolveDirectPanelOpenParams(
        { panelKey: "campaign_list", params: {} },
        "ws-1",
      )
    ).toEqual({
      workspace_id: "ws-1",
    });
    expect(
      resolveDirectPanelOpenParams(
        { panelKey: "campaign_list", params: { create: true } },
        "ws-1",
      )
    ).toEqual({
      workspace_id: "ws-1",
      create: true,
    });
  });

  it("injects workspace context for solution list open params", () => {
    expect(
      resolveDirectPanelOpenParams(
        { panelKey: "solution_list", params: {} },
        "ws-1",
      )
    ).toEqual({
      workspace_id: "ws-1",
    });
    expect(
      resolveDirectPanelOpenParams(
        { panelKey: "solution_list", params: { solution_name: "deal finder" } },
        "ws-1",
      )
    ).toEqual({
      workspace_id: "ws-1",
      solution_name: "deal finder",
    });
  });

  it("opens generic composer in neutral workspace context", () => {
    window.localStorage.setItem(
      "xyn:composer:selected-effort:ws-1",
      JSON.stringify({ application_id: "app-knowledgebase" }),
    );
    expect(
      resolveDirectPanelOpenParams(
        { panelKey: "composer_detail", params: {} },
        "ws-1",
      )
    ).toEqual({
      workspace_id: "ws-1",
    });
  });
});

describe("resolvePanelCommand", () => {
  it("parses list namespace artifacts", () => {
    expect(resolvePanelCommand("list workspaces")).toEqual({
      panelKey: "workspaces",
      params: {
        query: {
          entity: "workspaces",
          filters: [],
          sort: [{ field: "name", dir: "asc" }],
          limit: 50,
          offset: 0,
        },
      },
    });
    expect(resolvePanelCommand("show runs")).toEqual({
      panelKey: "runs",
      params: {
        query: {
          entity: "runs",
          filters: [],
          sort: [{ field: "created_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    });
    expect(resolvePanelCommand("show recent runs")).toEqual({
      panelKey: "runs",
      params: {
        query: {
          entity: "runs",
          filters: [{ field: "created_at", op: "gte", value: "now-24h" }],
          sort: [{ field: "created_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    });
    expect(resolvePanelCommand("show failed runs")).toEqual({
      panelKey: "runs",
      params: {
        query: {
          entity: "runs",
          filters: [{ field: "status", op: "eq", value: "failed" }],
          sort: [{ field: "created_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    });
    expect(resolvePanelCommand("describe run 123e4567-e89b-12d3-a456-426614174000")).toEqual({
      panelKey: "run_detail",
      params: { run_id: "123e4567-e89b-12d3-a456-426614174000" },
    });
    expect(resolvePanelCommand("show drafts")).toEqual({
      panelKey: "drafts_list",
      params: {},
    });
    expect(resolvePanelCommand("open composer")).toEqual({
      panelKey: "composer_detail",
      params: {},
    });
    expect(resolvePanelCommand("open workbench")).toEqual({
      panelKey: "composer_detail",
      params: {},
    });
    expect(resolvePanelCommand("open jobs")).toEqual({
      panelKey: "jobs_list",
      params: {},
    });
    expect(resolvePanelCommand("show solutions")).toEqual({
      panelKey: "solution_list",
      params: {},
    });
    expect(resolvePanelCommand("list solutions")).toEqual({
      panelKey: "solution_list",
      params: {},
    });
    expect(resolvePanelCommand("open solution Deal Finder")).toEqual({
      panelKey: "solution_list",
      params: { solution_name: "deal finder" },
    });
    expect(resolvePanelCommand("create solution add a new operator workflow")).toEqual({
      panelKey: "solution_list",
      params: { create_solution_objective: "add a new operator workflow" },
    });
    expect(resolvePanelCommand("build solution stabilize watcher evaluation")).toEqual({
      panelKey: "solution_list",
      params: { create_solution_objective: "stabilize watcher evaluation" },
    });
    expect(resolvePanelCommand("campaigns")).toBeNull();
    expect(resolvePanelCommand("show campaigns")).toBeNull();
    expect(resolvePanelCommand("open campaigns")).toBeNull();
    expect(resolvePanelCommand("new campaign")).toBeNull();
    expect(resolvePanelCommand("create campaign")).toBeNull();

    expect(resolvePanelCommand("list core artifacts")).toEqual({
      panelKey: "artifact_list",
      params: { namespace: "core" },
    });
    expect(resolvePanelCommand("list ore artifacts")).toEqual({
      panelKey: "artifact_list",
      params: { namespace: "ore" },
    });
    expect(resolvePanelCommand("show installed artifacts")).toEqual({
      panelKey: "artifact_list",
      params: {
        query: {
          entity: "artifacts",
          filters: [{ field: "installed", op: "eq", value: true }],
          sort: [{ field: "updated_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    });
    expect(resolvePanelCommand("show artifacts updated in the last hour")).toEqual({
      panelKey: "artifact_list",
      params: {
        query: {
          entity: "artifacts",
          filters: [{ field: "updated_at", op: "gte", value: "now-1h" }],
          sort: [{ field: "updated_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    });
    expect(resolvePanelCommand("show artifacts of kind module")).toEqual({
      panelKey: "artifact_list",
      params: {
        query: {
          entity: "artifacts",
          filters: [{ field: "kind", op: "eq", value: "module" }],
          sort: [{ field: "updated_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    });
    expect(resolvePanelCommand("show artifacts in namespace core")).toEqual({
      panelKey: "artifact_list",
      params: {
        query: {
          entity: "artifacts",
          filters: [{ field: "namespace", op: "eq", value: "core" }],
          sort: [{ field: "updated_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    });
    expect(resolvePanelCommand("show me a list of artifacts")).toEqual({
      panelKey: "artifact_list",
      params: {},
    });
    expect(resolvePanelCommand("open artifacts")).toEqual({
      panelKey: "artifact_list",
      params: {},
    });
    expect(resolvePanelCommand("please, show me a list of artifacts.")).toEqual({
      panelKey: "artifact_list",
      params: {},
    });
    expect(resolvePanelCommand("show me artifacts created yesterday")).toEqual({
      panelKey: "artifact_list",
      params: {
        query: {
          entity: "artifacts",
          filters: [
            { field: "created_at", op: "gte", value: "day-start:-1" },
            { field: "created_at", op: "lt", value: "day-start:0" },
          ],
          sort: [{ field: "created_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    });
    expect(resolvePanelCommand("show me the artifacts created two days ago")).toEqual({
      panelKey: "artifact_list",
      params: {
        query: {
          entity: "artifacts",
          filters: [
            { field: "created_at", op: "gte", value: "day-start:-2" },
            { field: "created_at", op: "lt", value: "day-start:-1" },
          ],
          sort: [{ field: "created_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    });
    expect(resolvePanelCommand("show me artifacts with status draft")).toBeNull();
    expect(resolvePanelCommand("summarize artifact changes from the last run")).toBeNull();
  });

  it("keeps explicit artifact detail intent mapped to detail open action", () => {
    expect(
      buildUiActionFromPrompt("open artifact core.authn-jwt", {
        view_type: "table",
        dataset: { name: "artifacts", primary_key: "slug", columns: [{ key: "slug", searchable: true }] },
        query: { entity: "artifacts", filters: [], sort: [{ field: "updated_at", dir: "desc" }], limit: 50, offset: 0 },
        selection: { selected_row_ids: [], focused_row_id: null, row_order_ids: [] },
        pagination: { limit: 50, offset: 0, total_count: 0 },
        ui: { active_panel_id: "panel-artifacts", panel_id: "panel-artifacts" },
      } as never)
    ).toEqual({
      type: "ui.action",
      action: {
        name: "canvas.open_detail",
        params: {
          entity_type: "artifact",
          entity_id: "core.authn-jwt",
          open_in: "new_panel",
          placement: "right",
        },
      },
    });
  });

  it("preserves direct panel intent precedence in artifact table context", () => {
    const artifactTableContext = {
      view_type: "table",
      dataset: { name: "artifacts", primary_key: "slug", columns: [{ key: "slug", searchable: true }] },
      query: { entity: "artifacts", filters: [], sort: [{ field: "updated_at", dir: "desc" }], limit: 50, offset: 0 },
      selection: { selected_row_ids: [], focused_row_id: null, row_order_ids: [] },
      pagination: { limit: 50, offset: 0, total_count: 0 },
      ui: { active_panel_id: "panel-artifacts", panel_id: "panel-artifacts" },
    } as never;

    // A direct panel intent that is not mapped to local canvas ui.action
    // should return null so submitPrompt can execute the direct panel branch.
    expect(buildUiActionFromPrompt("open solutions", artifactTableContext)).toBeNull();
    expect(buildUiActionFromPrompt("open composer", artifactTableContext)).toBeNull();

    // Nearby direct panel commands that are intentionally mapped to table opens
    // should continue producing deterministic ui.action envelopes.
    expect(buildUiActionFromPrompt("open drafts", artifactTableContext)).toEqual({
      type: "ui.action",
      action: {
        name: "canvas.open_table",
        params: {
          dataset: "drafts",
          query: {
            entity: "drafts",
            filters: [],
            sort: [{ field: "updated_at", dir: "desc" }],
            limit: 50,
            offset: 0,
          },
          title: "drafts",
          open_in: "new_panel",
          placement: "center",
        },
      },
    });
    expect(buildUiActionFromPrompt("open jobs", artifactTableContext)).toEqual({
      type: "ui.action",
      action: {
        name: "canvas.open_table",
        params: {
          dataset: "jobs",
          query: {
            entity: "jobs",
            filters: [],
            sort: [{ field: "created_at", dir: "desc" }],
            limit: 50,
            offset: 0,
          },
          title: "jobs",
          open_in: "new_panel",
          placement: "center",
        },
      },
    });
  });

  it("preserves direct panel intent precedence in non-artifact table context", () => {
    const runsTableContext = {
      view_type: "table",
      dataset: { name: "runs", primary_key: "id", columns: [{ key: "id", searchable: true }] },
      query: { entity: "runs", filters: [], sort: [{ field: "created_at", dir: "desc" }], limit: 50, offset: 0 },
      selection: { selected_row_ids: [], focused_row_id: null, row_order_ids: [] },
      pagination: { limit: 50, offset: 0, total_count: 0 },
      ui: { active_panel_id: "panel-runs", panel_id: "panel-runs" },
    } as never;

    expect(buildUiActionFromPrompt("open solutions", runsTableContext)).toBeNull();
  });

  it("parses artifact detail/raw/files commands", () => {
    expect(resolvePanelCommand("open artifact core.authn-jwt")).toEqual({
      panelKey: "artifact_detail",
      params: { slug: "core.authn-jwt" },
    });
    expect(resolvePanelCommand("edit artifact core.authn-jwt raw")).toEqual({
      panelKey: "artifact_raw_json",
      params: { slug: "core.authn-jwt" },
    });
    expect(resolvePanelCommand("edit artifact core.authn-jwt files")).toEqual({
      panelKey: "artifact_files",
      params: { slug: "core.authn-jwt" },
    });
  });

  it("parses ems panel commands", () => {
    expect(resolvePanelCommand("show unregistered devices")).toEqual({
      panelKey: "ems_devices",
      params: {
        query: {
          entity: "ems_devices",
          filters: [{ field: "state", op: "eq", value: "unregistered" }],
          sort: [{ field: "created_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    });
    expect(resolvePanelCommand("show registrations in the past 24 hours")).toEqual({
      panelKey: "ems_registrations",
      params: {
        query: {
          entity: "ems_registrations",
          filters: [{ field: "registered_at", op: "gte", value: "now-24h" }],
          sort: [{ field: "registered_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    });
    expect(resolvePanelCommand("show device statuses")).toEqual({
      panelKey: "ems_device_status_rollup",
      params: {},
    });
    expect(resolvePanelCommand("show devices with state offline")).toEqual({
      panelKey: "ems_devices",
      params: {
        query: {
          entity: "ems_devices",
          filters: [{ field: "state", op: "eq", value: "offline" }],
          sort: [{ field: "created_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    });
    expect(resolvePanelCommand("show devices for customer ACME")).toEqual({
      panelKey: "ems_devices",
      params: {
        query: {
          entity: "ems_devices",
          filters: [{ field: "customer", op: "contains", value: "ACME" }],
          sort: [{ field: "updated_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    });
    expect(resolvePanelCommand("show registrations timeseries last 12 hours")).toEqual({
      panelKey: "ems_registrations_timeseries",
      params: { hours: 12 },
    });
    expect(resolvePanelCommand("describe dataset ems_devices")).toEqual({
      panelKey: "ems_dataset_schema",
      params: { dataset: "ems_devices" },
    });
  });
});
