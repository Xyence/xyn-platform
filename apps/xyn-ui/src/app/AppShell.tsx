import { Suspense, lazy, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { getAuthMode, getMe, getMyProfile, getTenantBranding, listArtifactNavSurfaces, listWorkspaces } from "../api/xyn";
import { setRuntimeAuthMode } from "../api/client";
import type { ArtifactSurface } from "../api/types";
import { CREATE_ACTIONS, NAV_GROUPS, NAV_MOVE_TOAST_STORAGE_KEY, NavGroup, NavUserContext } from "./nav/nav.config";
import { getBreadcrumbs, visibleNav } from "./nav/nav.utils";
import { withArtifactSurfaceNav } from "./nav/artifactSurfaceNav";
import Sidebar from "./components/nav/Sidebar";
const BlueprintsPage = lazy(() => import("./pages/BlueprintsPage"));
const InstancesPage = lazy(() => import("./pages/InstancesPage"));
const SecretConfigurationPage = lazy(() => import("./pages/SecretConfigurationPage"));
const AIConfigPage = lazy(() => import("./pages/AIConfigPage"));
const IdentityConfigurationPage = lazy(() => import("./pages/IdentityConfigurationPage"));
const AccessControlPage = lazy(() => import("./pages/AccessControlPage"));
const RunsPage = lazy(() => import("./pages/RunsPage"));
const SourceInspectionReviewPage = lazy(() => import("./pages/SourceInspectionReviewPage"));
const ApplicationNotificationsPage = lazy(() => import("./pages/ApplicationNotificationsPage"));
const ApplicationNotificationSettingsPage = lazy(() => import("./pages/ApplicationNotificationSettingsPage"));
const JobsListPage = lazy(() => import("./pages/JobsListPage"));
const JobDetailPage = lazy(() => import("./pages/JobDetailPage"));
const ActivityPage = lazy(() => import("./pages/ActivityPage"));
const DevTasksPage = lazy(() => import("./pages/DevTasksPage"));
const PlatformBrandingPage = lazy(() => import("./pages/PlatformBrandingPage"));
const ControlPlanePage = lazy(() => import("./pages/ControlPlanePage"));
const GuidesPage = lazy(() => import("./pages/GuidesPage"));
const ToursPage = lazy(() => import("./pages/ToursPage"));
const TourDetailPage = lazy(() => import("./pages/TourDetailPage"));
const XynMapPage = lazy(() => import("./pages/XynMapPage"));
const CapabilityExplorerPage = lazy(() => import("./pages/CapabilityExplorerPage"));
const PlatformSettingsPage = lazy(() => import("./pages/PlatformSettingsPage"));
const PlatformSettingsHubPage = lazy(() => import("./pages/PlatformSettingsHubPage"));
const AIAgentRoutingPage = lazy(() => import("./pages/AIAgentRoutingPage"));
const PlatformDeploySettingsPage = lazy(() => import("./pages/PlatformDeploySettingsPage"));
const PlatformRenderingSettingsPage = lazy(() => import("./pages/PlatformRenderingSettingsPage"));
const VideoAdapterConfigPage = lazy(() => import("./pages/VideoAdapterConfigPage"));
const SeedPacksPage = lazy(() => import("./pages/SeedPacksPage"));
const ArtifactsRegistryPage = lazy(() => import("./pages/ArtifactsRegistryPage"));
const ArtifactsLibraryPage = lazy(() => import("./pages/ArtifactsLibraryPage"));
const ArtifactDetailPage = lazy(() => import("./pages/ArtifactDetailPage"));
const ArtifactComposerPage = lazy(() => import("./pages/ArtifactComposerPage"));
const SolutionsPage = lazy(() => import("./pages/SolutionsPage"));
const SolutionDetailPage = lazy(() => import("./pages/SolutionDetailPage"));
const ArtifactSurfaceRoutePage = lazy(() => import("./pages/ArtifactSurfaceRoutePage"));
const ArticleSurfaceEditorRedirectPage = lazy(() => import("./pages/ArticleSurfaceEditorRedirectPage"));
const ArticleSurfaceDocsPage = lazy(() => import("./pages/ArticleSurfaceDocsPage"));
const WorkbenchPage = lazy(() => import("./pages/WorkbenchPage"));
const WorkspaceSettingsPage = lazy(() => import("./pages/WorkspaceSettingsPage"));
const DraftsListPage = lazy(() => import("./pages/DraftsListPage"));
const DraftCreatePage = lazy(() => import("./pages/DraftCreatePage"));
const DraftDetailPage = lazy(() => import("./pages/DraftDetailPage"));
const WorkspacesPage = lazy(() => import("./pages/WorkspacesPage"));
const PlatformInitializationPage = lazy(() => import("./pages/PlatformInitializationPage"));
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
import PreviewBanner from "./components/preview/PreviewBanner";
import XynConsoleNode from "./components/console/XynConsoleNode";
import HeaderUtilityMenu from "./components/common/HeaderUtilityMenu";
import LinkedDevSessionBanner from "./components/common/LinkedDevSessionBanner";
import SuggestionSwitcher from "./components/console/SuggestionSwitcher";
import { useXynConsole } from "./state/xynConsoleStore";
import useWorkspaceFromRoute from "./hooks/useWorkspaceFromRoute";
import {
  DEFAULT_WORKSPACE_SUBPATH,
  isWorkspaceScopedPath,
  swapWorkspaceInPath,
  toWorkspacePath,
  withWorkspaceInNavPath,
} from "./routing/workspaceRouting";
import { requiresPlatformInitialization, resolveDefaultWorkspaceForUser, resolvePostLoginDestination } from "./routing/bootstrapResolver";
import { canonicalLegacyRouteForPlatformSettings } from "./routing/promptSurfaceResolver";
import { emitCapabilityEvent } from "./events/emitCapabilityEvent";

function readFlag(value: unknown): boolean {
  return String(value || "").trim().toLowerCase() === "true";
}

function navDebugEnabled(search: string): boolean {
  if (typeof window === "undefined") return false;
  const query = new URLSearchParams(String(search || ""));
  return query.get("xyn_debug_nav") === "1" || window.localStorage.getItem("xyn.debug.nav") === "1";
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

function PlatformSettingsLegacyRoute({ workspaceId }: { workspaceId: string }) {
  const location = useLocation();
  const incomingParams = new URLSearchParams(location.search);
  if (incomingParams.get("legacy") === "1") {
    return <PlatformSettingsPage />;
  }
  const tab = String(incomingParams.get("tab") || "").trim().toLowerCase();
  const wsTab = String(incomingParams.get("wsTab") || "").trim().toLowerCase();
  if (tab === "security") return <Navigate to="/app/platform/settings/security" replace />;
  if (tab === "integrations") return <Navigate to="/app/platform/settings/integrations" replace />;
  if (tab === "deploy") return <Navigate to="/app/platform/deploy" replace />;
  if (tab === "workspaces") {
    if (wsTab === "members") return <Navigate to="/app/platform/access-control?tab=users" replace />;
    return <Navigate to="/app/platform/workspaces" replace />;
  }
  if (tab === "general") return <Navigate to="/app/platform/settings/general" replace />;
  const canonical = canonicalLegacyRouteForPlatformSettings(workspaceId);
  if (!canonical) {
    return <PlatformSettingsPage />;
  }
  const canonicalUrl = new URL(canonical, "http://xyn.local");
  const merged = new URLSearchParams(canonicalUrl.search);
  for (const [key, value] of incomingParams.entries()) {
    if (key === "legacy") continue;
    if (!merged.has(key)) merged.set(key, value);
  }
  const nextTarget = `${canonicalUrl.pathname}${merged.toString() ? `?${merged.toString()}` : ""}`;
  const currentTarget = `${location.pathname}${location.search || ""}`;
  if (nextTarget === currentTarget) {
    return <PlatformSettingsPage />;
  }
  return <Navigate to={nextTarget} replace />;
}

function RouteLoadingFallback() {
  return (
    <section className="card">
      <p className="muted">Loading view…</p>
    </section>
  );
}

type PlatformSettingsSurface =
  | "hub"
  | "access_control"
  | "identity_configuration"
  | "secrets"
  | "activity"
  | "ai_routing"
  | "ai_agents"
  | "rendering_settings"
  | "deploy_settings"
  | "workspaces"
  | "branding";

type PlatformSettingsTab = {
  id: string;
  surface: PlatformSettingsSurface;
  label: string;
};

const DEFAULT_PLATFORM_SETTINGS_TAB: PlatformSettingsTab = {
  id: "platform-settings-hub",
  surface: "hub",
  label: "Platform Settings",
};

function platformSettingsSurfaceLabel(surface: PlatformSettingsSurface): string {
  switch (surface) {
    case "access_control":
      return "Access Control";
    case "identity_configuration":
      return "Identity Configuration";
    case "secrets":
      return "Secrets";
    case "activity":
      return "Activity";
    case "ai_routing":
      return "AI Agent Routing";
    case "ai_agents":
      return "AI Agents";
    case "rendering_settings":
      return "Rendering Settings";
    case "deploy_settings":
      return "Deploy";
    case "workspaces":
      return "Workspaces";
    case "branding":
      return "Branding";
    default:
      return "Platform Settings";
  }
}

function platformSettingsSurfacePath(surface: PlatformSettingsSurface): string {
  switch (surface) {
    case "access_control":
      return "/app/platform/access-control";
    case "identity_configuration":
      return "/app/platform/identity-configuration";
    case "secrets":
      return "/app/platform/secrets";
    case "activity":
      return "/app/platform/activity";
    case "ai_routing":
      return "/app/platform/ai-routing";
    case "ai_agents":
      return "/app/platform/ai-agents";
    case "rendering_settings":
      return "/app/platform/rendering-settings";
    case "deploy_settings":
      return "/app/platform/deploy";
    case "workspaces":
      return "/app/platform/workspaces";
    case "branding":
      return "/app/platform/branding";
    default:
      return "/app/platform/hub";
  }
}

function mapPlatformSettingsRouteToSurface(route: string): PlatformSettingsSurface | null {
  const path = String(route || "").split("?", 1)[0].trim().toLowerCase();
  if (path.endsWith("/platform/access-control")) return "access_control";
  if (path.endsWith("/platform/identity-configuration")) return "identity_configuration";
  if (path.endsWith("/platform/secrets")) return "secrets";
  if (path.endsWith("/platform/activity")) return "activity";
  if (path.endsWith("/platform/ai-routing")) return "ai_routing";
  if (path.endsWith("/platform/ai-agents")) return "ai_agents";
  if (path.endsWith("/platform/rendering-settings")) return "rendering_settings";
  if (path.endsWith("/platform/deploy")) return "deploy_settings";
  if (path.endsWith("/platform/workspaces")) return "workspaces";
  if (path.endsWith("/platform/branding")) return "branding";
  if (path.endsWith("/platform/hub")) return "hub";
  return null;
}

function GlobalPlatformSettingsRoute({
  initialSurface,
  sectionOverride,
  activeWorkspaceId,
  activeWorkspaceName,
  canWorkspaceAdmin,
  canManageWorkspaces,
}: {
  initialSurface: PlatformSettingsSurface;
  sectionOverride?: "general" | "security" | "integrations" | "deploy" | "workspaces";
  activeWorkspaceId: string;
  activeWorkspaceName: string;
  canWorkspaceAdmin: boolean;
  canManageWorkspaces: boolean;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const [tabs, setTabs] = useState<PlatformSettingsTab[]>(() =>
    initialSurface === "hub"
      ? [DEFAULT_PLATFORM_SETTINGS_TAB]
      : [DEFAULT_PLATFORM_SETTINGS_TAB, { id: `platform-settings-${initialSurface}`, surface: initialSurface, label: platformSettingsSurfaceLabel(initialSurface) }]
  );
  const [activeTabId, setActiveTabId] = useState<string>(
    initialSurface === "hub" ? DEFAULT_PLATFORM_SETTINGS_TAB.id : `platform-settings-${initialSurface}`
  );

  useEffect(() => {
    const routeSurface = mapPlatformSettingsRouteToSurface(location.pathname) || initialSurface;
    const tabId = routeSurface === "hub" ? DEFAULT_PLATFORM_SETTINGS_TAB.id : `platform-settings-${routeSurface}`;
    setTabs((current) => {
      if (routeSurface === "hub") return current;
      if (current.some((item) => item.id === tabId)) return current;
      return [...current, { id: tabId, surface: routeSurface, label: platformSettingsSurfaceLabel(routeSurface) }];
    });
    setActiveTabId(tabId);
  }, [initialSurface, location.pathname]);

  const activeSurface =
    tabs.find((item) => item.id === activeTabId)?.surface ||
    tabs[tabs.length - 1]?.surface ||
    DEFAULT_PLATFORM_SETTINGS_TAB.surface;

  const closeSurfaceTab = (tabId: string) => {
    if (tabId === DEFAULT_PLATFORM_SETTINGS_TAB.id) return;
    const closingActive = activeTabId === tabId;
    setTabs((current) => {
      const next = current.filter((item) => item.id !== tabId);
      return next.length ? next : [DEFAULT_PLATFORM_SETTINGS_TAB];
    });
    if (closingActive) {
      setActiveTabId(DEFAULT_PLATFORM_SETTINGS_TAB.id);
      navigate("/app/platform/hub", { replace: true });
    }
  };

  const navigateToSurface = (surface: PlatformSettingsSurface) => {
    navigate(platformSettingsSurfacePath(surface));
  };

  return (
    <div style={{ display: "grid", gap: 8 }}>
      <div className="page-tabs" aria-label="Platform settings tabs">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {tabs.map((tab) => (
            <div key={tab.id} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <button
                type="button"
                className={activeTabId === tab.id ? "ghost active" : "ghost"}
                onClick={() => navigateToSurface(tab.surface)}
                aria-current={activeTabId === tab.id ? "page" : undefined}
              >
                {tab.label}
              </button>
              {tab.id !== DEFAULT_PLATFORM_SETTINGS_TAB.id ? (
                <button type="button" className="ghost sm" onClick={() => closeSurfaceTab(tab.id)} aria-label={`Close ${tab.label}`}>
                  x
                </button>
              ) : null}
            </div>
          ))}
        </div>
      </div>
      {activeSurface === "hub" ? (
        <PlatformSettingsHubPage
          sectionOverride={sectionOverride}
          onOpenRoute={(route) => {
            const mapped = mapPlatformSettingsRouteToSurface(route);
            if (!mapped) {
              navigate(route);
              return;
            }
            navigateToSurface(mapped);
          }}
        />
      ) : null}
      {activeSurface === "access_control" ? <AccessControlPage /> : null}
      {activeSurface === "identity_configuration" ? <IdentityConfigurationPage /> : null}
      {activeSurface === "secrets" ? <SecretConfigurationPage /> : null}
      {activeSurface === "activity" ? <ActivityPage workspaceId="" /> : null}
      {activeSurface === "ai_routing" ? <AIAgentRoutingPage /> : null}
      {activeSurface === "ai_agents" ? <AIConfigPage /> : null}
      {activeSurface === "rendering_settings" ? <PlatformRenderingSettingsPage /> : null}
      {activeSurface === "deploy_settings" ? <PlatformDeploySettingsPage /> : null}
      {activeSurface === "workspaces" ? (
        <WorkspacesPage
          activeWorkspaceId={activeWorkspaceId}
          activeWorkspaceName={activeWorkspaceName}
          canWorkspaceAdmin={canWorkspaceAdmin}
          canManageWorkspaces={canManageWorkspaces}
        />
      ) : null}
      {activeSurface === "branding" ? <PlatformBrandingPage /> : null}
    </div>
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
  const [platformInitRequired, setPlatformInitRequired] = useState(false);
  const invalidWorkspaceRecoveryRef = useRef<string>("");
  const { push } = useNotifications();
  const { runningAiCount } = useOperations();
  const { preview, disablePreviewMode } = usePreview();
  const { handleRouteChange } = useXynConsole();
  const hideFloatingConsoleNode = location.pathname.includes("/console");
  const workspaceRoute = useWorkspaceFromRoute(workspaces);
  const workspaceIdFromRoute = workspaceRoute.workspaceId;
  const inWorkspaceScope = isWorkspaceScopedPath(location.pathname);
  const routeWorkspaceIsValid = Boolean(workspaceIdFromRoute && workspaces.some((workspace) => workspace.id === workspaceIdFromRoute));
  const preferredWorkspaceIsValid = Boolean(preferredWorkspaceId && workspaces.some((workspace) => workspace.id === preferredWorkspaceId));
  const invalidWorkspaceRoute = Boolean(inWorkspaceScope && workspaceIdFromRoute && !routeWorkspaceIsValid);
  const activeWorkspaceId = inWorkspaceScope ? (routeWorkspaceIsValid ? workspaceIdFromRoute : "") : (preferredWorkspaceIsValid ? preferredWorkspaceId : "");

  useEffect(() => {
    let mounted = true;
    const debugEnabled = navDebugEnabled(typeof window !== "undefined" ? window.location.search : location.search);
    const authBootstrapTimeout = window.setTimeout(() => {
      if (!mounted) return;
      if (debugEnabled) {
        console.debug("[xyn-auth] bootstrap timeout; forcing authLoaded=true");
      }
      setAuthLoaded(true);
    }, 12000);
    (async () => {
      try {
        if (debugEnabled) {
          console.debug("[xyn-auth] bootstrap start", { path: location.pathname });
        }
        try {
          const modePayload = await getAuthMode();
          setRuntimeAuthMode(modePayload?.auth_mode || "dev");
          if (debugEnabled) {
            console.debug("[xyn-auth] mode loaded", modePayload);
          }
        } catch {
          // Fallback to bootstrap response if auth mode endpoint is unavailable.
        }
        const me = await getMe();
        if (debugEnabled) {
          console.debug("[xyn-auth] me loaded", {
            user: me?.user?.email || me?.user?.subject || null,
            workspace_count: Array.isArray(me?.workspaces) ? me.workspaces.length : 0,
          });
        }
        if (!mounted) return;
        if (me?.auth_mode) {
          setRuntimeAuthMode(String(me.auth_mode));
        }
        setAuthed(Boolean(me?.user));
        setAuthUser((me?.user as Record<string, unknown>) || null);
        setRoles(me?.roles ?? []);
        setPermissions(me?.permissions ?? []);
        setActorRoles(me?.actor_roles ?? me?.roles ?? []);
        setPlatformInitRequired(requiresPlatformInitialization(me));
        setUserContext({
          id: (me?.user?.subject as string | null) || (me?.user?.sub as string | null) || "",
          email: (me?.user?.email as string | null) || "",
        });
        const meWorkspaces = me?.workspaces || [];
        if (Array.isArray(meWorkspaces) && meWorkspaces.length > 0) {
          setWorkspaces(meWorkspaces);
          const persisted = String(window.localStorage.getItem("xyn.activeWorkspaceId") || "").trim();
          const resolved = resolveDefaultWorkspaceForUser(me, persisted);
          if (persisted && persisted !== resolved) {
            window.localStorage.removeItem("xyn.activeWorkspaceId");
          }
          setPreferredWorkspaceId(resolved || "");
        } else {
          try {
            const ws = await listWorkspaces();
            if (!mounted) return;
            setWorkspaces(ws.workspaces || []);
            const fallbackMe = { ...me, workspaces: ws.workspaces || [] };
            const persisted = String(window.localStorage.getItem("xyn.activeWorkspaceId") || "").trim();
            const resolved = resolveDefaultWorkspaceForUser(fallbackMe, persisted);
            if (persisted && persisted !== resolved) {
              window.localStorage.removeItem("xyn.activeWorkspaceId");
            }
            setPreferredWorkspaceId(resolved || "");
            if (debugEnabled) {
              console.debug("[xyn-auth] loaded workspaces via /xyn/api/workspaces", {
                workspace_count: Array.isArray(ws.workspaces) ? ws.workspaces.length : 0,
              });
            }
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
        if (debugEnabled) {
          console.debug("[xyn-auth] bootstrap failed; marking unauthenticated");
        }
        setAuthed(false);
        setAuthUser(null);
        setRoles([]);
        setPermissions([]);
        setActorRoles([]);
        setPlatformInitRequired(false);
      } finally {
        if (mounted) {
          window.clearTimeout(authBootstrapTimeout);
          setAuthLoaded(true);
        }
      }
    })();
    return () => {
      mounted = false;
      window.clearTimeout(authBootstrapTimeout);
    };
  }, []);

  useEffect(() => {
    if (!authed) {
      setSurfaceNavItems([]);
      return;
    }
    const navWorkspaceId = inWorkspaceScope ? activeWorkspaceId || undefined : undefined;
    let mounted = true;
    (async () => {
      try {
        const payload = await listArtifactNavSurfaces(navWorkspaceId);
        if (!mounted) return;
        setSurfaceNavItems(payload.surfaces || []);
      } catch (error) {
        if (!mounted) return;
        const message = error instanceof Error ? error.message : String(error || "");
        const normalized = message.toLowerCase();
        if ((normalized.includes("forbidden") || normalized.includes("403")) && navWorkspaceId) {
          push({
            level: "warning",
            title: "Workspace access denied",
            message: `Current workspace is not accessible (${navWorkspaceId}).`,
          });
        }
        setSurfaceNavItems([]);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [authed, activeWorkspaceId, inWorkspaceScope, navRefreshToken, push]);

  useEffect(() => {
    const onWorkspaceArtifactsChanged = () => {
      const workspaceId = activeWorkspaceId || workspaceIdFromRoute || "";
      setNavRefreshToken((value) => value + 1);
      void emitCapabilityEvent({
        eventType: "artifact_created",
        workspaceId,
      });
    };
    window.addEventListener("xyn:workspace-artifacts-changed", onWorkspaceArtifactsChanged);
    return () => window.removeEventListener("xyn:workspace-artifacts-changed", onWorkspaceArtifactsChanged);
  }, [activeWorkspaceId, workspaceIdFromRoute]);

  useEffect(() => {
    if (activeWorkspaceId) {
      localStorage.setItem("xyn.activeWorkspaceId", activeWorkspaceId);
      return;
    }
    localStorage.removeItem("xyn.activeWorkspaceId");
  }, [activeWorkspaceId]);

  useEffect(() => {
    if (workspaceIdFromRoute) {
      setPreferredWorkspaceId(workspaceIdFromRoute);
    }
  }, [workspaceIdFromRoute]);

  useEffect(() => {
    if (!authLoaded || !authed || !platformInitRequired) return;
    if (location.pathname === "/app/setup/initialize") return;
    navigate("/app/setup/initialize", { replace: true });
  }, [authLoaded, authed, location.pathname, navigate, platformInitRequired]);

  useEffect(() => {
    if (!authLoaded || !authed) return;
    if (!inWorkspaceScope || !workspaceIdFromRoute || routeWorkspaceIsValid) return;
    const recoveryTarget = resolvePostLoginDestination(
      {
        workspaces: workspaces.map((workspace) => ({ id: workspace.id, slug: workspace.slug, name: workspace.name, role: workspace.role })),
        preferred_workspace_id: preferredWorkspaceId || undefined,
        platform_initialization: {
          initialized: !platformInitRequired,
          requires_setup: platformInitRequired,
          workspace_count: workspaces.length,
          auth_mode: "unknown",
        },
      },
      preferredWorkspaceId
    );
    const dedupeKey = `${location.pathname}${location.search}->${recoveryTarget}`;
    if (invalidWorkspaceRecoveryRef.current === dedupeKey) return;
    invalidWorkspaceRecoveryRef.current = dedupeKey;
    window.localStorage.removeItem("xyn.activeWorkspaceId");
    push({
      level: "warning",
      title: "Workspace unavailable",
      message: `Recovered from stale workspace ${workspaceIdFromRoute}.`,
    });
    navigate(recoveryTarget, { replace: true });
  }, [
    authLoaded,
    authed,
    inWorkspaceScope,
    location.pathname,
    location.search,
    navigate,
    platformInitRequired,
    preferredWorkspaceId,
    push,
    routeWorkspaceIsValid,
    workspaces,
    workspaceIdFromRoute,
  ]);

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
    return withArtifactSurfaceNav(NAV_GROUPS, surfaceNavItems || [], activeWorkspaceId || "");
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
    () => workspaces.find((workspace) => workspace.id === activeWorkspaceId) || null,
    [workspaces, activeWorkspaceId]
  );
  const workspaceSelectionOptions = useMemo(
    () => workspaces.map((workspace) => ({ id: workspace.id, name: workspace.name, slug: workspace.slug })),
    [workspaces]
  );
  const workspaceScopedContextId = inWorkspaceScope ? activeWorkspace?.id || "" : "";
  const isWorkbenchRoute = useMemo(
    () => /\/w\/[^/]+\/workbench\/?$/.test(location.pathname) || /^\/app\/platform(?:\/|$)/.test(location.pathname),
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
          <Link className="brand brand-link" to="/">
            <img className="brand-logo" src="/xyence-logo.png" alt="Xyence logo" />
            <div>
              <h1>Xyn</h1>
              <p>Loading session...</p>
            </div>
          </Link>
        </header>
      </div>
    );
  }

  if (!authed) {
    return (
      <div className="app-shell">
        <header className="app-header">
          <Link className="brand brand-link" to="/">
            <img className="brand-logo" src="/xyence-logo.png" alt="Xyence logo" />
            <div>
              <h1>Xyn</h1>
              <p>Redirecting to sign in...</p>
            </div>
          </Link>
        </header>
      </div>
    );
  }

  return (
    <div className={`app-shell ${isWorkbenchRoute ? "is-workbench" : ""}`}>
      <header className={`app-header ${isWorkbenchRoute ? "is-workbench" : ""}`} ref={headerRef}>
        <div className="app-header-branding">
          <Link className="brand brand-link" to="/">
            <img className="brand-logo" src={brandLogo} alt="Xyence logo" />
            <div>
              <h1>Xyn</h1>
            </div>
          </Link>
          {isWorkbenchRoute && activeWorkspace?.name ? (
            <div className="app-header-workspace">
              <label htmlFor="workspace-selector" className="sr-only">
                Workspace
              </label>
              <select
                id="workspace-selector"
                className="workspace-selector"
                value={activeWorkspace.id}
                onChange={(event) => handleWorkspaceChange(String(event.target.value || ""))}
              >
                {workspaceSelectionOptions.map((workspace) => (
                  <option key={workspace.id} value={workspace.id}>
                    {workspace.name}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
        </div>
        <div className="header-meta">
          {authed ? (
            <>
              {isWorkbenchRoute && activeWorkspace?.id ? (
                <HeaderUtilityMenu
                  workspaceId={activeWorkspace.id}
                  actorRoles={actorRoles}
                  actorLabel={String(authUser?.email || authUser?.display_name || authUser?.subject || "current user")}
                  onOpenAgentActivity={() => setAgentActivityOpen(true)}
                  onMessage={({ level, title, message }) => push({ level, title, message })}
                />
              ) : null}
              <NotificationBell />
              <UserMenu
                user={authUser || {}}
                onReport={() => setReportOpen(true)}
                onSignOut={signOut}
              />
              {runningAiCount > 0 && <span className="agent-thinking-label">Agents active ({runningAiCount})</span>}
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
        <main className={`app-content ${isWorkbenchRoute ? "app-content-workbench" : ""}`} ref={contentRef}>
          <div className={`preview-banner-slot ${preview.enabled ? "active" : ""}`}>
            <PreviewBanner
              actorLabel={String(authUser?.email || authUser?.display_name || authUser?.subject || "current user")}
              onExit={async () => {
                await disablePreviewMode();
                push({ level: "success", title: "Preview ended" });
              }}
            />
          </div>
          {isWorkbenchRoute && activeWorkspace?.id ? (
            <LinkedDevSessionBanner workspaceId={activeWorkspace.id} />
          ) : null}
          {!isWorkbenchRoute && breadcrumbTrail.length > 0 && (
            <div className="app-breadcrumbs" aria-label="Breadcrumb">
              {breadcrumbTrail.map((crumb) => crumb.label).join(" / ")}
            </div>
          )}
          {invalidWorkspaceRoute ? (
            <LegacyStatePanel
              title="Workspace Not Accessible"
              message={`Workspace "${workspaceIdFromRoute}" is unavailable or you do not have access. Select a workspace manually from the sidebar.`}
              actionLabel="Go to Global Platform Settings"
              actionTo="/app/platform/hub"
            />
          ) : (
          <Suspense fallback={<RouteLoadingFallback />}>
          <Routes>
            <Route path="/" element={<Navigate to={inWorkspaceScope ? DEFAULT_WORKSPACE_SUBPATH : "/"} replace />} />
            <Route
              path="workbench"
              element={(
                <WorkbenchPage
                  workspaceName={activeWorkspace?.name || ""}
                  workspaceColor={workspaceRoute.workspaceColor}
                  currentUser={authUser}
                />
              )}
            />
            <Route path="capabilities" element={<CapabilityExplorerPage />} />
            <Route path="console" element={<Navigate to={workspaceScopedTarget(DEFAULT_WORKSPACE_SUBPATH)} replace />} />
            <Route path="apps/articles/edit" element={<ArticleSurfaceEditorRedirectPage />} />
            <Route path="apps/articles/docs" element={<ArticleSurfaceDocsPage />} />
            {/* Compatibility-only routes.
                New capability UX must be palette -> panel intent -> workbench panel.
                These routes must remain thin redirects and must not own business logic. */}
            <Route path="solutions" element={<SolutionsPage workspaceId={activeWorkspace?.id || ""} />} />
            <Route path="solutions/:applicationId" element={<SolutionDetailPage workspaceId={activeWorkspace?.id || ""} />} />
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
              element={<ArtifactComposerPage workspaceId={activeWorkspace?.id || ""} />}
            />
            <Route
              path="build/artifacts/:artifactId/detail"
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
              element={<Navigate to={workspaceScopedTarget("drafts")} replace />}
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
              element={<DraftDetailPage workspaceId={activeWorkspace?.id || ""} workspaceName={activeWorkspace?.name || ""} workspaceColor={workspaceRoute.workspaceColor} />}
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
            <Route path="sources" element={<SourceInspectionReviewPage workspaceId={activeWorkspace?.id || ""} workspaceName={activeWorkspace?.name || ""} />} />
            <Route path="notifications" element={<ApplicationNotificationsPage />} />
            <Route
              path="notifications/settings"
              element={<ApplicationNotificationSettingsPage workspaceId={activeWorkspace?.id || ""} workspaceRole={activeWorkspace?.role || ""} />}
            />
            <Route
              path="run/jobs"
              element={<JobsListPage workspaceId={activeWorkspace?.id || ""} workspaceName={activeWorkspace?.name || ""} workspaceColor={workspaceRoute.workspaceColor} />}
            />
            <Route path="run/dev-tasks" element={<Navigate to={runsDevTasksPath} replace />} />
            <Route path="govern/activity" element={<ActivityPage workspaceId={activeWorkspace?.id || ""} />} />
            <Route path="govern/contributions" element={<ActivityPage workspaceId={activeWorkspace?.id || ""} defaultTab="contributions" />} />

            <Route
              path="drafts"
              element={<DraftsListPage workspaceId={activeWorkspace?.id || ""} workspaceName={activeWorkspace?.name || ""} workspaceColor={workspaceRoute.workspaceColor} />}
            />
            <Route
              path="drafts/new"
              element={<DraftCreatePage workspaceId={activeWorkspace?.id || ""} workspaceName={activeWorkspace?.name || ""} workspaceColor={workspaceRoute.workspaceColor} />}
            />
            <Route
              path="drafts/:draftId"
              element={<DraftDetailPage workspaceId={activeWorkspace?.id || ""} workspaceName={activeWorkspace?.name || ""} workspaceColor={workspaceRoute.workspaceColor} />}
            />
            <Route
              path="jobs"
              element={<JobsListPage workspaceId={activeWorkspace?.id || ""} workspaceName={activeWorkspace?.name || ""} workspaceColor={workspaceRoute.workspaceColor} />}
            />
            <Route
              path="jobs/:jobId"
              element={<JobDetailPage workspaceId={activeWorkspace?.id || ""} workspaceName={activeWorkspace?.name || ""} workspaceColor={workspaceRoute.workspaceColor} />}
            />

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
              path="draft-sessions"
              element={<Navigate to={workspaceScopedTarget("drafts")} replace />}
            />
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
            <Route path="setup/initialize" element={<PlatformInitializationPage />} />
            <Route
              path="platform/hub"
              element={
                <GlobalPlatformSettingsRoute
                  initialSurface="hub"
                  activeWorkspaceId={activeWorkspace?.id || ""}
                  activeWorkspaceName={activeWorkspace?.name || "Workspace"}
                  canWorkspaceAdmin={canWorkspaceAdmin}
                  canManageWorkspaces={isPlatformManager && !isPreviewReadOnly}
                />
              }
            />
            <Route
              path="platform/settings/general"
              element={
                <GlobalPlatformSettingsRoute
                  initialSurface="hub"
                  sectionOverride="general"
                  activeWorkspaceId={activeWorkspace?.id || ""}
                  activeWorkspaceName={activeWorkspace?.name || "Workspace"}
                  canWorkspaceAdmin={canWorkspaceAdmin}
                  canManageWorkspaces={isPlatformManager && !isPreviewReadOnly}
                />
              }
            />
            <Route
              path="platform/settings/security"
              element={
                <GlobalPlatformSettingsRoute
                  initialSurface="hub"
                  sectionOverride="security"
                  activeWorkspaceId={activeWorkspace?.id || ""}
                  activeWorkspaceName={activeWorkspace?.name || "Workspace"}
                  canWorkspaceAdmin={canWorkspaceAdmin}
                  canManageWorkspaces={isPlatformManager && !isPreviewReadOnly}
                />
              }
            />
            <Route
              path="platform/settings/integrations"
              element={
                <GlobalPlatformSettingsRoute
                  initialSurface="hub"
                  sectionOverride="integrations"
                  activeWorkspaceId={activeWorkspace?.id || ""}
                  activeWorkspaceName={activeWorkspace?.name || "Workspace"}
                  canWorkspaceAdmin={canWorkspaceAdmin}
                  canManageWorkspaces={isPlatformManager && !isPreviewReadOnly}
                />
              }
            />
            <Route
              path="platform/settings/deploy"
              element={
                <GlobalPlatformSettingsRoute
                  initialSurface="deploy_settings"
                  activeWorkspaceId={activeWorkspace?.id || ""}
                  activeWorkspaceName={activeWorkspace?.name || "Workspace"}
                  canWorkspaceAdmin={canWorkspaceAdmin}
                  canManageWorkspaces={isPlatformManager && !isPreviewReadOnly}
                />
              }
            />
            <Route
              path="platform/settings/workspaces"
              element={
                <GlobalPlatformSettingsRoute
                  initialSurface="workspaces"
                  activeWorkspaceId={activeWorkspace?.id || ""}
                  activeWorkspaceName={activeWorkspace?.name || "Workspace"}
                  canWorkspaceAdmin={canWorkspaceAdmin}
                  canManageWorkspaces={isPlatformManager && !isPreviewReadOnly}
                />
              }
            />
            <Route
              path="platform/access-control"
              element={
                <GlobalPlatformSettingsRoute
                  initialSurface="access_control"
                  activeWorkspaceId={activeWorkspace?.id || ""}
                  activeWorkspaceName={activeWorkspace?.name || "Workspace"}
                  canWorkspaceAdmin={canWorkspaceAdmin}
                  canManageWorkspaces={isPlatformManager && !isPreviewReadOnly}
                />
              }
            />
            <Route path="platform/access-explorer" element={<RedirectLegacyAccessControlRoute tab="explorer" />} />
            <Route path="platform/users" element={<RedirectLegacyAccessControlRoute tab="users" />} />
            <Route path="platform/roles" element={<RedirectLegacyAccessControlRoute tab="roles" />} />
            <Route
              path="platform/branding"
              element={
                <GlobalPlatformSettingsRoute
                  initialSurface="branding"
                  activeWorkspaceId={activeWorkspace?.id || ""}
                  activeWorkspaceName={activeWorkspace?.name || "Workspace"}
                  canWorkspaceAdmin={canWorkspaceAdmin}
                  canManageWorkspaces={isPlatformManager && !isPreviewReadOnly}
                />
              }
            />
            <Route path="platform/settings" element={<PlatformSettingsLegacyRoute workspaceId={activeWorkspace?.id || ""} />} />
            <Route path="platform/settings/legacy" element={<PlatformSettingsPage />} />
            <Route path="platform/video-adapter-configs/:artifactId" element={<VideoAdapterConfigPage />} />
            <Route
              path="platform/rendering-settings"
              element={
                <GlobalPlatformSettingsRoute
                  initialSurface="rendering_settings"
                  activeWorkspaceId={activeWorkspace?.id || ""}
                  activeWorkspaceName={activeWorkspace?.name || "Workspace"}
                  canWorkspaceAdmin={canWorkspaceAdmin}
                  canManageWorkspaces={isPlatformManager && !isPreviewReadOnly}
                />
              }
            />
            <Route
              path="platform/deploy"
              element={
                <GlobalPlatformSettingsRoute
                  initialSurface="deploy_settings"
                  activeWorkspaceId={activeWorkspace?.id || ""}
                  activeWorkspaceName={activeWorkspace?.name || "Workspace"}
                  canWorkspaceAdmin={canWorkspaceAdmin}
                  canManageWorkspaces={isPlatformManager && !isPreviewReadOnly}
                />
              }
            />
            <Route
              path="platform/workspaces"
              element={
                <GlobalPlatformSettingsRoute
                  initialSurface="workspaces"
                  activeWorkspaceId={activeWorkspace?.id || ""}
                  activeWorkspaceName={activeWorkspace?.name || "Workspace"}
                  canWorkspaceAdmin={canWorkspaceAdmin}
                  canManageWorkspaces={isPlatformManager && !isPreviewReadOnly}
                />
              }
            />
            <Route
              path="platform/activity"
              element={
                <GlobalPlatformSettingsRoute
                  initialSurface="activity"
                  activeWorkspaceId={activeWorkspace?.id || ""}
                  activeWorkspaceName={activeWorkspace?.name || "Workspace"}
                  canWorkspaceAdmin={canWorkspaceAdmin}
                  canManageWorkspaces={isPlatformManager && !isPreviewReadOnly}
                />
              }
            />
            <Route path="platform/seeds" element={<SeedPacksPage />} />
            <Route
              path="platform/identity-configuration"
              element={
                <GlobalPlatformSettingsRoute
                  initialSurface="identity_configuration"
                  activeWorkspaceId={activeWorkspace?.id || ""}
                  activeWorkspaceName={activeWorkspace?.name || "Workspace"}
                  canWorkspaceAdmin={canWorkspaceAdmin}
                  canManageWorkspaces={isPlatformManager && !isPreviewReadOnly}
                />
              }
            />
            <Route path="platform/identity-providers" element={<RedirectLegacyIdentityRoute tab="identity-providers" />} />
            <Route path="platform/oidc-app-clients" element={<RedirectLegacyIdentityRoute tab="oidc-app-clients" />} />
            <Route
              path="platform/secrets"
              element={
                <GlobalPlatformSettingsRoute
                  initialSurface="secrets"
                  activeWorkspaceId={activeWorkspace?.id || ""}
                  activeWorkspaceName={activeWorkspace?.name || "Workspace"}
                  canWorkspaceAdmin={canWorkspaceAdmin}
                  canManageWorkspaces={isPlatformManager && !isPreviewReadOnly}
                />
              }
            />
            <Route path="platform/secret-stores" element={<RedirectLegacySecretsRoute tab="stores" />} />
            <Route path="platform/secret-refs" element={<RedirectLegacySecretsRoute tab="refs" />} />
            <Route path="platform/ai-config" element={<Navigate to={workspaceScopedTarget("platform/ai-agents")} replace />} />
            <Route path="platform/ai-configuration" element={<Navigate to={workspaceScopedTarget("platform/ai-agents")} replace />} />
            <Route
              path="platform/ai-routing"
              element={
                <GlobalPlatformSettingsRoute
                  initialSurface="ai_routing"
                  activeWorkspaceId={activeWorkspace?.id || ""}
                  activeWorkspaceName={activeWorkspace?.name || "Workspace"}
                  canWorkspaceAdmin={canWorkspaceAdmin}
                  canManageWorkspaces={isPlatformManager && !isPreviewReadOnly}
                />
              }
            />
            <Route
              path="platform/ai-agents"
              element={
                <GlobalPlatformSettingsRoute
                  initialSurface="ai_agents"
                  activeWorkspaceId={activeWorkspace?.id || ""}
                  activeWorkspaceName={activeWorkspace?.name || "Workspace"}
                  canWorkspaceAdmin={canWorkspaceAdmin}
                  canManageWorkspaces={isPlatformManager && !isPreviewReadOnly}
                />
              }
            />
            <Route path="platform/ai/credentials" element={<RedirectLegacyAiRoute tab="credentials" />} />
            <Route path="platform/ai/model-configs" element={<RedirectLegacyAiRoute tab="model-configs" />} />
            <Route path="platform/ai/agents" element={<RedirectLegacyAiRoute tab="agents" />} />
            <Route path="platform/ai/purposes" element={<RedirectLegacyAiRoute tab="purposes" />} />
            <Route path="platform/ai/routing" element={<Navigate to={workspaceScopedTarget("platform/ai-routing")} replace />} />
            <Route path="settings" element={<WorkspaceSettingsPage workspaceName={activeWorkspace?.name || "Workspace"} />} />
            <Route path="*" element={<Navigate to={inWorkspaceScope ? DEFAULT_WORKSPACE_SUBPATH : "workspaces"} replace />} />
          </Routes>
          </Suspense>
          )}
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
      <SuggestionSwitcher workspaceId={workspaceScopedContextId} />
      <ToastHost />
    </div>
  );
}
