import {
  NAV_GROUPS,
  NAV_STATE_STORAGE_KEY,
  NavGroup,
  NavItem,
  NavSubgroup,
  NavUserContext,
  NavVisibility,
} from "./nav.config";

export type NavState = {
  expandedGroupIds: string[];
  expandedSubgroupIds: string[];
  collapsed: boolean;
};

export type ActiveNavMatch = {
  groupId: string;
  subgroupId?: string;
  item: NavItem;
};

export type NavMatch = {
  groupId: string;
  subgroupId?: string;
  item: NavItem;
};

export type NavBreadcrumb = {
  label: string;
  path?: string;
};

export type FilteredNav = {
  groups: NavGroup[];
  matches: NavMatch[];
};

const DEFAULT_STATE: NavState = {
  expandedGroupIds: ["home", "build", "apps", "run", "admin"],
  expandedSubgroupIds: [],
  collapsed: false,
};

function uniq(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)));
}

export function normalizePath(pathname: string): string {
  if (!pathname) return "/";
  const hash = pathname.split("#")[0];
  const clean = hash.split("?")[0];
  if (clean.length > 1 && clean.endsWith("/")) return clean.slice(0, -1);
  return clean;
}

function pathMatches(itemPath: string, pathname: string): boolean {
  const item = normalizePath(itemPath);
  const current = normalizePath(pathname);
  return current === item || current.startsWith(`${item}/`);
}

function textMatch(query: string, ...values: string[]): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return values.some((value) => value.toLowerCase().includes(q));
}

function hasAny(haystack: string[], needles: string[]): boolean {
  if (!needles.length) return true;
  if (!haystack.length) return false;
  const set = new Set(haystack);
  return needles.some((needle) => set.has(needle));
}

function expandRoles(roles: string[]): string[] {
  const expanded = new Set(roles || []);
  if (expanded.has("platform_owner")) {
    expanded.add("platform_admin");
    expanded.add("platform_architect");
    expanded.add("platform_operator");
    expanded.add("app_user");
  }
  if (expanded.has("platform_admin")) {
    expanded.add("platform_architect");
    expanded.add("platform_operator");
  }
  if (expanded.has("platform_architect")) {
    expanded.add("platform_operator");
  }
  return Array.from(expanded);
}

export function canViewNavItem(user: NavUserContext, node: NavVisibility): boolean {
  // TODO: connect requiredPermissions once the auth payload provides permission claims.
  const roles = expandRoles(user.roles || []);
  const permissions = user.permissions || [];
  const requiredRoles = node.requiredRoles || [];
  const requiredPermissions = node.requiredPermissions || [];
  const hiddenRoles = node.hiddenRoles || [];

  if (hiddenRoles.length > 0 && hasAny(roles, hiddenRoles)) {
    return false;
  }
  return hasAny(roles, requiredRoles) && hasAny(permissions, requiredPermissions);
}

export function hydrateNavState(): NavState {
  if (typeof window === "undefined") return DEFAULT_STATE;
  try {
    const raw = window.localStorage.getItem(NAV_STATE_STORAGE_KEY);
    if (!raw) return DEFAULT_STATE;
    const parsed = JSON.parse(raw) as Partial<
      NavState & { expandedGroups?: string[]; expandedSubgroups?: string[] }
    >;
    return {
      expandedGroupIds: uniq(parsed.expandedGroupIds || parsed.expandedGroups || DEFAULT_STATE.expandedGroupIds),
      expandedSubgroupIds: uniq(
        parsed.expandedSubgroupIds || parsed.expandedSubgroups || DEFAULT_STATE.expandedSubgroupIds,
      ),
      collapsed: Boolean(parsed.collapsed),
    };
  } catch {
    return DEFAULT_STATE;
  }
}

export function persistNavState(state: NavState): void {
  if (typeof window === "undefined") return;
  const normalized: NavState = {
    expandedGroupIds: uniq(state.expandedGroupIds),
    expandedSubgroupIds: uniq(state.expandedSubgroupIds),
    collapsed: Boolean(state.collapsed),
  };
  window.localStorage.setItem(NAV_STATE_STORAGE_KEY, JSON.stringify(normalized));
}

export function visibleNav(groups: NavGroup[], user: NavUserContext): NavGroup[] {
  return groups
    .map((group) => {
      const items = (group.items || []).filter((item) => canViewNavItem(user, item));
      const subgroups = (group.subgroups || [])
        .map((subgroup) => ({
          ...subgroup,
          items: subgroup.items.filter((item) => canViewNavItem(user, item)),
        }))
        .filter((subgroup) => subgroup.items.length > 0);
      return {
        ...group,
        items,
        subgroups,
      };
    })
    .filter((group) => (group.items || []).length > 0 || (group.subgroups || []).length > 0)
    .filter((group) => canViewNavItem(user, group));
}

export function findActiveItem(pathname: string, groups: NavGroup[] = NAV_GROUPS): ActiveNavMatch | null {
  for (const group of groups) {
    for (const item of group.items || []) {
      if (pathMatches(item.path, pathname)) return { groupId: group.id, item };
    }
    for (const subgroup of group.subgroups || []) {
      for (const item of subgroup.items) {
        if (pathMatches(item.path, pathname)) return { groupId: group.id, subgroupId: subgroup.id, item };
      }
    }
  }
  return null;
}

export function findActiveNavItem(pathname: string, groups: NavGroup[] = NAV_GROUPS): ActiveNavMatch | null {
  return findActiveItem(pathname, groups);
}

export function getBreadcrumbs(pathname: string, groups: NavGroup[] = NAV_GROUPS): NavBreadcrumb[] {
  const active = findActiveItem(pathname, groups);
  if (!active) return [];
  const group = groups.find((entry) => entry.id === active.groupId);
  if (!group) return [];

  if (!active.subgroupId) {
    return [{ label: group.label }, { label: active.item.label, path: active.item.path }];
  }

  const subgroup = (group.subgroups || []).find((entry) => entry.id === active.subgroupId);
  return subgroup
    ? [{ label: group.label }, { label: subgroup.label }, { label: active.item.label, path: active.item.path }]
    : [{ label: group.label }, { label: active.item.label, path: active.item.path }];
}

export function filterNav(groups: NavGroup[], query: string): FilteredNav {
  const q = query.trim().toLowerCase();
  const matches: NavMatch[] = [];

  if (!q) {
    groups.forEach((group) => {
      (group.items || []).forEach((item) => matches.push({ groupId: group.id, item }));
      (group.subgroups || []).forEach((subgroup) => {
        subgroup.items.forEach((item) => matches.push({ groupId: group.id, subgroupId: subgroup.id, item }));
      });
    });
    return { groups, matches };
  }

  const filtered = groups
    .map((group) => {
      const matchedItems = (group.items || []).filter((item) => {
        const ok = textMatch(q, item.label, ...(item.keywords || []), group.label);
        if (ok) matches.push({ groupId: group.id, item });
        return ok;
      });

      const matchedSubgroups = (group.subgroups || [])
        .map((subgroup) => {
          const subgroupLabelMatched = textMatch(q, subgroup.label, group.label);
          const items = subgroup.items.filter((item) => {
            const ok = subgroupLabelMatched || textMatch(q, item.label, ...(item.keywords || []), subgroup.label, group.label);
            if (ok) matches.push({ groupId: group.id, subgroupId: subgroup.id, item });
            return ok;
          });
          return { ...subgroup, items };
        })
        .filter((subgroup) => subgroup.items.length > 0);

      return { ...group, items: matchedItems, subgroups: matchedSubgroups };
    })
    .filter((group) => (group.items || []).length > 0 || (group.subgroups || []).length > 0);

  return { groups: filtered, matches };
}

export function mergedExpandedState(
  state: NavState,
  _pathname: string,
  filtered: FilteredNav,
  _groups: NavGroup[],
  query: string,
): Pick<NavState, "expandedGroupIds" | "expandedSubgroupIds"> {
  const expandedGroupIds = new Set(state.expandedGroupIds);
  const expandedSubgroupIds = new Set(state.expandedSubgroupIds);

  if (query.trim()) {
    filtered.matches.forEach((match) => {
      expandedGroupIds.add(match.groupId);
      if (match.subgroupId) expandedSubgroupIds.add(match.subgroupId);
    });
  }

  return {
    expandedGroupIds: Array.from(expandedGroupIds),
    expandedSubgroupIds: Array.from(expandedSubgroupIds),
  };
}

export function findGroupBySubgroupId(groups: NavGroup[], subgroupId: string): NavGroup | null {
  for (const group of groups) {
    if ((group.subgroups || []).some((subgroup) => subgroup.id === subgroupId)) return group;
  }
  return null;
}

export function flattenItems(groups: NavGroup[]): Array<{ group: NavGroup; subgroup?: NavSubgroup; item: NavItem }> {
  const output: Array<{ group: NavGroup; subgroup?: NavSubgroup; item: NavItem }> = [];
  groups.forEach((group) => {
    (group.items || []).forEach((item) => output.push({ group, item }));
    (group.subgroups || []).forEach((subgroup) => {
      subgroup.items.forEach((item) => output.push({ group, subgroup, item }));
    });
  });
  return output;
}
