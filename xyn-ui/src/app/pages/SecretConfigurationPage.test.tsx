import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SecretConfigurationPage from "./SecretConfigurationPage";

const apiMocks = vi.hoisted(() => ({
  listSecretStores: vi.fn(),
  listSecretRefs: vi.fn(),
  createSecretStore: vi.fn(),
  updateSecretStore: vi.fn(),
  setDefaultSecretStore: vi.fn(),
}));

vi.mock("../../api/xyn", () => apiMocks);

describe("SecretConfigurationPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listSecretStores.mockResolvedValue({
      secret_stores: [
        {
          id: "store-1",
          name: "Primary",
          kind: "aws_secrets_manager",
          is_default: true,
          config_json: { aws_region: "us-east-1", name_prefix: "/xyn", kms_key_id: "", tags: { "xyn:managed": "true" } },
        },
      ],
    });
    apiMocks.listSecretRefs.mockResolvedValue({ secret_refs: [] });
  });

  it("defaults to Secret Stores and allows switching to Secret Refs", async () => {
    render(
      <MemoryRouter initialEntries={["/app/platform/secrets"]}>
        <Routes>
          <Route path="/app/platform/secrets" element={<SecretConfigurationPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText("Secret Configuration")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Create store" })).toBeInTheDocument());
    await userEvent.click(screen.getByRole("tab", { name: "Secret Refs" }));
    expect(await screen.findByText("Secret references")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create store" })).not.toBeInTheDocument();
  });
});
