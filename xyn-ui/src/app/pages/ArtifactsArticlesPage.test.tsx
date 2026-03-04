import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ArtifactsArticlesPage from "./ArtifactsArticlesPage";
import type { ArticleSummary } from "../../api/types";

const apiMocks = vi.hoisted(() => ({
  createArticle: vi.fn(),
  createArticleCategory: vi.fn(),
  createCategoryBinding: vi.fn(),
  deleteArticleCategory: vi.fn(),
  deleteCategoryBinding: vi.fn(),
  listArticleCategories: vi.fn(),
  listArticles: vi.fn(),
  listCategoryBindings: vi.fn(),
  updateArticleCategory: vi.fn(),
}));

const navigateMock = vi.hoisted(() => vi.fn());
const pushMock = vi.hoisted(() => vi.fn());

vi.mock("../../api/xyn", () => apiMocks);
vi.mock("../state/notificationsStore", () => ({
  useNotifications: () => ({ push: pushMock }),
}));
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

function makeArticle(overrides: Partial<ArticleSummary> = {}): ArticleSummary {
  return {
    id: "art-1",
    workspace_id: "ws-1",
    type: "article",
    format: "standard",
    title: "Sample Article",
    slug: "sample-article",
    status: "draft",
    version: 1,
    category: "web",
    visibility_type: "private",
    allowed_roles: [],
    route_bindings: [],
    tags: [],
    summary: "",
    ...overrides,
  };
}

describe("ArtifactsArticlesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listArticles.mockResolvedValue({ articles: [makeArticle(), makeArticle({ id: "art-2", title: "Second", slug: "second" })] });
    apiMocks.listArticleCategories.mockResolvedValue({
      categories: [
        { id: "cat-1", slug: "web", name: "Web", description: "", enabled: true, referenced_article_count: 1 },
        { id: "cat-2", slug: "demo", name: "Demo", description: "", enabled: true, referenced_article_count: 0 },
      ],
    });
    apiMocks.listCategoryBindings.mockResolvedValue({ bindings: [] });
    apiMocks.createArticle.mockResolvedValue({ article: { id: "art-99" } });
  });

  it("opens and closes New Article modal", async () => {
    render(
      <MemoryRouter>
        <ArtifactsArticlesPage workspaceId="ws-1" canCreate />
      </MemoryRouter>
    );

    await screen.findByText("Sample Article");
    await userEvent.click(screen.getByRole("button", { name: "New Article" }));
    expect(screen.getByRole("dialog", { name: "New Article" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "New Article" })).not.toBeInTheDocument());
  });

  it("creates a draft and navigates to the editor route", async () => {
    render(
      <MemoryRouter>
        <ArtifactsArticlesPage workspaceId="ws-1" canCreate />
      </MemoryRouter>
    );

    await screen.findByText("Sample Article");
    await userEvent.click(screen.getByRole("button", { name: "New Article" }));
    await userEvent.type(screen.getByLabelText("Title"), "My Draft");
    await userEvent.selectOptions(screen.getByLabelText("Category"), "demo");
    await userEvent.selectOptions(screen.getByLabelText("Create as"), "video_explainer");
    await userEvent.click(screen.getByRole("button", { name: "Create draft" }));

    await waitFor(() =>
      expect(apiMocks.createArticle).toHaveBeenCalledWith(
        expect.objectContaining({ title: "My Draft", category: "demo", format: "video_explainer" })
      )
    );
    expect(navigateMock).toHaveBeenCalledWith("/app/artifacts/art-99");
  });

  it("filters the article list from the search input", async () => {
    render(
      <MemoryRouter>
        <ArtifactsArticlesPage workspaceId="ws-1" canCreate />
      </MemoryRouter>
    );

    expect(await screen.findByText("Sample Article")).toBeInTheDocument();
    expect(screen.getByText("Second")).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText("Search title, slug, summary, tags"), "sample");
    expect(screen.getByText("Sample Article")).toBeInTheDocument();
    expect(screen.queryByText("Second")).not.toBeInTheDocument();
  });
});
