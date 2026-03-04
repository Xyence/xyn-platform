import { MemoryRouter, Route, Routes } from "react-router-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PlatformSettingsPage from "./PlatformSettingsPage";

const mockNavigate = vi.hoisted(() => vi.fn());
const apiMocks = vi.hoisted(() => ({
  createVideoAdapterConfig: vi.fn(),
  getPlatformConfig: vi.fn(),
  listVideoAdapterConfigs: vi.fn(),
  listVideoAdapters: vi.fn(),
  testVideoAdapterConnection: vi.fn(),
  updatePlatformConfig: vi.fn(),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock("../../api/xyn", () => apiMocks);

function renderPage(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/w/:workspaceId/platform/settings" element={<PlatformSettingsPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("PlatformSettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getPlatformConfig.mockResolvedValue({
      version: 1,
      config: undefined,
    });
    apiMocks.listVideoAdapters.mockResolvedValue({ adapters: [], feature_flags: {} });
    apiMocks.listVideoAdapterConfigs.mockResolvedValue({ configs: [] });
    apiMocks.updatePlatformConfig.mockResolvedValue({ version: 1, config: undefined });
    apiMocks.createVideoAdapterConfig.mockResolvedValue({ config: null });
    apiMocks.testVideoAdapterConnection.mockResolvedValue({ ok: true, checks: [] });
  });

  it("renders new IA tabs and removes govern tab", async () => {
    renderPage("/w/ws-1/platform/settings");
    expect(await screen.findByRole("tab", { name: "General" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Security" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Integrations" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Deploy" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Workspaces" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Govern" })).not.toBeInTheDocument();
  });

  it("deep-links to deploy tab and keeps Instances as power-user link", async () => {
    renderPage("/w/ws-1/platform/settings?tab=deploy");
    expect(await screen.findByText("Release Plans")).toBeInTheDocument();
    expect(screen.getByText("Instances")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Instances" }));
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith("/w/ws-1/run/instances"));
  });
});
