import type {
  BlueprintCreatePayload,
  BlueprintDetail,
  BlueprintDeprovisionPlan,
  BlueprintListResponse,
  BlueprintSummary,
  BlueprintDraftSession,
  BlueprintDraftSessionDetail,
  DraftSessionRevision,
  ContextPackDefaultsResponse,
  BlueprintVoiceNote,
  DevTaskDetail,
  DevTaskListResponse,
  DevTaskSummary,
  DevTaskCreatePayload,
  EnvironmentCreatePayload,
  EnvironmentListResponse,
  ModuleCreatePayload,
  ModuleDetail,
  ModuleListResponse,
  RegistryCreatePayload,
  RegistryDetail,
  RegistryListResponse,
  ReleasePlanCreatePayload,
  ReleasePlanDetail,
  ReleasePlanListResponse,
  ReleaseCreatePayload,
  ReleaseDetail,
  ReleaseListResponse,
  ReleaseSummary,
  ReleaseTarget,
  ReleaseTargetCreatePayload,
  ReleaseTargetListResponse,
  RunArtifact,
  RunCommandExecution,
  RunDetail,
  RunListResponse,
  RunLogResponse,
  ContextPackCreatePayload,
  ContextPackDetail,
  ContextPackListResponse,
  SeedPackListResponse,
  SeedPackDetailResponse,
  SeedApplyResponse,
  Tenant,
  TenantCreatePayload,
  TenantListResponse,
  Contact,
  ContactCreatePayload,
  ContactListResponse,
  IdentityListResponse,
  IdentityProviderListResponse,
  IdentityProviderPayload,
  OidcAppClientListResponse,
  OidcAppClientPayload,
  RoleBindingListResponse,
  RoleBindingCreatePayload,
  MembershipListResponse,
  MembershipCreatePayload,
  MyProfile,
  BrandingPayload,
  BrandingResponse,
  PlatformBranding,
  PlatformBrandingPayload,
  BrandingTokens,
  AppBrandingOverride,
  AppBrandingOverridePayload,
  DeviceListResponse,
  DevicePayload,
  Device,
  DraftAction,
  ActionEvent,
  ActionEvidence,
  ActionRatification,
  ExecutionReceipt,
  ControlPlaneStateResponse,
  XynMapResponse,
  SecretStore,
  SecretStoreListResponse,
  SecretRefListResponse,
  UnifiedArtifact,
  UnifiedArtifactType,
  UnifiedArtifactListResponse,
  ArtifactSurface,
  ArtifactRuntimeRole,
  ArtifactSurfaceResolveResponse,
  ArtifactBinding,
  ArtifactPackageRecord,
  ArtifactPackageValidationResult,
  ArtifactInstallReceipt,
  LedgerEventSummary,
  LedgerSummaryByUserRow,
  ReportPayload,
  ReportRecord,
  PlatformConfig,
  PlatformConfigResponse,
  VideoAdapterConfigDetailResponse,
  VideoAdapterConfigListResponse,
  VideoAdaptersResponse,
  VideoAdapterTestResponse,
  WorkspaceSummary,
  WorkspaceListResponse,
  WorkspaceInstalledArtifactSummary,
  CatalogArtifactSummary,
  ArtifactRawMetadataResponse,
  RawFilesListResponse,
  RawFilePreviewResponse,
  ArtifactDetail,
  ArticleSummary,
  ArticleDetail,
  ArticleRevision,
  VideoRender,
  VideoAiConfigEntry,
  ArticleCategoryRecord,
  PublishBindingRecord,
  ArtifactEventSummary,
  AiActivityEntry,
  WorkspaceMembershipSummary,
  WorkspaceAuthPolicy,
  DocPage,
  TourDefinition,
  WorkflowActionCatalogResponse,
  WorkflowActionExecuteResponse,
  WorkflowCreatePayload,
  WorkflowDetailResponse,
  WorkflowListResponse,
  WorkflowRun,
  IntentScript,
  WorkflowSpec,
  AiPurpose,
  AiProvider,
  AiCredential,
  AiModelConfig,
  AiAgent,
  AiBootstrapStatusResponse,
  AiInvokeResponse,
  AiModelConfigCompat,
  AccessRegistryResponse,
  AccessUserSummary,
  AccessUserRolesResponse,
  AccessUserEffectiveResponse,
  AccessRoleDetailResponse,
  XynIntentResolutionResult,
  XynIntentOptionsResponse,
  RecentArtifactItem,
  RecentArtifactListResponse,
  EmsDeviceListResponse,
  EmsRegistrationsResponse,
  EmsStatusCountsResponse,
  ArtifactStructuredQuery,
  ArtifactCanvasTableResponse,
  CanvasTableResponse,
  ArtifactConsoleListResponse,
  ArtifactConsoleDetailResponse,
  ArtifactConsoleFilesResponse,
  LocalProvisionResponse,
} from "./types";
import { authHeaders, resolveApiBaseUrl, resolveSeedBaseUrl } from "./client";

const jsonHeaders = {
  "Content-Type": "application/json",
};

const buildHeaders = (extra?: Record<string, string>) => ({
  ...jsonHeaders,
  ...authHeaders(),
  ...(extra || {}),
});

function apiFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const headers = { ...authHeaders(), ...(init.headers || {}) } as Record<string, string>;
  return fetch(input, { ...init, headers });
}

function htmlAuthErrorMessage(response: Response, body: string): string {
  const url = (response.url || "").toLowerCase();
  const text = (body || "").toLowerCase();
  if (
    response.status === 401 ||
    response.status === 403 ||
    url.includes("/auth/login") ||
    url.includes("/accounts/login") ||
    url.includes("/admin/login") ||
    text.includes("login")
  ) {
    return "Not authenticated. Please sign in.";
  }
  if (response.status >= 500) {
    return `Server error (${response.status}). Please try again.`;
  }
  return `Unexpected HTML response (${response.status}).`;
}

async function handle<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") || "";
  if (!response.ok) {
    if (contentType.includes("application/json")) {
      try {
        const payload = (await response.json()) as Record<string, unknown>;
        const code = String(payload.code || "");
        const message = String(payload.message || payload.error || "");
        if (code === "PREVIEW_READ_ONLY") {
          window.dispatchEvent(new CustomEvent("xyn:preview-read-only"));
        }
        throw new Error(code ? `${code}${message ? `: ${message}` : ""}` : message || `Request failed (${response.status})`);
      } catch (err) {
        if (err instanceof Error) throw err;
      }
    }
    const message = await response.text();
    if (message.includes("<!DOCTYPE") || message.includes("<html")) {
      throw new Error(htmlAuthErrorMessage(response, message));
    }
    throw new Error(message || `Request failed (${response.status})`);
  }
  if (response.status === 204) {
    return {} as T;
  }
  if (!contentType.includes("application/json")) {
    const message = await response.text();
    if (message.includes("<!DOCTYPE") || message.includes("<html")) {
      throw new Error(htmlAuthErrorMessage(response, message));
    }
    throw new Error(message || "Unexpected response format.");
  }
  return (await response.json()) as T;
}

export async function getWhoAmI(): Promise<{ authenticated: boolean; username?: string; email?: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/auth/whoami`, {
    credentials: "include",
  });
  return handle<{ authenticated: boolean; username?: string; email?: string }>(response);
}

export async function getAiBootstrapStatus(): Promise<AiBootstrapStatusResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/bootstrap-status`, {
    credentials: "include",
    headers: buildHeaders(),
  });
  return handle<AiBootstrapStatusResponse>(response);
}

export async function provisionLocalXynInstance(payload: {
  name?: string;
  job?: { prompt: string; repo_ref: string };
}): Promise<LocalProvisionResponse> {
  const seedBaseUrl = resolveSeedBaseUrl();
  const response = await apiFetch(`${seedBaseUrl}/api/v1/provision/local-instance`, {
    method: "POST",
    headers: buildHeaders(),
    body: JSON.stringify(payload),
  });
  return handle<LocalProvisionResponse>(response);
}

export async function resolveXynIntent(payload: {
  message: string;
  context?: { artifact_id?: string | null; artifact_type?: string | null; workspace_id?: string | null };
  snapshot?: Record<string, unknown>;
}): Promise<XynIntentResolutionResult> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/xyn/intent/resolve`, {
    method: "POST",
    credentials: "include",
    headers: buildHeaders(),
    body: JSON.stringify(payload),
  });
  return handle<XynIntentResolutionResult>(response);
}

export async function applyXynIntent(payload: {
  action_type: "CreateDraft" | "ApplyPatch";
  artifact_type: "ArticleDraft" | "ContextPack" | "Workspace";
  artifact_id?: string | null;
  payload: Record<string, unknown>;
}): Promise<XynIntentResolutionResult> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/xyn/intent/apply`, {
    method: "POST",
    credentials: "include",
    headers: buildHeaders(),
    body: JSON.stringify(payload),
  });
  return handle<XynIntentResolutionResult>(response);
}

export async function getXynIntentOptions(params: {
  artifact_type: "ArticleDraft" | "ContextPack";
  field: "category" | "format" | "duration";
}): Promise<XynIntentOptionsResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/xyn/intent/options`);
  url.searchParams.set("artifact_type", params.artifact_type);
  url.searchParams.set("field", params.field);
  const response = await apiFetch(url.toString(), {
    credentials: "include",
    headers: buildHeaders(),
  });
  return handle<XynIntentOptionsResponse>(response);
}

export async function listEmsDevices(state?: string): Promise<EmsDeviceListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/api/apps/ems/devices`);
  if (state) url.searchParams.set("state", state);
  const response = await apiFetch(url.toString(), {
    credentials: "include",
    headers: buildHeaders(),
  });
  return handle<EmsDeviceListResponse>(response);
}

export async function getEmsRegistrations(hours = 24): Promise<EmsRegistrationsResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/api/apps/ems/registrations`);
  url.searchParams.set("hours", String(Math.max(1, Math.min(hours, 168))));
  const response = await apiFetch(url.toString(), {
    credentials: "include",
    headers: buildHeaders(),
  });
  return handle<EmsRegistrationsResponse>(response);
}

export async function getEmsStatusCounts(): Promise<EmsStatusCountsResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/api/apps/ems/status-counts`, {
    credentials: "include",
    headers: buildHeaders(),
  });
  return handle<EmsStatusCountsResponse>(response);
}

export async function queryEmsDevicesCanvasTable(params: {
  query: {
    entity: "ems_devices";
    filters: Array<{ field: string; op: string; value: unknown }>;
    sort: Array<{ field: string; dir: "asc" | "desc" }>;
    limit: number;
    offset: number;
  };
}): Promise<CanvasTableResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/api/ems/devices`);
  url.searchParams.set("filters", JSON.stringify(params.query.filters || []));
  url.searchParams.set("sort", JSON.stringify(params.query.sort || []));
  url.searchParams.set("limit", String(params.query.limit || 50));
  url.searchParams.set("offset", String(params.query.offset || 0));
  const response = await apiFetch(url.toString(), {
    credentials: "include",
    headers: buildHeaders(),
  });
  return handle<CanvasTableResponse>(response);
}

export async function queryEmsRegistrationsCanvasTable(params: {
  query: {
    entity: "ems_registrations";
    filters: Array<{ field: string; op: string; value: unknown }>;
    sort: Array<{ field: string; dir: "asc" | "desc" }>;
    limit: number;
    offset: number;
  };
}): Promise<CanvasTableResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/api/ems/registrations`);
  url.searchParams.set("filters", JSON.stringify(params.query.filters || []));
  url.searchParams.set("sort", JSON.stringify(params.query.sort || []));
  url.searchParams.set("limit", String(params.query.limit || 50));
  url.searchParams.set("offset", String(params.query.offset || 0));
  const response = await apiFetch(url.toString(), {
    credentials: "include",
    headers: buildHeaders(),
  });
  return handle<CanvasTableResponse>(response);
}

export async function getEmsStatusRollupCanvasTable(): Promise<CanvasTableResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/api/ems/reports/device-status-rollup`, {
    credentials: "include",
    headers: buildHeaders(),
  });
  return handle<CanvasTableResponse>(response);
}

export async function getEmsRegistrationsTimeseriesCanvasTable(params?: { range?: string; bucket?: string }): Promise<CanvasTableResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/api/ems/reports/registrations-timeseries`);
  if (params?.range) url.searchParams.set("range", params.range);
  if (params?.bucket) url.searchParams.set("bucket", params.bucket);
  const response = await apiFetch(url.toString(), {
    credentials: "include",
    headers: buildHeaders(),
  });
  return handle<CanvasTableResponse>(response);
}

export async function getEmsDatasetSchemaTable(dataset: string): Promise<CanvasTableResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/api/ems/datasets/${encodeURIComponent(dataset)}/schema`, {
    credentials: "include",
    headers: buildHeaders(),
  });
  return handle<CanvasTableResponse>(response);
}

export async function listArtifactConsole(params?: {
  namespace?: string;
  kind?: string;
  q?: string;
}): Promise<ArtifactConsoleListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/artifacts`);
  if (params?.namespace) url.searchParams.set("namespace", params.namespace);
  if (params?.kind) url.searchParams.set("kind", params.kind);
  if (params?.q) url.searchParams.set("q", params.q);
  const response = await apiFetch(url.toString(), {
    credentials: "include",
    headers: buildHeaders(),
  });
  return handle<ArtifactConsoleListResponse>(response);
}

export async function queryArtifactCanvasTable(params: {
  query: ArtifactStructuredQuery;
  workspaceId?: string;
}): Promise<ArtifactCanvasTableResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/artifacts`);
  url.searchParams.set("entity", "artifacts");
  url.searchParams.set("filters", JSON.stringify(params.query.filters || []));
  url.searchParams.set("sort", JSON.stringify(params.query.sort || []));
  url.searchParams.set("limit", String(params.query.limit || 50));
  url.searchParams.set("offset", String(params.query.offset || 0));
  if (params.workspaceId) url.searchParams.set("workspace_id", params.workspaceId);
  const response = await apiFetch(url.toString(), {
    credentials: "include",
    headers: buildHeaders(),
  });
  return handle<ArtifactCanvasTableResponse>(response);
}

export async function getArtifactConsoleDetailBySlug(
  slug: string,
  options?: { workspaceId?: string }
): Promise<ArtifactConsoleDetailResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/artifacts/slug/${encodeURIComponent(slug)}`);
  if (options?.workspaceId) url.searchParams.set("workspace_id", options.workspaceId);
  const response = await apiFetch(url.toString(), {
    credentials: "include",
    headers: buildHeaders(),
  });
  return handle<ArtifactConsoleDetailResponse>(response);
}

export async function getArtifactConsoleFilesBySlug(slug: string): Promise<ArtifactConsoleFilesResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/slug/${encodeURIComponent(slug)}/files`, {
    credentials: "include",
    headers: buildHeaders(),
  });
  return handle<ArtifactConsoleFilesResponse>(response);
}

export async function getRecentArtifacts(limit = 6): Promise<RecentArtifactListResponse> {
  const requested = Math.max(1, Math.min(limit, 50));
  const payload = await listArtifacts({ limit: Math.max(50, Math.min(500, requested * 8)), offset: 0 });
  const toRoute = (item: UnifiedArtifact): string => {
    const source = (item.source || {}) as Record<string, unknown>;
    const sourceId = String(source.id || item.source_ref_id || "").trim();
    const artifactId = String(item.artifact_id || item.id || "").trim();
    if (item.artifact_type === "draft_session" && sourceId) return `/app/drafts/${sourceId}`;
    if (item.artifact_type === "blueprint" && sourceId) return `/app/blueprints/${sourceId}`;
    if (item.artifact_type === "article" && artifactId) return `/app/artifacts/${artifactId}`;
    if (item.artifact_type === "workflow") return `/app/artifacts/workflows${sourceId ? `?workflow=${encodeURIComponent(sourceId)}` : ""}`;
    if (item.artifact_type === "module") return "/app/modules";
    if (item.artifact_type === "context_pack") {
      if (sourceId) return `/app/context-packs?pack=${encodeURIComponent(sourceId)}`;
      return "/app/context-packs";
    }
    return "/app/artifacts/all";
  };

  const sorted = [...(payload.artifacts || [])].sort((a, b) => {
    const aTime = Date.parse(a.updated_at || a.created_at || "");
    const bTime = Date.parse(b.updated_at || b.created_at || "");
    return (Number.isFinite(bTime) ? bTime : 0) - (Number.isFinite(aTime) ? aTime : 0);
  });

  const perTypeCap = Math.max(2, Math.ceil(requested / 2));
  const selected: UnifiedArtifact[] = [];
  const byTypeCount = new Map<string, number>();
  const seenIds = new Set<string>();

  for (const item of sorted) {
    const id = String(item.artifact_id || item.id || "").trim();
    if (!id || seenIds.has(id)) continue;
    const key = String(item.artifact_type || "artifact");
    const count = byTypeCount.get(key) || 0;
    if (count >= perTypeCap) continue;
    selected.push(item);
    seenIds.add(id);
    byTypeCount.set(key, count + 1);
  }

  for (const item of sorted) {
    if (selected.length >= Math.max(24, requested * 4)) break;
    const id = String(item.artifact_id || item.id || "").trim();
    if (!id || seenIds.has(id)) continue;
    selected.push(item);
    seenIds.add(id);
  }

  const items: RecentArtifactItem[] = selected.map((item) => ({
    artifact_id: item.artifact_id || item.id,
    artifact_type: String(item.artifact_type || ""),
    artifact_state: item.artifact_state || null,
    title: item.title || "Untitled artifact",
    updated_at: item.updated_at || item.created_at || undefined,
    route: toRoute(item),
  }));

  return { items };
}

export async function getMe(): Promise<{
  user: Record<string, string | null>;
  roles: string[];
  permissions?: string[];
  actor_roles?: string[];
  preview?: {
    enabled: boolean;
    roles: string[];
    read_only: boolean;
    started_at?: number | null;
    expires_at?: number | null;
    actor_roles?: string[];
    effective_roles?: string[];
  };
  workspaces?: Array<{ id: string; slug: string; name: string; role: string; termination_authority?: boolean }>;
}> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/me`, { credentials: "include" });
  return handle<{
    user: Record<string, string | null>;
    roles: string[];
    permissions?: string[];
    actor_roles?: string[];
    preview?: {
      enabled: boolean;
      roles: string[];
      read_only: boolean;
      started_at?: number | null;
      expires_at?: number | null;
      actor_roles?: string[];
      effective_roles?: string[];
    };
    workspaces?: Array<{ id: string; slug: string; name: string; role: string; termination_authority?: boolean }>;
  }>(response);
}

export type PreviewStatus = {
  enabled: boolean;
  roles: string[];
  read_only: boolean;
  started_at?: number | null;
  expires_at?: number | null;
  actor_roles?: string[];
  effective_roles?: string[];
};

export async function getPreviewStatus(): Promise<{ preview: PreviewStatus }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/preview/status`, { credentials: "include" });
  return handle<{ preview: PreviewStatus }>(response);
}

export async function getAccessRegistry(): Promise<AccessRegistryResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/access/registry`, { credentials: "include" });
  return handle<AccessRegistryResponse>(response);
}

export async function searchAccessUsers(query = ""): Promise<{ users: AccessUserSummary[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/access/users`);
  if (query.trim()) url.searchParams.set("query", query.trim());
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<{ users: AccessUserSummary[] }>(response);
}

export async function getAccessUserRoles(userId: string): Promise<AccessUserRolesResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/access/users/${userId}/roles`, { credentials: "include" });
  return handle<AccessUserRolesResponse>(response);
}

export async function getAccessUserEffective(userId: string): Promise<AccessUserEffectiveResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/access/users/${userId}/effective`, { credentials: "include" });
  return handle<AccessUserEffectiveResponse>(response);
}

export async function getAccessRoleDetail(roleId: string): Promise<AccessRoleDetailResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/access/roles/${encodeURIComponent(roleId)}`, { credentials: "include" });
  return handle<AccessRoleDetailResponse>(response);
}

export async function enablePreview(payload: { roles: string[]; readOnly: boolean }): Promise<{ preview: PreviewStatus }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/preview/enable`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ preview: PreviewStatus }>(response);
}

export async function disablePreview(): Promise<{ preview: PreviewStatus }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/preview/disable`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify({}),
  });
  return handle<{ preview: PreviewStatus }>(response);
}

export async function listWorkspaces(): Promise<WorkspaceListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces`, { credentials: "include" });
  return handle<WorkspaceListResponse>(response);
}

export async function listWorkspacesCanvasApi(): Promise<WorkspaceListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/api/workspaces`, { credentials: "include" });
  return handle<WorkspaceListResponse>(response);
}

export async function createWorkspace(payload: {
  name: string;
  slug?: string;
  description?: string;
  org_name?: string;
  kind?: string;
  lifecycle_stage?: string;
  auth_mode?: "local" | "oidc" | "mixed";
  oidc_config_ref?: string;
  parent_workspace_id?: string | null;
  metadata?: Record<string, unknown>;
}): Promise<{ workspace: WorkspaceSummary }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ workspace: WorkspaceSummary }>(response);
}

export async function updateWorkspace(
  workspaceId: string,
  payload: Partial<{
    name: string;
    slug: string;
    description: string;
    status: "active" | "deprecated";
    org_name: string;
    kind: string;
    lifecycle_stage: string;
    auth_mode: "local" | "oidc" | "mixed";
    oidc_config_ref: string;
    parent_workspace_id: string | null;
    metadata: Record<string, unknown>;
  }>
): Promise<{ workspace: WorkspaceSummary }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ workspace: WorkspaceSummary }>(response);
}

export async function getWorkspaceAuthPolicy(workspaceId: string): Promise<{ auth_policy: WorkspaceAuthPolicy }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/auth-policy`, {
    credentials: "include",
  });
  return handle<{ auth_policy: WorkspaceAuthPolicy }>(response);
}

export async function updateWorkspaceAuthPolicy(
  workspaceId: string,
  payload: Partial<WorkspaceAuthPolicy>
): Promise<{ auth_policy: WorkspaceAuthPolicy }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/auth-policy`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ auth_policy: WorkspaceAuthPolicy }>(response);
}

export async function testWorkspaceOidcDiscovery(
  workspaceId: string
): Promise<{ ok: boolean; discovery_url: string; issuer?: string; authorization_endpoint?: string; token_endpoint?: string; jwks_uri?: string; error?: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/auth-policy/test-discovery`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ ok: boolean; discovery_url: string; issuer?: string; authorization_endpoint?: string; token_endpoint?: string; jwks_uri?: string; error?: string }>(response);
}

export async function listWorkspaceArtifacts(
  workspaceId: string,
  filters?: { type?: string; status?: string }
): Promise<{ artifacts: WorkspaceInstalledArtifactSummary[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/artifacts`);
  if (filters?.type) url.searchParams.set("type", filters.type);
  if (filters?.status) url.searchParams.set("status", filters.status);
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<{ artifacts: WorkspaceInstalledArtifactSummary[] }>(response);
}

export async function listArtifactsCatalog(
  filters?: { query?: string; kind?: string; workspace_id?: string }
): Promise<{ artifacts: CatalogArtifactSummary[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/artifacts/catalog`);
  if (filters?.query) url.searchParams.set("query", filters.query);
  if (filters?.kind) url.searchParams.set("kind", filters.kind);
  if (filters?.workspace_id) url.searchParams.set("workspace_id", filters.workspace_id);
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<{ artifacts: CatalogArtifactSummary[] }>(response);
}

export async function createWorkspaceArtifact(
  workspaceId: string,
  payload: Record<string, unknown>
): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/artifacts`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function installWorkspaceArtifact(
  workspaceId: string,
  payload: { artifact_id?: string; slug?: string; enabled?: boolean }
): Promise<{ artifact: WorkspaceInstalledArtifactSummary; created: boolean }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/artifacts`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ artifact: WorkspaceInstalledArtifactSummary; created: boolean }>(response);
}

export async function uninstallWorkspaceArtifact(
  workspaceId: string,
  bindingId: string
): Promise<{ deleted: boolean; artifact: WorkspaceInstalledArtifactSummary }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/artifacts/${bindingId}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handle<{ deleted: boolean; artifact: WorkspaceInstalledArtifactSummary }>(response);
}

export async function getWorkspaceArtifact(workspaceId: string, artifactId: string): Promise<ArtifactDetail> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/artifacts/${artifactId}`, {
    credentials: "include",
  });
  return handle<ArtifactDetail>(response);
}

export async function listArtifacts(params: {
  type?: UnifiedArtifactType;
  state?: "provisional" | "canonical" | "immutable" | "deprecated";
  query?: string;
  owner?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<UnifiedArtifactListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/artifacts`);
  if (params.type) url.searchParams.set("type", params.type);
  if (params.state) url.searchParams.set("state", params.state);
  if (params.query) url.searchParams.set("query", params.query);
  if (params.owner) url.searchParams.set("owner", params.owner);
  if (typeof params.limit === "number") url.searchParams.set("limit", String(params.limit));
  if (typeof params.offset === "number") url.searchParams.set("offset", String(params.offset));
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<UnifiedArtifactListResponse>(response);
}

export async function getArtifact(artifactId: string): Promise<UnifiedArtifact> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/${artifactId}`, {
    credentials: "include",
  });
  return handle<UnifiedArtifact>(response);
}

export async function listArtifactSurfaces(artifactId: string): Promise<{ artifact_id: string; surfaces: ArtifactSurface[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/${encodeURIComponent(artifactId)}/surfaces`, {
    credentials: "include",
  });
  return handle<{ artifact_id: string; surfaces: ArtifactSurface[] }>(response);
}

export async function listArtifactRuntimeRoles(artifactId: string): Promise<{ artifact_id: string; runtime_roles: ArtifactRuntimeRole[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/${encodeURIComponent(artifactId)}/runtime-roles`, {
    credentials: "include",
  });
  return handle<{ artifact_id: string; runtime_roles: ArtifactRuntimeRole[] }>(response);
}

export async function listArtifactNavSurfaces(workspaceId?: string): Promise<{ surfaces: ArtifactSurface[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/artifact-surfaces/nav`);
  if (workspaceId && workspaceId.trim().length > 0) {
    url.searchParams.set("workspace_id", workspaceId);
  }
  const response = await apiFetch(url.toString(), {
    credentials: "include",
  });
  return handle<{ surfaces: ArtifactSurface[] }>(response);
}

export async function resolveArtifactSurface(pathname: string): Promise<ArtifactSurfaceResolveResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/artifact-surfaces/resolve`);
  url.searchParams.set("path", pathname);
  const response = await apiFetch(url.toString(), {
    credentials: "include",
  });
  return handle<ArtifactSurfaceResolveResponse>(response);
}

export async function listArtifactActivity(
  artifactId: string,
  params: {
    limit?: number;
    offset?: number;
    action?: string;
    since?: string;
    until?: string;
  } = {}
): Promise<{ events: LedgerEventSummary[]; count: number; limit: number; offset: number }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/artifacts/${artifactId}/activity`);
  if (typeof params.limit === "number") url.searchParams.set("limit", String(params.limit));
  if (typeof params.offset === "number") url.searchParams.set("offset", String(params.offset));
  if (params.action) url.searchParams.set("action", params.action);
  if (params.since) url.searchParams.set("since", params.since);
  if (params.until) url.searchParams.set("until", params.until);
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<{ events: LedgerEventSummary[]; count: number; limit: number; offset: number }>(response);
}

export async function listArtifactBindings(): Promise<{ bindings: ArtifactBinding[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/bindings`, {
    credentials: "include",
  });
  return handle<{ bindings: ArtifactBinding[] }>(response);
}

export async function upsertArtifactBinding(payload: {
  name: string;
  type: ArtifactBinding["type"];
  value?: unknown;
  description?: string;
  secret_ref_id?: string | null;
}): Promise<{ binding: ArtifactBinding }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/bindings`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ binding: ArtifactBinding }>(response);
}

export async function deleteArtifactBinding(bindingId: string): Promise<void> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/bindings/${encodeURIComponent(bindingId)}`, {
    method: "DELETE",
    credentials: "include",
  });
  await handle<void>(response);
}

export async function listArtifactPackages(): Promise<{ packages: ArtifactPackageRecord[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/packages`, {
    credentials: "include",
  });
  return handle<{ packages: ArtifactPackageRecord[] }>(response);
}

export async function importArtifactPackage(file: File): Promise<{ package: ArtifactPackageRecord }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const form = new FormData();
  form.append("file", file);
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/packages/import`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  return handle<{ package: ArtifactPackageRecord }>(response);
}

export async function validateArtifactPackage(
  packageId: string,
  payload?: { binding_overrides?: Record<string, unknown> }
): Promise<ArtifactPackageValidationResult> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/packages/${encodeURIComponent(packageId)}/validate`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload || {}),
  });
  return handle<ArtifactPackageValidationResult>(response);
}

export async function installArtifactPackage(
  packageId: string,
  payload?: { binding_overrides?: Record<string, unknown> }
): Promise<{ receipt: ArtifactInstallReceipt }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/packages/${encodeURIComponent(packageId)}/install`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload || {}),
  });
  return handle<{ receipt: ArtifactInstallReceipt }>(response);
}

export async function listArtifactInstallReceipts(params?: { artifact_id?: string }): Promise<{ receipts: ArtifactInstallReceipt[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/artifacts/install-receipts`);
  if (params?.artifact_id) url.searchParams.set("artifact_id", params.artifact_id);
  const response = await apiFetch(url.toString(), {
    credentials: "include",
  });
  return handle<{ receipts: ArtifactInstallReceipt[] }>(response);
}

export async function exportArtifactPackage(payload: {
  artifact_id: string;
  package_name: string;
  package_version: string;
}): Promise<Blob> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/${encodeURIComponent(payload.artifact_id)}/export-package`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify({
      package_name: payload.package_name,
      package_version: payload.package_version,
    }),
  });
  if (!response.ok) {
    await handle(response);
  }
  return response.blob();
}

export async function getArtifactRawMetadata(artifactId: string): Promise<ArtifactRawMetadataResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/${encodeURIComponent(artifactId)}/raw/metadata`, {
    credentials: "include",
  });
  return handle<ArtifactRawMetadataResponse>(response);
}

export async function getArtifactRawArtifactJson(artifactId: string): Promise<Record<string, unknown>> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/${encodeURIComponent(artifactId)}/raw/artifact-json`, {
    credentials: "include",
  });
  return handle<Record<string, unknown>>(response);
}

export async function listArtifactRawFiles(artifactId: string, path = "/"): Promise<RawFilesListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/artifacts/${encodeURIComponent(artifactId)}/raw/files`);
  url.searchParams.set("path", path);
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<RawFilesListResponse>(response);
}

export async function getArtifactRawFilePreview(artifactId: string, path: string): Promise<RawFilePreviewResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/artifacts/${encodeURIComponent(artifactId)}/raw/file`);
  url.searchParams.set("path", path);
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<RawFilePreviewResponse>(response);
}

export function getArtifactRawFileDownloadUrl(artifactId: string, path: string): string {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/artifacts/${encodeURIComponent(artifactId)}/raw/file`);
  url.searchParams.set("path", path);
  url.searchParams.set("download", "1");
  return url.toString();
}

export async function getArtifactPackageRawManifest(packageId: string): Promise<{ manifest: Record<string, unknown> }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/packages/${encodeURIComponent(packageId)}/raw/manifest`, {
    credentials: "include",
  });
  return handle<{ manifest: Record<string, unknown> }>(response);
}

export async function listArtifactPackageRawTree(packageId: string, path = "/"): Promise<RawFilesListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/artifacts/packages/${encodeURIComponent(packageId)}/raw/tree`);
  url.searchParams.set("path", path);
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<RawFilesListResponse>(response);
}

export async function getArtifactPackageRawFilePreview(packageId: string, path: string): Promise<RawFilePreviewResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/artifacts/packages/${encodeURIComponent(packageId)}/raw/file`);
  url.searchParams.set("path", path);
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<RawFilePreviewResponse>(response);
}

export function getArtifactPackageRawFileDownloadUrl(packageId: string, path: string): string {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/artifacts/packages/${encodeURIComponent(packageId)}/raw/file`);
  url.searchParams.set("path", path);
  url.searchParams.set("download", "1");
  return url.toString();
}

export async function listLedgerEvents(params: {
  workspace?: string;
  actor?: string;
  artifact_type?: string;
  action?: string;
  artifact_id?: string;
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<{ events: LedgerEventSummary[]; count: number; limit: number; offset: number }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/ledger`);
  if (params.workspace) url.searchParams.set("workspace", params.workspace);
  if (params.actor) url.searchParams.set("actor", params.actor);
  if (params.artifact_type) url.searchParams.set("artifact_type", params.artifact_type);
  if (params.action) url.searchParams.set("action", params.action);
  if (params.artifact_id) url.searchParams.set("artifact_id", params.artifact_id);
  if (params.since) url.searchParams.set("since", params.since);
  if (params.until) url.searchParams.set("until", params.until);
  if (typeof params.limit === "number") url.searchParams.set("limit", String(params.limit));
  if (typeof params.offset === "number") url.searchParams.set("offset", String(params.offset));
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<{ events: LedgerEventSummary[]; count: number; limit: number; offset: number }>(response);
}

export async function getLedgerSummaryByUser(params: {
  workspace?: string;
  since?: string;
  until?: string;
} = {}): Promise<{ rows: LedgerSummaryByUserRow[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/ledger/summary/by-user`);
  if (params.workspace) url.searchParams.set("workspace", params.workspace);
  if (params.since) url.searchParams.set("since", params.since);
  if (params.until) url.searchParams.set("until", params.until);
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<{ rows: LedgerSummaryByUserRow[] }>(response);
}

export async function getLedgerSummaryByArtifact(artifactId: string): Promise<{
  artifact_id: string;
  counts: Array<{ action: string; count: number }>;
  events: LedgerEventSummary[];
}> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/ledger/summary/by-artifact`);
  url.searchParams.set("artifact_id", artifactId);
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<{
    artifact_id: string;
    counts: Array<{ action: string; count: number }>;
    events: LedgerEventSummary[];
  }>(response);
}

export async function createDraftSessionArtifact(payload: {
  title?: string;
  name?: string;
  kind?: "blueprint" | "solution";
  draft_kind?: "blueprint" | "solution";
  blueprint_kind?: "solution" | "module" | "bundle";
  namespace?: string;
  project_key?: string;
  blueprint_id?: string;
  initial_prompt?: string;
  revision_instruction?: string;
  selected_context_pack_ids?: string[];
}): Promise<{ artifact_id: string; session_id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/create-draft-session`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ artifact_id: string; session_id: string }>(response);
}

export async function createBlueprintArtifact(payload: {
  name: string;
  namespace?: string;
  description?: string;
  spec_text?: string;
  metadata_json?: Record<string, unknown> | null;
  parent_artifact_id?: string;
  artifact_state?: "canonical" | "provisional";
}): Promise<{ artifact_id: string; blueprint_id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/create-blueprint`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ artifact_id: string; blueprint_id: string }>(response);
}

export async function canonizeDraftArtifactToBlueprint(
  artifactId: string,
  payload: {
    title?: string;
    name?: string;
    namespace?: string;
    description?: string;
  } = {}
): Promise<{
  blueprint_id: string;
  blueprint_artifact_id: string;
  parent_artifact_id: string;
  lineage_root_id?: string | null;
}> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/${artifactId}/canonize-to-blueprint`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{
    blueprint_id: string;
    blueprint_artifact_id: string;
    parent_artifact_id: string;
    lineage_root_id?: string | null;
  }>(response);
}

export async function updateWorkspaceArtifact(
  workspaceId: string,
  artifactId: string,
  payload: Record<string, unknown>
): Promise<ArtifactDetail> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/artifacts/${artifactId}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<ArtifactDetail>(response);
}

export async function listArticles(filters?: {
  workspace_id?: string;
  category?: string;
  status?: string;
  visibility?: string;
  route_id?: string;
  q?: string;
  include_unpublished?: boolean;
}): Promise<{ articles: ArticleSummary[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/articles`);
  if (filters?.workspace_id) url.searchParams.set("workspace_id", filters.workspace_id);
  if (filters?.category) url.searchParams.set("category", filters.category);
  if (filters?.status) url.searchParams.set("status", filters.status);
  if (filters?.visibility) url.searchParams.set("visibility", filters.visibility);
  if (filters?.route_id) url.searchParams.set("route_id", filters.route_id);
  if (filters?.q) url.searchParams.set("q", filters.q);
  if (filters?.include_unpublished) url.searchParams.set("include_unpublished", "1");
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<{ articles: ArticleSummary[] }>(response);
}

export async function createArticle(payload: Record<string, unknown>): Promise<{ article: ArticleDetail }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ article: ArticleDetail }>(response);
}

export async function getArticle(articleId: string): Promise<{ article: ArticleDetail }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/${articleId}`, {
    credentials: "include",
  });
  return handle<{ article: ArticleDetail }>(response);
}

export async function updateArticle(articleId: string, payload: Record<string, unknown>): Promise<{ article: ArticleDetail }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/${articleId}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ article: ArticleDetail }>(response);
}

export async function listArticleRevisions(articleId: string): Promise<{ revisions: ArticleRevision[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/${articleId}/revisions`, {
    credentials: "include",
  });
  return handle<{ revisions: ArticleRevision[] }>(response);
}

export async function createArticleRevision(
  articleId: string,
  payload: Record<string, unknown>
): Promise<{ revision: ArticleRevision; article: ArticleDetail }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/${articleId}/revisions`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ revision: ArticleRevision; article: ArticleDetail }>(response);
}

export async function convertArticleHtmlToMarkdown(
  articleId: string
): Promise<{ revision: ArticleRevision; article: ArticleDetail; converted: boolean; reason?: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/${articleId}/convert-html`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ revision: ArticleRevision; article: ArticleDetail; converted: boolean; reason?: string }>(response);
}

export async function transitionArticle(
  articleId: string,
  toStatus: "reviewed" | "ratified" | "published" | "deprecated"
): Promise<{ article: ArticleDetail }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/${articleId}/transition`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify({ to_status: toStatus }),
  });
  return handle<{ article: ArticleDetail }>(response);
}

export async function initializeArticleVideo(articleId: string): Promise<{ article: ArticleDetail }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/${articleId}/video/initialize`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ article: ArticleDetail }>(response);
}

export async function generateArticleVideoScript(
  articleId: string,
  payload: { agent_slug?: string; context_pack_id?: string | null; context_packs?: unknown }
): Promise<{ article: ArticleDetail; proposal: Record<string, unknown>; overwrote_draft: boolean }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/${articleId}/video/generate-script`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ article: ArticleDetail; proposal: Record<string, unknown>; overwrote_draft: boolean }>(response);
}

export async function generateArticleVideoStoryboard(
  articleId: string,
  payload: { agent_slug?: string; context_pack_id?: string | null; context_packs?: unknown }
): Promise<{ article: ArticleDetail; proposal: Record<string, unknown>; overwrote_draft: boolean }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/${articleId}/video/generate-storyboard`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ article: ArticleDetail; proposal: Record<string, unknown>; overwrote_draft: boolean }>(response);
}

export async function getArticleVideoAiConfig(articleId: string): Promise<{
  overrides: {
    agents: Record<string, string>;
    context_packs: Record<string, { mode?: string; context_pack_refs?: unknown[] } | unknown>;
  };
  effective: Record<string, VideoAiConfigEntry>;
}> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/${articleId}/video/ai-config`, {
    credentials: "include",
  });
  return handle<{
    overrides: {
      agents: Record<string, string>;
      context_packs: Record<string, { mode?: string; context_pack_refs?: unknown[] } | unknown>;
    };
    effective: Record<string, VideoAiConfigEntry>;
  }>(response);
}

export async function updateArticleVideoAiConfig(
  articleId: string,
  payload: {
    reset_all?: boolean;
    agents?: Record<string, string | null>;
    context_packs?: Record<string, { mode?: "extend" | "replace"; context_pack_refs?: unknown[] } | unknown>;
  }
): Promise<{
  overrides: {
    agents: Record<string, string>;
    context_packs: Record<string, { mode?: string; context_pack_refs?: unknown[] } | unknown>;
  };
  effective: Record<string, VideoAiConfigEntry>;
  article: ArticleDetail;
}> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/${articleId}/video/ai-config`, {
    method: "PUT",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{
    overrides: {
      agents: Record<string, string>;
      context_packs: Record<string, { mode?: string; context_pack_refs?: unknown[] } | unknown>;
    };
    effective: Record<string, VideoAiConfigEntry>;
    article: ArticleDetail;
  }>(response);
}

export async function listArticleVideoRenders(articleId: string): Promise<{ renders: VideoRender[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/${articleId}/video/renders`, {
    credentials: "include",
  });
  return handle<{ renders: VideoRender[] }>(response);
}

export async function renderArticleVideo(
  articleId: string,
  payload: { provider?: string; context_pack_id?: string | null; request_payload_json?: Record<string, unknown> }
): Promise<{ render: VideoRender; article: ArticleDetail }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/${articleId}/video/render`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ render: VideoRender; article: ArticleDetail }>(response);
}

export async function getVideoRender(renderId: string): Promise<{ render: VideoRender }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/video-renders/${renderId}`, {
    credentials: "include",
  });
  return handle<{ render: VideoRender }>(response);
}

export async function cancelVideoRender(renderId: string): Promise<{ render: VideoRender }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/video-renders/${renderId}/cancel`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ render: VideoRender }>(response);
}

export async function retryVideoRender(renderId: string): Promise<{ render: VideoRender }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/video-renders/${renderId}/retry`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ render: VideoRender }>(response);
}

export async function listArticleCategories(): Promise<{ categories: ArticleCategoryRecord[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/categories`, {
    credentials: "include",
  });
  return handle<{ categories: ArticleCategoryRecord[] }>(response);
}

export async function createArticleCategory(payload: {
  slug: string;
  name: string;
  description?: string;
  enabled?: boolean;
}): Promise<{ category: ArticleCategoryRecord }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/categories`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ category: ArticleCategoryRecord }>(response);
}

export async function updateArticleCategory(
  slug: string,
  payload: { name?: string; description?: string; enabled?: boolean }
): Promise<{ category: ArticleCategoryRecord }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/categories/${slug}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ category: ArticleCategoryRecord }>(response);
}

export async function deleteArticleCategory(slug: string): Promise<{ ok: boolean }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/categories/${slug}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handle<{ ok: boolean }>(response);
}

export async function listCategoryBindings(slug: string): Promise<{ bindings: PublishBindingRecord[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/categories/${slug}/bindings`, {
    credentials: "include",
  });
  return handle<{ bindings: PublishBindingRecord[] }>(response);
}

export async function createCategoryBinding(
  slug: string,
  payload: { label: string; target_type: string; target_value: string; enabled?: boolean }
): Promise<{ binding: PublishBindingRecord }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/categories/${slug}/bindings`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ binding: PublishBindingRecord }>(response);
}

export async function updateCategoryBinding(
  slug: string,
  bindingId: string,
  payload: { label?: string; target_type?: string; target_value?: string; enabled?: boolean }
): Promise<{ binding: PublishBindingRecord }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/categories/${slug}/bindings/${bindingId}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ binding: PublishBindingRecord }>(response);
}

export async function deleteCategoryBinding(slug: string, bindingId: string): Promise<{ ok: boolean }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/categories/${slug}/bindings/${bindingId}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handle<{ ok: boolean }>(response);
}

export async function listArticleBindings(articleId: string): Promise<{
  bindings: PublishBindingRecord[];
  inherited_bindings: PublishBindingRecord[];
}> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/${articleId}/bindings`, {
    credentials: "include",
  });
  return handle<{ bindings: PublishBindingRecord[]; inherited_bindings: PublishBindingRecord[] }>(response);
}

export async function createArticleBinding(
  articleId: string,
  payload: { label: string; target_type: string; target_value: string; enabled?: boolean }
): Promise<{ binding: PublishBindingRecord }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/${articleId}/bindings`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ binding: PublishBindingRecord }>(response);
}

export async function updateArticleBinding(
  articleId: string,
  bindingId: string,
  payload: { label?: string; target_type?: string; target_value?: string; enabled?: boolean }
): Promise<{ binding: PublishBindingRecord }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/${articleId}/bindings/${bindingId}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ binding: PublishBindingRecord }>(response);
}

export async function deleteArticleBinding(articleId: string, bindingId: string): Promise<{ ok: boolean }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/articles/${articleId}/bindings/${bindingId}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handle<{ ok: boolean }>(response);
}

export async function publishWorkspaceArtifact(workspaceId: string, artifactId: string): Promise<{ id: string; status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/artifacts/${artifactId}/publish`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ id: string; status: string }>(response);
}

export async function deprecateWorkspaceArtifact(workspaceId: string, artifactId: string): Promise<{ id: string; status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/artifacts/${artifactId}/deprecate`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ id: string; status: string }>(response);
}

export async function reactToWorkspaceArtifact(workspaceId: string, artifactId: string, value: "endorse" | "oppose" | "neutral"): Promise<void> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/artifacts/${artifactId}/reactions`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify({ value }),
  });
  await handle<void>(response);
}

export async function commentOnWorkspaceArtifact(
  workspaceId: string,
  artifactId: string,
  payload: { body: string; parent_comment_id?: string | null }
): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/artifacts/${artifactId}/comments`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function moderateWorkspaceComment(
  workspaceId: string,
  artifactId: string,
  commentId: string,
  status: "hidden" | "deleted"
): Promise<void> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(
    `${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/artifacts/${artifactId}/comments/${commentId}`,
    {
      method: "PATCH",
      headers: buildHeaders(),
      credentials: "include",
      body: JSON.stringify({ status }),
    }
  );
  await handle<void>(response);
}

export async function listWorkspaceActivity(workspaceId: string): Promise<{ events: ArtifactEventSummary[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/activity`, { credentials: "include" });
  return handle<{ events: ArtifactEventSummary[] }>(response);
}

export async function listAiActivity(params?: {
  workspaceId?: string;
  artifactId?: string;
  limit?: number;
}): Promise<{ items: AiActivityEntry[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/ai/activity`);
  if (params?.workspaceId) url.searchParams.set("workspace_id", params.workspaceId);
  if (params?.artifactId) url.searchParams.set("artifact_id", params.artifactId);
  if (params?.limit) url.searchParams.set("limit", String(params.limit));
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<{ items: AiActivityEntry[] }>(response);
}

export async function listWorkspaceMemberships(workspaceId: string): Promise<{ memberships: WorkspaceMembershipSummary[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/memberships`, { credentials: "include" });
  return handle<{ memberships: WorkspaceMembershipSummary[] }>(response);
}

export async function listWorkspaceMembers(workspaceId: string): Promise<{ memberships: WorkspaceMembershipSummary[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/members`, { credentials: "include" });
  return handle<{ memberships: WorkspaceMembershipSummary[] }>(response);
}

export async function addWorkspaceMember(
  workspaceId: string,
  payload: { email: string; role: "admin" | "member" }
): Promise<{
  id: string;
  member: WorkspaceMembershipSummary;
  created_user?: boolean;
  temp_password?: string;
  invite_link?: string;
  demo_mode?: boolean;
}> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/members`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{
    id: string;
    member: WorkspaceMembershipSummary;
    created_user?: boolean;
    temp_password?: string;
    invite_link?: string;
    demo_mode?: boolean;
  }>(response);
}

export async function deleteWorkspaceMember(workspaceId: string, memberId: string): Promise<{ status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/members/${memberId}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handle<{ status: string }>(response);
}

export async function createWorkspaceMembership(
  workspaceId: string,
  payload: { user_identity_id: string; role: string; termination_authority?: boolean }
): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/memberships`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function updateWorkspaceMembership(
  workspaceId: string,
  membershipId: string,
  payload: { role?: string; termination_authority?: boolean }
): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workspaces/${workspaceId}/memberships/${membershipId}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function getDocByRoute(routeId: string, workspaceId?: string): Promise<{ doc: DocPage | null; route_id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/docs/by-route`);
  url.searchParams.set("route_id", routeId);
  if (workspaceId) {
    url.searchParams.set("workspace_id", workspaceId);
  }
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<{ doc: DocPage | null; route_id: string }>(response);
}

export async function listDocs(params?: { tags?: string[]; includeDrafts?: boolean }): Promise<{ docs: DocPage[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/docs`);
  if (params?.tags && params.tags.length > 0) {
    url.searchParams.set("tags", params.tags.join(","));
  }
  if (params?.includeDrafts) {
    url.searchParams.set("include_drafts", "1");
  }
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<{ docs: DocPage[] }>(response);
}

export async function getDocBySlug(slug: string): Promise<{ doc: DocPage }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/docs/slug/${encodeURIComponent(slug)}`, { credentials: "include" });
  return handle<{ doc: DocPage }>(response);
}

export async function createDoc(payload: {
  title: string;
  slug?: string;
  body_markdown?: string;
  summary?: string;
  visibility?: "private" | "team" | "public";
  route_bindings?: string[];
  tags?: string[];
}): Promise<{ doc: DocPage }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/docs`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ doc: DocPage }>(response);
}

export async function updateDoc(
  docId: string,
  payload: Partial<{
    title: string;
    slug: string;
    body_markdown: string;
    summary: string;
    visibility: "private" | "team" | "public";
    route_bindings: string[];
    tags: string[];
  }>
): Promise<{ doc: DocPage }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/docs/${docId}`, {
    method: "PUT",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ doc: DocPage }>(response);
}

export async function publishDoc(docId: string): Promise<{ doc: DocPage }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/docs/${docId}/publish`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ doc: DocPage }>(response);
}

export async function getTour(tourSlug: string): Promise<TourDefinition> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/tours/${encodeURIComponent(tourSlug)}`, { credentials: "include" });
  return handle<TourDefinition>(response);
}

export async function listWorkflows(params: {
  workspace_id?: string;
  profile?: string;
  category?: string;
  status?: string;
  include_unpublished?: boolean;
  q?: string;
} = {}): Promise<WorkflowListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/workflows`);
  if (params.workspace_id) url.searchParams.set("workspace_id", params.workspace_id);
  if (params.profile) url.searchParams.set("profile", params.profile);
  if (params.category) url.searchParams.set("category", params.category);
  if (params.status) url.searchParams.set("status", params.status);
  if (params.include_unpublished !== undefined) url.searchParams.set("include_unpublished", params.include_unpublished ? "1" : "0");
  if (params.q) url.searchParams.set("q", params.q);
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<WorkflowListResponse>(response);
}

export async function createWorkflow(payload: WorkflowCreatePayload): Promise<WorkflowDetailResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workflows`, {
    method: "POST",
    credentials: "include",
    headers: buildHeaders(),
    body: JSON.stringify(payload),
  });
  return handle<WorkflowDetailResponse>(response);
}

export async function getWorkflow(id: string): Promise<WorkflowDetailResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workflows/${encodeURIComponent(id)}`, { credentials: "include" });
  return handle<WorkflowDetailResponse>(response);
}

export async function updateWorkflowSpec(
  id: string,
  payload: Partial<WorkflowCreatePayload> & { workflow_spec_json: WorkflowSpec }
): Promise<WorkflowDetailResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workflows/${encodeURIComponent(id)}/spec`, {
    method: "PUT",
    credentials: "include",
    headers: buildHeaders(),
    body: JSON.stringify(payload),
  });
  return handle<WorkflowDetailResponse>(response);
}

export async function transitionWorkflow(id: string, to_status: string): Promise<WorkflowDetailResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workflows/${encodeURIComponent(id)}/transition`, {
    method: "POST",
    credentials: "include",
    headers: buildHeaders(),
    body: JSON.stringify({ to_status }),
  });
  return handle<WorkflowDetailResponse>(response);
}

export async function listWorkflowActions(): Promise<WorkflowActionCatalogResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workflows/actions`, { credentials: "include" });
  return handle<WorkflowActionCatalogResponse>(response);
}

export async function executeWorkflowAction(payload: {
  action_id: string;
  params?: Record<string, unknown>;
  idempotency_key?: string;
  dry_run?: boolean;
}): Promise<WorkflowActionExecuteResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workflows/actions/execute`, {
    method: "POST",
    credentials: "include",
    headers: buildHeaders(),
    body: JSON.stringify(payload),
  });
  return handle<WorkflowActionExecuteResponse>(response);
}

export async function startWorkflowRun(id: string): Promise<{ run: WorkflowRun }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workflows/${encodeURIComponent(id)}/run/start`, {
    method: "POST",
    credentials: "include",
    headers: buildHeaders(),
    body: JSON.stringify({ started_from: "ui" }),
  });
  return handle<{ run: WorkflowRun }>(response);
}

export async function logWorkflowRunEvent(
  id: string,
  runId: string,
  payload: { step_id?: string; type: string; payload_json?: Record<string, unknown> }
): Promise<{ event_id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workflows/${encodeURIComponent(id)}/run/${encodeURIComponent(runId)}/event`, {
    method: "POST",
    credentials: "include",
    headers: buildHeaders(),
    body: JSON.stringify(payload),
  });
  return handle<{ event_id: string }>(response);
}

export async function completeWorkflowRun(
  id: string,
  runId: string,
  status: "completed" | "failed" | "aborted"
): Promise<{ run: WorkflowRun }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/workflows/${encodeURIComponent(id)}/run/${encodeURIComponent(runId)}/complete`, {
    method: "POST",
    credentials: "include",
    headers: buildHeaders(),
    body: JSON.stringify({ status }),
  });
  return handle<{ run: WorkflowRun }>(response);
}

export async function generateIntentScript(payload: {
  scope_type: "tour" | "artifact" | "manual";
  scope_ref_id?: string;
  audience?: string;
  tone?: string;
  length_target?: string;
  title?: string;
}): Promise<{ item: IntentScript }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/intent-scripts/generate`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ item: IntentScript }>(response);
}

export async function listIntentScripts(params: {
  scope?: string;
  scope_type?: "tour" | "artifact" | "manual";
  scope_ref_id?: string;
} = {}): Promise<{ items: IntentScript[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/intent-scripts`);
  if (params.scope) url.searchParams.set("scope", params.scope);
  if (params.scope_type) url.searchParams.set("scope_type", params.scope_type);
  if (params.scope_ref_id) url.searchParams.set("scope_ref_id", params.scope_ref_id);
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<{ items: IntentScript[] }>(response);
}

export async function getIntentScript(scriptId: string): Promise<{ item: IntentScript }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/intent-scripts/${scriptId}`, { credentials: "include" });
  return handle<{ item: IntentScript }>(response);
}

export async function updateIntentScript(
  scriptId: string,
  payload: Partial<{
    title: string;
    status: "draft" | "final";
    script_text: string;
    script_json: Record<string, unknown>;
  }>
): Promise<{ item: IntentScript }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/intent-scripts/${scriptId}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ item: IntentScript }>(response);
}

export async function listAiPurposes(): Promise<{ purposes: AiPurpose[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/purposes`, { credentials: "include" });
  return handle<{ purposes: AiPurpose[] }>(response);
}

export async function updateAiPurpose(
  slug: string,
  payload: Partial<{
    slug: string;
    name: string;
    description: string;
    enabled: boolean;
    status: "active" | "deprecated";
    preamble: string;
    model_config: {
      provider: "openai" | "anthropic" | "google";
      model_name: string;
      temperature?: number;
      max_tokens?: number;
      top_p?: number;
      frequency_penalty?: number;
      presence_penalty?: number;
      extra_json?: Record<string, unknown>;
    };
  }>
): Promise<{ purpose: AiPurpose }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/purposes/${encodeURIComponent(slug)}`, {
    method: "PUT",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ purpose: AiPurpose }>(response);
}

export async function createAiPurpose(
  payload: {
    slug: string;
    name: string;
    description?: string;
    enabled?: boolean;
    status?: "active" | "deprecated";
    preamble?: string;
  }
): Promise<{ purpose: AiPurpose }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/purposes`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ purpose: AiPurpose }>(response);
}

export async function deleteAiPurpose(slug: string): Promise<{ purpose: AiPurpose }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/purposes/${encodeURIComponent(slug)}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handle<{ purpose: AiPurpose }>(response);
}

export async function listAiProviders(): Promise<{ providers: AiProvider[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/providers`, { credentials: "include" });
  return handle<{ providers: AiProvider[] }>(response);
}

export async function listAiCredentials(): Promise<{ credentials: AiCredential[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/credentials`, { credentials: "include" });
  return handle<{ credentials: AiCredential[] }>(response);
}

export async function createAiCredential(
  payload: Partial<AiCredential> & { provider: "openai" | "anthropic" | "google"; name: string; auth_type: "api_key" | "env_ref"; api_key?: string }
): Promise<{ credential: AiCredential }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/credentials`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ credential: AiCredential }>(response);
}

export async function updateAiCredential(
  id: string,
  payload: Partial<AiCredential> & { api_key?: string }
): Promise<{ credential: AiCredential }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/credentials/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ credential: AiCredential }>(response);
}

export async function deleteAiCredential(id: string): Promise<void> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/credentials/${encodeURIComponent(id)}`, {
    method: "DELETE",
    credentials: "include",
  });
  await handle<void>(response);
}

export async function listAiModelConfigs(): Promise<{ model_configs: AiModelConfig[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/model-configs`, { credentials: "include" });
  return handle<{ model_configs: AiModelConfig[] }>(response);
}

export async function createAiModelConfig(payload: Partial<AiModelConfig> & { provider: "openai" | "anthropic" | "google"; model_name: string }): Promise<{ model_config: AiModelConfig }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/model-configs`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ model_config: AiModelConfig }>(response);
}

export async function updateAiModelConfig(id: string, payload: Partial<AiModelConfig>): Promise<{ model_config: AiModelConfig }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/model-configs/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ model_config: AiModelConfig }>(response);
}

export async function deleteAiModelConfig(id: string): Promise<{ model_config: AiModelConfig; status: string; message?: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/model-configs/${encodeURIComponent(id)}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handle<{ model_config: AiModelConfig; status: string; message?: string }>(response);
}

export async function getAiModelConfigCompat(id: string): Promise<AiModelConfigCompat> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/model-configs/${encodeURIComponent(id)}/compat`, {
    credentials: "include",
  });
  return handle<AiModelConfigCompat>(response);
}

export async function listAiAgents(params?: { purpose?: string; enabled?: boolean }): Promise<{ agents: AiAgent[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/ai/agents`);
  if (params?.purpose) url.searchParams.set("purpose", params.purpose);
  if (params?.enabled !== undefined) url.searchParams.set("enabled", params.enabled ? "true" : "false");
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<{ agents: AiAgent[] }>(response);
}

export async function createAiAgent(payload: {
  slug: string;
  name: string;
  model_config_id: string;
  override_prompt_text?: string;
  default_context_pack_refs_json?: unknown[];
  // Backward-compatible aliases.
  system_prompt_text?: string;
  context_pack_refs_json?: unknown[];
  is_default?: boolean;
  enabled?: boolean;
  purposes?: string[];
}): Promise<{ agent: AiAgent }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/agents`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ agent: AiAgent }>(response);
}

export async function updateAiAgent(
  id: string,
  payload: Partial<{
    slug: string;
    name: string;
    model_config_id: string;
    override_prompt_text: string;
    default_context_pack_refs_json: unknown[];
    // Backward-compatible aliases.
    system_prompt_text: string;
    context_pack_refs_json: unknown[];
    is_default: boolean;
    enabled: boolean;
    purposes: string[];
  }>
): Promise<{ agent: AiAgent }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/agents/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ agent: AiAgent }>(response);
}

export async function deleteAiAgent(id: string): Promise<void> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/agents/${encodeURIComponent(id)}`, {
    method: "DELETE",
    credentials: "include",
  });
  await handle<void>(response);
}

export async function invokeAi(payload: {
  agent_slug: string;
  messages: Array<{ role: "system" | "user" | "assistant"; content: string }>;
  metadata?: Record<string, unknown>;
}): Promise<AiInvokeResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/ai/invoke`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<AiInvokeResponse>(response);
}

export async function getMyProfile(): Promise<MyProfile> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/my/profile`, { credentials: "include" });
  return handle<MyProfile>(response);
}

export async function getTenantBranding(tenantId: string): Promise<BrandingResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/tenants/${tenantId}/branding`, {
    credentials: "include",
  });
  return handle<BrandingResponse>(response);
}

export async function updateTenantBranding(tenantId: string, payload: BrandingPayload): Promise<void> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/tenants/${tenantId}/branding`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  await handle<void>(response);
}

export async function getPlatformBranding(): Promise<PlatformBranding> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/platform/branding`, {
    credentials: "include",
  });
  return handle<PlatformBranding>(response);
}

export async function updatePlatformBranding(payload: PlatformBrandingPayload): Promise<PlatformBranding> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/platform/branding`, {
    method: "PUT",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<PlatformBranding>(response);
}

export async function getAppBrandingOverride(appId: string): Promise<AppBrandingOverride> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/platform/branding/apps/${encodeURIComponent(appId)}`, {
    credentials: "include",
  });
  return handle<AppBrandingOverride>(response);
}

export async function updateAppBrandingOverride(
  appId: string,
  payload: AppBrandingOverridePayload
): Promise<AppBrandingOverride> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/platform/branding/apps/${encodeURIComponent(appId)}`, {
    method: "PUT",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<AppBrandingOverride>(response);
}

export async function getPublicBranding(appId: string): Promise<Record<string, unknown>> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/public/branding?appId=${encodeURIComponent(appId)}`);
  return handle<Record<string, unknown>>(response);
}

export async function getBrandingTokens(appId: string): Promise<BrandingTokens> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/branding/tokens?app=${encodeURIComponent(appId)}`);
  return handle<BrandingTokens>(response);
}

export function getBrandingThemeCssUrl(appId: string): string {
  const apiBaseUrl = resolveApiBaseUrl();
  return `${apiBaseUrl}/xyn/api/branding/theme.css?app=${encodeURIComponent(appId)}`;
}

export async function setActiveTenant(tenantId: string): Promise<void> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/my/active-tenant`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify({ tenant_id: tenantId }),
  });
  await handle<void>(response);
}

export async function listTenantDevices(): Promise<DeviceListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/tenant/devices`, {
    credentials: "include",
  });
  return handle<DeviceListResponse>(response);
}

export async function createDevice(payload: DevicePayload): Promise<Device> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/tenant/devices`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<Device>(response);
}

export async function updateDevice(id: string, payload: DevicePayload): Promise<Device> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/devices/${id}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<Device>(response);
}

export async function deleteDevice(id: string): Promise<void> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/devices/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  await handle<void>(response);
}

export async function createDeviceAction(
  deviceId: string,
  payload: { action_type: string; params?: Record<string, unknown>; instance_id?: string; instance_ref?: string }
): Promise<{ action: DraftAction; requires_confirmation: boolean; requires_ratification: boolean; next_status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/devices/${deviceId}/actions`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ action: DraftAction; requires_confirmation: boolean; requires_ratification: boolean; next_status: string }>(
    response
  );
}

export async function confirmAction(
  actionId: string
): Promise<{ action: DraftAction; receipt?: ExecutionReceipt; success?: boolean }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/actions/${actionId}/confirm`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify({}),
  });
  return handle<{ action: DraftAction; receipt?: ExecutionReceipt; success?: boolean }>(response);
}

export async function ratifyAction(
  actionId: string,
  payload: { method?: string; notes?: string } = {}
): Promise<{ action: DraftAction; receipt?: ExecutionReceipt; success?: boolean }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/actions/${actionId}/ratify`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ action: DraftAction; receipt?: ExecutionReceipt; success?: boolean }>(response);
}

export async function executeAction(
  actionId: string
): Promise<{ action: DraftAction; receipt: ExecutionReceipt; success: boolean }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/actions/${actionId}/execute`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify({}),
  });
  return handle<{ action: DraftAction; receipt: ExecutionReceipt; success: boolean }>(response);
}

export async function listActions(deviceId?: string): Promise<{ actions: DraftAction[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/actions`);
  if (deviceId) {
    url.searchParams.set("device_id", deviceId);
  }
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<{ actions: DraftAction[] }>(response);
}

export async function getAction(
  actionId: string
): Promise<{ action: DraftAction; timeline: ActionEvent[]; evidence: ActionEvidence[]; ratifications: ActionRatification[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/actions/${actionId}`, {
    credentials: "include",
  });
  return handle<{ action: DraftAction; timeline: ActionEvent[]; evidence: ActionEvidence[]; ratifications: ActionRatification[] }>(response);
}

export async function getActionReceipts(actionId: string): Promise<{ receipts: ExecutionReceipt[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/actions/${actionId}/receipts`, {
    credentials: "include",
  });
  return handle<{ receipts: ExecutionReceipt[] }>(response);
}

export async function listBlueprints(query = "", mode: "all" | "drafts" | "versions" = "all"): Promise<BlueprintListResponse> {
  const payload = await listUnifiedArtifacts({ type: "blueprint", query, limit: 200, offset: 0 });
  const order: Record<string, number> = { canonical: 0, provisional: 1, deprecated: 2 };
  const blueprints = payload.artifacts
    .map((artifact) => mapArtifactToBlueprintSummary(artifact))
    .filter((item) => {
      const state = String(item.artifact_state || "").toLowerCase();
      if (mode === "drafts") return state === "provisional";
      if (mode === "versions") return state === "canonical" || state === "deprecated";
      return true;
    })
    .sort((a, b) => {
      const rankA = order[String(a.artifact_state || "").toLowerCase()] ?? 99;
      const rankB = order[String(b.artifact_state || "").toLowerCase()] ?? 99;
      if (rankA !== rankB) return rankA - rankB;
      const aUpdated = Date.parse(String(a.updated_at || "")) || 0;
      const bUpdated = Date.parse(String(b.updated_at || "")) || 0;
      return bUpdated - aUpdated;
    });
  return {
    blueprints,
    count: blueprints.length,
    next: null,
    prev: null,
  };
}

export async function getBlueprint(id: string): Promise<BlueprintDetail> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/blueprints/${id}`, {
    credentials: "include",
  });
  return handle<BlueprintDetail>(response);
}

export async function reviseBlueprintArtifact(
  artifactId: string
): Promise<{ artifact_id: string; blueprint_id: string; family_id: string; parent_artifact_id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/blueprints/${artifactId}/revise`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify({}),
  });
  return handle<{ artifact_id: string; blueprint_id: string; family_id: string; parent_artifact_id: string }>(response);
}

export async function publishBlueprintArtifact(
  artifactId: string
): Promise<{ artifact_id: string; artifact_state: string; family_id: string; superseded_artifact_id?: string | null }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/blueprints/${artifactId}/publish`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify({}),
  });
  return handle<{ artifact_id: string; artifact_state: string; family_id: string; superseded_artifact_id?: string | null }>(
    response
  );
}

export async function updateArtifactRecord(
  artifactId: string,
  payload: Record<string, unknown>
): Promise<UnifiedArtifact> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/artifacts/${artifactId}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<UnifiedArtifact>(response);
}

export async function createBlueprint(payload: BlueprintCreatePayload): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/blueprints`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function updateBlueprint(id: string, payload: BlueprintCreatePayload): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/blueprints/${id}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function listTenants(): Promise<TenantListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/tenants`, { credentials: "include" });
  return handle<TenantListResponse>(response);
}

export async function listVisibleTenants(): Promise<TenantListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/tenants`, { credentials: "include" });
  return handle<TenantListResponse>(response);
}

export async function createTenant(payload: TenantCreatePayload): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/tenants`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function updateTenant(id: string, payload: Partial<TenantCreatePayload>): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/tenants/${id}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function deleteTenant(id: string): Promise<void> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/tenants/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  await handle<void>(response);
}

export async function listContacts(tenantId: string): Promise<ContactListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/tenants/${tenantId}/contacts`, {
    credentials: "include",
  });
  return handle<ContactListResponse>(response);
}

export async function createContact(tenantId: string, payload: ContactCreatePayload): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/tenants/${tenantId}/contacts`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function updateContact(id: string, payload: Partial<ContactCreatePayload>): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/contacts/${id}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function deleteContact(id: string): Promise<void> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/contacts/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  await handle<void>(response);
}

export async function listIdentities(): Promise<IdentityListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/identities`, {
    credentials: "include",
  });
  return handle<IdentityListResponse>(response);
}

export async function listRoleBindings(identityId?: string): Promise<RoleBindingListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/internal/role_bindings`);
  if (identityId) {
    url.searchParams.set("identity_id", identityId);
  }
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<RoleBindingListResponse>(response);
}

export async function createRoleBinding(payload: RoleBindingCreatePayload): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/role_bindings`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function deleteRoleBinding(id: string): Promise<void> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/role_bindings/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  await handle<void>(response);
}

export async function listMemberships(tenantId: string): Promise<MembershipListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/tenants/${tenantId}/memberships`, {
    credentials: "include",
  });
  return handle<MembershipListResponse>(response);
}

export async function createMembership(
  tenantId: string,
  payload: MembershipCreatePayload
): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/tenants/${tenantId}/memberships`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function updateMembership(id: string, payload: Partial<MembershipCreatePayload>): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/memberships/${id}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function deleteMembership(id: string): Promise<void> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/memberships/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  await handle<void>(response);
}

export async function listBlueprintDraftSessions(
  blueprintId: string
): Promise<{ sessions: BlueprintDraftSession[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/blueprints/${blueprintId}/draft-sessions`, {
    credentials: "include",
  });
  return handle<{ sessions: BlueprintDraftSession[] }>(response);
}

export async function listDraftSessions(params: {
  status?: string;
  kind?: "blueprint" | "solution";
  namespace?: string;
  project_key?: string;
  blueprint_id?: string;
  q?: string;
} = {}): Promise<{ sessions: BlueprintDraftSession[] }> {
  const payload = await listUnifiedArtifacts({ type: "draft_session", query: params.q || "", limit: 500, offset: 0 });
  let sessions = payload.artifacts.map((artifact) => mapArtifactToDraftSessionSummary(artifact));
  if (params.status) sessions = sessions.filter((item) => item.status === params.status);
  if (params.kind) sessions = sessions.filter((item) => item.kind === params.kind);
  if (params.namespace) sessions = sessions.filter((item) => (item.namespace || "") === params.namespace);
  if (params.project_key) sessions = sessions.filter((item) => (item.project_key || "") === params.project_key);
  if (params.blueprint_id) sessions = sessions.filter((item) => (item.blueprint_id || "") === params.blueprint_id);
  return { sessions };
}

async function listUnifiedArtifacts(params: {
  type: "blueprint" | "draft_session";
  query?: string;
  limit?: number;
  offset?: number;
}): Promise<UnifiedArtifactListResponse> {
  return listArtifacts(params);
}

function mapArtifactToBlueprintSummary(artifact: UnifiedArtifact): BlueprintSummary {
  const source = (artifact.source || {}) as Record<string, unknown>;
  return {
    id: String(source.id || artifact.source_ref_id || artifact.id),
    artifact_id: artifact.artifact_id,
    artifact_state: artifact.artifact_state,
    family_id: artifact.family_id || "",
    parent_artifact_id: artifact.parent_artifact_id ?? null,
    name: String(artifact.title || source.name || "Untitled blueprint"),
    namespace: String(source.namespace || "core"),
    status: (source.status as BlueprintSummary["status"]) || "active",
    description: String(source.description || artifact.summary || ""),
    created_at: String(source.created_at || artifact.created_at || ""),
    updated_at: String(source.updated_at || artifact.updated_at || ""),
  };
}

function mapArtifactToDraftSessionSummary(artifact: UnifiedArtifact): BlueprintDraftSession {
  const source = (artifact.source || {}) as Record<string, unknown>;
  return {
    id: String(source.id || artifact.source_ref_id || artifact.id),
    artifact_id: artifact.artifact_id,
    name: String(source.name || artifact.title || "Untitled draft"),
    title: String(source.title || artifact.title || "Untitled draft"),
    kind: (source.kind as BlueprintDraftSession["kind"]) || "blueprint",
    status: String(source.status || "drafting"),
    blueprint_kind: String(source.blueprint_kind || "solution"),
    namespace: (source.namespace as string | null | undefined) ?? null,
    project_key: (source.project_key as string | null | undefined) ?? null,
    blueprint_id: (source.blueprint_id as string | null | undefined) ?? null,
    linked_blueprint_id: (source.linked_blueprint_id as string | null | undefined) ?? null,
    created_at: String(source.created_at || artifact.created_at || ""),
    updated_at: String(source.updated_at || artifact.updated_at || ""),
  };
}

export async function listReleaseTargets(blueprintId?: string): Promise<ReleaseTargetListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/release-targets`);
  if (blueprintId) {
    url.searchParams.set("blueprint_id", blueprintId);
  }
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<ReleaseTargetListResponse>(response);
}

export async function createReleaseTarget(payload: ReleaseTargetCreatePayload): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/release-targets`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function getReleaseTarget(id: string): Promise<ReleaseTarget> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/release-targets/${id}`, {
    credentials: "include",
  });
  return handle<ReleaseTarget>(response);
}

export async function updateReleaseTarget(
  id: string,
  payload: Partial<ReleaseTargetCreatePayload>
): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/release-targets/${id}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function deleteReleaseTarget(id: string): Promise<void> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/release-targets/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  await handle<void>(response);
}

export async function fetchMap(filters?: {
  blueprint_id?: string;
  environment_id?: string;
  tenant_id?: string;
  include_runs?: boolean;
  include_instances?: boolean;
}): Promise<XynMapResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/map`);
  if (filters?.blueprint_id) {
    url.searchParams.set("blueprint_id", filters.blueprint_id);
  }
  if (filters?.environment_id) {
    url.searchParams.set("environment_id", filters.environment_id);
  }
  if (filters?.tenant_id) {
    url.searchParams.set("tenant_id", filters.tenant_id);
  }
  if (filters?.include_runs !== undefined) {
    url.searchParams.set("include_runs", filters.include_runs ? "true" : "false");
  }
  if (filters?.include_instances !== undefined) {
    url.searchParams.set("include_instances", filters.include_instances ? "true" : "false");
  }
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<XynMapResponse>(response);
}

export async function deployLatest(releaseTargetId: string): Promise<{ run_id?: string; status?: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/release-targets/${releaseTargetId}/deploy_latest`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ run_id?: string; status?: string }>(response);
}

export async function rollbackLastSuccess(releaseTargetId: string): Promise<{ run_id?: string; status?: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/release-targets/${releaseTargetId}/rollback_last_success`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ run_id?: string; status?: string }>(response);
}

export async function checkDrift(releaseTargetId: string): Promise<{
  drift?: boolean;
  expected?: Record<string, unknown>;
  actual?: Record<string, unknown>;
}> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/release-targets/${releaseTargetId}/check_drift`, {
    credentials: "include",
  });
  return handle(response);
}

export async function createBlueprintDraftSession(
  blueprintId: string,
  payload: {
    name?: string;
    title?: string;
    kind?: "blueprint" | "solution";
    draft_kind?: "blueprint" | "solution";
    blueprint_kind?: string;
    namespace?: string;
    project_key?: string;
    initial_prompt?: string;
    revision_instruction?: string;
    generate_code?: boolean;
    context_pack_ids?: string[];
    selected_context_pack_ids?: string[];
    source_artifacts?: Array<{ type: "text" | "audio_transcript"; content: string; meta?: Record<string, unknown> }>;
  }
): Promise<{ session_id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/blueprints/${blueprintId}/draft-sessions`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ session_id: string }>(response);
}

export async function createDraftSession(payload: {
  name?: string;
  title?: string;
  kind?: "blueprint" | "solution";
  draft_kind?: "blueprint" | "solution";
  blueprint_kind?: string;
  namespace?: string;
  project_key?: string;
  initial_prompt?: string;
  revision_instruction?: string;
  generate_code?: boolean;
  blueprint_id?: string;
  context_pack_ids?: string[];
  selected_context_pack_ids?: string[];
  source_artifacts?: Array<{ type: "text" | "audio_transcript"; content: string; meta?: Record<string, unknown> }>;
}): Promise<{ session_id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/draft-sessions`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ session_id: string }>(response);
}

export async function getContextPackDefaults(params: {
  draft_kind: "blueprint" | "solution";
  namespace?: string;
  project_key?: string;
  generate_code?: boolean;
}): Promise<ContextPackDefaultsResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/context-pack-defaults`);
  url.searchParams.set("draft_kind", params.draft_kind);
  if (params.namespace) url.searchParams.set("namespace", params.namespace);
  if (params.project_key) url.searchParams.set("project_key", params.project_key);
  if (params.generate_code !== undefined) {
    url.searchParams.set("generate_code", params.generate_code ? "1" : "0");
  }
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<ContextPackDefaultsResponse>(response);
}

export async function getDraftSession(sessionId: string): Promise<BlueprintDraftSessionDetail> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/draft-sessions/${sessionId}`, {
    credentials: "include",
  });
  return handle<BlueprintDraftSessionDetail>(response);
}

export async function updateDraftSession(
  sessionId: string,
  payload: {
    title?: string;
    kind?: "blueprint" | "solution";
    namespace?: string;
    project_key?: string;
    initial_prompt?: string;
    revision_instruction?: string;
    selected_context_pack_ids?: string[];
    source_artifacts?: Array<{ type: "text" | "audio_transcript"; content: string; meta?: Record<string, unknown> }>;
  }
): Promise<BlueprintDraftSessionDetail> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/draft-sessions/${sessionId}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<BlueprintDraftSessionDetail>(response);
}

export async function deleteDraftSession(sessionId: string): Promise<{ status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/draft-sessions/${sessionId}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handle<{ status: string }>(response);
}

export async function enqueueDraftGeneration(
  sessionId: string
): Promise<{
  status: string;
  job_id: string;
  effective_context_hash?: string;
  context_resolved_at?: string | null;
  context_stale?: boolean;
}> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(
    `${apiBaseUrl}/xyn/api/draft-sessions/${sessionId}/enqueue-draft-generation`,
    {
      method: "POST",
      credentials: "include",
    }
  );
  return handle<{
    status: string;
    job_id: string;
    effective_context_hash?: string;
    context_resolved_at?: string | null;
    context_stale?: boolean;
  }>(response);
}

export async function enqueueDraftRevision(
  sessionId: string,
  payload: { instruction?: string }
): Promise<{ status: string; job_id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(
    `${apiBaseUrl}/xyn/api/draft-sessions/${sessionId}/enqueue-draft-revision`,
    {
      method: "POST",
      headers: buildHeaders(),
      credentials: "include",
      body: JSON.stringify(payload ?? {}),
    }
  );
  return handle<{ status: string; job_id: string }>(response);
}

export async function resolveDraftSessionContext(
  sessionId: string,
  payload: { context_pack_ids?: string[] } = {}
): Promise<{
  context_pack_refs: unknown[];
  effective_context_hash?: string;
  effective_context_preview?: string;
  context_resolved_at?: string | null;
  context_stale?: boolean;
}> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/draft-sessions/${sessionId}/resolve-context`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{
    context_pack_refs: unknown[];
    effective_context_hash?: string;
    effective_context_preview?: string;
    context_resolved_at?: string | null;
    context_stale?: boolean;
  }>(response);
}

export async function saveDraftSession(
  sessionId: string,
  payload: { draft_json: Record<string, unknown> }
): Promise<{ status: string; validation_errors: string[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/draft-sessions/${sessionId}/save`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ status: string; validation_errors: string[] }>(response);
}

export async function publishDraftSession(
  sessionId: string
): Promise<{ ok: boolean; deprecated?: boolean; snapshot_id?: string; session_id?: string; status?: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/draft-sessions/${sessionId}/publish`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ ok: boolean; deprecated?: boolean; snapshot_id?: string; session_id?: string; status?: string }>(
    response
  );
}

export async function snapshotDraftSession(
  sessionId: string,
  payload: { note?: string } = {}
): Promise<{ ok: boolean; snapshot_id?: string; session_id?: string; status?: string; updated_at?: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/draft-sessions/${sessionId}/snapshot`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload ?? {}),
  });
  return handle<{ ok: boolean; snapshot_id?: string; session_id?: string; status?: string; updated_at?: string }>(
    response
  );
}

export async function submitDraftSession(
  sessionId: string,
  payload: {
    initial_prompt?: string;
    selected_context_pack_ids?: string[];
    source_artifacts?: Array<{ type: "text" | "audio_transcript"; content: string; meta?: Record<string, unknown> }>;
    generate_code?: boolean;
    release_target?: {
      environment_id?: string;
      environment_name?: string;
      target_instance_id?: string;
      target_instance_name?: string;
      fqdn?: string;
      hostname?: string;
    };
  } = {}
): Promise<{
  ok: boolean;
  status: string;
  session_id: string;
  submission_payload: Record<string, unknown>;
  entity_type?: string;
  entity_id?: string;
  revision?: number;
}> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/draft-sessions/${sessionId}/submit`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{
    ok: boolean;
    status: string;
    session_id: string;
    submission_payload: Record<string, unknown>;
    entity_type?: string;
    entity_id?: string;
    revision?: number;
  }>(response);
}

export async function extractDraftSessionReleaseTarget(
  sessionId: string,
  payload: { text?: string } = {}
): Promise<{
  intent?: Record<string, unknown> | null;
  resolved?: {
    environment_id?: string | null;
    environment_name?: string | null;
    instance_id?: string | null;
    instance_name?: string | null;
    fqdn?: string | null;
  };
  warnings?: string[];
}> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/draft-sessions/${sessionId}/extract_release_target`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload ?? {}),
  });
  return handle<{
    intent?: Record<string, unknown> | null;
    resolved?: {
      environment_id?: string | null;
      environment_name?: string | null;
      instance_id?: string | null;
      instance_name?: string | null;
      fqdn?: string | null;
    };
    warnings?: string[];
  }>(response);
}

export async function listDraftSessionRevisions(
  sessionId: string,
  params: { q?: string; page?: number; page_size?: number } = {}
): Promise<{ revisions: DraftSessionRevision[]; total: number; page: number; page_size: number }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/draft-sessions/${sessionId}/revisions`);
  if (params.q) url.searchParams.set("q", params.q);
  if (params.page) url.searchParams.set("page", String(params.page));
  if (params.page_size) url.searchParams.set("page_size", String(params.page_size));
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<{ revisions: DraftSessionRevision[]; total: number; page: number; page_size: number }>(response);
}

export async function listBlueprintVoiceNotes(
  blueprintId: string
): Promise<{ voice_notes: BlueprintVoiceNote[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/blueprints/${blueprintId}/voice-notes`, {
    credentials: "include",
  });
  return handle<{ voice_notes: BlueprintVoiceNote[] }>(response);
}

export async function listDraftSessionVoiceNotes(
  sessionId: string
): Promise<{ voice_notes: BlueprintVoiceNote[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/draft-sessions/${sessionId}/voice-notes`, {
    credentials: "include",
  });
  return handle<{ voice_notes: BlueprintVoiceNote[] }>(response);
}

export async function uploadVoiceNote(
  file: File,
  payload: { session_id?: string; title?: string; language_code?: string }
): Promise<{ voice_note_id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const form = new FormData();
  form.append("file", file);
  if (payload.session_id) form.append("session_id", payload.session_id);
  if (payload.title) form.append("title", payload.title);
  if (payload.language_code) form.append("language_code", payload.language_code);
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/voice-notes`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  return handle<{ voice_note_id: string }>(response);
}

export async function enqueueVoiceNoteTranscription(
  voiceNoteId: string
): Promise<{ status: string; job_id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/voice-notes/${voiceNoteId}/enqueue-transcription`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ status: string; job_id: string }>(response);
}

export async function deleteBlueprint(id: string): Promise<{ status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/blueprints/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handle<{ status: string }>(response);
}

export async function archiveBlueprint(id: string): Promise<{ status: string; id: string; archived_at?: string | null }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/blueprints/${id}/archive`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ status: string; id: string; archived_at?: string | null }>(response);
}

export async function getBlueprintDeprovisionPlan(
  id: string,
  options?: {
    mode?: "safe" | "stop_services" | "force";
    delete_dns?: boolean;
    remove_runtime_markers?: boolean;
  }
): Promise<BlueprintDeprovisionPlan> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/blueprints/${id}/deprovision_plan`);
  if (options?.mode) url.searchParams.set("mode", options.mode);
  if (options?.delete_dns !== undefined) url.searchParams.set("delete_dns", options.delete_dns ? "1" : "0");
  if (options?.remove_runtime_markers !== undefined) {
    url.searchParams.set("remove_runtime_markers", options.remove_runtime_markers ? "1" : "0");
  }
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<BlueprintDeprovisionPlan>(response);
}

export async function deprovisionBlueprint(
  id: string,
  payload: {
    confirm_text: string;
    mode: "safe" | "stop_services" | "force";
    stop_services: boolean;
    delete_dns: boolean;
    remove_runtime_markers: boolean;
    dry_run?: boolean;
    release_target_ids?: string[];
  }
): Promise<{ run_id: string; status: string; blueprint_status: string; task_count: number; dry_run: boolean }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/blueprints/${id}/deprovision`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ run_id: string; status: string; blueprint_status: string; task_count: number; dry_run: boolean }>(
    response
  );
}

export async function submitBlueprint(
  id: string,
  releaseTargetId?: string
): Promise<{ run_id?: string; instance_id?: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/blueprints/${id}/submit`, {
    method: "POST",
    credentials: "include",
    headers: releaseTargetId ? buildHeaders() : undefined,
    body: releaseTargetId ? JSON.stringify({ release_target_id: releaseTargetId }) : undefined,
  });
  return handle<{ run_id?: string; instance_id?: string }>(response);
}

export async function submitBlueprintWithDevTasks(
  id: string,
  releaseTargetId?: string
): Promise<{ run_id?: string; instance_id?: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/blueprints/${id}/submit?queue_dev_tasks=1`, {
    method: "POST",
    credentials: "include",
    headers: releaseTargetId ? buildHeaders() : undefined,
    body: releaseTargetId ? JSON.stringify({ release_target_id: releaseTargetId }) : undefined,
  });
  return handle<{ run_id?: string; instance_id?: string }>(response);
}

export async function listContextPacks(params: {
  scope?: string;
  purpose?: string;
  namespace?: string;
  project_key?: string;
  active?: boolean;
} = {}): Promise<ContextPackListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/context-packs`);
  if (params.scope) url.searchParams.set("scope", params.scope);
  if (params.purpose) url.searchParams.set("purpose", params.purpose);
  if (params.namespace) url.searchParams.set("namespace", params.namespace);
  if (params.project_key) url.searchParams.set("project_key", params.project_key);
  if (params.active !== undefined) url.searchParams.set("active", params.active ? "1" : "0");
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<ContextPackListResponse>(response);
}

export async function getContextPack(id: string): Promise<ContextPackDetail> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/context-packs/${id}`, {
    credentials: "include",
  });
  return handle<ContextPackDetail>(response);
}

export async function createContextPack(payload: ContextPackCreatePayload): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/context-packs`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function updateContextPack(
  id: string,
  payload: Partial<ContextPackCreatePayload>
): Promise<ContextPackDetail> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/context-packs/${id}`, {
    method: "PUT",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<ContextPackDetail>(response);
}

export async function activateContextPack(id: string): Promise<{ status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/context-packs/${id}/activate`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ status: string }>(response);
}

export async function deactivateContextPack(id: string): Promise<{ status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/context-packs/${id}/deactivate`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ status: string }>(response);
}

export async function listSeedPacks(params: { include_items?: boolean } = {}): Promise<SeedPackListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/seeds/packs`);
  if (params.include_items !== undefined) url.searchParams.set("include_items", params.include_items ? "1" : "0");
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<SeedPackListResponse>(response);
}

export async function getSeedPack(slug: string): Promise<SeedPackDetailResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/seeds/packs/${encodeURIComponent(slug)}`, {
    credentials: "include",
  });
  return handle<SeedPackDetailResponse>(response);
}

export async function applySeedPacks(payload: {
  pack_slugs?: string[];
  apply_core?: boolean;
  dry_run?: boolean;
}): Promise<SeedApplyResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/seeds/apply`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload || {}),
  });
  return handle<SeedApplyResponse>(response);
}

export async function listModules(query = ""): Promise<ModuleListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/modules`);
  if (query) {
    url.searchParams.set("q", query);
  }
  url.searchParams.set("page_size", "200");
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<ModuleListResponse>(response);
}

export async function getModule(ref: string): Promise<ModuleDetail> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/modules/${ref}`, {
    credentials: "include",
  });
  return handle<ModuleDetail>(response);
}

export async function createModule(payload: ModuleCreatePayload): Promise<{ id: string; fqn?: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/modules`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string; fqn?: string }>(response);
}

export async function updateModule(id: string, payload: ModuleCreatePayload): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/modules/${id}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function deleteModule(id: string): Promise<{ status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/modules/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handle<{ status: string }>(response);
}

export async function listRegistries(): Promise<RegistryListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/registries`);
  url.searchParams.set("page_size", "200");
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<RegistryListResponse>(response);
}

export async function getRegistry(id: string): Promise<RegistryDetail> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/registries/${id}`, {
    credentials: "include",
  });
  return handle<RegistryDetail>(response);
}

export async function createRegistry(payload: RegistryCreatePayload): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/registries`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function updateRegistry(id: string, payload: RegistryCreatePayload): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/registries/${id}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function deleteRegistry(id: string): Promise<{ status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/registries/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handle<{ status: string }>(response);
}

export async function syncRegistry(id: string): Promise<{ status: string; last_sync_at?: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/registries/${id}/sync`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ status: string; last_sync_at?: string }>(response);
}

export async function listReleasePlans(): Promise<ReleasePlanListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/release-plans`);
  url.searchParams.set("page_size", "200");
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<ReleasePlanListResponse>(response);
}

export async function markReleasePlanDeployment(
  id: string,
  payload: { instance_id: string; last_applied_at?: string }
): Promise<{ status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/release-plans/${id}/deployments`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ status: string }>(response);
}

export async function getReleasePlan(id: string): Promise<ReleasePlanDetail> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/release-plans/${id}`, {
    credentials: "include",
  });
  return handle<ReleasePlanDetail>(response);
}

export async function createReleasePlan(payload: ReleasePlanCreatePayload): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/release-plans`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function updateReleasePlan(id: string, payload: ReleasePlanCreatePayload): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/release-plans/${id}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function deleteReleasePlan(id: string): Promise<{ status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/release-plans/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handle<{ status: string }>(response);
}

export async function generateReleasePlan(id: string): Promise<{ run_id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/release-plans/${id}/generate`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ run_id: string }>(response);
}

export async function listRuns(
  entity?: string,
  status?: string,
  query?: string,
  page?: number,
  pageSize?: number
): Promise<RunListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/runs`);
  url.searchParams.set("page_size", String(pageSize ?? 50));
  if (page) {
    url.searchParams.set("page", String(page));
  }
  if (entity) {
    url.searchParams.set("entity", entity);
  }
  if (status) {
    url.searchParams.set("status", status);
  }
  if (query) {
    url.searchParams.set("q", query);
  }
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<RunListResponse>(response);
}

export async function listRunsCanvasApi(
  entity?: string,
  status?: string,
  query?: string,
  page?: number,
  pageSize?: number
): Promise<RunListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/api/runs`);
  url.searchParams.set("page_size", String(pageSize ?? 50));
  if (page) {
    url.searchParams.set("page", String(page));
  }
  if (entity) {
    url.searchParams.set("entity", entity);
  }
  if (status) {
    url.searchParams.set("status", status);
  }
  if (query) {
    url.searchParams.set("q", query);
  }
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<RunListResponse>(response);
}

export async function listReleases(
  blueprintId?: string,
  status?: string,
  page?: number,
  pageSize?: number
): Promise<ReleaseListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/releases`);
  url.searchParams.set("page_size", String(pageSize ?? 20));
  if (page) {
    url.searchParams.set("page", String(page));
  }
  if (blueprintId) {
    url.searchParams.set("blueprint_id", blueprintId);
  }
  if (status) {
    url.searchParams.set("status", status);
  }
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<ReleaseListResponse>(response);
}

export async function deleteRelease(id: string): Promise<{ status: string; image_cleanup?: Record<string, unknown> }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/releases/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handle<{ status: string; image_cleanup?: Record<string, unknown> }>(response);
}

export async function bulkDeleteReleases(
  releaseIds: string[]
): Promise<{
  status: string;
  requested_count: number;
  deleted_count: number;
  skipped_count: number;
  deleted: string[];
  skipped: Array<{ id: string; reason: string }>;
  image_cleanup?: Record<string, unknown>;
}> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/releases/bulk-delete`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify({ release_ids: releaseIds }),
  });
  return handle<{
    status: string;
    requested_count: number;
    deleted_count: number;
    skipped_count: number;
    deleted: string[];
    skipped: Array<{ id: string; reason: string }>;
    image_cleanup?: Record<string, unknown>;
  }>(response);
}

export async function listEnvironments(): Promise<EnvironmentListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/environments`);
  url.searchParams.set("page_size", "200");
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<EnvironmentListResponse>(response);
}

export async function createEnvironment(
  payload: EnvironmentCreatePayload
): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/environments`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function updateEnvironment(
  id: string,
  payload: EnvironmentCreatePayload
): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/environments/${id}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function deleteEnvironment(id: string): Promise<{ status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/environments/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handle<{ status: string }>(response);
}

export async function getRelease(id: string): Promise<ReleaseDetail> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/releases/${id}`, {
    credentials: "include",
  });
  return handle<ReleaseDetail>(response);
}

export async function createRelease(payload: ReleaseCreatePayload): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/releases`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function updateRelease(id: string, payload: Partial<ReleaseSummary>): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/releases/${id}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function getRun(id: string): Promise<RunDetail> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/runs/${id}`, {
    credentials: "include",
  });
  return handle<RunDetail>(response);
}

export async function getRunCanvasApi(id: string): Promise<RunDetail> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/api/runs/${id}`, {
    credentials: "include",
  });
  return handle<RunDetail>(response);
}

export async function getRunLogs(id: string): Promise<RunLogResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/runs/${id}/logs`, {
    credentials: "include",
  });
  return handle<RunLogResponse>(response);
}

export async function getRunArtifacts(id: string): Promise<RunArtifact[]> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/runs/${id}/artifacts`, {
    credentials: "include",
  });
  const data = await handle<{ artifacts: RunArtifact[] }>(response);
  return data.artifacts;
}

export async function getRunCommands(id: string): Promise<RunCommandExecution[]> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/runs/${id}/commands`, {
    credentials: "include",
  });
  const data = await handle<{ commands: RunCommandExecution[] }>(response);
  return data.commands;
}

export async function listDevTasks(
  status?: string,
  query?: string,
  page?: number,
  pageSize?: number
): Promise<DevTaskListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/dev-tasks`);
  url.searchParams.set("page_size", String(pageSize ?? 50));
  if (page) {
    url.searchParams.set("page", String(page));
  }
  if (status) {
    url.searchParams.set("status", status);
  }
  if (query) {
    url.searchParams.set("q", query);
  }
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<DevTaskListResponse>(response);
}

export async function createDevTask(payload: DevTaskCreatePayload): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/dev-tasks`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function getDevTask(id: string): Promise<DevTaskDetail> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/dev-tasks/${id}`, {
    credentials: "include",
  });
  return handle<DevTaskDetail>(response);
}

export async function runDevTask(id: string, force = false): Promise<{ run_id: string; status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/dev-tasks/${id}/run`);
  if (force) {
    url.searchParams.set("force", "1");
  }
  const response = await apiFetch(url.toString(), {
    method: "POST",
    credentials: "include",
  });
  return handle<{ run_id: string; status: string }>(response);
}

export async function retryDevTask(id: string): Promise<{ run_id: string; status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/dev-tasks/${id}/retry`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ run_id: string; status: string }>(response);
}

export async function cancelDevTask(id: string): Promise<{ status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/dev-tasks/${id}/cancel`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ status: string }>(response);
}

export async function listBlueprintDevTasks(id: string): Promise<{ dev_tasks: DevTaskSummary[] }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/blueprints/${id}/dev-tasks`, {
    credentials: "include",
  });
  return handle<{ dev_tasks: DevTaskSummary[] }>(response);
}

export async function listIdentityProviders(): Promise<IdentityProviderListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/platform/identity-providers`, {
    credentials: "include",
  });
  return handle<IdentityProviderListResponse>(response);
}

export async function listSecretStores(): Promise<SecretStoreListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/secret-stores`, {
    credentials: "include",
  });
  return handle<SecretStoreListResponse>(response);
}

export async function createSecretStore(payload: {
  name: string;
  kind?: "aws_secrets_manager";
  is_default?: boolean;
  config_json?: SecretStore["config_json"];
}): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/secret-stores`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function updateSecretStore(id: string, payload: Partial<SecretStore>): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/secret-stores/${id}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function setDefaultSecretStore(id: string): Promise<{ id: string; is_default: boolean }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/secret-stores/${id}/set_default`, {
    method: "POST",
    credentials: "include",
  });
  return handle<{ id: string; is_default: boolean }>(response);
}

export async function listSecretRefs(filters?: {
  scope_kind?: string;
  scope_id?: string;
}): Promise<SecretRefListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/internal/secret-refs`);
  if (filters?.scope_kind) url.searchParams.set("scope_kind", filters.scope_kind);
  if (filters?.scope_id) url.searchParams.set("scope_id", filters.scope_id);
  const response = await apiFetch(url.toString(), {
    credentials: "include",
  });
  return handle<SecretRefListResponse>(response);
}

export async function createSecretValue(payload: {
  name: string;
  scope_kind: "platform" | "tenant" | "user" | "team";
  scope_id?: string | null;
  store_id?: string | null;
  value: string;
  description?: string;
}): Promise<{
  secret_ref: {
    id: string;
    name: string;
    scope_kind: string;
    scope_id?: string | null;
    store_id: string;
    updated_at?: string;
  };
}> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/internal/secrets`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle(response);
}

export async function createReport(payload: ReportPayload, files: File[]): Promise<ReportRecord> {
  const apiBaseUrl = resolveApiBaseUrl();
  const form = new FormData();
  form.append("payload", JSON.stringify(payload));
  for (const file of files) {
    form.append("attachments", file);
  }
  const response = await apiFetch(`${apiBaseUrl}/api/v1/reports`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  return handle<ReportRecord>(response);
}

export async function getReport(id: string): Promise<ReportRecord> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/api/v1/reports/${id}`, {
    credentials: "include",
  });
  return handle<ReportRecord>(response);
}

export async function getPlatformConfig(): Promise<PlatformConfigResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/api/v1/platform-config`, {
    credentials: "include",
  });
  return handle<PlatformConfigResponse>(response);
}

export async function updatePlatformConfig(config: PlatformConfig): Promise<PlatformConfigResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/api/v1/platform-config`, {
    method: "PUT",
    credentials: "include",
    headers: buildHeaders(),
    body: JSON.stringify(config),
  });
  return handle<PlatformConfigResponse>(response);
}

export async function listVideoAdapters(): Promise<VideoAdaptersResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/video/adapters`, {
    credentials: "include",
  });
  return handle<VideoAdaptersResponse>(response);
}

export async function listVideoAdapterConfigs(
  adapterId?: string,
  state: "canonical" | "provisional" | "deprecated" | string = "canonical"
): Promise<VideoAdapterConfigListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/video/adapter-configs`);
  if (adapterId) {
    url.searchParams.set("adapter_id", adapterId);
  }
  if (state) {
    url.searchParams.set("state", state);
  }
  const response = await apiFetch(url.toString(), {
    credentials: "include",
  });
  return handle<VideoAdapterConfigListResponse>(response);
}

export async function createVideoAdapterConfig(payload: {
  title: string;
  slug?: string;
  adapter_id: string;
  config_json?: Record<string, unknown>;
}): Promise<VideoAdapterConfigDetailResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/video/adapter-configs`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<VideoAdapterConfigDetailResponse>(response);
}

export async function updateVideoAdapterConfig(
  artifactId: string,
  payload: Partial<{
    title: string;
    slug: string;
    adapter_id: string;
    artifact_state: string;
    config_json: Record<string, unknown>;
  }>
): Promise<VideoAdapterConfigDetailResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/video/adapter-configs/${artifactId}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<VideoAdapterConfigDetailResponse>(response);
}

export async function getVideoAdapterConfig(artifactId: string): Promise<VideoAdapterConfigDetailResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/video/adapter-configs/${artifactId}`, {
    credentials: "include",
  });
  return handle<VideoAdapterConfigDetailResponse>(response);
}

export async function testVideoAdapterConnection(payload: {
  adapter_id: string;
  adapter_config_id?: string;
}): Promise<VideoAdapterTestResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/video/adapters/test`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<VideoAdapterTestResponse>(response);
}

export async function createIdentityProvider(payload: IdentityProviderPayload): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/platform/identity-providers`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function updateIdentityProvider(
  id: string,
  payload: Partial<IdentityProviderPayload>
): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/platform/identity-providers/${id}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function deleteIdentityProvider(id: string): Promise<{ status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/platform/identity-providers/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handle<{ status: string }>(response);
}

export async function testIdentityProvider(id: string): Promise<{
  ok: boolean;
  authorization_endpoint?: string;
  token_endpoint?: string;
  jwks_uri?: string;
}> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/platform/identity-providers/${id}/test`, {
    credentials: "include",
  });
  return handle(response);
}

export async function listOidcAppClients(): Promise<OidcAppClientListResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/platform/oidc-app-clients`, {
    credentials: "include",
  });
  return handle<OidcAppClientListResponse>(response);
}

export async function createOidcAppClient(payload: OidcAppClientPayload): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/platform/oidc-app-clients`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function updateOidcAppClient(
  id: string,
  payload: Partial<OidcAppClientPayload>
): Promise<{ id: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/platform/oidc-app-clients/${id}`, {
    method: "PATCH",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ id: string }>(response);
}

export async function deleteOidcAppClient(id: string): Promise<{ status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/platform/oidc-app-clients/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  return handle<{ status: string }>(response);
}

export async function getControlPlaneState(environmentId?: string): Promise<ControlPlaneStateResponse> {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/control-plane/state`);
  if (environmentId) {
    url.searchParams.set("environment_id", environmentId);
  }
  const response = await apiFetch(url.toString(), { credentials: "include" });
  return handle<ControlPlaneStateResponse>(response);
}

export async function triggerControlPlaneDeploy(payload: {
  environment_id: string;
  app_id: string;
  release_id: string;
  instance_id?: string;
}): Promise<{ deployment_id: string; status: string; rollback_deployment_id?: string | null }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/control-plane/deploy`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ deployment_id: string; status: string; rollback_deployment_id?: string | null }>(response);
}

export async function triggerControlPlaneRollback(payload: {
  deployment_id?: string;
  environment_id?: string;
  app_id?: string;
}): Promise<{ rollback_deployment_id: string; rollback_status: string }> {
  const apiBaseUrl = resolveApiBaseUrl();
  const response = await apiFetch(`${apiBaseUrl}/xyn/api/control-plane/rollback`, {
    method: "POST",
    headers: buildHeaders(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  return handle<{ rollback_deployment_id: string; rollback_status: string }>(response);
}
