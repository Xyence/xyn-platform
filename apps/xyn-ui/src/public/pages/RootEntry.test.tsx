import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RootEntry from "./RootEntry";

vi.mock("../../api/public", () => ({
  fetchPublicRootResolution: vi.fn(),
  checkAuthenticated: vi.fn(),
}));

vi.mock("./HomePage", () => ({
  default: () => <div>PUBLIC_HOME</div>,
}));

import { checkAuthenticated, fetchPublicRootResolution } from "../../api/public";

describe("RootEntry", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders public home when root mode is public", async () => {
    vi.mocked(fetchPublicRootResolution).mockResolvedValue({ mode: "public" });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <RootEntry />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText("PUBLIC_HOME")).toBeInTheDocument());
    expect(checkAuthenticated).not.toHaveBeenCalled();
  });

  it("routes authenticated private users to open-console", async () => {
    vi.mocked(fetchPublicRootResolution).mockResolvedValue({ mode: "private" });
    vi.mocked(checkAuthenticated).mockResolvedValue(true);

    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<RootEntry />} />
          <Route path="/open-console" element={<div>OPEN_CONSOLE</div>} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText("OPEN_CONSOLE")).toBeInTheDocument());
  });

  it("sends unauthenticated private users to login entrypoint", async () => {
    vi.mocked(fetchPublicRootResolution).mockResolvedValue({ mode: "private" });
    vi.mocked(checkAuthenticated).mockResolvedValue(false);
    const replaceSpy = vi.fn();
    delete (window as any).location;
    (window as any).location = { ...originalLocation, replace: replaceSpy };

    render(
      <MemoryRouter initialEntries={["/"]}>
        <RootEntry />
      </MemoryRouter>
    );

    await waitFor(() =>
      expect(replaceSpy).toHaveBeenCalledWith(
        "/auth/login?appId=xyn-ui&returnTo=%2Fopen-console"
      )
    );
    delete (window as any).location;
    (window as any).location = originalLocation;
  });
});
