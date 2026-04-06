import type { ArtifactSurface } from "../../api/types";
import type { NavGroup, NavItem } from "./nav.config";
import { withWorkspaceInNavPath } from "../routing/workspaceRouting";
import { isCompatibilityFallbackSurface } from "../pages/shellSurfaceRenderers";

function mapNavPath(path: string, workspaceId: string, scope?: string): string {
  if (String(scope || "").trim().toLowerCase() === "global") return path;
  if (!workspaceId) return path;
  return withWorkspaceInNavPath(path, workspaceId);
}

export function withArtifactSurfaceNav(
  baseGroups: NavGroup[],
  surfaceNavItems: ArtifactSurface[],
  workspaceId: string,
): NavGroup[] {
  const mapped = baseGroups.map((group) => ({
    ...group,
    items: group.items ? group.items.map((item) => ({ ...item, path: mapNavPath(item.path, workspaceId) })) : [],
    subgroups: group.subgroups
      ? group.subgroups.map((subgroup) => ({
          ...subgroup,
          items: subgroup.items.map((item) => ({ ...item, path: mapNavPath(item.path, workspaceId) })),
        }))
      : [],
  }));

  const appsGroup = mapped.find((group) => group.id === "apps");
  if (!appsGroup) return mapped;

  const pathSeen = new Set<string>();
  mapped.forEach((group) => {
    (group.items || []).forEach((item) => pathSeen.add(item.path));
    (group.subgroups || []).forEach((subgroup) => subgroup.items.forEach((item) => pathSeen.add(item.path)));
  });

  const appItems: Array<{ sortOrder: number; item: NavItem }> = [];
  (surfaceNavItems || [])
    .filter((surface) => String(surface.nav_visibility || "").toLowerCase() === "always")
    .filter((surface) => !isCompatibilityFallbackSurface(surface))
    .forEach((surface) => {
      const route = String(surface.route || "").trim();
      if (!route || pathSeen.has(route)) return;
      const permissionsSpec = (surface.permissions || {}) as Record<string, unknown>;
      const requiredRoles = Array.isArray(permissionsSpec.required_roles)
        ? permissionsSpec.required_roles.map((entry) => String(entry).trim()).filter(Boolean)
        : [];
      const requiredPermissions = Array.isArray(permissionsSpec.required_permissions)
        ? permissionsSpec.required_permissions.map((entry) => String(entry).trim()).filter(Boolean)
        : [];
      const navItem: NavItem = {
        id: `surface-${surface.id}`,
        label: String(surface.nav_label || surface.title || "Surface"),
        path: mapNavPath(route, workspaceId, String(surface.ui_mount_scope || "")),
        icon: String(surface.nav_icon || "").trim() || "Sparkles",
        requiredRoles: requiredRoles.length ? requiredRoles : undefined,
        requiredPermissions: requiredPermissions.length ? requiredPermissions : undefined,
      };
      appItems.push({ sortOrder: Number(surface.sort_order || 0), item: navItem });
      pathSeen.add(route);
    });

  appsGroup.items = appItems
    .sort((a, b) => (a.sortOrder - b.sortOrder) || a.item.label.localeCompare(b.item.label))
    .map((entry) => entry.item);
  appsGroup.subgroups = [];

  return mapped;
}
