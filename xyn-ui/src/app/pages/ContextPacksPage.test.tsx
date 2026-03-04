import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi, beforeEach } from "vitest";
import ContextPacksPage from "./ContextPacksPage";

const apiMocks = vi.hoisted(() => ({
  listContextPacks: vi.fn(),
  listArtifacts: vi.fn(),
  getContextPack: vi.fn(),
  getArtifact: vi.fn(),
  listArtifactActivity: vi.fn(),
  createContextPack: vi.fn(),
  updateArtifactRecord: vi.fn(),
}));

vi.mock("../../api/xyn", () => apiMocks);

describe("ContextPacksPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    apiMocks.listContextPacks.mockResolvedValue({
      context_packs: [
        {
          id: "pack-a",
          artifact_id: "artifact-a",
          name: "Pack A",
          purpose: "any",
          scope: "global",
          version: "1.0.0",
          is_active: true,
          is_default: false,
          applies_to_json: {},
        },
        {
          id: "pack-b",
          artifact_id: "artifact-b",
          name: "Pack B",
          purpose: "planner",
          scope: "global",
          version: "1.0.0",
          is_active: true,
          is_default: false,
          applies_to_json: {},
        },
      ],
    });

    apiMocks.listArtifacts.mockResolvedValue({
      artifacts: [
        {
          id: "artifact-a",
          artifact_id: "artifact-a",
          artifact_type: "context_pack",
          artifact_state: "canonical",
          title: "Pack A",
        },
        {
          id: "artifact-b",
          artifact_id: "artifact-b",
          artifact_type: "context_pack",
          artifact_state: "canonical",
          title: "Pack B",
        },
      ],
      count: 2,
      limit: 500,
      offset: 0,
    });

    apiMocks.getContextPack.mockImplementation(async (id: string) => ({
      id,
      artifact_id: id === "pack-a" ? "artifact-a" : "artifact-b",
      name: id === "pack-a" ? "Pack A" : "Pack B",
      purpose: "any",
      scope: "global",
      version: "1.0.0",
      is_active: true,
      is_default: false,
      applies_to_json: {},
      content_markdown: "{}",
    }));

    apiMocks.getArtifact.mockResolvedValue({
      id: "artifact-a",
      artifact_id: "artifact-a",
      artifact_type: "context_pack",
      artifact_state: "canonical",
      title: "Pack A",
    });

    apiMocks.listArtifactActivity.mockResolvedValue({ events: [], count: 0, limit: 30, offset: 0 });
  });

  it("keeps selected pack stable when switching rows", async () => {
    render(
      <MemoryRouter initialEntries={["/app/context-packs?pack=pack-a"]}>
        <Routes>
          <Route path="/app/context-packs" element={<ContextPacksPage />} />
        </Routes>
      </MemoryRouter>
    );

    await screen.findByRole("button", { name: /Pack A/i });

    const packBButton = await screen.findByRole("button", { name: /Pack B/i });
    await userEvent.click(packBButton);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Pack B/i }).className).toContain("active");
    });

    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(screen.getByRole("button", { name: /Pack B/i }).className).toContain("active");
  });

  it("does not render generic artifact share and intent actions", async () => {
    render(
      <MemoryRouter initialEntries={["/app/context-packs?pack=pack-a"]}>
        <Routes>
          <Route path="/app/context-packs" element={<ContextPacksPage />} />
        </Routes>
      </MemoryRouter>
    );

    await screen.findByText("Context pack detail");
    expect(screen.queryByRole("button", { name: /Generate Intent Script/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Copy summary/i })).not.toBeInTheDocument();
  });
});
