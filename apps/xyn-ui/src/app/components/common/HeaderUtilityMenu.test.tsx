import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import HeaderUtilityMenu from "./HeaderUtilityMenu";

const navigateMock = vi.hoisted(() => vi.fn());
const apiMocks = vi.hoisted(() => ({
  getAiRoutingStatus: vi.fn(),
  getSystemReadiness: vi.fn(),
  getWorkspaceLinkedChangeSession: vi.fn(),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock("../../../api/xyn", async () => {
  const actual = await vi.importActual<typeof import("../../../api/xyn")>("../../../api/xyn");
  return {
    ...actual,
    getAiRoutingStatus: apiMocks.getAiRoutingStatus,
    getSystemReadiness: apiMocks.getSystemReadiness,
    getWorkspaceLinkedChangeSession: apiMocks.getWorkspaceLinkedChangeSession,
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
    navigateMock.mockReset();
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
    apiMocks.getWorkspaceLinkedChangeSession.mockResolvedValue({ linked_session: null });
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

  it("shows resume control only when linked session is active and navigates to composer session route", async () => {
    apiMocks.getWorkspaceLinkedChangeSession.mockResolvedValue({
      linked_session: {
        workspace_id: "ws-1",
        application_id: "app-1",
        solution_change_session_id: "scs-1",
        status: "planned",
        execution_status: "preview_ready",
      },
    });
    render(
      <MemoryRouter>
        <HeaderUtilityMenu
          workspaceId="ws-1"
          actorRoles={["platform_admin"]}
          actorLabel="user@example.com"
          onOpenAgentActivity={vi.fn()}
          onMessage={vi.fn()}
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Utilities" }));
    const button = await screen.findByRole("button", { name: /Resume change session/i });
    fireEvent.click(button);
    expect(navigateMock).toHaveBeenCalledWith(
      "/w/ws-1/workbench?panel=composer_detail&application_id=app-1&solution_change_session_id=scs-1"
    );
  });

  it("shows feedback and skips navigation when linked session is already focused", async () => {
    const onMessage = vi.fn();
    apiMocks.getWorkspaceLinkedChangeSession.mockResolvedValue({
      linked_session: {
        workspace_id: "ws-1",
        application_id: "app-1",
        solution_change_session_id: "scs-1",
        status: "planned",
      },
    });
    render(
      <MemoryRouter initialEntries={["/w/ws-1/workbench?panel=composer_detail&application_id=app-1&solution_change_session_id=scs-1"]}>
        <HeaderUtilityMenu
          workspaceId="ws-1"
          actorRoles={["platform_admin"]}
          actorLabel="user@example.com"
          onOpenAgentActivity={vi.fn()}
          onMessage={onMessage}
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Utilities" }));
    const button = await screen.findByRole("button", { name: /Resume change session/i });
    fireEvent.click(button);
    expect(navigateMock).not.toHaveBeenCalled();
    expect(onMessage).toHaveBeenCalledWith({ level: "success", title: "Already viewing linked session" });
  });

  it("hides resume control when no linked session is present", async () => {
    apiMocks.getWorkspaceLinkedChangeSession.mockResolvedValue({ linked_session: null });
    render(
      <MemoryRouter>
        <HeaderUtilityMenu
          workspaceId="ws-1"
          actorRoles={["platform_admin"]}
          actorLabel="user@example.com"
          onOpenAgentActivity={vi.fn()}
          onMessage={vi.fn()}
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Utilities" }));
    await waitFor(() => expect(apiMocks.getWorkspaceLinkedChangeSession).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /Resume change session/i })).not.toBeInTheDocument();
  });

  it("hides resume control when linked session payload is malformed", async () => {
    apiMocks.getWorkspaceLinkedChangeSession.mockResolvedValue({
      linked_session: {
        workspace_id: "ws-1",
        application_id: "",
        solution_change_session_id: "",
      },
    });
    render(
      <MemoryRouter>
        <HeaderUtilityMenu
          workspaceId="ws-1"
          actorRoles={["platform_admin"]}
          actorLabel="user@example.com"
          onOpenAgentActivity={vi.fn()}
          onMessage={vi.fn()}
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Utilities" }));
    await waitFor(() => expect(apiMocks.getWorkspaceLinkedChangeSession).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /Resume change session/i })).not.toBeInTheDocument();
  });
});
