import { render, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import SolutionsPage from "./SolutionsPage";

const navigateMock = vi.hoisted(() => vi.fn());
const listApplicationsMock = vi.hoisted(() => vi.fn());

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock("../../api/xyn", () => ({
  listApplications: listApplicationsMock,
}));

describe("SolutionsPage compatibility route", () => {
  it("redirects to workbench solution panel", async () => {
    render(
      <MemoryRouter initialEntries={["/w/ws-1/solutions"]}>
        <Routes>
          <Route path="/w/:workspaceId/solutions" element={<SolutionsPage workspaceId="ws-1" />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() =>
      expect(navigateMock).toHaveBeenCalledWith("/w/ws-1/workbench?panel=solution_list", { replace: true })
    );
    expect(listApplicationsMock).not.toHaveBeenCalled();
  });
});
