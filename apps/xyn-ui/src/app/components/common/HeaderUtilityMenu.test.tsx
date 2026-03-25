import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import HeaderUtilityMenu from "./HeaderUtilityMenu";

const apiMocks = vi.hoisted(() => ({
  getAiRoutingStatus: vi.fn(),
  getSystemReadiness: vi.fn(),
}));

vi.mock("../../../api/xyn", async () => {
  const actual = await vi.importActual<typeof import("../../../api/xyn")>("../../../api/xyn");
  return {
    ...actual,
    getAiRoutingStatus: apiMocks.getAiRoutingStatus,
    getSystemReadiness: apiMocks.getSystemReadiness,
  };
});

vi.mock("../console/capabilitySuggestions", () => ({
  useCapabilitySuggestions: () => ({
    loading: false,
    error: null,
    capabilities: [
      {
        key: "cap-1",
        artifactId: "artifact-1",
        artifactSlug: "artifact-1",
        title: "Campaigns",
        description: "Campaign workflows",
        version: "1.0.0",
        visibility: "capabilities",
        order: 10,
        managePath: "/app/campaigns",
        docsPath: "",
        suggestions: [
          {
            key: "s1",
            artifactId: "artifact-1",
            artifactSlug: "artifact-1",
            capabilityVisibility: "capabilities",
            capabilityLabel: "Campaigns",
            suggestionId: "s1",
            suggestionLabel: "Show campaigns",
            prompt: "show campaigns",
            description: "",
            order: 1,
            group: "",
            visibility: ["capability"],
          },
        ],
      },
    ],
    platform: [],
    landingSuggestions: [],
    paletteSuggestions: [],
  }),
}));

vi.mock("../preview/HeaderPreviewControl", () => ({
  default: () => <div>Preview control</div>,
}));

vi.mock("../../state/xynConsoleStore", () => ({
  useXynConsole: () => ({
    openPanel: vi.fn(),
    setInputText: vi.fn(),
    setOpen: vi.fn(),
    requestSubmit: vi.fn(),
  }),
}));

describe("HeaderUtilityMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getAiRoutingStatus.mockResolvedValue({
      routing: [
        { purpose: "default", resolved_agent_name: "Xyn Default Assistant", resolution_source: "explicit" },
        { purpose: "planning", resolved_agent_name: "gpt-planning", resolution_source: "explicit" },
        { purpose: "coding", resolved_agent_name: "gpt-coding", resolution_source: "default_fallback" },
      ],
      recent_resolutions: [],
    });
    apiMocks.getSystemReadiness.mockResolvedValue({
      ready: false,
      summary: "Configuration required",
      checks: [{ component: "coding_agents", status: "missing", message: "No usable coding credentials." }],
    });
  });

  it("renders consolidated utility sections and opens agent activity", async () => {
    const onOpenAgentActivity = vi.fn();
    render(
      <MemoryRouter>
        <HeaderUtilityMenu
          workspaceId="ws-1"
          actorRoles={["platform_admin"]}
          actorLabel="user@example.com"
          onOpenAgentActivity={onOpenAgentActivity}
          onMessage={vi.fn()}
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Utilities" }));
    expect(await screen.findByRole("heading", { name: /Capabilities/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Activity/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Preview As Role/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /AI Agent Routing/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /System Readiness/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Open Agent Activity/i }));
    expect(onOpenAgentActivity).toHaveBeenCalledTimes(1);

    await waitFor(() => expect(apiMocks.getAiRoutingStatus).toHaveBeenCalled());
    await waitFor(() => expect(apiMocks.getSystemReadiness).toHaveBeenCalled());
  });
});
