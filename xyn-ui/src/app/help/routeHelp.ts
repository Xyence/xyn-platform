import type { AtlasNode } from "../components/help/AtlasFlow";

export type RouteHelp = {
  routeId: string;
  title: string;
  whatYouDo: string[];
  atlasNode: AtlasNode;
  nextSteps: Array<{ label: string; to: string }>;
};

const HELP_BY_ROUTE: Record<string, RouteHelp> = {
  "app.home": {
    routeId: "app.home",
    title: "Workspace Home",
    whatYouDo: ["Check workspace context", "Scan current artifacts and activity", "Start from the golden path"],
    atlasNode: "design",
    nextSteps: [
      { label: "Open Blueprints", to: "/app/blueprints" },
      { label: "Open Drafts", to: "/app/drafts" },
      { label: "View Guides", to: "/app/guides" },
    ],
  },
  "app.artifacts.articles": {
    routeId: "app.artifacts.articles",
    title: "Artifacts / Articles",
    whatYouDo: ["Create article drafts", "Manage article lifecycle and revisions", "Open article detail and AI assist"],
    atlasNode: "observe",
    nextSteps: [
      { label: "All Artifacts", to: "/app/artifacts/all" },
      { label: "Workspace Activity", to: "/app/activity" },
    ],
  },
  "app.artifacts.all": {
    routeId: "app.artifacts.all",
    title: "Artifacts / All Artifacts",
    whatYouDo: ["Search across artifact types", "Filter by status and type", "Open typed detail views"],
    atlasNode: "observe",
    nextSteps: [
      { label: "Articles", to: "/app/artifacts/articles" },
      { label: "Workspace Activity", to: "/app/activity" },
    ],
  },
  "app.activity": {
    routeId: "app.activity",
    title: "Activity",
    whatYouDo: ["Review immutable lifecycle events", "Audit moderation and promotion actions", "Trace event actors"],
    atlasNode: "observe",
    nextSteps: [
      { label: "Articles", to: "/app/artifacts/articles" },
      { label: "Workspaces", to: "/app/platform/settings?tab=workspaces&wsTab=profile" },
    ],
  },
  "app.workspaces": {
    routeId: "app.workspaces",
    title: "Workspaces",
    whatYouDo: ["Create and manage workspace records", "Deprecate or reactivate workspaces", "Manage people and roles by workspace"],
    atlasNode: "run",
    nextSteps: [
      { label: "Workspace Settings", to: "/app/settings" },
      { label: "Articles", to: "/app/artifacts/articles" },
    ],
  },
  "app.settings": {
    routeId: "app.settings",
    title: "Settings",
    whatYouDo: ["Adjust workspace behavior", "Confirm ownership and governance defaults", "Review operational configuration"],
    atlasNode: "run",
    nextSteps: [
      { label: "Workspaces", to: "/app/platform/settings?tab=workspaces&wsTab=profile" },
      { label: "Guides", to: "/app/guides" },
    ],
  },
  "app.blueprints": {
    routeId: "app.blueprints",
    title: "Blueprints",
    whatYouDo: ["Define app/service intent", "Inspect lifecycle and dev tasks", "Queue downstream generation"],
    atlasNode: "design",
    nextSteps: [
      { label: "Drafts", to: "/app/drafts" },
      { label: "Release Plans", to: "/app/release-plans" },
      { label: "Run Tour", to: "/app/tours" },
    ],
  },
  "app.drafts": {
    routeId: "app.drafts",
    title: "Draft Sessions",
    whatYouDo: ["Generate draft outputs", "Revise and validate draft material", "Submit drafts into blueprint flow"],
    atlasNode: "shape",
    nextSteps: [
      { label: "Blueprints", to: "/app/blueprints" },
      { label: "Release Plans", to: "/app/release-plans" },
    ],
  },
  "app.release-plans": {
    routeId: "app.release-plans",
    title: "Release Plans",
    whatYouDo: ["Bind releases to runtime targets", "Launch governed deployments", "Track current deployment intent"],
    atlasNode: "package",
    nextSteps: [
      { label: "Releases", to: "/app/releases" },
      { label: "Instances", to: "/app/instances" },
      { label: "Runs", to: "/app/runs" },
    ],
  },
  "app.releases": {
    routeId: "app.releases",
    title: "Releases",
    whatYouDo: ["Inspect build outputs", "Manage release lifecycle", "Promote deployable artifacts"],
    atlasNode: "package",
    nextSteps: [
      { label: "Release Plans", to: "/app/release-plans" },
      { label: "Runs", to: "/app/runs" },
    ],
  },
  "app.instances": {
    routeId: "app.instances",
    title: "Instances",
    whatYouDo: ["Select runtime targets", "Inspect health and substrate status", "Validate deployment readiness"],
    atlasNode: "run",
    nextSteps: [
      { label: "Release Plans", to: "/app/release-plans" },
      { label: "Runs", to: "/app/runs" },
    ],
  },
  "app.runs": {
    routeId: "app.runs",
    title: "Runs",
    whatYouDo: ["Inspect command execution", "Read logs and artifacts", "Identify failing stages quickly"],
    atlasNode: "observe",
    nextSteps: [
      { label: "Dev Tasks", to: "/app/dev-tasks" },
      { label: "Blueprints", to: "/app/blueprints" },
    ],
  },
  "app.guides": {
    routeId: "app.guides",
    title: "Guides",
    whatYouDo: ["Read route-bound docs", "Use core concept references", "Start onboarding tours"],
    atlasNode: "design",
    nextSteps: [
      { label: "Start tour", to: "/app/tours" },
      { label: "Blueprints", to: "/app/blueprints" },
    ],
  },
  "app.tours": {
    routeId: "app.tours",
    title: "Tours",
    whatYouDo: ["Start guided workflows", "Follow deterministic onboarding steps", "Resume or restart tours"],
    atlasNode: "design",
    nextSteps: [
      { label: "Guides", to: "/app/guides" },
      { label: "Blueprints", to: "/app/blueprints" },
    ],
  },
};

export function resolveRouteId(pathname: string): string {
  const workspaceNormalized = pathname.replace(/^\/w\/[^/]+/, "/app");
  const current = workspaceNormalized;
  if (current.startsWith("/app/build/blueprints") || current.startsWith("/app/blueprints")) return "app.blueprints";
  if (current.startsWith("/app/build/drafts") || current.startsWith("/app/drafts")) return "app.drafts";
  if (current.startsWith("/app/package/release-plans") || current.startsWith("/app/release-plans")) return "app.release-plans";
  if (current.startsWith("/app/package/releases") || current.startsWith("/app/releases")) return "app.releases";
  if (current.startsWith("/app/run/instances") || current.startsWith("/app/instances")) return "app.instances";
  if (current.startsWith("/app/run/runs") || current.startsWith("/app/runs")) return "app.runs";
  if (current.startsWith("/app/guides")) return "app.guides";
  if (current.startsWith("/app/tours")) return "app.tours";
  if (current.startsWith("/app/build/artifacts") || current.startsWith("/app/artifacts/all")) return "app.artifacts.all";
  if (current.startsWith("/app/artifacts/articles")) return "app.artifacts.articles";
  if (current.startsWith("/app/artifacts/")) return "app.artifacts.articles";
  if (current === "/app/artifacts") return "app.artifacts.articles";
  if (current.startsWith("/app/govern/activity") || current.startsWith("/app/activity")) return "app.activity";
  if (current.startsWith("/app/workspaces")) return "app.workspaces";
  if (current.startsWith("/app/people-roles")) return "app.workspaces";
  if (current.startsWith("/app/settings")) return "app.settings";
  return "app.home";
}

export function getRouteHelp(routeId: string): RouteHelp {
  return HELP_BY_ROUTE[routeId] || HELP_BY_ROUTE["app.home"];
}
