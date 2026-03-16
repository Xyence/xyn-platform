import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useContextualCapabilities } from "../components/console/contextualCapabilities";
import { useCapabilityPaths } from "../components/console/capabilityPaths";
import { emitCapabilityEvent } from "./emitCapabilityEvent";

const apiMocks = vi.hoisted(() => ({
  getContextualCapabilities: vi.fn(),
  getCapabilityPaths: vi.fn(),
  emitCapabilityRefreshEvent: vi.fn(),
}));

vi.mock("../../api/xyn", () => ({
  getContextualCapabilities: apiMocks.getContextualCapabilities,
  getCapabilityPaths: apiMocks.getCapabilityPaths,
  emitCapabilityRefreshEvent: apiMocks.emitCapabilityRefreshEvent,
}));

function Harness() {
  const capabilities = useContextualCapabilities({
    context: "app_intent_draft",
    entityId: "draft-1",
    workspaceId: "ws-1",
    includeUnavailable: true,
  });
  const paths = useCapabilityPaths({
    context: "app_intent_draft",
    entityId: "draft-1",
    workspaceId: "ws-1",
  });

  return (
    <div>
      <span data-testid="capabilities">{capabilities.capabilities.map((entry) => entry.id).join(",")}</span>
      <span data-testid="path">{paths.selectedPath?.steps?.[0]?.capability_id || ""}</span>
    </div>
  );
}

describe("emitCapabilityEvent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getContextualCapabilities
      .mockResolvedValueOnce({
        context: "app_intent_draft",
        attributes: {},
        capabilities: [
          {
            id: "continue_application_draft",
            name: "Continue application design",
            description: "Continue shaping the current application draft in the workbench.",
            visibility: "primary",
            available: true,
          },
        ],
      })
      .mockResolvedValueOnce({
        context: "app_intent_draft",
        attributes: {},
        capabilities: [
          {
            id: "open_application_workspace",
            name: "Open application workspace",
            description: "Open the application workbench for this application context.",
            visibility: "secondary",
            available: true,
          },
        ],
      });
    apiMocks.getCapabilityPaths
      .mockResolvedValueOnce({
        context: "app_intent_draft",
        paths: [
          {
            id: "build_application",
            name: "Build Application",
            description: "Guided flow",
            steps: [{ capability_id: "continue_application_draft", name: "Continue application design", description: "", visibility: "primary" }],
          },
        ],
      })
      .mockResolvedValueOnce({
        context: "app_intent_draft",
        paths: [
          {
            id: "build_application",
            name: "Build Application",
            description: "Guided flow",
            steps: [{ capability_id: "open_application_workspace", name: "Open application workspace", description: "", visibility: "secondary" }],
          },
        ],
      });
    apiMocks.emitCapabilityRefreshEvent.mockResolvedValue({
      event_type: "execution_completed",
      entityId: "draft-1",
      workspaceId: "ws-1",
      contexts: [
        {
          context: "app_intent_draft",
          entityId: "draft-1",
          workspaceId: "ws-1",
          attributes: {},
          capabilities: [],
          paths: [],
        },
      ],
    });
  });

  it("refreshes capability hooks when a matching capability event is emitted", async () => {
    render(<Harness />);

    await waitFor(() => expect(screen.getByTestId("capabilities").textContent).toBe("continue_application_draft"));
    await waitFor(() => expect(screen.getByTestId("path").textContent).toBe("continue_application_draft"));

    await act(async () => {
      await emitCapabilityEvent({
        eventType: "execution_completed",
        entityId: "draft-1",
        workspaceId: "ws-1",
      });
    });

    await waitFor(() => expect(screen.getByTestId("capabilities").textContent).toBe("open_application_workspace"));
    await waitFor(() => expect(screen.getByTestId("path").textContent).toBe("open_application_workspace"));
    expect(apiMocks.emitCapabilityRefreshEvent).toHaveBeenCalledWith({
      event_type: "execution_completed",
      entity_id: "draft-1",
      workspace_id: "ws-1",
    });
    expect(apiMocks.getContextualCapabilities).toHaveBeenCalledTimes(2);
    expect(apiMocks.getCapabilityPaths).toHaveBeenCalledTimes(2);
  });
});
