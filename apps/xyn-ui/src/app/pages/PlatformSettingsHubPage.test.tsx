import { MemoryRouter, Route, Routes } from "react-router-dom";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PlatformSettingsHubPage from "./PlatformSettingsHubPage";

const mockNavigate = vi.hoisted(() => vi.fn());

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/w/ws-1/platform/hub"]}>
      <Routes>
        <Route path="/w/:workspaceId/platform/hub" element={<PlatformSettingsHubPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("PlatformSettingsHubPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uses in-panel open callback when provided", async () => {
    const onOpenRoute = vi.fn();
    render(
      <MemoryRouter initialEntries={["/w/ws-1/platform/hub"]}>
        <Routes>
          <Route path="/w/:workspaceId/platform/hub" element={<PlatformSettingsHubPage onOpenRoute={onOpenRoute} />} />
        </Routes>
      </MemoryRouter>
    );
    fireEvent.click((await screen.findAllByRole("button", { name: "Open" }))[0]);
    expect(onOpenRoute).toHaveBeenCalledTimes(1);
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("falls back to route navigation without callback", async () => {
    renderPage();
    fireEvent.click((await screen.findAllByRole("button", { name: "Open" }))[0]);
    expect(mockNavigate).toHaveBeenCalledTimes(1);
  });
});
