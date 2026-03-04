import { beforeEach, describe, expect, it } from "vitest";
import { NAV_GROUPS, NAV_STATE_STORAGE_KEY } from "./nav.config";
import {
  canViewNavItem,
  filterNav,
  findActiveItem,
  getBreadcrumbs,
  hydrateNavState,
  persistNavState,
  visibleNav,
} from "./nav.utils";

describe("nav.utils", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("finds active item and containing group/subgroup", () => {
    const match = findActiveItem("/app/artifacts/all", NAV_GROUPS);
    expect(match?.groupId).toBe("build");
    expect(match?.subgroupId).toBeUndefined();
    expect(match?.item.id).toBe("installed");
  });

  it("builds breadcrumbs from nav config", () => {
    const crumbs = getBreadcrumbs("/app/platform/settings", NAV_GROUPS);
    expect(crumbs.map((entry) => entry.label)).toEqual(["Admin", "Platform Settings"]);
  });

  it("persists and hydrates nav state", () => {
    persistNavState({
      expandedGroupIds: ["home", "build"],
      expandedSubgroupIds: [],
      collapsed: true,
    });
    const hydrated = hydrateNavState();
    expect(hydrated.expandedGroupIds).toEqual(["home", "build"]);
    expect(hydrated.expandedSubgroupIds).toEqual([]);
    expect(hydrated.collapsed).toBe(true);
    expect(window.localStorage.getItem(NAV_STATE_STORAGE_KEY)).toContain("expandedGroupIds");
  });

  it("filters by label/keywords and returns matches", () => {
    const filtered = filterNav(NAV_GROUPS, "catalog");
    const labels = filtered.matches.map((entry) => entry.item.label);
    expect(labels).toContain("Catalog");
    expect(filtered.groups.length).toBeGreaterThan(0);
  });

  it("RBAC visibility can filter by required roles", () => {
    const roleLocked = [{ id: "x", label: "X", icon: "BookOpen", items: [{ id: "a", label: "A", path: "/a", requiredRoles: ["admin"] }] }];
    const userNav = visibleNav(NAV_GROUPS, { roles: [] });
    expect(userNav.length).toBeGreaterThan(0);
    expect(visibleNav(roleLocked, { roles: [] }).length).toBe(0);
    expect(visibleNav(roleLocked, { roles: ["admin"] }).length).toBe(1);
  });

  it("supports hidden roles for specific items", () => {
    expect(canViewNavItem({ roles: ["platform_admin"] }, { hiddenRoles: ["platform_admin"] })).toBe(false);
    expect(canViewNavItem({ roles: ["platform_admin"] }, { requiredRoles: ["platform_admin"] })).toBe(true);
  });
});
