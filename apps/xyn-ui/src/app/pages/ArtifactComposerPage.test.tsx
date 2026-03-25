import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ArtifactComposerPage from "./ArtifactComposerPage";

const apiMocks = vi.hoisted(() => ({
  getArtifact: vi.fn(),
}));

vi.mock("../../api/xyn", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/xyn")>();
  return {
    ...actual,
    getArtifact: (...args: unknown[]) => apiMocks.getArtifact(...args),
  };
});

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{`${location.pathname}${location.search}`}</div>;
}

describe("ArtifactComposerPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("opens composer-oriented workbench flow scoped to the selected artifact", async () => {
    apiMocks.getArtifact.mockResolvedValue({
      id: "artifact-1",
      slug: "xyn-api",
      name: "xyn-api",
      title: "Xyn API",
      type: "service",
      version: "0.1.0",
      package_version: "0.1.0",
      updated_at: "2026-03-24T00:00:00Z",
      created_at: "2026-03-24T00:00:00Z",
    });

    render(
      <MemoryRouter initialEntries={["/w/ws-1/build/artifacts/artifact-1"]}>
        <Routes>
          <Route path="/w/:workspaceId/build/artifacts/:artifactId" element={<ArtifactComposerPage workspaceId="ws-1" />} />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    );

    await screen.findByText("Xyn API");
    fireEvent.click(screen.getByRole("button", { name: "Generate Plan" }));

    await waitFor(() =>
      expect(screen.getByTestId("location-probe").textContent).toContain("/w/ws-1/workbench?")
    );
    const destination = String(screen.getByTestId("location-probe").textContent || "");
    expect(destination).toContain("panel=composer_detail");
    expect(destination).toContain("revise=1");
    expect(destination).toContain("artifact_slug=xyn-api");
    expect(destination).toContain("artifact_type=service");
  });
});

