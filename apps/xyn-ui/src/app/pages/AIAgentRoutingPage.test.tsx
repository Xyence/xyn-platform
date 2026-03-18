import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AIAgentRoutingPage from "./AIAgentRoutingPage";

const apiMocks = vi.hoisted(() => ({
  getAiRoutingStatus: vi.fn(),
  listAiAgents: vi.fn(),
  updateAiRouting: vi.fn(),
}));

const notificationMocks = vi.hoisted(() => ({
  push: vi.fn(),
}));

vi.mock("../../api/xyn", () => apiMocks);
vi.mock("../state/notificationsStore", () => ({
  useNotifications: () => notificationMocks,
}));

describe("AIAgentRoutingPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getAiRoutingStatus.mockResolvedValue({
      routing: [
        {
          purpose: "default",
          resolved_agent_id: "agent-default",
          resolved_agent_name: "Bootstrap Default Agent",
          resolution_source: "default_fallback",
          resolution_type: "required_default",
        },
        {
          purpose: "planning",
          resolved_agent_id: "agent-default",
          resolved_agent_name: "Bootstrap Default Agent",
          fallback_agent_id: "agent-default",
          fallback_agent_name: "Bootstrap Default Agent",
          resolution_source: "default_fallback",
          resolution_type: "falls_back_to_default",
        },
        {
          purpose: "coding",
          resolved_agent_id: "agent-default",
          resolved_agent_name: "Bootstrap Default Agent",
          fallback_agent_id: "agent-default",
          fallback_agent_name: "Bootstrap Default Agent",
          resolution_source: "default_fallback",
          resolution_type: "falls_back_to_default",
        },
      ],
      recent_resolutions: [],
    });
    apiMocks.listAiAgents.mockResolvedValue({
      agents: [
        {
          id: "agent-default",
          slug: "default-assistant",
          name: "Bootstrap Default Agent",
          model_config_id: "model-1",
          is_default: true,
          enabled: true,
          purposes: ["planning", "coding"],
        },
        {
          id: "agent-plan",
          slug: "planner",
          name: "Claude Planning Agent",
          model_config_id: "model-2",
          is_default: false,
          enabled: true,
          purposes: ["planning"],
        },
      ],
    });
  });

  it("renders routing rows", async () => {
    render(<AIAgentRoutingPage />);
    expect(await screen.findByRole("heading", { name: "AI Agent Routing" })).toBeInTheDocument();
    expect(screen.getByText("Default")).toBeInTheDocument();
    expect(screen.getByText("Planning")).toBeInTheDocument();
    expect(screen.getByText("Coding")).toBeInTheDocument();
    expect(screen.getByText("Required Default")).toBeInTheDocument();
    expect(screen.getAllByText("Falls Back To Default").length).toBeGreaterThan(0);
  });

  it("assigns and clears planning routing", async () => {
    const user = userEvent.setup();
    apiMocks.updateAiRouting
      .mockResolvedValueOnce({
        routing: [
          {
            purpose: "default",
            resolved_agent_id: "agent-default",
            resolved_agent_name: "Bootstrap Default Agent",
            resolution_source: "default_fallback",
            resolution_type: "required_default",
          },
          {
            purpose: "planning",
            resolved_agent_id: "agent-plan",
            resolved_agent_name: "Claude Planning Agent",
            explicit_agent_id: "agent-plan",
            explicit_agent_name: "Claude Planning Agent",
            fallback_agent_id: "agent-default",
            fallback_agent_name: "Bootstrap Default Agent",
            resolution_source: "explicit",
            resolution_type: "explicit",
          },
          {
            purpose: "coding",
            resolved_agent_id: "agent-default",
            resolved_agent_name: "Bootstrap Default Agent",
            fallback_agent_id: "agent-default",
            fallback_agent_name: "Bootstrap Default Agent",
            resolution_source: "default_fallback",
            resolution_type: "falls_back_to_default",
          },
        ],
        recent_resolutions: [],
      })
      .mockResolvedValueOnce({
        routing: [
          {
            purpose: "default",
            resolved_agent_id: "agent-default",
            resolved_agent_name: "Bootstrap Default Agent",
            resolution_source: "default_fallback",
            resolution_type: "required_default",
          },
          {
            purpose: "planning",
            resolved_agent_id: "agent-default",
            resolved_agent_name: "Bootstrap Default Agent",
            fallback_agent_id: "agent-default",
            fallback_agent_name: "Bootstrap Default Agent",
            resolution_source: "default_fallback",
            resolution_type: "falls_back_to_default",
          },
          {
            purpose: "coding",
            resolved_agent_id: "agent-default",
            resolved_agent_name: "Bootstrap Default Agent",
            fallback_agent_id: "agent-default",
            fallback_agent_name: "Bootstrap Default Agent",
            resolution_source: "default_fallback",
            resolution_type: "falls_back_to_default",
          },
        ],
        recent_resolutions: [],
      });

    render(<AIAgentRoutingPage />);
    await screen.findByRole("heading", { name: "AI Agent Routing" });

    const planningRow = screen.getByText("Planning").closest("tr");
    expect(planningRow).toBeTruthy();
    if (!planningRow) return;

    await user.click(within(planningRow).getByRole("button", { name: "Change" }));
    await user.selectOptions(within(planningRow).getByRole("combobox", { name: "Planning agent selector" }), "agent-plan");
    await user.click(within(planningRow).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(apiMocks.updateAiRouting).toHaveBeenCalledWith({ planning_agent_id: "agent-plan" }));

    await user.click(within(planningRow).getByRole("button", { name: "Change" }));
    await user.click(within(planningRow).getByRole("button", { name: "Clear" }));

    await waitFor(() => expect(apiMocks.updateAiRouting).toHaveBeenCalledWith({ planning_agent_id: null }));
  });
});
