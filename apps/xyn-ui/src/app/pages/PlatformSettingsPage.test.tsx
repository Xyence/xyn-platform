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
      storage_status: {
        configured_provider: { name: "local", type: "local", complete: true, summary: "Local platform-managed storage at /tmp/xyn-uploads" },
        effective_platform_storage: { provider: "local", mode: "filesystem", configured: true },
        effective_runtime_artifact_storage: { provider: "local", mode: "filesystem", path: "/app/media" },
        remote_durability_active: false,
        warnings: [
          "Artifacts are currently stored only on local filesystem storage. Remote-backed storage is not active, so artifacts may not be preserved across host loss or environment rebuilds.",
        ],
      },
    });
    apiMocks.listVideoAdapters.mockResolvedValue({ adapters: [], feature_flags: {} });
    apiMocks.listVideoAdapterConfigs.mockResolvedValue({ configs: [] });
    apiMocks.updatePlatformConfig.mockResolvedValue({
      version: 1,
      config: undefined,
      storage_status: {
        configured_provider: { name: "local", type: "local", complete: true, summary: "Local platform-managed storage at /tmp/xyn-uploads" },
        effective_platform_storage: { provider: "local", mode: "filesystem", configured: true },
        effective_runtime_artifact_storage: { provider: "local", mode: "filesystem", path: "/app/media" },
        remote_durability_active: false,
        warnings: [
          "Artifacts are currently stored only on local filesystem storage. Remote-backed storage is not active, so artifacts may not be preserved across host loss or environment rebuilds.",
        ],
      },
    });
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

  it("shows a warning when runtime artifact storage is local-only", async () => {
    renderPage("/w/ws-1/platform/settings");
    expect(await screen.findByText("Effective runtime artifact storage")).toBeInTheDocument();
    expect(screen.getByText("Remote-backed durability")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Artifacts are currently stored only on local filesystem storage. Remote-backed storage is not active, so artifacts may not be preserved across host loss or environment rebuilds."
      )
    ).toBeInTheDocument();
  });

  it("distinguishes configured S3 from effective runtime storage", async () => {
    apiMocks.getPlatformConfig.mockResolvedValueOnce({
      version: 2,
      config: {
        storage: {
          primary: { type: "s3", name: "default" },
          providers: [
            { name: "local", type: "local", local: { base_path: "/tmp/xyn-uploads" } },
            { name: "default", type: "s3", s3: { bucket: "xyn-artifacts", region: "us-east-1", prefix: "xyn/", acl: "private" } },
          ],
        },
        notifications: { enabled: true, channels: [] },
      },
      storage_status: {
        configured_provider: { name: "default", type: "s3", complete: true, summary: "S3 bucket xyn-artifacts in us-east-1" },
        effective_platform_storage: { provider: "s3", mode: "object_storage", configured: true },
        effective_runtime_artifact_storage: { provider: "local", mode: "filesystem", path: "/app/media" },
        remote_durability_active: false,
        warnings: [
          "Artifacts are currently stored only on local filesystem storage. Remote-backed storage is not active, so artifacts may not be preserved across host loss or environment rebuilds.",
          "S3 is configured for platform-managed storage, but core runtime artifacts still use local filesystem storage today.",
        ],
      },
    });

    renderPage("/w/ws-1/platform/settings");
    expect(await screen.findByText("S3 bucket xyn-artifacts in us-east-1")).toBeInTheDocument();
    expect(screen.getByText("S3 object storage")).toBeInTheDocument();
    expect(screen.getByText("Local filesystem")).toBeInTheDocument();
    expect(
      screen.getByText("S3 is configured for platform-managed storage, but core runtime artifacts still use local filesystem storage today.")
    ).toBeInTheDocument();
  });
});
