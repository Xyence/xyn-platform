import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WorkbenchPanelHost from "./WorkbenchPanelHost";
import { emitEntityChange } from "../../utils/entityChangeEvents";

const apiMocks = vi.hoisted(() => ({
  executeAppPalettePrompt: vi.fn(),
}));

vi.mock("../../../api/xyn", async () => {
  const actual = await vi.importActual<typeof import("../../../api/xyn")>("../../../api/xyn");
  return {
    ...actual,
    executeAppPalettePrompt: apiMocks.executeAppPalettePrompt,
  };
});

describe("WorkbenchPanelHost entity refresh", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("reloads a visible matching entity table after an entity change", async () => {
    apiMocks.executeAppPalettePrompt.mockResolvedValue({
      kind: "table",
      columns: ["id", "name", "status"],
      rows: [{ id: "dev-2", name: "router-2", status: "offline" }],
      text: "Found 1 devices.",
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{
            panel_id: "panel-1",
            panel_type: "table",
            instance_key: "palette_result",
            title: "Palette Result",
            key: "palette_result",
            params: {
              prompt: "show devices",
              result: {
                kind: "table",
                columns: ["id", "name", "status"],
                rows: [{ id: "dev-1", name: "router-1", status: "online" }],
                text: "Found 1 devices.",
              },
            },
          }}
          onOpenPanel={() => {}}
        />
      </MemoryRouter>
    );

    expect(screen.getByText("router-1")).toBeInTheDocument();
    emitEntityChange({ entityKey: "devices", operation: "update", source: "palette" });

    await waitFor(() => expect(apiMocks.executeAppPalettePrompt).toHaveBeenCalledWith("ws-1", { prompt: "show devices" }));
    await waitFor(() => expect(screen.getByText("router-2")).toBeInTheDocument());
  });

  it("does not reload when a different entity changes", async () => {
    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{
            panel_id: "panel-1",
            panel_type: "table",
            instance_key: "palette_result",
            title: "Palette Result",
            key: "palette_result",
            params: {
              prompt: "show devices",
              result: {
                kind: "table",
                columns: ["id", "name", "status"],
                rows: [{ id: "dev-1", name: "router-1", status: "online" }],
                text: "Found 1 devices.",
              },
            },
          }}
          onOpenPanel={() => {}}
        />
      </MemoryRouter>
    );

    emitEntityChange({ entityKey: "locations", operation: "delete", source: "palette" });

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(apiMocks.executeAppPalettePrompt).not.toHaveBeenCalled();
    expect(screen.getByText("router-1")).toBeInTheDocument();
  });
});
