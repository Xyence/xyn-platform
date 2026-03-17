export type CapabilityGraphContext =
  | "landing"
  | "artifact_detail"
  | "app_intent_draft"
  | "application_workspace"
  | "artifact_registry"
  | "console"
  | "plan_review"
  | "unknown";

const KNOWN_CONTEXTS: CapabilityGraphContext[] = [
  "landing",
  "artifact_detail",
  "app_intent_draft",
  "application_workspace",
  "artifact_registry",
  "console",
  "plan_review",
  "unknown",
];

export function resolveCapabilityGraphContext(options: {
  pathname?: string;
  search?: string;
  explicitContext?: string | null;
  panelKey?: string | null;
  artifactId?: string | null;
  applicationId?: string | null;
  applicationPlanId?: string | null;
}): CapabilityGraphContext {
  const explicit = String(options.explicitContext || "").trim().toLowerCase();
  if (KNOWN_CONTEXTS.includes(explicit as CapabilityGraphContext)) {
    return explicit as CapabilityGraphContext;
  }

  const pathname = String(options.pathname || "").trim().toLowerCase();
  const search = String(options.search || "").trim().toLowerCase();
  const panelKey = String(options.panelKey || "").trim().toLowerCase();
  const artifactId = String(options.artifactId || "").trim();
  const applicationId = String(options.applicationId || "").trim();
  const applicationPlanId = String(options.applicationPlanId || "").trim();

  if (panelKey === "draft_detail" || /^\/w\/[^/]+\/drafts\/[^/]+\/?$/.test(pathname)) {
    return "app_intent_draft";
  }
  if (panelKey === "artifact_list" || /^\/w\/[^/]+\/build\/artifacts\/?$/.test(pathname)) {
    return "artifact_registry";
  }
  if (panelKey === "composer_detail" && pathname.includes("/workbench") && (Boolean(applicationPlanId) || /application_plan_id=/.test(search))) {
    return "plan_review";
  }
  if (artifactId || /^\/w\/[^/]+\/build\/artifacts\/[^/]+\/?$/.test(pathname) || /^\/app\/a\//.test(pathname)) {
    return "artifact_detail";
  }
  if (applicationId || panelKey === "application_detail") {
    return "application_workspace";
  }
  if (/^\/w\/[^/]+\/workbench\/?$/.test(pathname)) {
    return "console";
  }
  return "landing";
}
