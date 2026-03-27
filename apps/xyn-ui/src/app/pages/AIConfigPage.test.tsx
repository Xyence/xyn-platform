import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AIConfigPage from "./AIConfigPage";

const apiMocks = vi.hoisted(() => ({
  listAiProviders: vi.fn(),
  listAiCredentials: vi.fn(),
  listAiModelConfigs: vi.fn(),
  listAiPurposes: vi.fn(),
  listAiAgents: vi.fn(),
  listContextPacks: vi.fn(),
  updateAiCredential: vi.fn(),
  deleteAiCredential: vi.fn(),
  updateAiModelConfig: vi.fn(),
  deleteAiModelConfig: vi.fn(),
  updateAiAgent: vi.fn(),
  deleteAiAgent: vi.fn(),
  updateAiPurpose: vi.fn(),
  deleteAiPurpose: vi.fn(),
  createAiCredential: vi.fn(),
  createAiModelConfig: vi.fn(),
  createAiAgent: vi.fn(),
  createAiPurpose: vi.fn(),
}));

vi.mock("../../api/xyn", () => apiMocks);
vi.mock("../state/notificationsStore", () => ({
  useNotifications: () => ({ push: vi.fn() }),
}));

describe("AIConfigPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listAiProviders.mockResolvedValue({ providers: [{ id: "p1", slug: "openai", name: "OpenAI", enabled: true }] });
    apiMocks.listAiCredentials.mockResolvedValue({ credentials: [] });
    apiMocks.listAiModelConfigs.mockResolvedValue({ model_configs: [] });
    apiMocks.listAiPurposes.mockResolvedValue({ purposes: [{ slug: "documentation", status: "active", preamble: "", enabled: true }] });
    apiMocks.listAiAgents.mockResolvedValue({ agents: [] });
    apiMocks.listContextPacks.mockResolvedValue({ context_packs: [] });
    apiMocks.createAiAgent.mockResolvedValue({
      agent: {
        id: "agent-1",
        slug: "doc-agent",
        name: "Doc Agent",
        avatar_url: "https://example.test/agent.png",
        model_config_id: "model-1",
        enabled: true,
        purposes: ["documentation"],
      },
    });
  });

  it("defaults to agents tab and updates create label when switching tabs", async () => {
    render(
      <MemoryRouter initialEntries={["/app/platform/ai-agents"]}>
        <Routes>
          <Route path="/app/platform/ai-agents" element={<AIConfigPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText("AI Agents")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Create agent" })).toBeInTheDocument());
    await userEvent.click(screen.getByRole("tab", { name: "Credentials" }));
    expect(await screen.findByRole("button", { name: "Create credential" })).toBeInTheDocument();
  });

  it("captures an optional profile image URL when creating an agent", async () => {
    apiMocks.listAiModelConfigs.mockResolvedValue({
      model_configs: [{ id: "model-1", provider: "openai", model_name: "gpt-5-mini", enabled: true }],
    });

    render(
      <MemoryRouter initialEntries={["/app/platform/ai-agents"]}>
        <Routes>
          <Route path="/app/platform/ai-agents" element={<AIConfigPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText("AI Agents")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Model Configs" }));
    await userEvent.click(await screen.findByRole("tab", { name: "Agents" }));
    await userEvent.click(await screen.findByRole("button", { name: "Create agent" }));
    await userEvent.type(screen.getByLabelText("Name"), "Doc Agent");
    await userEvent.type(screen.getByLabelText("Slug"), "doc-agent");
    await userEvent.type(screen.getByLabelText("Profile image URL (optional)"), "https://example.test/agent.png");
    await userEvent.selectOptions(screen.getByLabelText("Model config"), "model-1");
    await userEvent.click(screen.getAllByRole("button", { name: "Create agent" }).slice(-1)[0]);

    await waitFor(() => {
      expect(apiMocks.createAiAgent).toHaveBeenCalledWith(
        expect.objectContaining({
          avatar_url: "https://example.test/agent.png",
        }),
      );
    });
  });
});
