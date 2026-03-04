import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { Bot } from "lucide-react";
import { getMe, getMyProfile, getTenantBranding, listArtifactNavSurfaces, listWorkspaces } from "../api/xyn";
import type { ArtifactSurface } from "../api/types";
import { CREATE_ACTIONS, NAV_GROUPS, NAV_MOVE_TOAST_STORAGE_KEY, NavGroup, NavItem, NavUserContext } from "./nav/nav.config";
import { getBreadcrumbs, visibleNav } from "./nav/nav.utils";
import Sidebar from "./components/nav/Sidebar";
import BlueprintsPage from "./pages/BlueprintsPage";
import DraftSessionsPage from "./pages/DraftSessionsPage";
import InstancesPage from "./pages/InstancesPage";
import SecretConfigurationPage from "./pages/SecretConfigurationPage";
import AIConfigPage from "./pages/AIConfigPage";
import IdentityConfigurationPage from "./pages/IdentityConfigurationPage";
import AccessControlPage from "./pages/AccessControlPage";
import RunsPage from "./pages/RunsPage";
import ActivityPage from "./pages/ActivityPage";
import DevTasksPage from "./pages/DevTasksPage";
import PlatformBrandingPage from "./pages/PlatformBrandingPage";
import ControlPlanePage from "./pages/ControlPlanePage";
import GuidesPage from "./pages/GuidesPage";
import ToursPage from "./pages/ToursPage";
import TourDetailPage from "./pages/TourDetailPage";
import XynMapPage from "./pages/XynMapPage";
import PlatformSettingsPage from "./pages/PlatformSettingsPage";
import VideoAdapterConfigPage from "./pages/VideoAdapterConfigPage";
import SeedPacksPage from "./pages/SeedPacksPage";
import ArtifactsRegistryPage from "./pages/ArtifactsRegistryPage";
import ArtifactsLibraryPage from "./pages/ArtifactsLibraryPage";
import ArtifactDetailPage from "./pages/ArtifactDetailPage";
import ArtifactSurfaceRoutePage from "./pages/ArtifactSurfaceRoutePage";
import ArticleSurfaceEditorRedirectPage from "./pages/ArticleSurfaceEditorRedirectPage";
import ArticleSurfaceDocsPage from "./pages/ArticleSurfaceDocsPage";
import WorkbenchPage from "./pages/WorkbenchPage";
import WorkspaceSettingsPage from "./pages/WorkspaceSettingsPage";
import { useGlobalHotkeys } from "./hooks/useGlobalHotkeys";
import ReportOverlay from "./components/ReportOverlay";
import UserMenu from "./components/common/UserMenu";
import NotificationBell from "./components/notifications/NotificationBell";
import ToastHost from "./components/notifications/ToastHost";
import AgentActivityDrawer from "./components/activity/AgentActivityDrawer";
import { useNotifications } from "./state/notificationsStore";
import { useOperations } from "./state/operationRegistry";
import { usePreview } from "./state/previewStore";
import HelpDrawer from "./components/help/HelpDrawer";
import TourOverlay from "./components/help/TourOverlay";
import { resolveRouteId } from "./help/routeHelp";
import HeaderPreviewControl from "./components/preview/HeaderPreviewControl";
import PreviewBanner from "./components/preview/PreviewBanner";
import XynConsoleNode from "./components/console/XynConsoleNode";
import CapabilitiesIndicator from "./components/console/CapabilitiesIndicator";
import SuggestionSwitcher from "./components/console/SuggestionSwitcher";
import { useXynConsole } from "./state/xynConsoleStore";
import useWorkspaceFromRoute from "./hooks/useWorkspaceFromRoute";
import {
  DEFAULT_WORKSPACE_SUBPATH,
  isWorkspaceScopedPath,
  swapWorkspaceInPath,
  toWorkspacePath,
  toWorkspaceScopedPath,
  withWorkspaceInNavPath,
} from "./routing/workspaceRouting";

function readFlag(value: unknown): boolean {
  return String(value || "").trim().toLowerCase() === "true";
}

const ENABLE_LEGACY_CONTROL_PLANE = readFlag(import.meta.env.VITE_XYN_UI_ENABLE_LEGACY_CONTROL_PLANE);
const ENABLE_LEGACY_GUIDES = readFlag(import.meta.env.VITE_XYN_UI_ENABLE_LEGACY_GUIDES);
const ENABLE_LEGACY_DEV_TASKS_PAGE = readFlag(import.meta.env.VITE_XYN_UI_ENABLE_LEGACY_DEV_TASKS_PAGE);
const ENABLE_LEGACY_BLUEPRINTS = readFlag(import.meta.env.VITE_XYN_UI_ENABLE_LEGACY_BLUEPRINTS);

function workspacePrefixFromPathname(pathname: string): string {
  const match = String(pathname || "").match(/^\/w\/([^/]+)(?:\/|$)/);
  if (!match?.[1]) return "";
  return `/w/${match[1]}`;
}

function withWorkspacePrefix(pathname: string, subpath: string): string {
  const prefix = workspacePrefixFromPathname(pathname);
  const clean = String(subpath || "").replace(/^\/+/, "");
  if (!prefix) return "/";
  return `${prefix}/${clean}`;
}

function RedirectLegacyAiRoute({ tab }: { tab: "credentials" | "model-configs" | "agents" | "purposes" }) {
  const location = useLocation();
  const currentParams = new URLSearchParams(location.search);
  currentParams.set("tab", tab);
  return <Navigate to={{ pathname: withWorkspacePrefix(location.pathname, "platform/ai-agents"), search: `?${currentParams.toString()}` }} replace />;
}

function RedirectLegacySecretsRoute({ tab }: { tab: "stores" | "refs" }) {
  const location = useLocation();
  const currentParams = new URLSearchParams(location.search);
  currentParams.set("tab", tab);
  return <Navigate to={{ pathname: withWorkspacePrefix(location.pathname, "platform/secrets"), search: `?${currentParams.toString()}` }} replace />;
}

function RedirectLegacyIdentityRoute({ tab }: { tab: "identity-providers" | "oidc-app-clients" }) {
  const location = useLocation();
  const currentParams = new URLSearchParams(location.search);
  currentParams.set("tab", tab);
  return (
    <Navigate to={{ pathname: withWorkspacePrefix(location.pathname, "platform/identity-configuration"), search: `?${currentParams.toString()}` }} replace />
  );
}

function RedirectLegacyAccessControlRoute({ tab }: { tab: "roles" | "users" | "explorer" }) {
  const location = useLocation();
  const currentParams = new URLSearchParams(location.search);
  currentParams.set("tab", tab);
  return <Navigate to={{ pathname: withWorkspacePrefix(location.pathname, "platform/access-control"), search: `?${currentParams.toString()}` }} replace />;
}

function RedirectLegacyWorkspaceAccessRoute() {
  const location = useLocation();
  const currentParams = new URLSearchParams(location.search);
  currentParams.set("tab", "workspaces");
  currentParams.set("wsTab", "members");
  return <Navigate to={{ pathname: withWorkspacePrefix(location.pathname, "platform/settings"), search: `?${currentParams.toString()}` }} replace />;
}

function RedirectLegacyWorkspacesRoute() {
  const location = useLocation();
  const currentParams = new URLSearchParams(location.search);
  const legacyTab = String(currentParams.get("tab") || "").toLowerCase();
  currentParams.set("tab", "workspaces");
  currentParams.set("wsTab", legacyTab === "people_roles" ? "members" : "profile");
  return <Navigate to={{ pathname: withWorkspacePrefix(location.pathname, "platform/settings"), search: `?${currentParams.toString()}` }} replace />;
}

function RedirectWithNotice({ to, notice }: { to: string; notice: string }) {
  const { push } = useNotifications();
  useEffect(() => {
    if (typeof window === "undefined") return;
    const key = `${NAV_MOVE_TOAST_STORAGE_KEY}:${to}`;
    if (!window.sessionStorage.getItem(key)) {
      push({ level: "info", title: "Moved", message: notice });
      window.sessionStorage.setItem(key, "1");
    }
  }, [push, to, notice]);
  return <Navigate to={to} replace />;
}

function RedirectLegacyTenantContactsDetailRoute() {
  const currentParams = new URLSearchParams();
  currentParams.set("tab", "workspaces");
  currentParams.set("wsTab", "all");
  const location = useLocation();
  return <Navigate to={{ pathname: withWorkspacePrefix(location.pathname, "platform/settings"), search: `?${currentParams.toString()}` }} replace />;
}

function LegacyStatePanel({
  title,
  message,
  actionLabel,
  actionTo,
}: {
  title: string;
  message: string;
  actionLabel: string;
  actionTo: string;
}) {
  const navigate = useNavigate();
  return (
    <section className="card">
      <div className="card-header">
        <h3>{title}</h3>
      </div>
      <p className="muted">{message}</p>
      <div className="form-actions">
        <button className="primary" onClick={() => navigate(actionTo)}>
          {actionLabel}
        </button>
      </div>
    </section>
  );
}

export default function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const headerRef = useRef<HTMLElement | null>(null);
  const contentRef = useRef<HTMLElement | null>(null);
  const [authed, setAuthed] = useState(false);
  const [roles, setRoles] = useState<string[]>([]);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [actorRoles, setActorRoles] = useState<string[]>([]);
  const [authUser, setAuthUser] = useState<Record<string, unknown> | null>(null);
  const [userContext, setUserContext] = useState<{ id?: string; email?: string }>({});
  const [authLoaded, setAuthLoaded] = useState(false);
  const [brandLogo, setBrandLogo] = useState<string>("/xyence-logo.png");
  const [reportOpen, setReportOpen] = useState(false);
  const [workspaces, setWorkspaces] = useState<Array<{ id: string; slug: string; name: string; role: string; termination_authority?: boolean }>>([]);
  const [preferredWorkspaceId, setPreferredWorkspaceId] = useState<string>(() => localStorage.getItem("xyn.activeWorkspaceId") || "");
  const [helpOpen, setHelpOpen] = useState(false);
  const [surfaceNavItems, setSurfaceNavItems] = useState<ArtifactSurface[]>([]);
  const [navRefreshToken, setNavRefreshToken] = useState(0);
  const [tourSlug, setTourSlug] = useState<string | null>(null);
  const [tourLaunchToken, setTourLaunchToken] = useState(0);
  const [agentActivityOpen, setAgentActivityOpen] = useState(false);
  const { push } = useNotifications();
  const { runningAiCount } = useOperations();
  const { preview, disablePreviewMode } = usePreview();
  const { handleRouteChange } = useXynConsole();
  const hideFloatingConsoleNode = location.pathname.includes("/console");
  const workspaceRoute = useWorkspaceFromRoute(workspaces);
  const workspaceIdFromRoute = workspaceRoute.workspaceId;
  const activeWorkspaceId = workspaceIdFromRoute || preferredWorkspaceId;
  const inWorkspaceScope = isWorkspaceScopedPath(location.pathname);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const me = await getMe();
        if (!mounted) return;
        setAuthed(Boolean(me?.user));
        setAuthUser((me?.user as Record<string, unknown>) || null);
        setRoles(me?.roles ?? []);
        setPermissions(me?.permissions ?? []);
        setActorRoles(me?.actor_roles ?? me?.roles ?? []);
        setUserContext({
          id: (me?.user?.subject as string | null) || (me?.user?.sub as string | null) || "",
          email: (me?.user?.email as string | null) || "",
        });
        const meWorkspaces = me?.workspaces || [];
        if (Array.isArray(meWorkspaces) && meWorkspaces.length > 0) {
          setWorkspaces(meWorkspaces);
          setPreferredWorkspaceId((current) => current || meWorkspaces[0].id);
        } else {
          try {
            const ws = await listWorkspaces();
            if (!mounted) return;
            setWorkspaces(ws.workspaces || []);
            setPreferredWorkspaceId((current) => current || ws.workspaces?.[0]?.id || "");
          } catch {
            // Keep empty workspaces in bootstrap errors.
          }
        }
        if (me?.user) {
          try {
            const profile = await getMyProfile();
            const membership = profile.memberships?.[0];
            if (membership?.tenant_id) {
              const branding = await getTenantBranding(membership.tenant_id);
              if (!mounted) return;
              setBrandLogo(branding.logo_url || "/xyence-logo.png");
              Object.entries(branding.theme || {}).forEach(([key, value]) => {
                if (key) {
                  document.documentElement.style.setProperty(key, value);
                }
              });
            }
          } catch {
            // Silent fallback to defaults.
          }
        }
      } catch {
        if (!mounted) return;
        setAuthed(false);
        setAuthUser(null);
        setRoles([]);
        setPermissions([]);
        setActorRoles([]);
      } finally {
        if (mounted) {
          setAuthLoaded(true);
        }
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!authed) {
      setSurfaceNavItems([]);
      return;
    }
    let mounted = true;
    (async () => {
      try {
        const payload = await listArtifactNavSurfaces(activeWorkspaceId || undefined);
        if (!mounted) return;
        setSurfaceNavItems(payload.surfaces || []);
      } catch {
        if (!mounted) return;
        setSurfaceNavItems([]);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [authed, activeWorkspaceId, navRefreshToken]);

  useEffect(() => {
    const onWorkspaceArtifactsChanged = () => setNavRefreshToken((value) => value + 1);
    window.addEventListener("xyn:workspace-artifacts-changed", onWorkspaceArtifactsChanged);
    return () => window.removeEventListener("xyn:workspace-artifacts-changed", onWorkspaceArtifactsChanged);
  }, []);

  useEffect(() => {
    if (activeWorkspaceId) localStorage.setItem("xyn.activeWorkspaceId", activeWorkspaceId);
  }, [activeWorkspaceId]);

  useEffect(() => {
    if (workspaceIdFromRoute) {
      setPreferredWorkspaceId(workspaceIdFromRoute);
    }
  }, [workspaceIdFromRoute]);

  useEffect(() => {
    if (!workspaces.length) return;
    const fallbackWorkspaceId = preferredWorkspaceId || workspaces[0]?.id || "";
    if (!fallbackWorkspaceId) return;

    if (inWorkspaceScope) {
      const valid = workspaces.some((workspace) => workspace.id === workspaceIdFromRoute);
      if (!valid) {
        navigate(toWorkspacePath(fallbackWorkspaceId, DEFAULT_WORKSPACE_SUBPATH), { replace: true });
      }
      return;
    }

    const redirected = toWorkspaceScopedPath(location.pathname, fallbackWorkspaceId);
    if (redirected) {
      navigate(
        {
          pathname: redirected,
          search: location.search,
          hash: location.hash,
        },
        { replace: true }
      );
    }
  }, [inWorkspaceScope, location.hash, location.pathname, location.search, navigate, preferredWorkspaceId, workspaceIdFromRoute, workspaces]);

  const startLogin = () => {
    const returnTo = window.location.pathname || "/";
    window.location.href = `/auth/login?appId=xyn-ui&returnTo=${encodeURIComponent(returnTo)}`;
  };

  const signOut = () =>
    fetch("/auth/logout", { method: "POST", credentials: "include" }).then(() => {
      setAuthed(false);
      setAuthUser(null);
      setPermissions([]);
    });

  const effectiveRoles = useMemo(() => {
    if (preview.enabled) {
      if (preview.effective_roles && preview.effective_roles.length > 0) return preview.effective_roles;
      if (preview.roles && preview.roles.length > 0) return preview.roles;
    }
    return roles;
  }, [preview.enabled, preview.effective_roles, preview.roles, roles]);
  const isPreviewReadOnly = Boolean(preview.enabled && preview.read_only);

  const isPlatformAdmin = effectiveRoles.includes("platform_admin") || effectiveRoles.includes("platform_owner");
  const isPlatformArchitect = effectiveRoles.includes("platform_architect");
  const isPlatformManager = isPlatformAdmin || isPlatformArchitect;

  const navUser: NavUserContext = useMemo(() => ({ roles: effectiveRoles, permissions }), [effectiveRoles, permissions]);
  const navGroups: NavGroup[] = useMemo(() => {
    const mapNavPath = (path: string, scope?: string): string => {
      if (String(scope || "").trim().toLowerCase() === "global") return path;
      if (!activeWorkspaceId) return path;
      return withWorkspaceInNavPath(path, activeWorkspaceId);
    };
    const baseGroups = NAV_GROUPS.map((group) => ({
      ...group,
      items: group.items ? group.items.map((item) => ({ ...item, path: mapNavPath(item.path) })) : [],
      subgroups: group.subgroups
        ? group.subgroups.map((subgroup) => ({
            ...subgroup,
            items: subgroup.items.map((item) => ({ ...item, path: mapNavPath(item.path) })),
          }))
        : [],
    }));
    const appsGroup = baseGroups.find((group) => group.id === "apps");
    if (!appsGroup) return baseGroups;

    const pathSeen = new Set<string>();
    baseGroups.forEach((group) => {
      (group.items || []).forEach((item) => pathSeen.add(item.path));
      (group.subgroups || []).forEach((subgroup) => subgroup.items.forEach((item) => pathSeen.add(item.path)));
    });

    const appItems: Array<{ sortOrder: number; item: NavItem }> = [];
    (surfaceNavItems || [])
      .filter((surface) => String(surface.nav_visibility || "").toLowerCase() === "always")
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
          path: mapNavPath(route, String(surface.ui_mount_scope || "")),
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

    return baseGroups;
  }, [activeWorkspaceId, surfaceNavItems]);
  const createActions = useMemo(
    () =>
      CREATE_ACTIONS.map((action) => ({
        ...action,
        path: activeWorkspaceId ? withWorkspaceInNavPath(action.path, activeWorkspaceId) : action.path,
      })),
    [activeWorkspaceId]
  );
  const activeWorkspace = useMemo(
    () => workspaces.find((workspace) => workspace.id === activeWorkspaceId) || workspaces[0] || null,
    [workspaces, activeWorkspaceId]
  );
  const isWorkbenchRoute = useMemo(
    () => /\/w\/[^/]+\/workbench\/?$/.test(location.pathname),
    [location.pathname]
  );
  const workspaceRole = activeWorkspace?.role || "reader";
  const canWorkspaceAdmin = workspaceRole === "admin";
  const breadcrumbTrail = useMemo(() => {
    const allowed = visibleNav(navGroups, navUser);
    return getBreadcrumbs(location.pathname, allowed);
  }, [location.pathname, navGroups, navUser]);
  const routeId = useMemo(() => resolveRouteId(location.pathname), [location.pathname]);
  const artifactRouteId = useMemo(() => {
    const match = location.pathname.match(/^\/w\/[^/]+\/build\/artifacts\/([^/]+)/) || location.pathname.match(/^\/app\/artifacts\/([^/]+)/);
    const candidate = match?.[1] || "";
    return /^[0-9a-f-]{36}$/i.test(candidate) ? candidate : "";
  }, [location.pathname]);
  const handleWorkspaceChange = (nextWorkspaceId: string) => {
    if (!nextWorkspaceId) return;
    setPreferredWorkspaceId(nextWorkspaceId);
    if (inWorkspaceScope && isWorkspaceScopedPath(location.pathname)) {
      navigate({
        pathname: swapWorkspaceInPath(location.pathname, nextWorkspaceId),
        search: location.search,
        hash: location.hash,
      });
      return;
    }
    navigate(toWorkspacePath(nextWorkspaceId, DEFAULT_WORKSPACE_SUBPATH));
  };
  const workspaceScopedTarget = (subpath: string): string => {
    if (!activeWorkspace?.id) return "/";
    return toWorkspacePath(activeWorkspace.id, subpath);
  };
  const settingsPath = workspaceScopedTarget("platform/settings");
  const settingsDeployPath = `${settingsPath}?tab=deploy`;
  const runsPath = workspaceScopedTarget("run/runs");
  const runsDevTasksPath = `${runsPath}?filter=dev_task`;

  useGlobalHotkeys((event) => {
    const target = event.target as HTMLElement | null;
    const targetTag = (target?.tagName || "").toLowerCase();
    const typingTarget = targetTag === "input" || targetTag === "textarea" || targetTag === "select" || target?.isContentEditable;
    if (!typingTarget && event.key === "?") {
      event.preventDefault();
      setHelpOpen((prev) => !prev);
      return;
    }
    const metaOrCtrl = event.metaKey || event.ctrlKey;
    if (!metaOrCtrl || !event.shiftKey) return;
    const hotkey = event.key.toLowerCase();
    if (hotkey === "a") {
      event.preventDefault();
      setAgentActivityOpen((prev) => !prev);
      return;
    }
    if (hotkey === "b") {
      event.preventDefault();
      setReportOpen(true);
    }
  });

  useEffect(() => {
    const onStartTour = (event: Event) => {
      const detail = (event as CustomEvent<{ slug?: string }>).detail || {};
      const slug = detail.slug || "deploy-subscriber-notes";
      setTourSlug(slug);
      setTourLaunchToken((value) => value + 1);
    };
    window.addEventListener("xyn:start-tour", onStartTour as EventListener);
    return () => window.removeEventListener("xyn:start-tour", onStartTour as EventListener);
  }, []);

  useEffect(() => {
    const onReadOnly = () => {
      push({
        level: "warning",
        title: "Preview mode is read-only",
        message: "Exit preview to perform this action.",
      });
    };
    window.addEventListener("xyn:preview-read-only", onReadOnly as EventListener);
    return () => window.removeEventListener("xyn:preview-read-only", onReadOnly as EventListener);
  }, [push]);

  useLayoutEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    if (contentRef.current) {
      contentRef.current.scrollTop = 0;
    }
  }, [location.pathname]);

  useEffect(() => {
    handleRouteChange(location.pathname);
  }, [handleRouteChange, location.pathname]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const root = document.documentElement;
    const updateHeaderHeightVar = () => {
      const height = Math.max(72, Math.round(headerRef.current?.offsetHeight || 88));
      root.style.setProperty("--xyn-header-height", `${height}px`);
    };
    updateHeaderHeightVar();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateHeaderHeightVar);
      return () => {
        window.removeEventListener("resize", updateHeaderHeightVar);
      };
    }
    const observer = new ResizeObserver(updateHeaderHeightVar);
    if (headerRef.current) observer.observe(headerRef.current);
    window.addEventListener("resize", updateHeaderHeightVar);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", updateHeaderHeightVar);
    };
  }, []);

  useEffect(() => {
    if (!authLoaded || authed) return;
    const returnTo = `${location.pathname}${location.search || ""}` || "/";
    window.location.href = `/auth/login?appId=xyn-ui&returnTo=${encodeURIComponent(returnTo)}`;
  }, [authLoaded, authed, location.pathname, location.search]);

  if (!authLoaded) {
    return (
      <div className="app-shell">
        <header className="app-header">
          <div className="brand">
            <img className="brand-logo" src="/xyence-logo.png" alt="Xyence logo" />
            <div>
              <h1>Xyn</h1>
              <p>Loading session...</p>
            </div>
          </div>
        </header>
      </div>
    );
  }

  if (!authed) {
    return (
      <div className="app-shell">
        <header className="app-header">
          <div className="brand">
            <img className="brand-logo" src="/xyence-logo.png" alt="Xyence logo" />
            <div>
              <h1>Xyn</h1>
              <p>Redirecting to sign in...</p>
            </div>
          </div>
        </header>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="app-header" ref={headerRef}>
        <div className="brand">
          <img className="brand-logo" src={brandLogo} alt="Xyence logo" />
          <div>
            <h1>Xyn</h1>
          </div>
        </div>
        <div className="header-meta">
          {authed ? (
            <>
              {isWorkbenchRoute ? <CapabilitiesIndicator workspaceId={activeWorkspace?.id || ""} /> : null}
              <NotificationBell />
              <HeaderPreviewControl
                actorRoles={actorRoles}
                actorLabel={String(authUser?.email || authUser?.display_name || authUser?.subject || "current user")}
                onMessage={({ level, title, message }) => push({ level, title, message })}
              />
              <button
                type="button"
                className={`ghost notification-bell agent-indicator ${runningAiCount > 0 ? "thinking" : ""}`}
                aria-label={runningAiCount > 0 ? `Agent activity, ${runningAiCount} AI operation in progress` : "Agent activity"}
                onClick={() => setAgentActivityOpen((prev) => !prev)}
              >
                <Bot size={16} />
                {runningAiCount > 0 && <span className="agent-indicator-dot" aria-hidden="true" />}
                <span className="sr-only" aria-live="polite">
                  {runningAiCount > 0 ? "AI operation in progress" : "No AI operations in progress"}
                </span>
              </button>
              <UserMenu
                user={authUser || {}}
                onReport={() => setReportOpen(true)}
                onAgentActivity={() => setAgentActivityOpen(true)}
                onSignOut={signOut}
              />
              {runningAiCount > 0 && <span className="agent-thinking-label">Thinking…</span>}
            </>
          ) : (
            <button className="ghost" onClick={startLogin}>
              Sign in
            </button>
          )}
        </div>
      </header>
      <div className={`app-body ${isPreviewReadOnly ? "preview-readonly" : ""} ${isWorkbenchRoute ? "app-body-workbench" : ""}`}>
        {!isWorkbenchRoute ? (
          <Sidebar
            user={navUser}
            navGroups={navGroups}
            createActions={createActions}
            workspaces={workspaces.map((workspace) => ({ id: workspace.id, name: workspace.name }))}
            activeWorkspaceId={activeWorkspace?.id || ""}
            onWorkspaceChange={handleWorkspaceChange}
          />
        ) : null}
        <main className="app-content" ref={contentRef}>
          <div className={`preview-banner-slot ${preview.enabled ? "active" : ""}`}>
            <PreviewBanner
              actorLabel={String(authUser?.email || authUser?.display_name || authUser?.subject || "current user")}
              onExit={async () => {
                await disablePreviewMode();
                push({ level: "success", title: "Preview ended" });
              }}
            />
          </div>
          {!isWorkbenchRoute && breadcrumbTrail.length > 0 && (
            <div className="app-breadcrumbs" aria-label="Breadcrumb">
              {breadcrumbTrail.map((crumb) => crumb.label).join(" / ")}
            </div>
          )}
          <Routes>
            <Route path="/" element={<Navigate to={inWorkspaceScope ? DEFAULT_WORKSPACE_SUBPATH : "/"} replace />} />
            <Route path="workbench" element={<WorkbenchPage />} />
            <Route path="console" element={<Navigate to={workspaceScopedTarget(DEFAULT_WORKSPACE_SUBPATH)} replace />} />
            <Route path="apps/articles/edit" element={<ArticleSurfaceEditorRedirectPage />} />
            <Route path="apps/articles/docs" element={<ArticleSurfaceDocsPage />} />
            <Route
              path="a/*"
              element={
                <ArtifactSurfaceRoutePage
                  workspaceId={activeWorkspace?.id || ""}
                  workspaceRole={workspaceRole}
                  canManageArticleLifecycle={isPlatformManager && !isPreviewReadOnly}
                  canCreate={isPlatformManager && !isPreviewReadOnly}
                />
              }
            />
            <Route path="build/artifacts" element={<ArtifactsRegistryPage workspaceId={activeWorkspace?.id || ""} workspaceName={activeWorkspace?.name || ""} workspaceColor={workspaceRoute.workspaceColor} />} />
            <Route path="build/catalog" element={<ArtifactsLibraryPage workspaceId={activeWorkspace?.id || ""} workspaceName={activeWorkspace?.name || ""} />} />
            <Route path="build/artifacts/library" element={<Navigate to={workspaceScopedTarget("build/catalog")} replace />} />
            <Route
              path="build/artifacts/:artifactId"
              element={
                <ArtifactDetailPage
                  workspaceId={activeWorkspace?.id || ""}
                  workspaceRole={workspaceRole}
                  canManageArticleLifecycle={isPlatformManager && !isPreviewReadOnly}
                />
              }
            />
            <Route
              path="build/modules"
              element={<RedirectWithNotice to={workspaceScopedTarget("build/artifacts")} notice="Modules moved into Installed/Catalog filters." />}
            />
            <Route
              path="build/blueprints"
              element={
                ENABLE_LEGACY_BLUEPRINTS ? (
                  <RedirectWithNotice to={workspaceScopedTarget("build/blueprints/versions")} notice="Blueprints moved to Build / Blueprints / Versions." />
                ) : (
                  <LegacyStatePanel
                    title="Blueprints Are Legacy"
                    message="Blueprints are disabled by default in this mode."
                    actionLabel="Open Installed Artifacts"
                    actionTo={workspaceScopedTarget("build/artifacts")}
                  />
                )
              }
            />
            <Route
              path="build/blueprints/drafts"
              element={
                ENABLE_LEGACY_BLUEPRINTS ? (
                  <BlueprintsPage mode="drafts" />
                ) : (
                  <Navigate to={workspaceScopedTarget("build/artifacts")} replace />
                )
              }
            />
            <Route
              path="build/blueprints/versions"
              element={
                ENABLE_LEGACY_BLUEPRINTS ? (
                  <BlueprintsPage mode="versions" />
                ) : (
                  <Navigate to={workspaceScopedTarget("build/artifacts")} replace />
                )
              }
            />
            <Route
              path="build/blueprints/:blueprintId"
              element={
                ENABLE_LEGACY_BLUEPRINTS ? (
                  <BlueprintsPage />
                ) : (
                  <Navigate to={workspaceScopedTarget("build/artifacts")} replace />
                )
              }
            />
            <Route
              path="build/drafts"
              element={
                ENABLE_LEGACY_BLUEPRINTS ? (
                  <RedirectWithNotice to={workspaceScopedTarget("build/blueprints/drafts")} notice="Draft Sessions moved to Build / Blueprints / Drafts." />
                ) : (
                  <Navigate to={workspaceScopedTarget("build/artifacts")} replace />
                )
              }
            />
            <Route
              path="build/draft-sessions"
              element={
                ENABLE_LEGACY_BLUEPRINTS ? (
                  <RedirectWithNotice to={workspaceScopedTarget("build/blueprints/drafts")} notice="Draft Sessions moved to Build / Blueprints / Drafts." />
                ) : (
                  <Navigate to={workspaceScopedTarget("build/artifacts")} replace />
                )
              }
            />
            <Route
              path="build/drafts/:draftId"
              element={ENABLE_LEGACY_BLUEPRINTS ? <DraftSessionsPage /> : <Navigate to={workspaceScopedTarget("build/artifacts")} replace />}
            />
            <Route
              path="build/context-packs"
              element={<RedirectWithNotice to={workspaceScopedTarget("build/artifacts")} notice="Context packs moved into Installed/Catalog filters." />}
            />
            <Route path="build/context-packs/drafts/:draftId" element={<Navigate to={workspaceScopedTarget("build/artifacts")} replace />} />
            <Route path="package/release-plans" element={<Navigate to={settingsDeployPath} replace />} />
            <Route path="package/releases" element={<Navigate to={settingsDeployPath} replace />} />
            <Route path="run/instances" element={<InstancesPage />} />
            <Route path="run/runs" element={<RunsPage />} />
            <Route path="run/dev-tasks" element={<Navigate to={runsDevTasksPath} replace />} />
            <Route path="govern/activity" element={<ActivityPage workspaceId={activeWorkspace?.id || ""} />} />
            <Route path="govern/contributions" element={<ActivityPage workspaceId={activeWorkspace?.id || ""} defaultTab="contributions" />} />

            <Route path="artifacts" element={<Navigate to={workspaceScopedTarget("build/artifacts")} replace />} />
            <Route
              path="artifacts/articles"
              element={<RedirectWithNotice to={workspaceScopedTarget("build/artifacts")} notice="Artifact kinds are now filters in Installed/Catalog." />}
            />
            <Route
              path="artifacts/workflows"
              element={<RedirectWithNotice to={workspaceScopedTarget("build/artifacts")} notice="Artifact kinds are now filters in Installed/Catalog." />}
            />
            <Route path="artifacts/all" element={<Navigate to={workspaceScopedTarget("build/artifacts")} replace />} />
            <Route path="artifacts/library" element={<Navigate to={workspaceScopedTarget("build/catalog")} replace />} />
            <Route path="catalog" element={<Navigate to={workspaceScopedTarget("build/catalog")} replace />} />
            <Route path="artifacts/:artifactId" element={<Navigate to={workspaceScopedTarget("build/artifacts")} replace />} />
            <Route path="activity" element={<Navigate to={workspaceScopedTarget("govern/activity")} replace />} />
            <Route path="home" element={<Navigate to={workspaceScopedTarget(DEFAULT_WORKSPACE_SUBPATH)} replace />} />
            <Route
              path="workspaces"
              element={<RedirectLegacyWorkspacesRoute />}
            />
            <Route path="people-roles" element={<RedirectLegacyWorkspaceAccessRoute />} />
            <Route
              path="devices"
              element={
                <LegacyStatePanel
                  title="Devices Removed"
                  message="Devices is removed from primary navigation in this mode."
                  actionLabel="Go To Runs"
                  actionTo={runsPath}
                />
              }
            />
            <Route
              path="guides"
              element={
                ENABLE_LEGACY_GUIDES ? (
                  <GuidesPage roles={effectiveRoles} />
                ) : (
                  <LegacyStatePanel
                    title="Guides Deprecated"
                    message="Guides/Tours/Map are removed from nav. Use artifact docs surfaces where available."
                    actionLabel="Open Catalog"
                    actionTo={workspaceScopedTarget("build/catalog")}
                  />
                )
              }
            />
            <Route
              path="tours"
              element={
                ENABLE_LEGACY_GUIDES ? (
                  <ToursPage />
                ) : (
                  <Navigate to={workspaceScopedTarget("build/catalog")} replace />
                )
              }
            />
            <Route
              path="tours/:workflowId"
              element={ENABLE_LEGACY_GUIDES ? <TourDetailPage /> : <Navigate to={workspaceScopedTarget("build/catalog")} replace />}
            />
            <Route
              path="map"
              element={ENABLE_LEGACY_GUIDES ? <XynMapPage /> : <Navigate to={workspaceScopedTarget("build/catalog")} replace />}
            />
            <Route path="blueprints" element={<Navigate to={workspaceScopedTarget("build/artifacts")} replace />} />
            <Route path="blueprints/drafts" element={<Navigate to={workspaceScopedTarget("build/artifacts")} replace />} />
            <Route path="blueprints/versions" element={<Navigate to={workspaceScopedTarget("build/artifacts")} replace />} />
            <Route path="blueprints/:blueprintId" element={<Navigate to={workspaceScopedTarget("build/artifacts")} replace />} />
            <Route
              path="drafts"
              element={<Navigate to={workspaceScopedTarget("build/drafts")} replace />}
            />
            <Route
              path="draft-sessions"
              element={<Navigate to={workspaceScopedTarget("build/drafts")} replace />}
            />
            <Route path="drafts/:draftId" element={<Navigate to={workspaceScopedTarget("build/drafts")} replace />} />
            <Route path="modules" element={<Navigate to={workspaceScopedTarget("build/artifacts")} replace />} />
            <Route path="release-plans" element={<Navigate to={settingsDeployPath} replace />} />
            <Route path="releases" element={<Navigate to={settingsDeployPath} replace />} />
            <Route path="instances" element={<Navigate to={workspaceScopedTarget("run/instances")} replace />} />
            <Route path="runs" element={<Navigate to={workspaceScopedTarget("run/runs")} replace />} />
            <Route
              path="dev-tasks"
              element={ENABLE_LEGACY_DEV_TASKS_PAGE ? <DevTasksPage /> : <Navigate to={runsDevTasksPath} replace />}
            />
            <Route path="environments" element={<Navigate to={runsPath} replace />} />
            <Route path="context-packs" element={<Navigate to={workspaceScopedTarget("build/artifacts")} replace />} />
            <Route path="context-packs/drafts/:draftId" element={<Navigate to={workspaceScopedTarget("build/artifacts")} replace />} />
            <Route path="my-tenants" element={<RedirectLegacyWorkspacesRoute />} />
            <Route
              path="control-plane"
              element={
                ENABLE_LEGACY_CONTROL_PLANE ? (
                  <ControlPlanePage />
                ) : (
                  <LegacyStatePanel
                    title="Control Plane Deprecated"
                    message="Control plane is removed from primary nav in this mode."
                    actionLabel="Open Platform Settings · Deploy"
                    actionTo={settingsDeployPath}
                  />
                )
              }
            />
            <Route path="platform/tenants" element={<RedirectLegacyWorkspacesRoute />} />
            <Route path="platform/tenants/:tenantId" element={<RedirectLegacyWorkspacesRoute />} />
            <Route path="platform/tenant-contacts" element={<RedirectLegacyWorkspacesRoute />} />
            <Route path="platform/tenant-contacts/:tenantId" element={<RedirectLegacyTenantContactsDetailRoute />} />
            <Route path="platform/access-control" element={<AccessControlPage />} />
            <Route path="platform/access-explorer" element={<RedirectLegacyAccessControlRoute tab="explorer" />} />
            <Route path="platform/users" element={<RedirectLegacyAccessControlRoute tab="users" />} />
            <Route path="platform/roles" element={<RedirectLegacyAccessControlRoute tab="roles" />} />
            <Route path="platform/branding" element={<PlatformBrandingPage />} />
            <Route path="platform/settings" element={<PlatformSettingsPage />} />
            <Route path="platform/video-adapter-configs/:artifactId" element={<VideoAdapterConfigPage />} />
            <Route path="platform/seeds" element={<SeedPacksPage />} />
            <Route path="platform/identity-configuration" element={<IdentityConfigurationPage />} />
            <Route path="platform/identity-providers" element={<RedirectLegacyIdentityRoute tab="identity-providers" />} />
            <Route path="platform/oidc-app-clients" element={<RedirectLegacyIdentityRoute tab="oidc-app-clients" />} />
            <Route path="platform/secrets" element={<SecretConfigurationPage />} />
            <Route path="platform/secret-stores" element={<RedirectLegacySecretsRoute tab="stores" />} />
            <Route path="platform/secret-refs" element={<RedirectLegacySecretsRoute tab="refs" />} />
            <Route path="platform/ai-config" element={<Navigate to={workspaceScopedTarget("platform/ai-agents")} replace />} />
            <Route path="platform/ai-configuration" element={<Navigate to={workspaceScopedTarget("platform/ai-agents")} replace />} />
            <Route path="platform/ai-agents" element={<AIConfigPage />} />
            <Route path="platform/ai/credentials" element={<RedirectLegacyAiRoute tab="credentials" />} />
            <Route path="platform/ai/model-configs" element={<RedirectLegacyAiRoute tab="model-configs" />} />
            <Route path="platform/ai/agents" element={<RedirectLegacyAiRoute tab="agents" />} />
            <Route path="platform/ai/purposes" element={<RedirectLegacyAiRoute tab="purposes" />} />
            <Route path="settings" element={<WorkspaceSettingsPage workspaceName={activeWorkspace?.name || "Workspace"} />} />
            <Route path="*" element={<Navigate to={inWorkspaceScope ? DEFAULT_WORKSPACE_SUBPATH : "workspaces"} replace />} />
          </Routes>
        </main>
      </div>
      <HelpDrawer
        open={helpOpen}
        onClose={() => setHelpOpen(false)}
        routeId={routeId}
        workspaceId={activeWorkspace?.id || ""}
        roles={effectiveRoles}
        onStartTour={(slug) => {
          setTourSlug(slug);
          setTourLaunchToken((value) => value + 1);
        }}
      />
      <TourOverlay
        userKey={userContext.id || userContext.email || "anon"}
        launchSlug={tourSlug}
        launchToken={tourLaunchToken}
        currentPath={location.pathname}
        navigateTo={(path) => navigate(path)}
        onClose={() => setTourSlug(null)}
        canRecord={isPlatformManager}
      />
      <ReportOverlay
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        user={userContext}
        onSubmitted={(reportId) =>
          push({
            level: "success",
            title: "Report submitted",
            message: reportId,
            action: "report.create",
            entityType: "unknown",
            entityId: reportId,
            status: "succeeded",
            dedupeKey: `report:${reportId}`,
          })
        }
      />
      <AgentActivityDrawer
        open={agentActivityOpen}
        onClose={() => setAgentActivityOpen(false)}
        workspaceId={activeWorkspace?.id || ""}
        artifactId={artifactRouteId || undefined}
      />
      {!hideFloatingConsoleNode ? <XynConsoleNode /> : null}
      <SuggestionSwitcher workspaceId={activeWorkspace?.id || ""} />
      <ToastHost />
    </div>
  );
}
