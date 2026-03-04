import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { NAV_STATE_STORAGE_KEY } from "../../nav/nav.config";
import Sidebar from "./Sidebar";

function renderSidebar(initialPath: string, roles: string[] = []) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="*" element={<Sidebar user={{ roles }} />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Sidebar", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders groups and items from nav config", async () => {
    renderSidebar("/app/artifacts/all");
    expect(screen.getByRole("link", { name: /^Initiate$/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^Installed$/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^Catalog$/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^Runs$/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^Instances$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^Platform Settings$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Package$/i })).not.toBeInTheDocument();
  });

  it("persists collapsed mode to localStorage", async () => {
    const user = userEvent.setup();
    renderSidebar("/app/console");
    await user.click(screen.getByRole("button", { name: /Collapse sidebar/i }));
    const stored = window.localStorage.getItem(NAV_STATE_STORAGE_KEY) || "";
    expect(stored).toContain('"collapsed":true');
  });

  it("search filtering reduces visible items and expands matching groups", async () => {
    const user = userEvent.setup();
    renderSidebar("/app/console");

    const search = screen.getByRole("textbox", { name: "Search" });
    await user.type(search, "catalog");

    expect(screen.getByRole("link", { name: /^Catalog$/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^Platform Settings$/i })).not.toBeInTheDocument();
  });

  it("does not render removed legacy sections", async () => {
    const user = userEvent.setup();
    renderSidebar("/app/console", []);
    await user.type(screen.getByRole("textbox", { name: "Search" }), "blueprint");
    expect(screen.queryByRole("link", { name: /Blueprints/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Modules/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Context Packs/i })).not.toBeInTheDocument();
  });
});
