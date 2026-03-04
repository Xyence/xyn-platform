import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ArtifactDetailPage from "./ArtifactDetailPage";

const apiMocks = vi.hoisted(() => ({
  getArticle: vi.fn(),
  listArticleRevisions: vi.fn(),
  listArticleCategories: vi.fn(),
  listArticleVideoRenders: vi.fn(),
  listContextPacks: vi.fn(),
  applySeedPacks: vi.fn(),
  updateArticle: vi.fn(),
  createArticleRevision: vi.fn(),
  listAiAgents: vi.fn(),
  invokeAi: vi.fn(),
  transitionArticle: vi.fn(),
  initializeArticleVideo: vi.fn(),
  generateArticleVideoScript: vi.fn(),
  generateArticleVideoStoryboard: vi.fn(),
  getArticleVideoAiConfig: vi.fn(),
  updateArticleVideoAiConfig: vi.fn(),
  renderArticleVideo: vi.fn(),
  retryVideoRender: vi.fn(),
  cancelVideoRender: vi.fn(),
  commentOnWorkspaceArtifact: vi.fn(),
  moderateWorkspaceComment: vi.fn(),
  reactToWorkspaceArtifact: vi.fn(),
  convertArticleHtmlToMarkdown: vi.fn(),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useParams: () => ({ artifactId: "art-1" }),
    useLocation: () => ({ pathname: "/w/ws-1/build/artifacts/art-1", search: "" }),
  };
});

vi.mock("../../api/xyn", () => apiMocks);

vi.mock("../components/editor/MarkdownWysiwygEditor", () => ({
  default: ({ value, onChange }: { value: string; onChange: (next: string) => void }) => (
    <textarea aria-label="Article editor" value={value} onChange={(event) => onChange(event.target.value)} />
  ),
}));

vi.mock("../state/notificationsStore", () => ({
  useNotifications: () => ({ push: vi.fn() }),
}));

vi.mock("../state/operationRegistry", () => ({
  useOperations: () => ({ startOperation: vi.fn(), finishOperation: vi.fn() }),
}));

vi.mock("../state/xynConsoleStore", () => ({
  useXynConsole: () => ({
    session: { pendingMissingFields: [] },
    setContext: vi.fn(),
    clearContext: vi.fn(),
    registerEditorBridge: vi.fn(),
    unregisterEditorBridge: vi.fn(),
  }),
}));

describe("ArtifactDetailPage video explainer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getArticle.mockResolvedValue({
      article: {
        id: "art-1",
        workspace_id: "ws-1",
        title: "Video Article",
        slug: "video-article",
        summary: "summary",
        body_markdown: "hello",
        body_html: "",
        category: "guide",
        format: "video_explainer",
        status: "draft",
        visibility_type: "private",
        allowed_roles: [],
        tags: [],
        published_to: [],
        video_context_pack_id: "pack-1",
        video_spec_json: {
          version: 1,
          title: "Video Article",
          intent: "initial intent",
          audience: "mixed",
          tone: "clear",
          duration_seconds_target: 120,
          voice: { style: "conversational", speaker: "neutral", pace: "medium" },
          script: { draft: "", last_generated_at: null, notes: "", proposals: [] },
          storyboard: { draft: [], last_generated_at: null, notes: "", proposals: [] },
          scenes: [],
          generation: { provider: null, status: "not_started", last_render_id: null },
        },
      },
    });
    apiMocks.listArticleRevisions.mockResolvedValue({ revisions: [] });
    apiMocks.listArticleCategories.mockResolvedValue({ categories: [{ slug: "guide", name: "Guide", enabled: true }] });
    apiMocks.listArticleVideoRenders.mockResolvedValue({ renders: [] });
    apiMocks.listContextPacks.mockResolvedValue({
      context_packs: [{ id: "pack-1", name: "Explainer Pack", purpose: "video_explainer", scope: "global", version: "1.0.0", is_active: true, is_default: false }],
    });
    apiMocks.getArticleVideoAiConfig.mockResolvedValue({
      overrides: { agents: {}, context_packs: {} },
      effective: {
        explainer_script: {
          purpose_slug: "explainer_script",
          purpose_name: "Script",
          description: "Generate explainer narration scripts.",
          agent: { id: "agent-1", slug: "writer", name: "Writer Agent", model_provider: "openai", model_name: "gpt-4o-mini" },
          context_packs: [],
          source: "purpose_default",
          agent_source: "purpose_default",
          context_source: "purpose_default",
        },
      },
    });
    apiMocks.updateArticleVideoAiConfig.mockResolvedValue({
      overrides: { agents: { explainer_script: "writer" }, context_packs: {} },
      effective: {
        explainer_script: {
          purpose_slug: "explainer_script",
          purpose_name: "Script",
          description: "Generate explainer narration scripts.",
          agent: { id: "agent-1", slug: "writer", name: "Writer Agent", model_provider: "openai", model_name: "gpt-4o-mini" },
          context_packs: [],
          source: "override",
          agent_source: "override",
          context_source: "purpose_default",
        },
      },
      article: {},
    });
    apiMocks.listAiAgents.mockResolvedValue({ agents: [] });
    apiMocks.updateArticle.mockResolvedValue({ article: {} });
  });

  it("renders video explainer panel and saves overview spec edits", async () => {
    render(<ArtifactDetailPage workspaceId="ws-1" workspaceRole="owner" canManageArticleLifecycle />);
    expect(await screen.findByText("Explainer Video")).toBeInTheDocument();
    await waitFor(() => expect(apiMocks.listContextPacks).toHaveBeenCalledWith({ purpose: "video_explainer", active: true }));
    expect(screen.queryByText("AI Assist")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Refine/i }).length).toBeGreaterThan(0);

    const intent = screen.getByLabelText("Intent");
    await userEvent.clear(intent);
    await userEvent.type(intent, "new intent");
    await userEvent.click(screen.getByRole("button", { name: "Save explainer settings" }));

    await waitFor(() => expect(apiMocks.updateArticle).toHaveBeenCalled());
    const lastCall = apiMocks.updateArticle.mock.calls[apiMocks.updateArticle.mock.calls.length - 1] as [string, Record<string, unknown>];
    const [, payload] = lastCall;
    expect(payload.format).toBe("video_explainer");
    expect((payload.video_spec_json as Record<string, unknown>).intent).toBe("new intent");
  });

  it("shows AI Config tab for video_explainer and saves overrides", async () => {
    apiMocks.listAiAgents.mockImplementation(async ({ purpose }: { purpose?: string }) => {
      if (purpose === "explainer_script") {
        return {
          agents: [
            {
              id: "agent-1",
              slug: "writer",
              name: "Writer Agent",
              model_config: { provider: "openai", model_name: "gpt-4o-mini" },
              purposes: ["explainer_script"],
              model_config_id: "cfg-1",
              enabled: true,
            },
          ],
        };
      }
      return { agents: [] };
    });
    apiMocks.listContextPacks.mockImplementation(async ({ purpose }: { purpose?: string }) => {
      if (purpose === "explainer_script") {
        return {
          context_packs: [
            { id: "pack-2", name: "Script Pack", purpose: "explainer_script", scope: "global", version: "1.0.0", is_active: true, is_default: false },
          ],
        };
      }
      return { context_packs: [] };
    });
    render(<ArtifactDetailPage workspaceId="ws-1" workspaceRole="owner" canManageArticleLifecycle />);
    expect(await screen.findByText("Explainer Video")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "AI Configuration" }));
    expect(await screen.findByText("Agent is the primary control. Context packs are optional per-step overrides under Advanced.")).toBeInTheDocument();

    const agentSelect = screen.getAllByLabelText("Agent")[0];
    await userEvent.selectOptions(agentSelect, "writer");
    const aiPanelHeading = screen.getByRole("heading", { name: "AI Configuration" });
    const aiPanel = aiPanelHeading.closest(".activity-ai-config-panel");
    expect(aiPanel).toBeTruthy();
    await userEvent.click(within(aiPanel as HTMLElement).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(apiMocks.updateArticleVideoAiConfig).toHaveBeenCalledWith(
        "art-1",
        expect.objectContaining({
          agents: expect.objectContaining({ explainer_script: "writer" }),
        })
      )
    );
  });

  it("does not show AI Config tab for standard articles", async () => {
    apiMocks.getArticle.mockResolvedValueOnce({
      article: {
        id: "art-1",
        workspace_id: "ws-1",
        title: "Standard Article",
        slug: "standard-article",
        summary: "summary",
        body_markdown: "hello",
        body_html: "",
        category: "guide",
        format: "standard",
        status: "draft",
        visibility_type: "private",
        allowed_roles: [],
        tags: [],
        published_to: [],
      },
    });
    render(<ArtifactDetailPage workspaceId="ws-1" workspaceRole="owner" canManageArticleLifecycle />);
    expect(await screen.findByText("Article Editor")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "AI Configuration" })).not.toBeInTheDocument();
  });

  it("renders filtered provider outcome with reasons and remediation actions", async () => {
    apiMocks.listArticleVideoRenders.mockResolvedValue({
      renders: [
        {
          id: "render-1",
          article_id: "art-1",
          provider: "google_veo",
          status: "filtered",
          outcome: "filtered",
          requested_at: "2026-02-28T17:41:29Z",
          user_message: "Provider blocked media output due to policy.",
          provider_filtered_count: 1,
          provider_filtered_reasons: [
            "Sorry, we can't create videos with real people's names or likenesses.",
          ],
          user_actions: ["edit_prompt", "neutralize_prompt", "retry"],
          output_assets: [{ type: "export_package", url: "/xyn/api/articles/art-1/video/export-package" }],
        },
      ],
    });
    render(<ArtifactDetailPage workspaceId="ws-1" workspaceRole="owner" canManageArticleLifecycle />);
    expect(await screen.findByText("Explainer Video")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^Render$/ }));
    expect(await screen.findByText(/real people's names or likenesses/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit prompt" })).toBeInTheDocument();
  });

  it("shows prompt lint warning for real-person references before render", async () => {
    apiMocks.getArticle.mockResolvedValueOnce({
      article: {
        id: "art-1",
        workspace_id: "ws-1",
        title: "Video Article",
        slug: "video-article",
        summary: "summary",
        body_markdown: "hello",
        body_html: "",
        category: "guide",
        format: "video_explainer",
        status: "draft",
        visibility_type: "private",
        allowed_roles: [],
        tags: [],
        published_to: [],
        video_context_pack_id: "pack-1",
        video_spec_json: {
          version: 1,
          title: "Video Article",
          intent: "looks like Taylor Swift walking through a forest.",
          audience: "mixed",
          tone: "clear",
          duration_seconds_target: 120,
          voice: { style: "conversational", speaker: "neutral", pace: "medium" },
          script: { draft: "", last_generated_at: null, notes: "", proposals: [] },
          storyboard: { draft: [], last_generated_at: null, notes: "", proposals: [] },
          scenes: [],
          generation: { provider: null, status: "not_started", last_render_id: null },
        },
      },
    });
    render(<ArtifactDetailPage workspaceId="ws-1" workspaceRole="owner" canManageArticleLifecycle />);
    expect(await screen.findByText("Explainer Video")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^Render$/ }));
    expect(await screen.findByText(/This render may be blocked by provider policy/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Neutralize prompt" })).toBeInTheDocument();
  });
});
