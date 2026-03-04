import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import IdentityConfigurationPage from "./IdentityConfigurationPage";

vi.mock("./IdentityProvidersPage", () => ({
  default: () => <div>Identity Providers Content</div>,
}));

vi.mock("./OidcAppClientsPage", () => ({
  default: () => <div>OIDC App Clients Content</div>,
}));

describe("IdentityConfigurationPage", () => {
  it("defaults to identity providers and switches tabs", async () => {
    render(
      <MemoryRouter initialEntries={["/app/platform/identity-configuration"]}>
        <Routes>
          <Route path="/app/platform/identity-configuration" element={<IdentityConfigurationPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText("Identity Configuration")).toBeInTheDocument();
    expect(screen.getByText("Identity Providers Content")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "OIDC App Clients" }));
    expect(await screen.findByText("OIDC App Clients Content")).toBeInTheDocument();
  });
});
