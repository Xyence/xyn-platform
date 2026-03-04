import { describe, expect, it } from "vitest";
import { buildUiActionFromPrompt } from "./XynConsoleCore";

function artifactsTableContext() {
  return {
    view_type: "table" as const,
    dataset: {
      name: "artifacts",
      primary_key: "slug",
      columns: [
        { key: "slug", searchable: true },
        { key: "kind", filterable: true },
        { key: "updated_at", filterable: true },
      ],
    },
    query: {
      entity: "artifacts",
      filters: [],
      sort: [{ field: "updated_at", dir: "desc" }],
      limit: 50,
      offset: 0,
    },
    selection: {
      selected_row_ids: [],
      focused_row_id: null,
      row_order_ids: ["core.authn-jwt", "ems"],
    },
    pagination: { limit: 50, offset: 0, total_count: 2 },
    ui: { active_panel_id: "p1", panel_id: "p1" },
  };
}

function artifactDetailContext() {
  return {
    view_type: "detail" as const,
    entity_type: "artifact",
    entity_id: "core.authn-jwt",
    available_tabs: ["overview", "raw", "files"],
    active_tab: "overview",
    ui: { active_panel_id: "p2", panel_id: "p2" },
  };
}

describe("buildUiActionFromPrompt", () => {
  it("patches active table query for filter command", () => {
    const action = buildUiActionFromPrompt("filter kind=module", artifactsTableContext());
    expect(action).toEqual({
      type: "ui.action",
      action: {
        name: "canvas.update_table_query",
        target: { panel_id: "p1" },
        params: {
          mode: "patch",
          query_patch: {
            filters_add: [{ field: "kind", op: "eq", value: "module" }],
          },
        },
      },
    });
  });

  it("opens registrations dataset for cross-dataset navigation", () => {
    const action = buildUiActionFromPrompt("show registrations in the past 24 hours", artifactsTableContext());
    expect(action?.type).toBe("ui.action");
    expect(action?.action.name).toBe("canvas.open_table");
    expect(action?.action.params.dataset).toBe("ems_registrations");
  });

  it("opens runs dataset for platform command", () => {
    const action = buildUiActionFromPrompt("show runs", artifactsTableContext());
    expect(action?.type).toBe("ui.action");
    expect(action?.action.name).toBe("canvas.open_table");
    expect(action?.action.params.dataset).toBe("runs");
  });

  it("applies namespace filter for list namespace artifacts command", () => {
    const action = buildUiActionFromPrompt("list core artifacts", artifactsTableContext());
    expect(action).toEqual({
      type: "ui.action",
      action: {
        name: "canvas.open_table",
        params: {
          dataset: "artifacts",
          query: {
            entity: "artifacts",
            filters: [{ field: "namespace", op: "eq", value: "core" }],
            sort: [{ field: "updated_at", dir: "desc" }],
            limit: 50,
            offset: 0,
          },
          title: "artifacts",
          open_in: "current_panel",
          placement: "center",
        },
      },
    });
  });

  it("opens detail tab action when current context is detail", () => {
    const action = buildUiActionFromPrompt("show raw", artifactDetailContext());
    expect(action).toEqual({
      type: "ui.action",
      action: {
        name: "canvas.open_detail",
        target: { panel_id: "p2" },
        params: { tab: "raw" },
      },
    });
  });

  it("selects and opens first row from active table", () => {
    const action = buildUiActionFromPrompt("open row 1", artifactsTableContext());
    expect(action).toEqual({
      type: "ui.action",
      action: {
        name: "canvas.select_rows",
        target: { panel_id: "p1" },
        params: {
          row_ids: ["core.authn-jwt"],
          focused_row_id: "core.authn-jwt",
          open_detail: true,
          entity_type: "artifact",
          entity_id: "core.authn-jwt",
          dataset: "artifacts",
        },
      },
    });
  });

  it("returns null for unsupported field filter", () => {
    const action = buildUiActionFromPrompt("filter no_such_field=abc", artifactsTableContext());
    expect(action).toBeNull();
  });

  it("falls back to context-aware table search for unmatched follow-up prompts", () => {
    const action = buildUiActionFromPrompt("show only artifacts related to auth", artifactsTableContext());
    expect(action).toEqual({
      type: "ui.action",
      action: {
        name: "canvas.update_table_query",
        target: { panel_id: "p1" },
        params: {
          mode: "patch",
          query_patch: {
            filters_add: [{ field: "slug", op: "contains", value: "only artifacts related to auth" }],
            offset: 0,
          },
        },
      },
    });
  });
});
