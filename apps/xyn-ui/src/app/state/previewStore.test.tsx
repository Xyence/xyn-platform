import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PreviewProvider, usePreview } from "./previewStore";

const apiMocks = vi.hoisted(() => ({
  getPreviewStatus: vi.fn(),
  enablePreview: vi.fn(),
  disablePreview: vi.fn(),
}));

vi.mock("../../api/xyn", async () => {
  const actual = await vi.importActual<typeof import("../../api/xyn")>("../../api/xyn");
  return {
    ...actual,
    getPreviewStatus: apiMocks.getPreviewStatus,
    enablePreview: apiMocks.enablePreview,
    disablePreview: apiMocks.disablePreview,
  };
});

function Harness() {
  const { preview, enablePreviewMode, disablePreviewMode } = usePreview();
  return (
    <div>
      <div data-testid="enabled">{String(preview.enabled)}</div>
      <div data-testid="role">{preview.roles?.[0] || ""}</div>
      <button onClick={() => void enablePreviewMode(["platform_operator"], true)}>Enable</button>
      <button onClick={() => void disablePreviewMode()}>Disable</button>
    </div>
  );
}

describe("previewStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getPreviewStatus.mockResolvedValue({
      preview: { enabled: false, roles: [], read_only: true, actor_roles: ["platform_admin"], effective_roles: ["platform_admin"] },
    });
    apiMocks.enablePreview.mockResolvedValue({
      preview: { enabled: true, roles: ["platform_operator"], read_only: true, actor_roles: ["platform_admin"], effective_roles: ["platform_operator"] },
    });
    apiMocks.disablePreview.mockResolvedValue({
      preview: { enabled: false, roles: [], read_only: true, actor_roles: ["platform_admin"], effective_roles: ["platform_admin"] },
    });
  });

  it("loads status and toggles preview", async () => {
    render(
      <PreviewProvider>
        <Harness />
      </PreviewProvider>
    );

    await waitFor(() => expect(screen.getByTestId("enabled").textContent).toBe("false"));
    await userEvent.click(screen.getByRole("button", { name: "Enable" }));
    await waitFor(() => expect(screen.getByTestId("enabled").textContent).toBe("true"));
    expect(screen.getByTestId("role").textContent).toBe("platform_operator");

    await userEvent.click(screen.getByRole("button", { name: "Disable" }));
    await waitFor(() => expect(screen.getByTestId("enabled").textContent).toBe("false"));
  });
});
