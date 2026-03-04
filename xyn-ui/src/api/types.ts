export type ProvisionStatus =
  | "requested"
  | "provisioning"
  | "running"
  | "ready"
  | "error"
  | "terminating"
  | "terminated";

export type ProvisionedInstance = {
  id: string;
  name: string;
  environment_id?: string | null;
  aws_region: string;
  instance_id: string | null;
  instance_type: string | null;
  ami_id: string | null;
  security_group_id: string | null;
  subnet_id: string | null;
  vpc_id: string | null;
  public_ip: string | null;
  private_ip: string | null;
  ssm_status: string | null;
  status: ProvisionStatus;
  last_error: string | null;
  desired_release_id?: string | null;
  observed_release_id?: string | null;
  observed_at?: string | null;
  last_deploy_run_id?: string | null;
  health_status?: "unknown" | "healthy" | "degraded" | "failed";
  tags?: Record<string, string>;
  created_at?: string;
  updated_at?: string;
};

export type InstanceListResponse = {
  instances: ProvisionedInstance[];
};

export type BootstrapLogResponse = {
  instance_id: string;
  status: string;
  stdout?: string;
  stderr?: string;
};

export type ContainerInfo = {
  id: string;
  name: string;
  image: string;
  status: string;
  ports: string;
};

export type InstanceContainersResponse = {
  instance_id: string;
  status: string;
  ssm_command_id?: string;
  error?: string;
  containers: ContainerInfo[];
};

export type CreateInstancePayload = {
  name?: string;
  region?: string;
  ami_id?: string;
  instance_type?: string;
  subnet_id?: string;
  vpc_id?: string;
  key_name?: string;
  repo_url?: string;
  iam_instance_profile_arn?: string;
  iam_instance_profile_name?: string;
  environment_id?: string;
};

export type PaginatedResponse<T, K extends string> = {
  count: number;
  next: number | null;
  prev: number | null;
} & Record<K, T[]>;

export type BlueprintSummary = {
  id: string;
  artifact_id?: string | null;
  artifact_state?: UnifiedArtifactState | string | null;
  family_id?: string;
  parent_artifact_id?: string | null;
  name: string;
  namespace: string;
  status?: "active" | "archived" | "deprovisioning" | "deprovisioned";
  archived_at?: string | null;
  deprovisioned_at?: string | null;
  deprovision_last_run_id?: string | null;
  description?: string;
  spec_text?: string;
  metadata_json?: Record<string, unknown> | null;
  created_at?: string;
  updated_at?: string;
  latest_revision?: number | null;
  active_draft_count?: number;
};

export type BlueprintDetail = BlueprintSummary & {
  spec_json?: Record<string, unknown> | null;
  derived_from_artifact_id?: string | null;
};

export type BlueprintDeprovisionStep = {
  id: string;
  title: string;
  capability: string;
};

export type BlueprintDeprovisionPlan = {
  blueprint_id: string;
  blueprint_name: string;
  blueprint_namespace: string;
  identifier: string;
  generated_at: string;
  mode: "safe" | "stop_services" | "force";
  flags: {
    stop_services: boolean;
    delete_dns: boolean;
    remove_runtime_markers: boolean;
    can_execute: boolean;
  };
  summary: {
    release_target_count: number;
    dns_record_count: number;
    runtime_root_count: number;
    step_count: number;
  };
  affected_release_targets: Array<{
    id: string;
    name: string;
    environment: string;
    fqdn: string;
    target_instance_id: string;
    remote_root: string;
    compose_file_path: string;
  }>;
  dns_records: Array<{
    release_target_id: string;
    fqdn: string;
    provider: string;
    zone_id: string;
    zone_name: string;
    ownership_proven: boolean;
  }>;
  runtime_roots: string[];
  warnings: string[];
  steps: BlueprintDeprovisionStep[];
};

export type BlueprintIntentTranscript = {
  id: string;
  ref?: string;
  text?: string;
  sha256?: string;
  createdAt?: string;
};

export type BlueprintIntentRequirements = {
  summary: string;
  functional: string[];
  ui: string[];
  dataModel: string[];
  operational: string[];
  definitionOfDone: string[];
};

export type BlueprintIntent = {
  sourceDraftSessionId: string;
  createdFrom: { type: "draft"; id: string };
  prompt: { text: string; sha256: string; createdAt: string };
  transcripts?: BlueprintIntentTranscript[];
  requirements: BlueprintIntentRequirements;
  codegen?: {
    repoTarget?: { name?: string; url?: string; ref?: string; pathRoot?: string };
    layout?: { apiPath?: string; webPath?: string };
  };
};

export type BlueprintCreatePayload = {
  name?: string;
  namespace?: string;
  description?: string;
  spec_json?: Record<string, unknown>;
  spec_text?: string;
  metadata_json?: Record<string, unknown> | null;
  blueprint_kind?: string;
};

export type BlueprintDraftSession = {
  id: string;
  artifact_id?: string | null;
  name: string;
  title?: string;
  kind?: "blueprint" | "solution";
  status: string;
  blueprint_kind: string;
  namespace?: string | null;
  project_key?: string | null;
  blueprint_id?: string | null;
  linked_blueprint_id?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type BlueprintDraftSessionDetail = {
  id: string;
  artifact_id?: string | null;
  title?: string;
  kind?: "blueprint" | "solution";
  blueprint_kind: string;
  status: string;
  draft?: Record<string, unknown> | null;
  namespace?: string | null;
  project_key?: string | null;
  initial_prompt?: string;
  initial_prompt_locked?: boolean;
  revision_instruction?: string;
  source_artifacts?: Array<{
    type: "text" | "audio_transcript";
    content: string;
    meta?: Record<string, unknown>;
  }>;
  has_generated_output?: boolean;
  requirements_summary?: string | null;
  validation_errors?: string[];
  suggested_fixes?: string[];
  job_id?: string | null;
  last_error?: string | null;
  diff_summary?: string | null;
  context_pack_refs?: Array<{
    id: string;
    name: string;
    purpose: string;
    scope: string;
    version: string;
    content_hash?: string;
    is_active?: boolean;
  }>;
  context_pack_ids?: string[];
  selected_context_pack_ids?: string[];
  effective_context_hash?: string | null;
  effective_context_preview?: string | null;
  context_resolved_at?: string | null;
  context_stale?: boolean;
  extracted_release_target_intent?: {
    environment_selector?: { id?: string; slug?: string; name?: string };
    target_instance_selector?: { id?: string; name?: string };
    fqdn?: string;
    tls_mode?: "none" | "nginx+acme" | "host-ingress";
    dns_provider?: "route53";
    runtime?: { type?: string; transport?: string; mode?: string; remote_root?: string };
    notes?: string[];
    confidence?: number;
    extraction_source?: "prompt" | "model" | "labels";
  } | null;
  extracted_release_target_intent_updated_at?: string | null;
  extracted_release_target_intent_source?: string | null;
  extracted_release_target_resolution?: {
    environment_id?: string | null;
    environment_name?: string | null;
    instance_id?: string | null;
    instance_name?: string | null;
    fqdn?: string | null;
    warnings?: string[];
  } | null;
  extracted_release_target_warnings?: string[];
  created_at?: string;
  updated_at?: string;
};

export type DraftSessionRevision = {
  id: string;
  revision_number: number;
  action: "generate" | "revise" | "save" | "snapshot" | "submit";
  instruction?: string;
  created_at: string;
  validation_errors_count: number;
  diff_summary?: string;
};

export type ContextPackDefaultsResponse = {
  draft_kind: "blueprint" | "solution";
  namespace?: string | null;
  project_key?: string | null;
  generate_code: boolean;
  recommended_context_pack_ids: string[];
  required_pack_names: string[];
  recommended_context_packs: ContextPackSummary[];
};

export type BlueprintVoiceNote = {
  id: string;
  title?: string;
  status: string;
  created_at?: string;
  session_id: string;
  job_id?: string | null;
  last_error?: string | null;
  transcript_text?: string | null;
  transcript_confidence?: number | null;
};

export type BlueprintListResponse = PaginatedResponse<BlueprintSummary, "blueprints">;

export type ModuleSummary = {
  id: string;
  artifact_id?: string;
  name: string;
  namespace: string;
  fqn: string;
  type: string;
  current_version: string;
  status: string;
  created_at?: string;
  updated_at?: string;
};

export type ModuleDetail = ModuleSummary & {
  latest_module_spec_json?: Record<string, unknown> | null;
};

export type ModuleCreatePayload = {
  name?: string;
  namespace?: string;
  type?: string;
  current_version?: string;
  status?: string;
  latest_module_spec_json?: Record<string, unknown>;
};

export type ModuleListResponse = PaginatedResponse<ModuleSummary, "modules">;

export type RegistrySummary = {
  id: string;
  name: string;
  registry_type: string;
  status: string;
  last_sync_at?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type RegistryDetail = RegistrySummary & {
  description?: string;
  url?: string;
};

export type RegistryCreatePayload = {
  name?: string;
  registry_type?: string;
  description?: string;
  url?: string;
  status?: string;
};

export type RegistryListResponse = PaginatedResponse<RegistrySummary, "registries">;

export type ReleasePlanSummary = {
  id: string;
  name: string;
  target_kind: string;
  target_fqn: string;
  from_version?: string;
  to_version?: string;
  blueprint_id?: string | null;
  environment_id?: string | null;
  last_run?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type ReleasePlanDetail = ReleasePlanSummary & {
  milestones_json?: Record<string, unknown> | null;
  current_release_id?: string | null;
  current_release_version?: string | null;
  deployments?: Array<{
    instance_id: string;
    instance_name: string;
    last_applied_hash?: string | null;
    last_applied_at?: string | null;
  }>;
};

export type ReleasePlanCreatePayload = {
  name?: string;
  target_kind?: string;
  target_fqn?: string;
  from_version?: string;
  to_version?: string;
  milestones_json?: Record<string, unknown>;
  blueprint_id?: string | null;
  environment_id?: string | null;
  release_id?: string | null;
  selected_release_id?: string | null;
};

export type ReleasePlanListResponse = PaginatedResponse<ReleasePlanSummary, "release_plans">;

export type ReleaseTarget = {
  id: string;
  blueprint_id: string;
  name: string;
  environment?: string;
  target_instance_id: string;
  fqdn: string;
  dns: {
    provider: string;
    zone_name?: string;
    zone_id?: string;
    record_type?: string;
    ttl?: number;
  };
  runtime: {
    type: string;
    transport: string;
    remote_root?: string;
    compose_file_path?: string;
    mode?: string;
    image_deploy?: boolean;
  };
  tls: {
    mode: string;
    termination?: string;
    provider?: string;
    acme_email?: string;
    expose_http?: boolean;
    expose_https?: boolean;
    redirect_http_to_https?: boolean;
  };
  ingress?: {
    network?: string;
    routes?: Array<{
      host: string;
      service: string;
      port: number;
      protocol?: string;
      health_path?: string;
    }>;
  };
  env?: Record<string, string>;
  secret_refs?: { name: string; ref: string }[];
  created_at?: string;
  updated_at?: string;
};

export type ReleaseTargetCreatePayload = {
  blueprint_id: string;
  name: string;
  environment?: string;
  target_instance_id: string;
  fqdn: string;
  dns?: {
    provider?: string;
    zone_name?: string;
    zone_id?: string;
    record_type?: string;
    ttl?: number;
  };
  runtime?: {
    type?: string;
    transport?: string;
    remote_root?: string;
    compose_file_path?: string;
    mode?: string;
    image_deploy?: boolean;
  };
  tls?: {
    mode?: string;
    termination?: string;
    provider?: string;
    acme_email?: string;
    expose_http?: boolean;
    expose_https?: boolean;
    redirect_http_to_https?: boolean;
  };
  ingress?: {
    network?: string;
    routes?: Array<{
      host: string;
      service: string;
      port: number;
      protocol?: string;
      health_path?: string;
    }>;
  };
  env?: Record<string, string>;
  secret_refs?: { name: string; ref: string }[];
};

export type ReleaseTargetListResponse = { release_targets: ReleaseTarget[] };

export type Tenant = {
  id: string;
  name: string;
  slug: string;
  status: string;
  metadata_json?: Record<string, unknown> | null;
  membership_role?: string;
  created_at?: string;
  updated_at?: string;
};

export type TenantListResponse = { tenants: Tenant[]; count?: number; next?: number | null; prev?: number | null };

export type TenantCreatePayload = {
  name?: string;
  slug?: string;
  status?: string;
  metadata_json?: Record<string, unknown> | null;
};

export type Contact = {
  id: string;
  tenant_id: string;
  name: string;
  email?: string | null;
  phone?: string | null;
  role_title?: string | null;
  status: string;
  metadata_json?: Record<string, unknown> | null;
  created_at?: string;
  updated_at?: string;
};

export type ContactListResponse = { contacts: Contact[] };

export type ContactCreatePayload = {
  name?: string;
  email?: string | null;
  phone?: string | null;
  role_title?: string | null;
  status?: string;
  metadata_json?: Record<string, unknown> | null;
};

export type IdentitySummary = {
  id: string;
  provider: string;
  provider_id?: string | null;
  provider_display_name?: string | null;
  issuer: string;
  subject: string;
  email?: string | null;
  display_name?: string | null;
  last_login_at?: string | null;
};

export type IdentityListResponse = { identities: IdentitySummary[] };

export type RoleBindingSummary = {
  id: string;
  user_identity_id: string;
  scope_kind: string;
  scope_id?: string | null;
  role: string;
  created_at?: string;
};

export type RoleBindingListResponse = { role_bindings: RoleBindingSummary[] };

export type RoleBindingCreatePayload = {
  user_identity_id: string;
  role: string;
};

export type MembershipSummary = {
  id: string;
  tenant_id: string;
  user_identity_id: string;
  role: string;
  status: string;
  user_email?: string | null;
  user_display_name?: string | null;
};

export type MembershipListResponse = { memberships: MembershipSummary[] };

export type MembershipCreatePayload = {
  user_identity_id: string;
  role: string;
};

export type MyProfile = {
  user: {
    issuer: string;
    subject: string;
    email?: string | null;
    display_name?: string | null;
  };
  roles: string[];
  memberships: Array<{
    tenant_id: string;
    tenant_name: string;
    role: string;
  }>;
};

export type BrandingPayload = {
  display_name?: string | null;
  logo_url?: string | null;
  primary_color?: string | null;
  secondary_color?: string | null;
  theme_json?: Record<string, string>;
};

export type BrandingResponse = {
  display_name: string;
  logo_url: string;
  theme: Record<string, string>;
};

export type PlatformBranding = {
  brand_name: string;
  logo_url: string;
  favicon_url: string;
  primary_color: string;
  background_color: string;
  background_gradient: string;
  text_color: string;
  font_family: string;
  button_radius_px: number;
};

export type PlatformBrandingPayload = Partial<PlatformBranding>;

export type AppBrandingOverride = {
  app_id: string;
  display_name: string;
  logo_url: string;
  primary_color: string;
  background_color: string;
  background_gradient: string;
  text_color: string;
  font_family: string;
  button_radius_px?: number | null;
};

export type AppBrandingOverridePayload = Partial<AppBrandingOverride>;

export type BrandingTokens = {
  appKey: string;
  brandName: string;
  logoUrl: string;
  faviconUrl: string;
  colors: {
    primary: string;
    text: string;
    mutedText: string;
    bg: string;
    surface: string;
    border: string;
  };
  radii: {
    button: number;
    card: number;
  };
  fonts: {
    ui: string;
  };
  spacing: {
    pageMaxWidth: number;
    gutter: number;
  };
  shadows: {
    card: string;
  };
};

export type Device = {
  id: string;
  tenant_id: string;
  name: string;
  device_type: string;
  mgmt_ip?: string | null;
  status: string;
  tags?: Record<string, unknown> | null;
  metadata_json?: Record<string, unknown> | null;
};

export type DeviceListResponse = { devices: Device[] };

export type DevicePayload = {
  name?: string;
  device_type?: string;
  mgmt_ip?: string | null;
  status?: string;
  tags?: Record<string, unknown> | null;
  metadata_json?: Record<string, unknown> | null;
};

export type GovernedActionStatus =
  | "draft"
  | "pending_verification"
  | "pending_ratification"
  | "executing"
  | "succeeded"
  | "failed"
  | "canceled";

export type DraftAction = {
  id: string;
  tenant_id: string;
  device_id?: string | null;
  instance_ref?: string | null;
  action_type: string;
  action_class: string;
  params_json: Record<string, unknown>;
  status: GovernedActionStatus;
  requested_by?: string | null;
  custodian_id?: string | null;
  last_error_code?: string;
  last_error_message?: string;
  provenance_json?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
};

export type ActionEvent = {
  id: string;
  event_type: string;
  from_status?: string;
  to_status?: string;
  actor_id?: string | null;
  payload_json?: Record<string, unknown>;
  created_at?: string;
};

export type ActionEvidence = {
  id: string;
  verifier_type: string;
  status: "required" | "satisfied" | "failed";
  evidence_json?: Record<string, unknown>;
  created_at?: string;
};

export type ActionRatification = {
  id: string;
  ratified_by?: string | null;
  ratified_at?: string;
  method: string;
  notes?: string;
};

export type ExecutionReceipt = {
  id: string;
  draft_action_id: string;
  executed_at?: string;
  executed_by?: string | null;
  adapter_key?: string;
  request_payload_redacted_json?: Record<string, unknown>;
  response_redacted_json?: Record<string, unknown>;
  outcome: "success" | "failure";
  error_code?: string;
  error_message?: string;
  logs_ref?: string;
};

export type ReleaseSummary = {
  id: string;
  version: string;
  status: string;
  build_state?: string;
  blueprint_id?: string | null;
  release_plan_id?: string | null;
  created_from_run_id?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type ReleaseDetail = ReleaseSummary & {
  artifacts_json?: Record<string, unknown> | Array<{ name: string; url: string }> | null;
};

export type ReleaseCreatePayload = {
  version: string;
  status?: string;
  build_state?: string;
  blueprint_id?: string | null;
  release_plan_id?: string | null;
  created_from_run_id?: string | null;
  artifacts_json?: Record<string, unknown> | Array<{ name: string; url: string }>;
};

export type ReleaseListResponse = PaginatedResponse<ReleaseSummary, "releases">;

export type EnvironmentSummary = {
  id: string;
  name: string;
  slug: string;
  base_domain?: string | null;
  aws_region?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type EnvironmentListResponse = PaginatedResponse<EnvironmentSummary, "environments">;

export type EnvironmentCreatePayload = {
  name?: string;
  slug?: string;
  base_domain?: string;
  aws_region?: string;
};

export type SecretRef = {
  type: string;
  ref: string;
  version?: string | null;
};

export type SecretStore = {
  id: string;
  name: string;
  kind: "aws_secrets_manager";
  is_default: boolean;
  config_json: {
    aws_region?: string;
    name_prefix?: string;
    kms_key_id?: string | null;
    tags?: Record<string, string>;
  };
  created_at?: string;
  updated_at?: string;
};

export type SecretStoreListResponse = {
  secret_stores: SecretStore[];
};

export type SecretRefMetadata = {
  id: string;
  name: string;
  scope_kind: "platform" | "tenant" | "user" | "team";
  scope_id?: string | null;
  store_id: string;
  store_name?: string;
  external_ref: string;
  type: string;
  version?: string | null;
  description?: string;
  metadata_json?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
};

export type SecretRefListResponse = {
  secret_refs: SecretRefMetadata[];
};

export type IdentityProvider = {
  id: string;
  display_name: string;
  enabled: boolean;
  issuer: string;
  discovery?: {
    mode?: string;
    jwksUri?: string | null;
    authorizationEndpoint?: string | null;
    tokenEndpoint?: string | null;
    userinfoEndpoint?: string | null;
  };
  client: {
    client_id: string;
    client_secret_ref?: SecretRef | null;
    client_secret_value?: string;
    store_id?: string | null;
  };
  scopes?: string[];
  pkce?: boolean;
  prompt?: string | null;
  domain_rules?: {
    allowedEmailDomains?: string[];
    allowedHostedDomain?: string | null;
  };
  claims?: Record<string, string>;
  audience_rules?: {
    acceptAudiences?: string[];
    acceptAzp?: boolean;
  };
  fallback_default_role_id?: string | null;
  require_group_match?: boolean;
  group_claim_path?: string;
  group_role_mappings?: Array<{
    remote_group_name: string;
    xyn_role_id: string;
  }>;
  last_discovery_refresh_at?: string;
};

export type IdentityProviderListResponse = { identity_providers: IdentityProvider[] };

export type IdentityProviderPayload = IdentityProvider;

export type WorkspaceSummary = {
  id: string;
  slug: string;
  name: string;
  org_name?: string;
  kind?: string;
  lifecycle_stage?: "lead" | "prospect" | "customer" | "churned" | "internal" | string;
  auth_mode?: "local" | "oidc" | "mixed" | string;
  oidc_config_ref?: string;
  oidc_enabled?: boolean;
  oidc_issuer_url?: string;
  oidc_client_id?: string;
  oidc_client_secret_ref_id?: string | null;
  oidc_scopes?: string;
  oidc_claim_email?: string;
  oidc_allow_auto_provision?: boolean;
  oidc_allowed_email_domains?: string[];
  tenant_auth_status?: {
    sso: "ready" | "not_configured" | string;
    local_login: "enabled" | "disabled" | string;
  };
  parent_workspace_id?: string | null;
  metadata?: Record<string, unknown>;
  description?: string;
  status?: "active" | "deprecated";
  role: "reader" | "contributor" | "publisher" | "moderator" | "admin";
  termination_authority?: boolean;
};

export type WorkspaceListResponse = {
  workspaces: WorkspaceSummary[];
};

export type ArtifactManifestSurfaceEntry = {
  label: string;
  path: string;
  order?: number;
  icon?: string;
  group?: string;
};

export type ArtifactCapability = {
  visibility: "capabilities" | "platform" | "hidden" | string;
  label?: string;
  description?: string;
  category?: "application" | "integration" | "platform" | "library" | string;
  order?: number;
  icon?: string;
  tags?: string[];
  permission?: {
    resource: string;
    action: string;
  };
};

export type ArtifactSuggestion = {
  id: string;
  name?: string;
  prompt: string;
  description?: string;
  visibility?: Array<"landing" | "capability" | "palette" | "hidden" | string>;
  order?: number;
  group?: string;
  capability_ref?: string;
  permission?: {
    resource: string;
    action: string;
  };
  ui?: {
    icon?: string;
    badge?: string;
  };
};

export type ArtifactManifestSummary = {
  roles: string[];
  ui_mount_scope?: "global" | "workspace" | string;
  capability?: ArtifactCapability;
  suggestions?: ArtifactSuggestion[];
  surfaces: {
    nav: ArtifactManifestSurfaceEntry[];
    manage: ArtifactManifestSurfaceEntry[];
    docs: ArtifactManifestSurfaceEntry[];
  };
};

export type WorkspaceInstalledArtifactSummary = {
  binding_id: string;
  artifact_id: string;
  name: string;
  title: string;
  kind?: string | null;
  description?: string | null;
  enabled: boolean;
  installed_state: string;
  version?: number;
  slug?: string;
  manifest_summary?: ArtifactManifestSummary;
  capability?: ArtifactCapability;
  suggestions?: ArtifactSuggestion[];
  updated_at?: string;
};

export type CatalogArtifactSummary = {
  id: string;
  slug: string;
  title: string;
  kind?: string | null;
  description?: string | null;
  version?: number | string | null;
  updated_at?: string;
  manifest_summary: ArtifactManifestSummary;
  capability?: ArtifactCapability;
  suggestions?: ArtifactSuggestion[];
};

export type ArtifactSummary = {
  id: string;
  workspace_id: string;
  type: string;
  title: string;
  slug: string;
  status: "draft" | "reviewed" | "ratified" | "published" | "deprecated";
  version: number;
  visibility: "private" | "team" | "public";
  published_at?: string | null;
  updated_at?: string;
  content?: {
    summary?: string;
    tags?: string[];
  };
};

export type ArtifactDetail = ArtifactSummary & {
  content: {
    title?: string;
    summary?: string;
    body_markdown?: string;
    body_html?: string;
    tags?: string[];
  };
  provenance_json?: Record<string, unknown>;
  scope_json?: Record<string, unknown>;
  reactions?: {
    endorse: number;
    oppose: number;
    neutral: number;
  };
  comments?: Array<{
    id: string;
    user_id?: string | null;
    parent_comment_id?: string | null;
    body: string;
    status: "visible" | "hidden" | "deleted";
    created_at?: string;
  }>;
};

export type UnifiedArtifactType =
  | "draft_session"
  | "blueprint"
  | "article"
  | "workflow"
  | "module"
  | "context_pack"
  | "app_shell"
  | "auth_login"
  | "data_model"
  | "ui_view"
  | "integration";
export type UnifiedArtifactState = "provisional" | "canonical" | "immutable" | "deprecated";

export type ArtifactSurface = {
  id: string;
  artifact_id: string;
  key: string;
  title: string;
  description?: string;
  surface_kind: "config" | "editor" | "dashboard" | "visualizer" | "docs" | string;
  route: string;
  nav_visibility: "hidden" | "contextual" | "always" | string;
  nav_label?: string;
  nav_icon?: string;
  nav_group?: string;
  renderer?: Record<string, unknown>;
  context?: Record<string, unknown>;
  permissions?: Record<string, unknown>;
  sort_order?: number;
  ui_mount_scope?: "global" | "workspace" | string;
  created_at?: string;
  updated_at?: string;
};

export type ArtifactRuntimeRole = {
  id: string;
  artifact_id: string;
  role_kind: "route_provider" | "job" | "event_handler" | "integration" | "auth" | "data_model" | string;
  spec?: Record<string, unknown>;
  enabled?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type UnifiedArtifact = {
  id: string;
  artifact_id: string;
  artifact_type: UnifiedArtifactType | string;
  artifact_state: UnifiedArtifactState | string;
  title: string;
  summary?: string;
  status?: string;
  package_version?: string;
  schema_version?: string;
  content_hash?: string;
  dependencies?: Array<Record<string, unknown>>;
  bindings?: Array<Record<string, unknown>>;
  content_ref?: Record<string, unknown>;
  validation_status?: "pass" | "fail" | "warning" | "unknown" | string;
  validation_errors?: string[];
  owner?: {
    id: string;
    email?: string;
    display_name?: string;
  } | null;
  created_via?: string;
  last_touched_by_agent?: string | null;
  source_ref_type?: string;
  source_ref_id?: string;
  family_id?: string;
  parent_artifact_id?: string | null;
  lineage_root_id?: string | null;
  tags?: string[];
  surfaces?: ArtifactSurface[];
  runtime_roles?: ArtifactRuntimeRole[];
  created_at?: string;
  updated_at?: string;
  source?: Record<string, unknown>;
};

export type UnifiedArtifactListResponse = {
  artifacts: UnifiedArtifact[];
  count: number;
  limit: number;
  offset: number;
};

export type ArtifactSurfaceResolveResponse = {
  surface: ArtifactSurface;
  artifact: UnifiedArtifact;
  params: Record<string, string>;
};

export type ArtifactBinding = {
  id: string;
  name: string;
  type: "string" | "secret_ref" | "model_ref" | "url" | "json";
  value?: unknown;
  description?: string;
  secret_ref_id?: string | null;
  updated_at?: string;
};

export type ArtifactPackageRecord = {
  id: string;
  name: string;
  version: string;
  package_hash: string;
  created_at?: string;
  artifact_count?: number;
  manifest?: Record<string, unknown>;
};

export type ArtifactPackageValidationResult = {
  valid: boolean;
  errors: string[];
  package?: {
    name: string;
    version: string;
    format_version: number;
  };
  dependency_plan?: Array<{ type: string; slug: string; version: string }>;
  required_bindings?: Array<Record<string, unknown>>;
  resolved_bindings?: Record<string, unknown>;
  planned_changes?: Array<{
    type: string;
    slug: string;
    from_version?: string | null;
    to_version: string;
    action: "install" | "upgrade" | "reinstall";
  }>;
};

export type ArtifactInstallReceipt = {
  id: string;
  package_name: string;
  package_version: string;
  package_hash: string;
  installed_at?: string;
  installed_by?: string | null;
  install_mode: "install" | "upgrade" | "reinstall";
  resolved_bindings?: Record<string, unknown>;
  operations?: Array<Record<string, unknown>>;
  status: "success" | "failed" | "partial";
  error_summary?: string;
  artifact_changes?: Array<{
    artifact_id: string;
    type: string;
    slug: string;
    from_version?: string | null;
    to_version?: string | null;
    action: string;
  }>;
};

export type RawFileEntry = {
  name: string;
  path: string;
  kind: "file" | "dir";
  size_bytes?: number | null;
  mime_guess?: string | null;
  sha256_optional?: string | null;
};

export type ArtifactRawMetadataResponse = {
  artifact: {
    id: string;
    type: string;
    slug: string;
    version: string;
    title: string;
    artifact_state: string;
    status: string;
  };
  artifact_hash?: string;
  content_ref?: Record<string, unknown>;
  dependencies?: Array<Record<string, unknown>>;
  bindings?: Array<Record<string, unknown>>;
  surfaces?: ArtifactSurface[];
  runtime_roles?: ArtifactRuntimeRole[];
  files_root?: { name: string; path: string; kind: "dir" };
};

export type RawFilesListResponse = {
  path: string;
  entries: RawFileEntry[];
};

export type RawFilePreviewResponse = {
  path: string;
  kind: "file";
  size_bytes: number;
  mime_guess: string;
  inline: boolean;
  content?: string;
  download_url?: string;
};

export type LedgerEventSummary = {
  ledger_event_id: string;
  created_at?: string;
  actor_user_id?: string;
  action: string;
  summary?: string;
  artifact_id: string;
  artifact_title?: string;
  artifact_slug?: string;
  artifact_workspace_id?: string;
  artifact_type?: string;
  artifact_state?: string;
  source_ref_type?: string;
  source_ref_id?: string;
  actor?: {
    id: string;
    email?: string;
    display_name?: string;
  } | null;
  metadata_json?: Record<string, unknown>;
};

export type LedgerSummaryByUserRow = {
  actor_user_id: string;
  email?: string;
  display_name?: string;
  create_count: number;
  update_count: number;
  publish_count: number;
  canonize_count: number;
  deprecate_count: number;
  archive_count: number;
  total_count: number;
  top_artifacts: Array<{
    artifact_id: string;
    title: string;
    count: number;
  }>;
};

export type ArticleVisibilityType = "public" | "authenticated" | "role_based" | "private";
export type ArticleCategory = "web" | "guide" | "core-concepts" | "release-note" | "internal" | "tutorial";
export type ArticleFormat = "standard" | "video_explainer";

export type VideoSpecScene = {
  id: string;
  title?: string;
  name: string;
  duration_seconds: number;
  voiceover?: string;
  narration: string;
  visual_prompt: string;
  on_screen?: string;
  on_screen_text: string;
  camera_motion: string;
  style_constraints: string[];
  generated?: {
    image_asset_url?: string | null;
    video_clip_url?: string | null;
  };
};

export type VideoSpec = {
  version: number;
  title: string;
  intent: string;
  audience: string;
  tone: string;
  duration_seconds_target: number;
  voice: {
    style: string;
    speaker: string;
    pace: string;
  };
  script: {
    draft: string;
    last_generated_at?: string | null;
    notes?: string;
    proposals?: Array<{
      id: string;
      text: string;
      created_at: string;
      model?: string;
      provider?: string;
      agent_slug?: string;
    }>;
  };
  storyboard: {
    draft: Array<{
      scene: number;
      time_range: string;
      on_screen_text: string;
      visual_description: string;
      motion: string;
      assets?: Array<{ type: string; value: string }>;
      narration: string;
    }>;
    last_generated_at?: string | null;
    notes?: string;
    proposals?: Array<{
      id: string;
      storyboard_draft: Array<Record<string, unknown>>;
      scenes: VideoSpecScene[];
      created_at: string;
      model?: string;
      provider?: string;
      agent_slug?: string;
    }>;
  };
  scenes: VideoSpecScene[];
  generation: {
    provider?: string | null;
    status: "not_started" | "queued" | "running" | "succeeded" | "failed" | "filtered" | "canceled";
    last_render_id?: string | null;
    updated_at?: string;
  };
};

export type VideoRender = {
  id: string;
  article_id: string;
  provider: string;
  model_name?: string;
  status: "queued" | "running" | "succeeded" | "failed" | "filtered" | "canceled";
  outcome?: "success" | "failed" | "filtered" | "canceled" | "timeout" | string;
  requested_at?: string;
  started_at?: string | null;
  completed_at?: string | null;
  request_payload_json?: Record<string, unknown>;
  result_payload_json?: Record<string, unknown>;
  output_assets?: Array<{
    type: string;
    url: string;
    metadata?: Record<string, unknown>;
  }>;
  context_pack_id?: string | null;
  context_pack_name?: string | null;
  context_pack_version?: string;
  context_pack_updated_at?: string | null;
  context_pack_hash?: string;
  spec_snapshot_hash?: string;
  input_snapshot_hash?: string;
  provider_operation_name?: string;
  provider_operation_id?: string;
  provider_filtered_count?: number | null;
  provider_filtered_reasons?: string[];
  provider_error_code?: string;
  provider_error_message?: string;
  provider_response_excerpt?: Record<string, unknown>;
  last_provider_status_at?: string | null;
  export_package_generated?: boolean;
  error_message?: string;
  error_details_json?: Record<string, unknown>;
  user_message?: string;
  user_actions?: string[];
};

export type ArticleSummary = {
  id: string;
  workspace_id: string;
  type: "article";
  format: ArticleFormat;
  video_context_pack_id?: string | null;
  title: string;
  slug: string;
  status: "draft" | "reviewed" | "ratified" | "published" | "deprecated";
  version: number;
  published_at?: string | null;
  updated_at?: string;
  category: ArticleCategory;
  visibility_type: ArticleVisibilityType;
  allowed_roles: string[];
  route_bindings: string[];
  tags: string[];
  summary?: string;
  cover_image_url?: string;
  canonical_url?: string;
  category_id?: string | null;
  category_name?: string;
};

export type ArticleDetail = ArticleSummary & {
  body_markdown: string;
  body_html?: string;
  video_spec_json?: VideoSpec | null;
  video_ai_config_json?: {
    agents?: Record<string, string>;
    context_packs?: Record<string, unknown>;
  } | null;
  video_context_pack_id?: string | null;
  video_context_pack?: {
    id: string;
    name: string;
    purpose: string;
    scope: string;
    version: string;
    updated_at?: string | null;
    content_hash?: string;
  } | null;
  video_latest_render_id?: string | null;
  category_ref?: {
    id: string | null;
    slug: string;
    name: string;
    enabled: boolean;
  };
  published_to?: Array<{
    label: string;
    target_type: "xyn_ui_route" | "public_web_path" | "external_url";
    target_value: string;
    source: "category" | "article";
  }>;
  provenance_json?: Record<string, unknown>;
  license_json?: Record<string, unknown>;
  reactions?: {
    endorse: number;
    oppose: number;
    neutral: number;
  };
  comments?: Array<{
    id: string;
    user_id?: string | null;
    parent_comment_id?: string | null;
    body: string;
    status: "visible" | "hidden" | "deleted";
    created_at?: string;
  }>;
  created_at?: string;
  created_by?: string | null;
  updated_by?: string | null;
  updated_by_email?: string | null;
};

export type ArticleRevision = {
  id: string;
  article_id: string;
  revision_number: number;
  body_markdown: string;
  body_html?: string;
  summary?: string;
  created_by?: string | null;
  created_by_email?: string | null;
  created_at?: string;
  provenance_json?: Record<string, unknown>;
};

export type ArticleCategoryRecord = {
  id: string;
  slug: string;
  name: string;
  description?: string;
  enabled: boolean;
  referenced_article_count?: number;
  created_at?: string;
  updated_at?: string;
  references?: {
    articles: number;
  };
};

export type PublishBindingRecord = {
  id: string;
  label: string;
  target_type: "xyn_ui_route" | "public_web_path" | "external_url";
  target_value: string;
  enabled: boolean;
  source: "category" | "article";
  created_at?: string;
  updated_at?: string;
};

export type DocPage = {
  id: string;
  artifact_id: string;
  workspace_id: string;
  type: string;
  title: string;
  slug: string;
  status: "draft" | "published" | "deprecated";
  visibility: "private" | "team" | "public";
  route_bindings: string[];
  tags: string[];
  body_markdown: string;
  summary?: string;
  version: number;
  created_at?: string;
  updated_at?: string;
  published_at?: string | null;
  created_by?: string | null;
  updated_by?: string | null;
  updated_by_email?: string | null;
};

export type WorkflowProfile = "tour";

export type WorkflowSummary = {
  id: string;
  artifact_id?: string;
  workspace_id: string;
  type: "workflow";
  format: "workflow";
  profile: WorkflowProfile;
  title: string;
  slug: string;
  description?: string;
  status: "draft" | "reviewed" | "ratified" | "published" | "deprecated";
  version: number;
  visibility_type: "public" | "authenticated" | "role_based" | "private";
  allowed_roles: string[];
  category: string;
  category_name?: string;
  category_id?: string | null;
  updated_at?: string;
  published_at?: string | null;
};

export type WorkflowStepCheck = {
  id: string;
  kind: "entity_exists" | "field_nonempty" | "route_is" | "custom";
  params?: Record<string, unknown>;
};

export type WorkflowStep = {
  id: string;
  type: "callout" | "modal" | "check" | "action" | "copy";
  title: string;
  body_md: string;
  route?: string;
  anchor?: {
    selector?: string;
    test_id?: string;
    anchor_id?: string;
    placement?: "top" | "right" | "bottom" | "left";
  };
  gating?: {
    requires?: WorkflowStepCheck[];
  };
  next?: {
    on_success?: string;
    on_failure?: string;
  };
  ui?: {
    highlight?: boolean;
    block_interaction?: boolean;
    allow_back?: boolean;
  };
  clipboard_text?: string;
  toast_on_copy?: string;
  action_id?: string;
  params?: Record<string, unknown>;
  idempotency_key_template?: string;
  success_toast?: string;
};

export type WorkflowSpec = {
  profile: WorkflowProfile;
  schema_version: number;
  title: string;
  description?: string;
  category_slug: string;
  entry?: { route?: string };
  settings?: {
    allow_skip?: boolean;
    show_progress?: boolean;
  };
  steps: WorkflowStep[];
};

export type WorkflowDetail = WorkflowSummary & {
  workflow_profile: WorkflowProfile;
  workflow_spec_json: WorkflowSpec;
  workflow_state_schema_version?: number | null;
  created_at?: string;
  created_by?: string | null;
};

export type WorkflowListResponse = { workflows: WorkflowSummary[] };
export type WorkflowDetailResponse = { workflow: WorkflowDetail };
export type WorkflowCreatePayload = {
  workspace_id: string;
  title: string;
  slug?: string;
  profile?: WorkflowProfile;
  category_slug?: string;
  visibility_type?: "public" | "authenticated" | "role_based" | "private";
  allowed_roles?: string[];
  tags?: string[];
  workflow_spec_json?: WorkflowSpec;
};

export type WorkflowActionCatalogItem = {
  action_id: string;
  name: string;
  description: string;
  params_schema_json: Record<string, unknown>;
  required_permissions: string[];
  supports_dry_run: boolean;
  idempotent: boolean;
};

export type WorkflowActionCatalogResponse = { actions: WorkflowActionCatalogItem[] };
export type WorkflowActionExecuteResponse = {
  ok: boolean;
  dry_run?: boolean;
  action_id: string;
  idempotency_key: string;
  result?: Record<string, unknown>;
};

export type WorkflowRun = {
  id: string;
  workflow_id: string;
  user_id?: string | null;
  status: "running" | "completed" | "failed" | "aborted";
  started_at?: string;
  completed_at?: string | null;
  metadata_json?: Record<string, unknown>;
};

export type IntentScriptScene = {
  id: string;
  title: string;
  duration_hint?: string;
  voiceover?: string;
  on_screen?: string;
  ui_route?: string;
  highlights?: string[];
  assets?: unknown[];
  notes?: string;
};

export type IntentScript = {
  intent_script_id: string;
  title: string;
  scope_type: "tour" | "artifact" | "manual";
  scope_ref_id: string;
  format_version: string;
  script_json: {
    scenes?: IntentScriptScene[];
    metadata?: Record<string, unknown>;
  };
  script_text: string;
  created_by?: string | null;
  created_at?: string;
  updated_at?: string;
  status: "draft" | "final";
  artifact_id?: string | null;
};

export type TourDefinition = {
  workflow_id: string;
  slug: string;
  title: string;
  description?: string;
  schema_version: number;
  profile: "tour";
  category_slug: string;
  settings?: {
    allow_skip?: boolean;
    show_progress?: boolean;
  };
  entry?: { route?: string };
  steps: WorkflowStep[];
};

export type AiPurpose = {
  slug: string;
  name?: string;
  description?: string;
  status: "active" | "deprecated";
  enabled?: boolean;
  preamble: string;
  system_prompt?: string;
  system_prompt_markdown?: string;
  referenced_by?: {
    agents: number;
  };
  updated_at?: string;
  model_config?: {
    id: string;
    provider: "openai" | "anthropic" | "google";
    model_name: string;
    temperature: number;
    max_tokens: number;
    top_p?: number;
    frequency_penalty?: number;
    presence_penalty?: number;
    extra_json?: Record<string, unknown>;
  } | null;
};

export type AiProvider = {
  id: string;
  slug: "openai" | "anthropic" | "google";
  name: string;
  enabled: boolean;
};

export type AiCredential = {
  id: string;
  provider: "openai" | "anthropic" | "google";
  provider_id: string;
  name: string;
  auth_type: "api_key" | "env_ref";
  secret_ref_id?: string | null;
  env_var_name?: string;
  is_default: boolean;
  enabled: boolean;
  secret?: {
    configured: boolean;
    masked?: string | null;
    last4?: string | null;
  };
  created_at?: string;
  updated_at?: string;
};

export type AiModelConfig = {
  id: string;
  provider: "openai" | "anthropic" | "google";
  provider_id: string;
  credential_id?: string | null;
  model_name: string;
  temperature?: number | null;
  max_tokens?: number | null;
  top_p?: number | null;
  frequency_penalty?: number | null;
  presence_penalty?: number | null;
  extra_json?: Record<string, unknown>;
  enabled: boolean;
  created_at?: string;
  updated_at?: string;
};

export type AiAgent = {
  id: string;
  slug: string;
  name: string;
  model_config_id: string;
  model_config?: AiModelConfig;
  override_prompt_text?: string;
  default_context_pack_refs_json?: unknown[];
  default_context_packs?: Array<{
    id: string;
    slug: string;
    name: string;
    purpose: string;
    scope: string;
    version: string;
    content_hash?: string;
    state?: "canonical" | "deprecated";
    is_active?: boolean;
  }>;
  // Backward-compatible aliases.
  system_prompt_text?: string;
  context_pack_refs_json?: unknown[];
  is_default?: boolean;
  enabled: boolean;
  purposes: string[];
  created_at?: string;
  updated_at?: string;
};

export type AiInvokeResponse = {
  content: string;
  provider: "openai" | "anthropic" | "google";
  model: string;
  usage?: Record<string, unknown> | null;
  effective_params?: Record<string, unknown>;
  warnings?: Array<{ param: string; reason: string; detail: string }>;
  agent_slug: string;
};

export type AiModelConfigCompat = {
  provider: "openai" | "anthropic" | "google";
  model_name: string;
  effective_params: Record<string, unknown>;
  warnings: Array<{ param: string; reason: string; detail: string }>;
};

export type AiBootstrapStatus = {
  provider: string;
  model: string;
  key_present: boolean;
  default_agent_id?: string | null;
  default_agent_slug?: string | null;
  default_agent_updated_at?: string | null;
};

export type AiBootstrapStatusResponse = {
  default_agent: AiBootstrapStatus;
};

export type LocalProvisionJobResult = {
  status: string;
  job_artifact_id?: string | null;
  job_run_artifact_id?: string | null;
  patch_artifact_id?: string | null;
  logs_artifact_id?: string | null;
  branch_name?: string | null;
  commit_sha?: string | null;
};

export type LocalProvisionResponse = {
  deployment_id: string;
  deployment_artifact_id: string;
  status: string;
  compose_project: string;
  compose_path: string;
  ui_url: string;
  api_url: string;
  surfaces?: Record<string, { label?: string; path?: string }>;
  job?: LocalProvisionJobResult;
};

export type ArtifactEventSummary = {
  id: string;
  artifact_id: string;
  artifact_title: string;
  event_type: string;
  actor_id?: string | null;
  payload_json?: Record<string, unknown>;
  created_at?: string;
};

export type VideoAiConfigEntry = {
  purpose_slug: string;
  purpose_name: string;
  description: string;
  agent: {
    id: string;
    slug: string;
    name: string;
    model_provider?: string | null;
    model_name?: string | null;
  } | null;
  context_packs: Array<{
    id: string;
    name: string;
    purpose: string;
    scope: string;
    version: string;
    updated_at?: string | null;
    content_hash?: string;
  }>;
  context_pack_hash?: string;
  effective_model_config_id?: string | null;
  context_pack_override_mode?: "extend" | "replace" | string;
  effective_context_pack_refs?: Array<{
    id: string;
    name: string;
    purpose?: string;
    scope?: string;
    version?: string;
    content_hash?: string;
    source?: "agent_default" | "override" | string;
  }>;
  source?: string;
  agent_source?: string;
  context_source?: string;
  warning?: string | null;
};

export type AiActivityEntry = {
  id: string;
  event_type: string;
  status: "running" | "succeeded" | "failed";
  summary?: string;
  created_at?: string;
  actor_id?: string | null;
  agent_slug?: string;
  provider?: "openai" | "anthropic" | "google" | string;
  model_name?: string;
  artifact_id?: string;
  artifact_type?: string;
  artifact_title?: string;
  source?: "audit_log" | "artifact_event";
};

export type WorkspaceMembershipSummary = {
  id: string;
  workspace_id: string;
  user_identity_id: string;
  email?: string;
  display_name?: string;
  auth_source?: string;
  auth_source_label?: string;
  auth_provider?: string;
  auth_provider_id?: string;
  auth_issuer?: string;
  role: "admin" | "member";
  termination_authority: boolean;
  created_at?: string;
};

export type WorkspaceAuthPolicy = {
  workspace_id: string;
  auth_mode: "local" | "oidc" | "mixed" | string;
  oidc_enabled: boolean;
  oidc_issuer_url: string;
  oidc_client_id: string;
  oidc_client_secret_ref_id?: string | null;
  oidc_scopes: string;
  oidc_claim_email: string;
  oidc_allow_auto_provision: boolean;
  oidc_allowed_email_domains: string[];
};

export type OidcAppClient = {
  id: string;
  app_id: string;
  login_mode: string;
  default_provider_id?: string | null;
  allowed_provider_ids: string[];
  redirect_uris: string[];
  post_logout_redirect_uris?: string[];
  session?: { cookieName?: string; maxAgeSeconds?: number };
  token_validation?: { issuerStrict?: boolean; clockSkewSeconds?: number };
};

export type OidcAppClientListResponse = { oidc_app_clients: OidcAppClient[] };

export type OidcAppClientPayload = OidcAppClient;

export type RunSummary = {
  id: string;
  entity_type: string;
  entity_id: string;
  status: string;
  summary?: string;
  created_at?: string;
  started_at?: string;
  finished_at?: string;
};

export type ContextPackRef = {
  id?: string;
  name?: string;
  purpose?: string;
  scope?: string;
  version?: string;
  content_hash?: string;
};

export type RunDetail = RunSummary & {
  error?: string;
  log_text?: string;
  metadata?: Record<string, unknown> | null;
  context_pack_refs?: Array<string | ContextPackRef> | null;
};

export type RunListResponse = PaginatedResponse<RunSummary, "runs">;

export type RunLogResponse = {
  log?: string;
  error?: string;
};

export type RunArtifact = {
  id: string;
  name: string;
  kind?: string;
  url?: string;
  metadata?: Record<string, unknown>;
  created_at?: string;
};

export type RunCommandExecution = {
  id: string;
  step_name?: string;
  command_index?: number;
  shell?: string;
  status?: string;
  exit_code?: number | null;
  started_at?: string | null;
  finished_at?: string | null;
  ssm_command_id?: string | null;
  stdout?: string;
  stderr?: string;
};

export type DevTaskSummary = {
  id: string;
  title: string;
  task_type: string;
  status: string;
  priority: number;
  attempts: number;
  max_attempts: number;
  locked_by?: string | null;
  locked_at?: string | null;
  source_entity_type?: string;
  source_entity_id?: string;
  source_run?: string | null;
  result_run?: string | null;
  context_purpose?: string;
  target_instance_id?: string | null;
  force?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type DevTaskDetail = DevTaskSummary & {
  input_artifact_key?: string;
  last_error?: string;
  context_packs?: Array<{
    id: string;
    name: string;
    purpose: string;
    scope: string;
    version: string;
  }>;
  result_run_detail?: {
    id: string;
    status?: string;
    summary?: string;
    error?: string;
    log_text?: string;
    started_at?: string | null;
    finished_at?: string | null;
  } | null;
  result_run_artifacts?: Array<{
    id: string;
    name: string;
    kind?: string;
    url?: string;
    metadata?: Record<string, unknown> | null;
    created_at?: string;
  }>;
  result_run_commands?: RunCommandExecution[];
  force?: boolean;
};

export type DevTaskListResponse = PaginatedResponse<DevTaskSummary, "dev_tasks">;

export type DevTaskCreatePayload = {
  title: string;
  task_type: string;
  status?: string;
  priority?: number;
  max_attempts?: number;
  source_entity_type?: string;
  source_entity_id?: string;
  source_run_id?: string | null;
  input_artifact_key?: string;
  context_purpose?: string;
  target_instance_id?: string | null;
  context_pack_ids?: string[];
  force?: boolean;
  release_id?: string | null;
};

export type ContextPackSummary = {
  id: string;
  artifact_id?: string;
  name: string;
  purpose: string;
  scope: string;
  namespace?: string;
  project_key?: string;
  version: string;
  is_active: boolean;
  is_default: boolean;
  applies_to_json?: Record<string, unknown>;
  updated_at?: string;
};

export type ContextPackDetail = ContextPackSummary & {
  content_markdown?: string;
};

export type ContextPackListResponse = {
  context_packs: ContextPackSummary[];
};

export type ContextPackCreatePayload = {
  name: string;
  purpose?: string;
  scope?: string;
  namespace?: string;
  project_key?: string;
  version: string;
  is_active?: boolean;
  is_default?: boolean;
  content_markdown: string;
  applies_to_json?: Record<string, unknown>;
};

export type SeedPackItemStatus = {
  id: string;
  entity_type: string;
  entity_slug: string;
  status: "missing" | "matches" | "drifted" | "skipped";
  content_hash: string;
  entity_unique_key_json?: Record<string, unknown>;
};

export type SeedPackStatus = {
  slug: string;
  name: string;
  description: string;
  version: string;
  scope: "core" | "optional";
  namespace?: string;
  last_applied?: string | null;
  last_status?: "succeeded" | "failed" | null;
  last_summary?: Record<string, number> | null;
  item_count: number;
  missing_count: number;
  matches_count: number;
  drifted_count: number;
  skipped_count: number;
  items?: SeedPackItemStatus[];
};

export type SeedPackListResponse = {
  packs: SeedPackStatus[];
};

export type SeedPackDetailResponse = {
  pack: SeedPackStatus;
};

export type SeedApplyResult = {
  pack_slug: string;
  pack_version: string;
  dry_run: boolean;
  created: number;
  updated: number;
  unchanged: number;
  skipped: number;
  failed: number;
  application_id?: string | null;
  items: Array<{
    seed_item_id: string;
    entity_type: string;
    entity_slug: string;
    action: "created" | "updated" | "unchanged" | "skipped" | "failed";
    target_entity_id?: string | null;
    message?: string;
  }>;
};

export type SeedApplyResponse = {
  pack_count: number;
  dry_run: boolean;
  summary: {
    created: number;
    updated: number;
    unchanged: number;
    skipped: number;
    failed: number;
  };
  results: SeedApplyResult[];
};

export type ControlPlaneAppRegistryItem = {
  app_id: string;
  display_name: string;
  category: string;
  default_health_checks: string[];
};

export type ControlPlaneStateItem = {
  environment_id: string;
  environment_name: string;
  app_id: string;
  display_name: string;
  category: string;
  current_release_id?: string | null;
  current_release_version?: string | null;
  last_good_release_id?: string | null;
  last_good_release_version?: string | null;
  last_deploy_run_id?: string | null;
  last_deployed_at?: string | null;
  last_good_at?: string | null;
  last_deployment_id?: string | null;
  last_deployment_status?: string | null;
  last_deployment_error?: string | null;
};

export type ControlPlaneReleaseOption = {
  id: string;
  app_id: string;
  version: string;
  release_plan_id?: string | null;
};

export type ControlPlaneStateResponse = {
  app_registry: ControlPlaneAppRegistryItem[];
  states: ControlPlaneStateItem[];
  releases: ControlPlaneReleaseOption[];
  instances: Array<{ id: string; name: string; environment_id?: string | null; status?: string | null }>;
};

export type XynMapNodeKind = "blueprint" | "release_plan" | "release" | "release_target" | "instance" | "run";

export type XynMapNode = {
  id: string;
  kind: XynMapNodeKind;
  ref: { id: string; kind: string };
  label: string;
  status: "ok" | "warn" | "error" | "unknown";
  badges: string[];
  metrics: Record<string, unknown>;
  links: Record<string, string>;
};

export type XynMapEdge = {
  id: string;
  from: string;
  to: string;
  kind: string;
};

export type XynMapResponse = {
  meta: {
    generated_at: string;
    filters: {
      blueprint_id?: string | null;
      environment_id?: string | null;
      tenant_id?: string | null;
      include_runs: boolean;
      include_instances: boolean;
    };
    options?: {
      blueprints?: Array<{ id: string; label: string }>;
      environments?: Array<{ id: string; name: string }>;
      tenants?: Array<{ id: string; name: string }>;
    };
  };
  nodes: XynMapNode[];
  edges: XynMapEdge[];
  suggested_layout?: string;
};

export type ReportPriority = "p0" | "p1" | "p2" | "p3";
export type ReportType = "bug" | "feature";

export type ReportContext = {
  url?: string;
  route?: string;
  build?: { version?: string; commit?: string };
  user?: { id?: string; email?: string };
  blueprint_ids?: string[];
  release_ids?: string[];
  instance_ids?: string[];
  client?: { user_agent?: string; viewport?: { w?: number; h?: number } };
  occurred_at_iso?: string;
  [key: string]: unknown;
};

export type ReportAttachmentMetadata = {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  storage: {
    provider: "s3" | "local";
    bucket?: string;
    key?: string;
    url_expires_at?: string;
  };
  created_at_iso?: string;
};

export type ReportPayload = {
  type: ReportType;
  title: string;
  description: string;
  priority?: ReportPriority;
  tags?: string[];
  context?: ReportContext;
};

export type ReportRecord = {
  id: string;
  type: ReportType;
  title: string;
  description: string;
  priority: ReportPriority;
  tags: string[];
  context?: ReportContext;
  attachments: ReportAttachmentMetadata[];
  created_at_iso?: string;
  created_by?: { id?: string; email?: string };
};

export type PlatformConfig = {
  storage: {
    primary: { type: "s3" | "local"; name: string };
    providers: Array<{
      name: string;
      type: "s3" | "local";
      s3?: {
        bucket?: string;
        region?: string;
        prefix?: string;
        acl?: string;
        kms_key_id?: string | null;
        use_presigned_put?: boolean;
        public_base_url?: string;
      };
      local?: { base_path?: string };
    }>;
  };
  notifications: {
    enabled: boolean;
    channels: Array<{
      name: string;
      type: "discord" | "aws_sns";
      enabled?: boolean;
      discord?: {
        webhook_url_ref?: string;
        username?: string;
        avatar_url?: string;
      };
      aws_sns?: {
        topic_arn?: string;
        region?: string;
        subject_prefix?: string;
        message_attributes?: Record<string, string>;
      };
    }>;
  };
  video_generation?: {
    enabled?: boolean;
    provider?: "unknown" | "export_package" | "json_export" | "http" | "http_adapter" | string;
    http?: {
      endpoint_url?: string;
      timeout_seconds?: number;
    };
  };
  video?: {
    rendering_mode?: "export_package_only" | "render_via_adapter" | "render_via_endpoint" | "render_via_model_config" | string;
    endpoint_url?: string | null;
    adapter_id?: string | null;
    adapter_config_id?: string | null;
    credential_ref?: string | null;
    timeout_seconds?: number;
    retry_count?: number;
  };
};

export type PlatformConfigResponse = {
  version: number;
  config: PlatformConfig;
};

export type VideoAdapterDefinition = {
  id: string;
  name: string;
  description: string;
  config_schema_version: number;
};

export type VideoAdaptersResponse = {
  adapters: VideoAdapterDefinition[];
  feature_flags?: {
    render_via_model_config?: boolean;
  };
};

export type VideoAdapterConfigRecord = {
  artifact_id: string;
  title: string;
  slug?: string;
  artifact_state: string;
  version: number;
  content_hash?: string;
  updated_at?: string;
  adapter_id: string;
  config_json: Record<string, unknown>;
};

export type VideoAdapterConfigListResponse = {
  configs: VideoAdapterConfigRecord[];
};

export type VideoAdapterConfigDetailResponse = {
  config: VideoAdapterConfigRecord;
};

export type VideoAdapterConnectionCheck = {
  name: string;
  status: "pass" | "warning" | "fail" | string;
  message: string;
  details?: Record<string, unknown>;
};

export type VideoAdapterTestResponse = {
  ok: boolean;
  adapter_id: string;
  adapter_config_id?: string | null;
  adapter_config_slug?: string;
  adapter_config_version?: number;
  provider_model_id?: string | null;
  checked_at?: string;
  checks: VideoAdapterConnectionCheck[];
};

export type AccessPermissionDefinition = {
  key: string;
  name: string;
  description: string;
  category: string;
  tags?: string[];
  isDangerous?: boolean;
};

export type AccessRoleDefinition = {
  id: string;
  name: string;
  description?: string;
  tier?: number;
};

export type AccessRolePermission = {
  roleId: string;
  permissionKey: string;
  scope?: Record<string, unknown> | null;
  effect?: "allow" | "deny" | string;
};

export type AccessRegistryResponse = {
  permissions: AccessPermissionDefinition[];
  roles: AccessRoleDefinition[];
  rolePermissions: AccessRolePermission[];
};

export type AccessUserSummary = {
  id: string;
  name: string;
  email: string;
};

export type AccessUserRolesResponse = {
  roles: Array<{
    roleId: string;
    roleName: string;
    scope?: Record<string, unknown>;
    assignedAt?: string;
  }>;
};

export type AccessEffectivePermissionSource = {
  viaRoleId: string;
  viaRoleName: string;
  roleScope?: Record<string, unknown>;
  permScope?: Record<string, unknown>;
  mergedScope?: Record<string, unknown>;
  ruleId?: string;
};

export type AccessEffectivePermission = {
  permissionKey: string;
  scope?: Record<string, unknown>;
  effect: "allow" | "deny" | string;
  sources: AccessEffectivePermissionSource[];
};

export type AccessUserEffectiveResponse = {
  effective: AccessEffectivePermission[];
  summary: {
    totalEffective: number;
    categories: Array<{ category: string; count: number }>;
  };
};

export type AccessRoleDetailResponse = {
  role: AccessRoleDefinition;
  permissions: Array<{
    permissionKey: string;
    scope?: Record<string, unknown>;
    effect?: "allow" | "deny" | string;
  }>;
};

export type XynIntentActionType = "CreateDraft" | "ProposePatch" | "ShowOptions" | "ValidateDraft" | "ApplyPatch";
export type XynIntentStatus = "DraftReady" | "MissingFields" | "ProposedPatch" | "ValidationError" | "UnsupportedIntent";

export type XynIntentMissingField = {
  field: string;
  reason: string;
  options_available: boolean;
};

export type XynIntentPatchChange = {
  field: string;
  from?: unknown;
  to?: unknown;
};

export type XynIntentResolutionResult = {
  status: XynIntentStatus;
  action_type: XynIntentActionType;
  artifact_type: string | null;
  artifact_id: string | null;
  summary: string;
  missing_fields?: XynIntentMissingField[];
  options?: unknown[];
  proposed_patch?: {
    changes: XynIntentPatchChange[];
    patch_object: Record<string, unknown>;
    requires_confirmation: boolean;
  };
  draft_payload?: Record<string, unknown>;
  validation_errors?: string[];
  next_actions?: Array<{ label: string; action: string; field?: string; path?: string; panel_key?: string; params?: Record<string, unknown> }>;
  audit?: {
    request_id?: string;
    confidence?: number;
    llm_model?: string;
    timestamp?: string;
  };
};

export type EmsDeviceRow = {
  id: string;
  mac: string;
  serial: string;
  model: string;
  state: string;
  last_seen: string;
  created_at: string;
};

export type EmsDeviceListResponse = {
  items: EmsDeviceRow[];
};

export type EmsRegistrationsResponse = {
  hours: number;
  summary_count: number;
  points: Array<{ bucket: string; count: number }>;
  items: Array<{
    id: string;
    device_id: string;
    workspace_id: string;
    registered_at: string;
    registered_by: string;
  }>;
};

export type EmsStatusCountsResponse = {
  items: Array<{ state: string; count: number }>;
  total: number;
};

export type ArtifactStructuredFilter = {
  field: string;
  op: "eq" | "neq" | "contains" | "in" | "gte" | "lte" | "gt" | "lt";
  value: unknown;
};

export type ArtifactStructuredSort = {
  field: string;
  dir: "asc" | "desc";
};

export type ArtifactStructuredQuery = {
  entity: "artifacts";
  filters: ArtifactStructuredFilter[];
  sort: ArtifactStructuredSort[];
  limit: number;
  offset: number;
};

export type CanvasDatasetColumn = {
  key: string;
  label: string;
  type: "string" | "string[]" | "integer" | "boolean" | "datetime";
  filterable?: boolean;
  sortable?: boolean;
  searchable?: boolean;
  enum?: string[];
};

export type ArtifactCanvasTableResponse = {
  type: "canvas.table";
  title: string;
  dataset: {
    name: "artifacts";
    primary_key: "slug";
    columns: CanvasDatasetColumn[];
    rows: Array<Record<string, unknown>>;
    total_count: number;
  };
  query: ArtifactStructuredQuery;
};

export type CanvasTableColumn = {
  key: string;
  label: string;
  type: "string" | "string[]" | "integer" | "boolean" | "datetime";
  filterable?: boolean;
  sortable?: boolean;
  searchable?: boolean;
  enum?: string[];
};

export type CanvasTableQuery = {
  entity: string;
  filters: Array<{ field: string; op: string; value: unknown }>;
  sort: Array<{ field: string; dir: "asc" | "desc" }>;
  limit: number;
  offset: number;
};

export type CanvasTableResponse = {
  type: "canvas.table";
  title: string;
  dataset: {
    name: string;
    primary_key: string;
    columns: CanvasTableColumn[];
    rows: Array<Record<string, unknown>>;
    total_count: number;
  };
  query: CanvasTableQuery;
};

export type ArtifactConsoleListItem = {
  id: string;
  slug: string;
  title: string;
  kind?: string | null;
  description?: string | null;
  version?: number | string | null;
  updated_at?: string;
  namespace?: string | null;
  manifest_summary?: ArtifactManifestSummary;
};

export type ArtifactConsoleListResponse = {
  artifacts: ArtifactConsoleListItem[];
  count?: number;
  limit?: number;
  offset?: number;
};

export type ArtifactConsoleFileRow = {
  path: string;
  size_bytes: number;
  sha256: string;
  mime_guess?: string;
};

export type ArtifactConsoleDetailResponse = {
  artifact: {
    id: string;
    slug: string;
    title: string;
    kind: string;
    version: number | string;
    artifact_state?: string;
    status?: string;
    updated_at?: string;
    manifest_ref?: string | null;
  };
  manifest: Record<string, unknown>;
  manifest_summary: ArtifactManifestSummary;
  capability?: ArtifactCapability;
  suggestions?: ArtifactSuggestion[];
  raw_artifact_json: Record<string, unknown>;
  files: ArtifactConsoleFileRow[];
  surfaces: Array<Record<string, unknown>>;
  runtime_roles: Array<Record<string, unknown>>;
};

export type ArtifactConsoleFilesResponse = {
  artifact: {
    id: string;
    slug: string;
  };
  files: ArtifactConsoleFileRow[];
};

export type XynIntentOptionsResponse = {
  artifact_type: "ArticleDraft" | "ContextPack";
  field: "category" | "format" | "duration";
  options: unknown[];
};

export type RecentArtifactItem = {
  artifact_id: string;
  artifact_type: string;
  artifact_state?: string | null;
  title: string;
  updated_at?: string;
  route: string;
};

export type RecentArtifactListResponse = {
  items: RecentArtifactItem[];
};
