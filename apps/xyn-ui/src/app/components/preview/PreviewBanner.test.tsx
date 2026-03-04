import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PreviewProvider } from "../../state/previewStore";
import PreviewBanner from "./PreviewBanner";

const apiMocks = vi.hoisted(() => ({
  getPreviewStatus: vi.fn(),
  enablePreview: vi.fn(),
  disablePreview: vi.fn(),
}));

vi.mock("../../../api/xyn", async () => {
  const actual = await vi.importActual<typeof import("../../../api/xyn")>("../../../api/xyn");
  return {
    ...actual,
    getPreviewStatus: apiMocks.getPreviewStatus,
    enablePreview: apiMocks.enablePreview,
    disablePreview: apiMocks.disablePreview,
  };
});

describe("PreviewBanner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders when preview is active and exits", async () => {
    apiMocks.getPreviewStatus.mockResolvedValue({
      preview: {
        enabled: true,
        roles: ["platform_operator"],
        read_only: true,
        actor_roles: ["platform_admin"],
        effective_roles: ["platform_operator"],
      },
    });
    apiMocks.disablePreview.mockResolvedValue({
      preview: {
        enabled: false,
        roles: [],
        read_only: true,
        actor_roles: ["platform_admin"],
        effective_roles: ["platform_admin"],
      },
    });

    const onExit = vi.fn(async () => undefined);

    render(
      <PreviewProvider>
        <PreviewBanner actorLabel="admin@example.com" onExit={onExit} />
      </PreviewProvider>
    );

    expect(await screen.findByText(/Previewing as: platform_operator/i)).toBeInTheDocument();
    expect(screen.getByText(/Read-only/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Exit preview" }));
    await waitFor(() => expect(onExit).toHaveBeenCalledTimes(1));
  });
});
