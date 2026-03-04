import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import CanvasRenderer from "./CanvasRenderer";
import { NotificationsProvider } from "../../app/state/notificationsStore";

function renderWithNotifications(ui: ReactElement) {
  return render(<NotificationsProvider>{ui}</NotificationsProvider>);
}

describe("CanvasRenderer", () => {
  it("renders artifacts dataset using shared canvas table", () => {
    renderWithNotifications(
      <CanvasRenderer
        payload={{
          type: "canvas.table",
          title: "Artifacts",
          dataset: {
            name: "artifacts",
            primary_key: "slug",
            columns: [
              { key: "slug", label: "Slug", type: "string", sortable: true },
              { key: "kind", label: "Kind", type: "string", sortable: true },
            ],
            rows: [{ slug: "core.authn-jwt", kind: "module" }],
            total_count: 1,
          },
          query: { entity: "artifacts", filters: [], sort: [{ field: "slug", dir: "asc" }], limit: 50, offset: 0 },
        }}
        query={{ entity: "artifacts", filters: [], sort: [{ field: "slug", dir: "asc" }], limit: 50, offset: 0 }}
      />
    );

    expect(screen.getByRole("grid")).toBeInTheDocument();
    expect(screen.getByText("core.authn-jwt")).toBeInTheDocument();
    expect(screen.getByText("module")).toBeInTheDocument();
  });

  it("renders EMS dataset with same shared table", () => {
    renderWithNotifications(
      <CanvasRenderer
        payload={{
          type: "canvas.table",
          title: "EMS Devices",
          dataset: {
            name: "ems_devices",
            primary_key: "device_id",
            columns: [
              { key: "device_id", label: "Device ID", type: "string", sortable: true },
              { key: "state", label: "State", type: "string", sortable: true },
            ],
            rows: [{ device_id: "dev-01", state: "offline" }],
            total_count: 1,
          },
          query: { entity: "ems_devices", filters: [], sort: [{ field: "device_id", dir: "asc" }], limit: 50, offset: 0 },
        }}
        query={{ entity: "ems_devices", filters: [], sort: [{ field: "device_id", dir: "asc" }], limit: 50, offset: 0 }}
      />
    );

    expect(screen.getByRole("grid")).toBeInTheDocument();
    expect(screen.getByText("dev-01")).toBeInTheDocument();
    expect(screen.getByText("offline")).toBeInTheDocument();
  });

  it("triggers sort update and row activation", () => {
    const onSort = vi.fn();
    const onRowActivate = vi.fn();

    renderWithNotifications(
      <CanvasRenderer
        payload={{
          type: "canvas.table",
          title: "Artifacts",
          dataset: {
            name: "artifacts",
            primary_key: "slug",
            columns: [
              { key: "slug", label: "Slug", type: "string", sortable: true },
              { key: "kind", label: "Kind", type: "string", sortable: false },
            ],
            rows: [{ slug: "ems", kind: "module" }],
            total_count: 1,
          },
          query: { entity: "artifacts", filters: [], sort: [{ field: "updated_at", dir: "desc" }], limit: 50, offset: 0 },
        }}
        query={{ entity: "artifacts", filters: [], sort: [{ field: "updated_at", dir: "desc" }], limit: 50, offset: 0 }}
        onSort={onSort}
        onRowActivate={onRowActivate}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /sort by slug/i }));
    expect(onSort).toHaveBeenCalledWith("slug", true);

    fireEvent.click(screen.getByText("ems"));
    expect(onRowActivate).toHaveBeenCalledWith("ems", expect.objectContaining({ slug: "ems" }));
  });

  it("opens mapped artifact detail target on row click", () => {
    const onOpenDetail = vi.fn();

    renderWithNotifications(
      <CanvasRenderer
        payload={{
          type: "canvas.table",
          title: "Artifacts",
          dataset: {
            name: "artifacts",
            primary_key: "slug",
            columns: [{ key: "slug", label: "Slug", type: "string", sortable: true }],
            rows: [{ slug: "core.authn-jwt" }],
            total_count: 1,
          },
          query: { entity: "artifacts", filters: [], sort: [{ field: "slug", dir: "asc" }], limit: 50, offset: 0 },
        }}
        query={{ entity: "artifacts", filters: [], sort: [{ field: "slug", dir: "asc" }], limit: 50, offset: 0 }}
        onOpenDetail={onOpenDetail}
      />
    );

    fireEvent.click(screen.getByText("core.authn-jwt"));
    expect(onOpenDetail).toHaveBeenCalledWith(
      { entity_type: "artifact", entity_id: "core.authn-jwt" },
      expect.objectContaining({ slug: "core.authn-jwt" })
    );
  });

  it("opens mapped device detail for EMS devices on row click", () => {
    const onOpenDetail = vi.fn();

    renderWithNotifications(
      <CanvasRenderer
        payload={{
          type: "canvas.table",
          title: "Devices",
          dataset: {
            name: "ems_devices",
            primary_key: "device_id",
            columns: [{ key: "device_id", label: "Device ID", type: "string", sortable: true }],
            rows: [{ device_id: "dev-01" }],
            total_count: 1,
          },
          query: { entity: "ems_devices", filters: [], sort: [{ field: "device_id", dir: "asc" }], limit: 50, offset: 0 },
        }}
        query={{ entity: "ems_devices", filters: [], sort: [{ field: "device_id", dir: "asc" }], limit: 50, offset: 0 }}
        onOpenDetail={onOpenDetail}
      />
    );

    fireEvent.click(screen.getByText("dev-01"));
    expect(onOpenDetail).toHaveBeenCalledWith(
      { entity_type: "device", entity_id: "dev-01" },
      expect.objectContaining({ device_id: "dev-01" })
    );
  });

  it("falls back to generic record detail for unknown dataset on row click", () => {
    const onOpenDetail = vi.fn();

    renderWithNotifications(
      <CanvasRenderer
        payload={{
          type: "canvas.table",
          title: "Unknown",
          dataset: {
            name: "unknown_records",
            primary_key: "id",
            columns: [{ key: "id", label: "ID", type: "string", sortable: true }],
            rows: [{ id: "rec-1" }],
            total_count: 1,
          },
          query: { entity: "unknown_records", filters: [], sort: [{ field: "id", dir: "asc" }], limit: 50, offset: 0 },
        }}
        query={{ entity: "unknown_records", filters: [], sort: [{ field: "id", dir: "asc" }], limit: 50, offset: 0 }}
        onOpenDetail={onOpenDetail}
      />
    );

    fireEvent.click(screen.getByText("rec-1"));
    expect(onOpenDetail).toHaveBeenCalledWith(
      { entity_type: "record", entity_id: "rec-1", dataset: "unknown_records" },
      expect.objectContaining({ id: "rec-1" })
    );
  });
});
