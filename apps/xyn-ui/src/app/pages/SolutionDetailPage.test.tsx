import { render, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import SolutionDetailPage from "./SolutionDetailPage";

const navigateMock = vi.hoisted(() => vi.fn());
const getApplicationMock = vi.hoisted(() => vi.fn());
const listSessionsMock = vi.hoisted(() => vi.fn());

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock("../../api/xyn", () => ({
  getApplication: getApplicationMock,
  listSolutionChangeSessions: listSessionsMock,
}));

describe("SolutionDetailPage compatibility route", () => {
  it("redirects to workbench solution detail panel", async () => {
    render(
      <MemoryRouter initialEntries={["/w/ws-1/solutions/app-1"]}>
        <Routes>
          <Route path="/w/:workspaceId/solutions/:applicationId" element={<SolutionDetailPage workspaceId="ws-1" />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() =>
      expect(navigateMock).toHaveBeenCalledWith("/w/ws-1/workbench?panel=solution_detail&application_id=app-1", { replace: true })
    );
    expect(getApplicationMock).not.toHaveBeenCalled();
    expect(listSessionsMock).not.toHaveBeenCalled();
  });
});
