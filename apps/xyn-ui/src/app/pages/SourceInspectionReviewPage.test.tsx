import { MemoryRouter, Route, Routes } from "react-router-dom";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SourceInspectionReviewPage from "./SourceInspectionReviewPage";

const apiMocks = vi.hoisted(() => ({
  listSourceConnectors: vi.fn(),
  listSourceInspections: vi.fn(),
  listSourceMappings: vi.fn(),
}));

vi.mock("../../api/xyn", () => apiMocks);

describe("SourceInspectionReviewPage", () => {
  let consoleError: ReturnType<typeof vi.spyOn> | null = null;

  beforeEach(() => {
    vi.clearAllMocks();
    consoleError = vi.spyOn(console, "error").mockImplementation((message, ...args) => {
      if (typeof message === "string" && message.includes("not wrapped in act")) {
        return;
      }
      console.warn(message, ...args);
    });
    apiMocks.listSourceConnectors.mockResolvedValue({ workspace_id: "ws-1", sources: [] });
    apiMocks.listSourceInspections.mockResolvedValue({ source_id: "s-1", inspections: [] });
    apiMocks.listSourceMappings.mockResolvedValue({ source_id: "s-1", mappings: [] });
  });

  afterEach(() => {
    consoleError?.mockRestore();
    consoleError = null;
  });

  function renderPage(workspaceId = "ws-1") {
    return render(
      <MemoryRouter initialEntries={["/w/ws-1/sources"]}>
        <Routes>
          <Route path="/w/:workspaceId/sources" element={<SourceInspectionReviewPage workspaceId={workspaceId} workspaceName="Workspace" />} />
        </Routes>
      </MemoryRouter>
    );
  }

  it("renders empty state when no inspections", async () => {
    await act(async () => {
      renderPage();
    });
    await waitFor(() => expect(apiMocks.listSourceConnectors).toHaveBeenCalled());
    await waitFor(() => expect(apiMocks.listSourceInspections).not.toHaveBeenCalled());
    expect(await screen.findByText(/No inspections captured/i)).toBeInTheDocument();
  });

  it("renders schema rows and sample preview", async () => {
    apiMocks.listSourceConnectors.mockResolvedValue({
      workspace_id: "ws-1",
      sources: [{ id: "s-1", key: "county", name: "County Feed", source_type: "records", source_mode: "file_upload" }],
    });
    apiMocks.listSourceInspections.mockResolvedValue({
      source_id: "s-1",
      inspections: [
        {
          id: "i-1",
          source_id: "s-1",
          status: "ok",
          detected_format: "csv",
          discovered_fields: [{ name: "parcel_id", type: "string" }],
          sample_metadata: {
            sample_rows: [{ parcel_id: "p1", city: "Austin" }],
            profile_summary: { row_count: 12, discovered_fields_count: 1, has_sample_rows: true, has_geometry: false },
          },
          validation_findings: [],
          inspected_at: "2026-03-20T00:00:00Z",
        },
      ],
    });
    await act(async () => {
      renderPage();
    });
    await waitFor(() => expect(apiMocks.listSourceConnectors).toHaveBeenCalled());
    await waitFor(() => expect(apiMocks.listSourceInspections).toHaveBeenCalled());
    expect(await screen.findByText(/County Feed/)).toBeInTheDocument();
    expect(await screen.findByText(/parcel_id/)).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "Sample" }));
    expect(await screen.findByText("Austin")).toBeInTheDocument();
  });

  it("renders mapping summary and geometry metadata", async () => {
    apiMocks.listSourceConnectors.mockResolvedValue({
      workspace_id: "ws-1",
      sources: [{ id: "s-1", key: "county", name: "County Feed", source_type: "records", source_mode: "file_upload" }],
    });
    apiMocks.listSourceInspections.mockResolvedValue({
      source_id: "s-1",
      inspections: [
        {
          id: "i-1",
          source_id: "s-1",
          status: "ok",
          detected_format: "geojson",
          discovered_fields: [{ name: "geometry", type: "geometry" }],
          sample_metadata: {
            sample_rows: [],
            profile_summary: { row_count: 0, discovered_fields_count: 1, has_sample_rows: false, has_geometry: true },
            geometry_summary: { present: true, geometry_types: ["Point"], bbox: [-96, 30, -95, 31], centroid: { x: -95.5, y: 30.5 } },
          },
          validation_findings: [],
          inspected_at: "2026-03-20T00:00:00Z",
        },
      ],
    });
    apiMocks.listSourceMappings.mockResolvedValue({
      source_id: "s-1",
      mappings: [
        {
          id: "m-1",
          source_id: "s-1",
          version: 1,
          status: "validated",
          is_current: true,
          field_mapping: { parcel_id: "parcel_id" },
          transformation_hints: { normalize: ["parcel_id"] },
          validation_state: {},
          created_at: "2026-03-20T00:00:00Z",
          updated_at: "2026-03-20T00:00:00Z",
        },
      ],
    });
    await act(async () => {
      renderPage();
    });
    await waitFor(() => expect(apiMocks.listSourceConnectors).toHaveBeenCalled());
    await waitFor(() => expect(apiMocks.listSourceInspections).toHaveBeenCalled());
    await waitFor(() => expect(apiMocks.listSourceMappings).toHaveBeenCalled());
    expect(await screen.findByText(/Geometry Types/)).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "Mapping" }));
    expect((await screen.findAllByText("parcel_id")).length).toBeGreaterThan(0);
  });

  it("shows empty sample state when no sample rows", async () => {
    apiMocks.listSourceConnectors.mockResolvedValue({
      workspace_id: "ws-1",
      sources: [{ id: "s-1", key: "county", name: "County Feed", source_type: "records", source_mode: "file_upload" }],
    });
    apiMocks.listSourceInspections.mockResolvedValue({
      source_id: "s-1",
      inspections: [
        {
          id: "i-1",
          source_id: "s-1",
          status: "ok",
          detected_format: "csv",
          discovered_fields: [{ name: "parcel_id", type: "string" }],
          sample_metadata: { sample_rows: [], profile_summary: { has_sample_rows: false } },
          validation_findings: [],
          inspected_at: "2026-03-20T00:00:00Z",
        },
      ],
    });
    await act(async () => {
      renderPage();
    });
    await waitFor(() => expect(apiMocks.listSourceConnectors).toHaveBeenCalled());
    await waitFor(() => expect(apiMocks.listSourceInspections).toHaveBeenCalled());
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "Sample" }));
    expect(await screen.findByText(/No sample rows captured/i)).toBeInTheDocument();
  });
});
