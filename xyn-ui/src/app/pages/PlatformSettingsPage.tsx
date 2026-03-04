import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import Tabs from "../components/ui/Tabs";
import {
  addWorkspaceMember,
  createWorkspace,
  createVideoAdapterConfig,
  deleteWorkspaceMember,
  getWorkspaceAuthPolicy,
  getPlatformConfig,
  listWorkspaceMembers,
  listWorkspaces,
  listVideoAdapterConfigs,
  listVideoAdapters,
  testVideoAdapterConnection,
  testWorkspaceOidcDiscovery,
  updatePlatformConfig,
  updateWorkspaceAuthPolicy,
  updateWorkspace,
} from "../../api/xyn";
import type {
  PlatformConfig,
  VideoAdapterConfigRecord,
  VideoAdapterDefinition,
  WorkspaceAuthPolicy,
  WorkspaceMembershipSummary,
  WorkspaceSummary,
} from "../../api/types";
import { toWorkspacePath } from "../routing/workspaceRouting";

type SettingsTab = "general" | "security" | "integrations" | "deploy" | "workspaces";

type SettingsCard = {
  title: string;
  description: string;
  actionLabel: string;
  path: string;
  status?: "Configured" | "Needs setup" | "Disabled" | "Available" | "Legacy";
};

const defaultWorkspaceAuthPolicy: WorkspaceAuthPolicy = {
  workspace_id: "",
  auth_mode: "oidc",
  oidc_enabled: false,
  oidc_issuer_url: "",
  oidc_client_id: "",
  oidc_client_secret_ref_id: null,
  oidc_scopes: "openid profile email",
  oidc_claim_email: "email",
  oidc_allow_auto_provision: false,
  oidc_allowed_email_domains: [],
};

const SETTINGS_TABS: Array<{ value: SettingsTab; label: string }> = [
  { value: "general", label: "General" },
  { value: "security", label: "Security" },
  { value: "integrations", label: "Integrations" },
  { value: "deploy", label: "Deploy" },
  { value: "workspaces", label: "Workspaces" },
];

const LIFECYCLE_OPTIONS = ["lead", "prospect", "customer", "churned", "internal"];
const KIND_OPTIONS = ["customer", "operator", "reseller", "internal"];
const WORKSPACES_PAGE_SIZE = 5;
const MEMBERS_PAGE_SIZE = 5;

function inferMemberAuthSource(member: WorkspaceMembershipSummary): string {
  const backendLabel = String(member.auth_source_label || "").trim();
  if (backendLabel) return backendLabel;
  const token = String(member.user_identity_id || "").toLowerCase();
  if (!token) return "Unknown";
  if (token.includes("google")) return "Google IdP";
  if (token.includes("aws")) return "Xyn/AWS IdP";
  if (token.includes("local")) return "Local";
  if (token.includes("oidc")) return "OIDC";
  if (token.includes(":")) return token.split(":", 1)[0].toUpperCase();
  return "Identity";
}

const defaultConfig: PlatformConfig = {
  storage: {
    primary: { type: "local", name: "local" },
    providers: [
      { name: "local", type: "local", local: { base_path: "/tmp/xyn-uploads" } },
      { name: "default", type: "s3", s3: { bucket: "", region: "", prefix: "xyn/", acl: "private" } },
    ],
  },
  notifications: {
    enabled: true,
    channels: [
      { name: "discord-default", type: "discord", enabled: false, discord: { webhook_url_ref: "" } },
      { name: "sns-default", type: "aws_sns", enabled: false, aws_sns: { topic_arn: "", region: "" } },
    ],
  },
  video_generation: {
    enabled: true,
    provider: "export_package",
    http: {
      endpoint_url: "",
      timeout_seconds: 90,
    },
  },
  video: {
    rendering_mode: "export_package_only",
    endpoint_url: "",
    adapter_id: "http_generic_renderer",
    adapter_config_id: null,
    credential_ref: "",
    timeout_seconds: 90,
    retry_count: 0,
  },
};

function ensureConfig(config?: PlatformConfig): PlatformConfig {
  const merged = config ? { ...defaultConfig, ...config } : { ...defaultConfig };
  const providers = merged.storage?.providers || [];
  const hasLocal = providers.some((p) => p.name === "local");
  const hasS3 = providers.some((p) => p.name === "default");
  if (!hasLocal) providers.push({ name: "local", type: "local", local: { base_path: "/tmp/xyn-uploads" } });
  if (!hasS3) providers.push({ name: "default", type: "s3", s3: { bucket: "", region: "", prefix: "xyn/", acl: "private" } });
  merged.storage.providers = providers;
  if (!merged.notifications.channels?.length) merged.notifications.channels = defaultConfig.notifications.channels;
  merged.video_generation = {
    ...defaultConfig.video_generation,
    ...(merged.video_generation || {}),
    http: {
      ...(defaultConfig.video_generation?.http || {}),
      ...((merged.video_generation && merged.video_generation.http) || {}),
    },
  };
  const incomingVideo = merged.video || {};
  const fallbackMode = (() => {
    const provider = String(merged.video_generation?.provider || "").trim().toLowerCase();
    if (provider === "http_adapter" || provider === "http") return "render_via_adapter";
    if (provider === "http_endpoint" || provider === "http_url") return "render_via_endpoint";
    return "export_package_only";
  })();
  merged.video = {
    ...defaultConfig.video,
    ...incomingVideo,
    rendering_mode: (incomingVideo.rendering_mode || fallbackMode) as NonNullable<PlatformConfig["video"]>["rendering_mode"],
    endpoint_url: incomingVideo.endpoint_url ?? merged.video_generation?.http?.endpoint_url ?? "",
    timeout_seconds: incomingVideo.timeout_seconds ?? merged.video_generation?.http?.timeout_seconds ?? 90,
    retry_count: incomingVideo.retry_count ?? 0,
  };
  return merged;
}

function statusChipClass(status: SettingsCard["status"]): string {
  if (status === "Configured" || status === "Available") return "status-chip active";
  if (status === "Legacy") return "status-chip deprecated";
  return "status-chip";
}

function HubCards({ cards, onOpen }: { cards: SettingsCard[]; onOpen: (path: string) => void }) {
  if (!cards.length) {
    return (
      <section className="card">
        <h3>No settings in this section yet</h3>
        <p className="muted">Add providers or platform features to populate this tab.</p>
      </section>
    );
  }
  return (
    <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
      {cards.map((card) => (
        <section key={card.title} className="card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <h3>{card.title}</h3>
            {card.status ? <span className={statusChipClass(card.status)}>{card.status}</span> : null}
          </div>
          <p className="muted">{card.description}</p>
          <div className="form-actions">
            <button type="button" className="ghost" onClick={() => onOpen(card.path)}>
              {card.actionLabel}
            </button>
          </div>
        </section>
      ))}
    </div>
  );
}

export default function PlatformSettingsPage() {
  const navigate = useNavigate();
  const params = useParams();
  const workspaceId = String(params.workspaceId || "").trim();
  const [searchParams, setSearchParams] = useSearchParams();
  const [config, setConfig] = useState<PlatformConfig>(defaultConfig);
  const [version, setVersion] = useState<number>(0);
  const [loading, setLoading] = useState(false);
  const [loadingAdapters, setLoadingAdapters] = useState(false);
  const [loadingAdapterConfigs, setLoadingAdapterConfigs] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [videoAdapters, setVideoAdapters] = useState<VideoAdapterDefinition[]>([]);
  const [adapterConfigs, setAdapterConfigs] = useState<VideoAdapterConfigRecord[]>([]);
  const [renderViaModelEnabled, setRenderViaModelEnabled] = useState(false);
  const [workspaceMembers, setWorkspaceMembers] = useState<WorkspaceMembershipSummary[]>([]);
  const [workspaceRows, setWorkspaceRows] = useState<WorkspaceSummary[]>([]);
  const [workspaceSummary, setWorkspaceSummary] = useState<WorkspaceSummary | null>(null);
  const [workspaceAuthPolicy, setWorkspaceAuthPolicy] = useState<WorkspaceAuthPolicy>(defaultWorkspaceAuthPolicy);
  const [memberEmail, setMemberEmail] = useState("");
  const [memberRole, setMemberRole] = useState<"admin" | "member">("member");
  const [membersLoading, setMembersLoading] = useState(false);
  const [memberActionLoading, setMemberActionLoading] = useState(false);
  const [demoCredentialNotice, setDemoCredentialNotice] = useState<string | null>(null);
  const [authPolicySaving, setAuthPolicySaving] = useState(false);
  const [authPolicyTesting, setAuthPolicyTesting] = useState(false);
  const [workspaceProfileSaving, setWorkspaceProfileSaving] = useState(false);
  const [allWorkspaceCreating, setAllWorkspaceCreating] = useState(false);
  const [allWorkspaceSearch, setAllWorkspaceSearch] = useState("");
  const [allWorkspacePage, setAllWorkspacePage] = useState(1);
  const [membersSearch, setMembersSearch] = useState("");
  const [membersPage, setMembersPage] = useState(1);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState("");
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [profileForm, setProfileForm] = useState({
    name: "",
    org_name: "",
    slug: "",
    description: "",
    kind: "customer",
    lifecycle_stage: "prospect",
    parent_workspace_id: "",
    metadata_text: "{}",
  });
  const [createForm, setCreateForm] = useState({
    name: "",
    org_name: "",
    slug: "",
    description: "",
    kind: "customer",
    lifecycle_stage: "prospect",
    parent_workspace_id: "",
  });

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await getPlatformConfig();
      setVersion(result.version);
      setConfig(ensureConfig(result.config));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const loadVideoAdapters = async () => {
    try {
      setLoadingAdapters(true);
      const result = await listVideoAdapters();
      setVideoAdapters(result.adapters || []);
      setRenderViaModelEnabled(Boolean(result.feature_flags?.render_via_model_config));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoadingAdapters(false);
    }
  };

  const loadAdapterConfigs = async (adapterId: string) => {
    try {
      setLoadingAdapterConfigs(true);
      const result = await listVideoAdapterConfigs(adapterId, "canonical");
      setAdapterConfigs(result.configs || []);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoadingAdapterConfigs(false);
    }
  };

  useEffect(() => {
    void loadVideoAdapters();
  }, []);

  const loadWorkspaceDirectory = async () => {
    try {
      const workspaceResult = await listWorkspaces();
      const allRows = workspaceResult.workspaces || [];
      setWorkspaceRows(allRows);
      setSelectedWorkspaceId((current) => {
        if (workspaceId && allRows.some((row) => row.id === workspaceId)) return workspaceId;
        if (current && allRows.some((row) => row.id === current)) return current;
        return allRows[0]?.id || "";
      });
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const loadSelectedWorkspace = async (targetWorkspaceId: string) => {
    if (!targetWorkspaceId) {
      setWorkspaceMembers([]);
      setWorkspaceSummary(null);
      setWorkspaceAuthPolicy(defaultWorkspaceAuthPolicy);
      return;
    }
    try {
      setMembersLoading(true);
      const membersResult = await listWorkspaceMembers(targetWorkspaceId);
      setWorkspaceMembers(membersResult.memberships || []);
      const row = workspaceRows.find((item) => item.id === targetWorkspaceId) || null;
      setWorkspaceSummary(row);
      try {
        const authResult = await getWorkspaceAuthPolicy(targetWorkspaceId);
        setWorkspaceAuthPolicy(authResult.auth_policy || { ...defaultWorkspaceAuthPolicy, workspace_id: targetWorkspaceId });
      } catch {
        setWorkspaceAuthPolicy({
          ...defaultWorkspaceAuthPolicy,
          workspace_id: targetWorkspaceId,
          auth_mode: row?.auth_mode || "oidc",
          oidc_enabled: Boolean(row?.oidc_enabled),
          oidc_issuer_url: row?.oidc_issuer_url || "",
          oidc_client_id: row?.oidc_client_id || "",
          oidc_client_secret_ref_id: row?.oidc_client_secret_ref_id || null,
          oidc_scopes: row?.oidc_scopes || "openid profile email",
          oidc_claim_email: row?.oidc_claim_email || "email",
          oidc_allow_auto_provision: Boolean(row?.oidc_allow_auto_provision),
          oidc_allowed_email_domains: row?.oidc_allowed_email_domains || [],
        });
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setMembersLoading(false);
    }
  };

  const activeVideoConfig = config.video || defaultConfig.video!;
  useEffect(() => {
    if (!activeVideoConfig.adapter_id) {
      setAdapterConfigs([]);
      return;
    }
    void loadAdapterConfigs(String(activeVideoConfig.adapter_id));
  }, [activeVideoConfig.adapter_id]);

  const setProvider = (name: string, next: Record<string, unknown>) => {
    const providers = (config.storage.providers || []).map((provider) =>
      provider.name === name ? { ...provider, ...next } : provider
    );
    setConfig({ ...config, storage: { ...config.storage, providers } });
  };

  const getProvider = (name: string) => (config.storage.providers || []).find((provider) => provider.name === name);
  const localProvider = getProvider("local") || { name: "local", type: "local", local: { base_path: "/tmp/xyn-uploads" } };
  const s3Provider = getProvider("default") || {
    name: "default",
    type: "s3",
    s3: { bucket: "", region: "", prefix: "xyn/", acl: "private" },
  };
  const discordChannel =
    config.notifications.channels.find((channel) => channel.type === "discord") ||
    ({ name: "discord-default", type: "discord", enabled: false, discord: { webhook_url_ref: "" } } as const);
  const snsChannel =
    config.notifications.channels.find((channel) => channel.type === "aws_sns") ||
    ({ name: "sns-default", type: "aws_sns", enabled: false, aws_sns: { topic_arn: "", region: "" } } as const);

  const updateChannel = (type: "discord" | "aws_sns", next: Record<string, unknown>) => {
    const channels = [...config.notifications.channels];
    const idx = channels.findIndex((channel) => channel.type === type);
    if (idx >= 0) channels[idx] = { ...channels[idx], ...next };
    else channels.push(next as PlatformConfig["notifications"]["channels"][number]);
    setConfig({ ...config, notifications: { ...config.notifications, channels } });
  };

  const renderingMode = activeVideoConfig.rendering_mode || "export_package_only";
  const selectedAdapter = useMemo(
    () => videoAdapters.find((item) => item.id === activeVideoConfig.adapter_id) || null,
    [videoAdapters, activeVideoConfig.adapter_id]
  );
  const selectedAdapterConfig = useMemo(
    () => adapterConfigs.find((item) => item.artifact_id === activeVideoConfig.adapter_config_id) || null,
    [adapterConfigs, activeVideoConfig.adapter_config_id]
  );

  const updateVideo = (next: Partial<NonNullable<PlatformConfig["video"]>>) => {
    setConfig({
      ...config,
      video: {
        ...activeVideoConfig,
        ...next,
      },
    });
  };

  const createAdapterConfigDraft = async () => {
    const adapterId = String(activeVideoConfig.adapter_id || "").trim();
    if (!adapterId) return;
    try {
      setLoading(true);
      const title = `${adapterId.replace(/_/g, " ")} config`.replace(/\b\w/g, (ch) => ch.toUpperCase());
      const result = await createVideoAdapterConfig({
        title,
        adapter_id: adapterId,
      });
      setMessage("Adapter config draft created.");
      await loadAdapterConfigs(adapterId);
      if (result.config?.artifact_id) {
        navigate(`/app/platform/video-adapter-configs/${result.config.artifact_id}`);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const save = async () => {
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      const result = await updatePlatformConfig(config);
      setVersion(result.version);
      setConfig(ensureConfig(result.config));
      setMessage("Platform settings saved.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const testConnection = () => {
    if (renderingMode !== "render_via_adapter" || !selectedAdapterConfig) {
      setError("Select an adapter and adapter config before testing.");
      return;
    }
    setLoading(true);
    setError(null);
    setMessage(null);
    testVideoAdapterConnection({
      adapter_id: selectedAdapterConfig.adapter_id,
      adapter_config_id: selectedAdapterConfig.artifact_id,
    })
      .then((result) => {
        const checksSummary = (result.checks || [])
          .map((item) => `${item.status.toUpperCase()}: ${item.name}`)
          .join(" · ");
        setMessage(
          `${result.ok ? "Connection test passed" : "Connection test reported issues"} for ${selectedAdapterConfig.title}. ${checksSummary}`
        );
      })
      .catch((err) => {
        setError((err as Error).message);
      })
      .finally(() => {
        setLoading(false);
      });
  };

  const requestedTab = (searchParams.get("tab") || "general").toLowerCase();
  const activeTab: SettingsTab =
    SETTINGS_TABS.find((tab) => tab.value === requestedTab)?.value || "general";

  const setActiveTab = (tab: SettingsTab) => {
    const next = new URLSearchParams(searchParams);
    if (tab === "general") next.delete("tab");
    else next.set("tab", tab);
    setSearchParams(next);
  };

  useEffect(() => {
    if (activeTab !== "workspaces") return;
    void loadWorkspaceDirectory();
  }, [activeTab, workspaceId]);

  useEffect(() => {
    if (activeTab !== "workspaces") return;
    if (!selectedWorkspaceId) return;
    void loadSelectedWorkspace(selectedWorkspaceId);
  }, [activeTab, selectedWorkspaceId, workspaceRows]);

  useEffect(() => {
    setMembersSearch("");
    setMembersPage(1);
  }, [selectedWorkspaceId]);

  useEffect(() => {
    if (!workspaceSummary) return;
    setProfileForm({
      name: workspaceSummary.name || "",
      org_name: workspaceSummary.org_name || workspaceSummary.name || "",
      slug: workspaceSummary.slug || "",
      description: workspaceSummary.description || "",
      kind: workspaceSummary.kind || "customer",
      lifecycle_stage: workspaceSummary.lifecycle_stage || "prospect",
      parent_workspace_id: workspaceSummary.parent_workspace_id || "",
      metadata_text: JSON.stringify(workspaceSummary.metadata || {}, null, 2),
    });
  }, [workspaceSummary]);

  const addMember = async () => {
    if (!selectedWorkspaceId || !memberEmail.trim()) return;
    try {
      setMemberActionLoading(true);
      setDemoCredentialNotice(null);
      const result = await addWorkspaceMember(selectedWorkspaceId, {
        email: memberEmail.trim(),
        role: memberRole,
      });
      if (result.temp_password) {
        setDemoCredentialNotice(
          `Demo mode credentials for ${memberEmail.trim()}: temporary password ${result.temp_password}`
        );
      } else if (result.invite_link) {
        setDemoCredentialNotice(`Invite link: ${result.invite_link}`);
      }
      setMemberEmail("");
      await loadSelectedWorkspace(selectedWorkspaceId);
      setMessage("Workspace member added.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setMemberActionLoading(false);
    }
  };

  const removeMember = async (memberId: string) => {
    if (!selectedWorkspaceId || !memberId) return;
    try {
      setMemberActionLoading(true);
      await deleteWorkspaceMember(selectedWorkspaceId, memberId);
      await loadSelectedWorkspace(selectedWorkspaceId);
      setMessage("Workspace member removed.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setMemberActionLoading(false);
    }
  };

  const saveWorkspaceAuthPolicy = async () => {
    if (!selectedWorkspaceId) return;
    try {
      setAuthPolicySaving(true);
      const payload: Partial<WorkspaceAuthPolicy> = {
        auth_mode: workspaceAuthPolicy.auth_mode,
        oidc_enabled: workspaceAuthPolicy.oidc_enabled,
        oidc_issuer_url: workspaceAuthPolicy.oidc_issuer_url,
        oidc_client_id: workspaceAuthPolicy.oidc_client_id,
        oidc_client_secret_ref_id: workspaceAuthPolicy.oidc_client_secret_ref_id || null,
        oidc_scopes: workspaceAuthPolicy.oidc_scopes,
        oidc_claim_email: workspaceAuthPolicy.oidc_claim_email,
        oidc_allow_auto_provision: workspaceAuthPolicy.oidc_allow_auto_provision,
        oidc_allowed_email_domains: workspaceAuthPolicy.oidc_allowed_email_domains,
      };
      const result = await updateWorkspaceAuthPolicy(selectedWorkspaceId, payload);
      setWorkspaceAuthPolicy(result.auth_policy);
      setMessage("Authentication policy saved.");
      await loadSelectedWorkspace(selectedWorkspaceId);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAuthPolicySaving(false);
    }
  };

  const testDiscovery = async () => {
    if (!selectedWorkspaceId) return;
    try {
      setAuthPolicyTesting(true);
      const result = await testWorkspaceOidcDiscovery(selectedWorkspaceId);
      if (result.ok) {
        setMessage(`OIDC discovery succeeded: ${result.issuer || "issuer resolved"}`);
      } else {
        setError(result.error || "OIDC discovery failed");
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAuthPolicyTesting(false);
    }
  };

  const saveWorkspaceProfile = async () => {
    if (!selectedWorkspaceId) return;
    try {
      setWorkspaceProfileSaving(true);
      let metadata: Record<string, unknown> = {};
      try {
        metadata = profileForm.metadata_text.trim()
          ? (JSON.parse(profileForm.metadata_text) as Record<string, unknown>)
          : {};
      } catch {
        setError("Metadata must be valid JSON object.");
        return;
      }
      await updateWorkspace(selectedWorkspaceId, {
        name: profileForm.name.trim(),
        org_name: profileForm.org_name.trim(),
        slug: profileForm.slug.trim(),
        description: profileForm.description,
        kind: profileForm.kind,
        lifecycle_stage: profileForm.lifecycle_stage,
        parent_workspace_id: profileForm.parent_workspace_id || null,
        metadata,
      });
      await loadWorkspaceDirectory();
      await loadSelectedWorkspace(selectedWorkspaceId);
      setMessage("Workspace profile saved.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setWorkspaceProfileSaving(false);
    }
  };

  const createWorkspaceFromHub = async () => {
    if (!createForm.name.trim()) return;
    try {
      setAllWorkspaceCreating(true);
      const result = await createWorkspace({
        name: createForm.name.trim(),
        org_name: createForm.org_name.trim() || undefined,
        slug: createForm.slug.trim() || undefined,
        description: createForm.description.trim() || undefined,
        kind: createForm.kind,
        lifecycle_stage: createForm.lifecycle_stage,
        parent_workspace_id: createForm.parent_workspace_id || undefined,
      });
      setCreateForm({
        name: "",
        org_name: "",
        slug: "",
        description: "",
        kind: "customer",
        lifecycle_stage: "prospect",
        parent_workspace_id: "",
      });
      await loadWorkspaceDirectory();
      setSelectedWorkspaceId(result.workspace.id);
      setCreateModalOpen(false);
      setMessage(`Workspace "${result.workspace.name}" created.`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAllWorkspaceCreating(false);
    }
  };

  const toScopedPath = (subpath: string, query?: Record<string, string>): string => {
    const rest = subpath.replace(/^\/+/, "");
    const base = workspaceId ? toWorkspacePath(workspaceId, rest) : `/app/${rest}`;
    if (!query || Object.keys(query).length === 0) return base;
    const params = new URLSearchParams(query);
    return `${base}?${params.toString()}`;
  };

  const storageStatus: SettingsCard["status"] =
    config.storage.primary.type === "local"
      ? "Configured"
      : s3Provider.s3?.bucket && s3Provider.s3?.region
      ? "Configured"
      : "Needs setup";
  const notificationsStatus: SettingsCard["status"] =
    !config.notifications.enabled
      ? "Disabled"
      : config.notifications.channels.some((channel) => channel.enabled)
      ? "Configured"
      : "Needs setup";
  const renderingStatus: SettingsCard["status"] =
    renderingMode === "export_package_only"
      ? "Disabled"
      : renderingMode === "render_via_adapter" && activeVideoConfig.adapter_config_id
      ? "Configured"
      : renderingMode === "render_via_endpoint" && activeVideoConfig.endpoint_url
      ? "Configured"
      : "Needs setup";
  const filteredWorkspaceRows = workspaceRows.filter((row) => {
    const q = allWorkspaceSearch.trim().toLowerCase();
    if (!q) return true;
    return (
      row.name.toLowerCase().includes(q) ||
      row.slug.toLowerCase().includes(q) ||
      (row.org_name || "").toLowerCase().includes(q)
    );
  });
  const workspacePageCount = Math.max(1, Math.ceil(filteredWorkspaceRows.length / WORKSPACES_PAGE_SIZE));
  const safeWorkspacePage = Math.min(allWorkspacePage, workspacePageCount);
  const workspacePageRows = filteredWorkspaceRows.slice(
    (safeWorkspacePage - 1) * WORKSPACES_PAGE_SIZE,
    safeWorkspacePage * WORKSPACES_PAGE_SIZE
  );
  const filteredMembers = workspaceMembers.filter((member) => {
    const q = membersSearch.trim().toLowerCase();
    if (!q) return true;
    return (
      String(member.email || "").toLowerCase().includes(q) ||
      String(member.display_name || "").toLowerCase().includes(q) ||
      String(member.user_identity_id || "").toLowerCase().includes(q) ||
      inferMemberAuthSource(member).toLowerCase().includes(q)
    );
  });
  const membersPageCount = Math.max(1, Math.ceil(filteredMembers.length / MEMBERS_PAGE_SIZE));
  const safeMembersPage = Math.min(membersPage, membersPageCount);
  const memberPageRows = filteredMembers.slice(
    (safeMembersPage - 1) * MEMBERS_PAGE_SIZE,
    safeMembersPage * MEMBERS_PAGE_SIZE
  );
  useEffect(() => {
    if (allWorkspacePage > workspacePageCount) setAllWorkspacePage(workspacePageCount);
  }, [allWorkspacePage, workspacePageCount]);
  useEffect(() => {
    if (membersPage > membersPageCount) setMembersPage(membersPageCount);
  }, [membersPage, membersPageCount]);

  const securityCards: SettingsCard[] = [
    {
      title: "Access Control",
      description: "Manage user roles, grants, and effective access across platform capabilities.",
      actionLabel: "Open Access Control",
      path: toScopedPath("platform/access-control"),
      status: "Available",
    },
    {
      title: "Identity Configuration",
      description: "Configure identity providers and OIDC app client settings for login and federation.",
      actionLabel: "Open Identity",
      path: toScopedPath("platform/identity-configuration"),
      status: "Needs setup",
    },
    {
      title: "Secrets",
      description: "Store and rotate credentials used by adapters, notifications, and integrations.",
      actionLabel: "Open Secrets",
      path: toScopedPath("platform/secrets"),
      status: "Available",
    },
    {
      title: "Activity",
      description: "Review governance-relevant activity and trace who changed what and when.",
      actionLabel: "Open Activity",
      path: toScopedPath("govern/activity"),
      status: "Available",
    },
  ];

  const integrationsCards: SettingsCard[] = [
    {
      title: "AI Agents",
      description: "Configure AI credentials, models, and agent purposes for assistant-driven workflows.",
      actionLabel: "Open AI Agents",
      path: toScopedPath("platform/ai-agents"),
      status: "Available",
    },
    {
      title: "Video Adapter Configs",
      description: "Manage renderer adapter configs used by runtime video render workflows.",
      actionLabel: selectedAdapterConfig ? "Open Active Config" : "Open Rendering Settings",
      path: selectedAdapterConfig
        ? toScopedPath(`platform/video-adapter-configs/${selectedAdapterConfig.artifact_id}`)
        : toScopedPath("platform/settings", { tab: "general" }),
      status: selectedAdapterConfig ? "Configured" : "Needs setup",
    },
  ];

  const deployCards: SettingsCard[] = [
    {
      title: "Release Plans",
      description: "Plan and trigger release activity from Runs and deployment workflows.",
      actionLabel: "Open Release Runs",
      path: toScopedPath("run/runs", { filter: "release_plan" }),
      status: "Available",
    },
    {
      title: "Releases",
      description: "Monitor active and historical release execution with linked run telemetry.",
      actionLabel: "Open Runs",
      path: toScopedPath("run/runs"),
      status: "Available",
    },
    {
      title: "Seed Packs",
      description: "Apply curated seed packs for baseline platform content and setup.",
      actionLabel: "Open Seed Packs",
      path: toScopedPath("platform/seeds"),
      status: "Available",
    },
    {
      title: "Instances",
      description: "Power-user deep link for instance management while Instances stays hidden from sidebar.",
      actionLabel: "Open Instances",
      path: toScopedPath("run/instances"),
      status: "Legacy",
    },
    {
      title: "Control Plane",
      description: "Legacy control-plane surface retained as a fallback while capabilities move to artifacts.",
      actionLabel: "Open Control Plane",
      path: toScopedPath("control-plane"),
      status: "Legacy",
    },
  ];

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Platform Settings</h2>
          <p className="muted">Version {version}</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" onClick={() => void load()} disabled={loading}>
            Refresh
          </button>
          <button className="primary" onClick={() => void save()} disabled={loading}>
            Save
          </button>
        </div>
      </div>

      <div className="page-tabs" style={{ marginBottom: 10 }}>
        <Tabs
          ariaLabel="Platform settings tabs"
          value={activeTab}
          onChange={setActiveTab}
          options={SETTINGS_TABS.map((tab) => ({ value: tab.value, label: tab.label }))}
        />
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      {activeTab === "security" ? <HubCards cards={securityCards} onOpen={(path) => navigate(path)} /> : null}
      {activeTab === "integrations" ? <HubCards cards={integrationsCards} onOpen={(path) => navigate(path)} /> : null}
      {activeTab === "deploy" ? <HubCards cards={deployCards} onOpen={(path) => navigate(path)} /> : null}
      {activeTab === "workspaces" ? (
        <>
          <section className="card">
            <div className="card-header">
              <h3>Workspace Management</h3>
              <button className="primary" type="button" onClick={() => setCreateModalOpen(true)}>
                Create Workspace
              </button>
            </div>
            <p className="muted small">Workspace is the tenant container. Select a workspace to edit details, members, and authentication in one place.</p>
          </section>

          <div style={{ display: "grid", gap: 12, gridTemplateColumns: "minmax(260px, 1fr) minmax(360px, 1.2fr)" }}>
            <section className="card" style={{ marginBottom: 0 }}>
              <div className="card-header">
                <h3>All Workspaces</h3>
                <span className="status-chip">{filteredWorkspaceRows.length}</span>
              </div>
              <input
                className="input"
                placeholder="Search workspaces"
                value={allWorkspaceSearch}
                onChange={(event) => {
                  setAllWorkspaceSearch(event.target.value);
                  setAllWorkspacePage(1);
                }}
              />
              <div className="instance-list" style={{ marginTop: 10 }}>
                {workspacePageRows.map((row) => (
                  <button
                    key={row.id}
                    type="button"
                    className={`instance-row ${selectedWorkspaceId === row.id ? "active" : ""}`}
                    onClick={() => setSelectedWorkspaceId(row.id)}
                  >
                    <div>
                      <strong>{row.name}</strong>
                      <div className="muted small">{row.slug}</div>
                    </div>
                    <span className="status-chip">{row.lifecycle_stage || "prospect"}</span>
                  </button>
                ))}
                {!workspacePageRows.length ? <p className="muted">No workspaces found.</p> : null}
              </div>
              <div className="form-actions">
                <button className="ghost" type="button" onClick={() => setAllWorkspacePage((value) => Math.max(1, value - 1))} disabled={safeWorkspacePage <= 1}>
                  Previous
                </button>
                <span className="muted small">Page {safeWorkspacePage} of {workspacePageCount}</span>
                <button className="ghost" type="button" onClick={() => setAllWorkspacePage((value) => Math.min(workspacePageCount, value + 1))} disabled={safeWorkspacePage >= workspacePageCount}>
                  Next
                </button>
              </div>
            </section>

            <section className="card" style={{ marginBottom: 0 }}>
              <div className="card-header">
                <h3>Workspace Profile</h3>
                <span className="status-chip active">
                  {(workspaceSummary?.name || "--")} · {(workspaceSummary?.slug || "--")} · kind: {(workspaceSummary?.kind || "customer")} · stage: {(workspaceSummary?.lifecycle_stage || "prospect")}
                </span>
              </div>
              <div className="form-grid">
                <label>
                  Name
                  <input className="input" value={profileForm.name} onChange={(event) => setProfileForm((current) => ({ ...current, name: event.target.value }))} />
                </label>
                <label>
                  Org name
                  <input className="input" value={profileForm.org_name} onChange={(event) => setProfileForm((current) => ({ ...current, org_name: event.target.value }))} />
                </label>
                <label>
                  Slug
                  <input className="input" value={profileForm.slug} onChange={(event) => setProfileForm((current) => ({ ...current, slug: event.target.value }))} />
                </label>
                <label>
                  Parent workspace
                  <select value={profileForm.parent_workspace_id} onChange={(event) => setProfileForm((current) => ({ ...current, parent_workspace_id: event.target.value }))}>
                    <option value="">(none)</option>
                    {workspaceRows
                      .filter((row) => row.id !== selectedWorkspaceId)
                      .map((row) => (
                        <option key={row.id} value={row.id}>
                          {row.name}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  Kind
                  <select value={profileForm.kind} onChange={(event) => setProfileForm((current) => ({ ...current, kind: event.target.value }))}>
                    {KIND_OPTIONS.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Lifecycle stage
                  <select value={profileForm.lifecycle_stage} onChange={(event) => setProfileForm((current) => ({ ...current, lifecycle_stage: event.target.value }))}>
                    {LIFECYCLE_OPTIONS.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="span-full">
                  Description
                  <textarea rows={3} value={profileForm.description} onChange={(event) => setProfileForm((current) => ({ ...current, description: event.target.value }))} />
                </label>
                <label className="span-full">
                  Metadata (JSON)
                  <textarea rows={4} value={profileForm.metadata_text} onChange={(event) => setProfileForm((current) => ({ ...current, metadata_text: event.target.value }))} />
                </label>
              </div>
              <div className="form-actions">
                <button className="primary" onClick={() => void saveWorkspaceProfile()} disabled={workspaceProfileSaving || !selectedWorkspaceId}>
                  {workspaceProfileSaving ? "Saving..." : "Save Profile"}
                </button>
              </div>
            </section>
          </div>

          <section className="card">
            <div className="card-header">
              <h3>Workspace Members</h3>
              <span className="status-chip">Workspace role</span>
            </div>
            <div className="form-grid" style={{ gridTemplateColumns: "2fr 1fr auto" }}>
              <label>
                Email
                <input className="input" placeholder="user@example.com" value={memberEmail} onChange={(event) => setMemberEmail(event.target.value)} />
              </label>
              <label>
                Workspace role
                <select value={memberRole} onChange={(event) => setMemberRole(event.target.value as "admin" | "member")}>
                  <option value="admin">Workspace Admin</option>
                  <option value="member">Workspace Member</option>
                </select>
              </label>
              <div className="form-actions" style={{ alignSelf: "end" }}>
                <button className="primary" onClick={() => void addMember()} disabled={memberActionLoading || !selectedWorkspaceId}>
                  {memberActionLoading ? "Adding..." : "Add member"}
                </button>
              </div>
            </div>
            {demoCredentialNotice ? <InlineMessage tone="info" title="Demo credentials" body={demoCredentialNotice} /> : null}
            <div className="form-grid" style={{ gridTemplateColumns: "2fr auto", alignItems: "end" }}>
              <label>
                Search members
                <input
                  className="input"
                  placeholder="Search email, identity, or auth source"
                  value={membersSearch}
                  onChange={(event) => {
                    setMembersSearch(event.target.value);
                    setMembersPage(1);
                  }}
                />
              </label>
            </div>
            <div style={{ marginTop: 10 }}>
              {membersLoading ? <p className="muted">Loading members...</p> : null}
              {!membersLoading && !memberPageRows.length ? <p className="muted">No members yet.</p> : null}
              {!membersLoading && memberPageRows.length
                ? memberPageRows.map((member) => (
                    <div key={member.id} className="instance-row" style={{ display: "grid", gridTemplateColumns: "minmax(240px, 1fr) auto auto auto", gap: 10 }}>
                      <div>
                        <strong>{member.email || member.display_name || member.user_identity_id}</strong>
                        <div className="muted small">{member.display_name || member.user_identity_id}</div>
                      </div>
                      <span className="status-chip">{inferMemberAuthSource(member)}</span>
                      <span className="status-chip">{member.role === "admin" ? "Workspace Admin" : "Workspace Member"}</span>
                      <button className="ghost" onClick={() => void removeMember(member.id)} disabled={memberActionLoading}>
                        Remove
                      </button>
                    </div>
                  ))
                : null}
            </div>
            <div className="form-actions">
              <button className="ghost" type="button" onClick={() => setMembersPage((value) => Math.max(1, value - 1))} disabled={safeMembersPage <= 1}>
                Previous
              </button>
              <span className="muted small">Page {safeMembersPage} of {membersPageCount}</span>
              <button className="ghost" type="button" onClick={() => setMembersPage((value) => Math.min(membersPageCount, value + 1))} disabled={safeMembersPage >= membersPageCount}>
                Next
              </button>
            </div>
          </section>

          <section className="card">
            <h3>Authentication</h3>
            <div className="form-grid">
              <label>
                Auth mode
                <select value={workspaceAuthPolicy.auth_mode} onChange={(event) => setWorkspaceAuthPolicy((current) => ({ ...current, auth_mode: event.target.value as "local" | "oidc" | "mixed" }))}>
                  <option value="oidc">OIDC</option>
                  <option value="local">Local</option>
                  <option value="mixed">Mixed</option>
                </select>
              </label>
              <label>
                OIDC enabled
                <select value={workspaceAuthPolicy.oidc_enabled ? "yes" : "no"} onChange={(event) => setWorkspaceAuthPolicy((current) => ({ ...current, oidc_enabled: event.target.value === "yes" }))}>
                  <option value="no">No</option>
                  <option value="yes">Yes</option>
                </select>
              </label>
              <label>
                Issuer URL
                <input className="input" value={workspaceAuthPolicy.oidc_issuer_url || ""} onChange={(event) => setWorkspaceAuthPolicy((current) => ({ ...current, oidc_issuer_url: event.target.value }))} />
              </label>
              <label>
                Client ID
                <input className="input" value={workspaceAuthPolicy.oidc_client_id || ""} onChange={(event) => setWorkspaceAuthPolicy((current) => ({ ...current, oidc_client_id: event.target.value }))} />
              </label>
              <label>
                Client SecretRef ID
                <input className="input" value={workspaceAuthPolicy.oidc_client_secret_ref_id || ""} onChange={(event) => setWorkspaceAuthPolicy((current) => ({ ...current, oidc_client_secret_ref_id: event.target.value || null }))} />
              </label>
              <label>
                Scopes
                <input className="input" value={workspaceAuthPolicy.oidc_scopes || ""} onChange={(event) => setWorkspaceAuthPolicy((current) => ({ ...current, oidc_scopes: event.target.value }))} />
              </label>
              <label>
                Email claim
                <input className="input" value={workspaceAuthPolicy.oidc_claim_email || ""} onChange={(event) => setWorkspaceAuthPolicy((current) => ({ ...current, oidc_claim_email: event.target.value }))} />
              </label>
              <label>
                Auto-provision
                <select value={workspaceAuthPolicy.oidc_allow_auto_provision ? "yes" : "no"} onChange={(event) => setWorkspaceAuthPolicy((current) => ({ ...current, oidc_allow_auto_provision: event.target.value === "yes" }))}>
                  <option value="no">No</option>
                  <option value="yes">Yes</option>
                </select>
              </label>
              <label className="span-full">
                Allowed domains (comma-separated)
                <input
                  className="input"
                  value={(workspaceAuthPolicy.oidc_allowed_email_domains || []).join(", ")}
                  onChange={(event) =>
                    setWorkspaceAuthPolicy((current) => ({
                      ...current,
                      oidc_allowed_email_domains: event.target.value.split(",").map((token) => token.trim().toLowerCase()).filter(Boolean),
                    }))
                  }
                />
              </label>
            </div>
            <div className="form-actions">
              <button className="ghost" onClick={() => void testDiscovery()} disabled={authPolicyTesting || !selectedWorkspaceId}>
                {authPolicyTesting ? "Testing..." : "Test OIDC discovery"}
              </button>
              <button className="primary" onClick={() => void saveWorkspaceAuthPolicy()} disabled={authPolicySaving || !selectedWorkspaceId}>
                {authPolicySaving ? "Saving..." : "Save Authentication"}
              </button>
            </div>
          </section>

          {createModalOpen ? (
            <div className="modal-backdrop" onClick={allWorkspaceCreating ? undefined : () => setCreateModalOpen(false)}>
              <section className="modal" role="dialog" aria-modal="true" aria-label="Create workspace" onClick={(event) => event.stopPropagation()}>
                <h3>Create Workspace</h3>
                <div className="form-grid" style={{ gridTemplateColumns: "2fr 1fr auto" }}>
                  <label>
                    Name
                    <input className="input" value={createForm.name} onChange={(event) => setCreateForm((current) => ({ ...current, name: event.target.value }))} />
                  </label>
                  <label>
                    Org name
                    <input className="input" value={createForm.org_name} onChange={(event) => setCreateForm((current) => ({ ...current, org_name: event.target.value }))} />
                  </label>
                  <label>
                    Slug
                    <input className="input" value={createForm.slug} onChange={(event) => setCreateForm((current) => ({ ...current, slug: event.target.value }))} />
                  </label>
                  <label>
                    Kind
                    <select value={createForm.kind} onChange={(event) => setCreateForm((current) => ({ ...current, kind: event.target.value }))}>
                      {KIND_OPTIONS.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Lifecycle stage
                    <select value={createForm.lifecycle_stage} onChange={(event) => setCreateForm((current) => ({ ...current, lifecycle_stage: event.target.value }))}>
                      {LIFECYCLE_OPTIONS.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Parent workspace
                    <select value={createForm.parent_workspace_id} onChange={(event) => setCreateForm((current) => ({ ...current, parent_workspace_id: event.target.value }))}>
                      <option value="">(none)</option>
                      {workspaceRows.map((row) => (
                        <option key={row.id} value={row.id}>
                          {row.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="span-full">
                    Description
                    <textarea rows={3} value={createForm.description} onChange={(event) => setCreateForm((current) => ({ ...current, description: event.target.value }))} />
                  </label>
                </div>
                <div className="form-actions">
                  <button className="ghost" type="button" onClick={() => setCreateModalOpen(false)} disabled={allWorkspaceCreating}>
                    Cancel
                  </button>
                  <button className="primary" onClick={() => void createWorkspaceFromHub()} disabled={allWorkspaceCreating || !createForm.name.trim()}>
                    {allWorkspaceCreating ? "Creating..." : "Create workspace"}
                  </button>
                </div>
              </section>
            </div>
          ) : null}
        </>
      ) : null}

      {activeTab === "general" ? (
        <div className="layout">
          <section className="card">
            <div className="card-header">
              <h3>Branding</h3>
              <span className="status-chip active">Configured</span>
            </div>
            <p className="muted">Workspace branding and theme settings are managed in the dedicated Branding surface.</p>
            <div className="form-actions">
              <button className="ghost" onClick={() => navigate(toScopedPath("platform/branding"))}>
                Open Branding
              </button>
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <h3>Storage</h3>
              <span className={statusChipClass(storageStatus)}>{storageStatus}</span>
            </div>
            <div className="form-grid">
              <label>
                Primary provider
                <select
                  value={config.storage.primary.type}
                  onChange={(event) =>
                    setConfig({
                      ...config,
                      storage: {
                        ...config.storage,
                        primary:
                          event.target.value === "s3"
                            ? { type: "s3", name: "default" }
                            : { type: "local", name: "local" },
                      },
                    })
                  }
                >
                  <option value="local">local</option>
                  <option value="s3">s3</option>
                </select>
              </label>
              <label>
                Local base path
                <input
                  className="input"
                  value={localProvider.local?.base_path || ""}
                  onChange={(event) =>
                    setProvider("local", {
                      local: { ...(localProvider.local || {}), base_path: event.target.value },
                    })
                  }
                />
              </label>
              <label>
                S3 bucket
                <input
                  className="input"
                  value={s3Provider.s3?.bucket || ""}
                  onChange={(event) =>
                    setProvider("default", {
                      s3: { ...(s3Provider.s3 || {}), bucket: event.target.value, acl: "private" },
                    })
                  }
                />
              </label>
              <label>
                S3 region
                <input
                  className="input"
                  value={s3Provider.s3?.region || ""}
                  onChange={(event) =>
                    setProvider("default", {
                      s3: { ...(s3Provider.s3 || {}), region: event.target.value, acl: "private" },
                    })
                  }
                />
              </label>
              <label>
                S3 prefix
                <input
                  className="input"
                  value={s3Provider.s3?.prefix || ""}
                  onChange={(event) =>
                    setProvider("default", {
                      s3: { ...(s3Provider.s3 || {}), prefix: event.target.value, acl: "private" },
                    })
                  }
                />
              </label>
              <label>
                S3 KMS key ID (optional)
                <input
                  className="input"
                  value={s3Provider.s3?.kms_key_id || ""}
                  onChange={(event) =>
                    setProvider("default", {
                      s3: { ...(s3Provider.s3 || {}), kms_key_id: event.target.value, acl: "private" },
                    })
                  }
                />
              </label>
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <h3>Notifications</h3>
              <span className={statusChipClass(notificationsStatus)}>{notificationsStatus}</span>
            </div>
            <div className="form-grid">
              <label>
                Notifications enabled
                <select
                  value={config.notifications.enabled ? "yes" : "no"}
                  onChange={(event) =>
                    setConfig({
                      ...config,
                      notifications: { ...config.notifications, enabled: event.target.value === "yes" },
                    })
                  }
                >
                  <option value="yes">Yes</option>
                  <option value="no">No</option>
                </select>
              </label>
              <label>
                Discord enabled
                <select
                  value={discordChannel.enabled ? "yes" : "no"}
                  onChange={(event) =>
                    updateChannel("discord", {
                      ...discordChannel,
                      enabled: event.target.value === "yes",
                    })
                  }
                >
                  <option value="no">No</option>
                  <option value="yes">Yes</option>
                </select>
              </label>
              <label>
                Discord webhook SecretRef
                <input
                  className="input"
                  placeholder="secret_ref:<uuid> or platform SecretRef name"
                  value={discordChannel.discord?.webhook_url_ref || ""}
                  onChange={(event) =>
                    updateChannel("discord", {
                      ...discordChannel,
                      discord: { ...(discordChannel.discord || {}), webhook_url_ref: event.target.value },
                    })
                  }
                />
              </label>
              <label>
                SNS enabled
                <select
                  value={snsChannel.enabled ? "yes" : "no"}
                  onChange={(event) =>
                    updateChannel("aws_sns", {
                      ...snsChannel,
                      enabled: event.target.value === "yes",
                    })
                  }
                >
                  <option value="no">No</option>
                  <option value="yes">Yes</option>
                </select>
              </label>
              <label>
                SNS topic ARN
                <input
                  className="input"
                  value={snsChannel.aws_sns?.topic_arn || ""}
                  onChange={(event) =>
                    updateChannel("aws_sns", {
                      ...snsChannel,
                      aws_sns: { ...(snsChannel.aws_sns || {}), topic_arn: event.target.value },
                    })
                  }
                />
              </label>
              <label>
                SNS region
                <input
                  className="input"
                  value={snsChannel.aws_sns?.region || ""}
                  onChange={(event) =>
                    updateChannel("aws_sns", {
                      ...snsChannel,
                      aws_sns: { ...(snsChannel.aws_sns || {}), region: event.target.value },
                    })
                  }
                />
              </label>
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <h3>Rendering</h3>
              <span className={statusChipClass(renderingStatus)}>{renderingStatus}</span>
            </div>
            <div className="form-grid">
              <label>
                Rendering mode
                <select
                  value={renderingMode}
                  onChange={(event) =>
                    updateVideo({
                      rendering_mode: event.target.value as NonNullable<PlatformConfig["video"]>["rendering_mode"],
                    })
                  }
                >
                  <option value="export_package_only">Export package only</option>
                  <option value="render_via_adapter">Render via adapter</option>
                  <option value="render_via_endpoint">Render via endpoint</option>
                  {renderViaModelEnabled ? <option value="render_via_model_config">Render via model config</option> : null}
                </select>
              </label>
              {renderingMode === "render_via_adapter" ? (
                <>
                  <label>
                    Renderer adapter
                    <select
                      value={activeVideoConfig.adapter_id || ""}
                      onChange={(event) =>
                        updateVideo({
                          adapter_id: event.target.value,
                          adapter_config_id: null,
                        })
                      }
                    >
                      <option value="">Select adapter</option>
                      {videoAdapters.map((adapter) => (
                        <option key={adapter.id} value={adapter.id}>
                          {adapter.name}
                        </option>
                      ))}
                    </select>
                    <span className="muted small">{selectedAdapter?.description || "Choose how Xyn hands render packages to a renderer."}</span>
                  </label>
                  <label>
                    Adapter config (canonical)
                    <select
                      value={activeVideoConfig.adapter_config_id || ""}
                      onChange={(event) => updateVideo({ adapter_config_id: event.target.value || null })}
                      disabled={!activeVideoConfig.adapter_id || loadingAdapterConfigs}
                    >
                      <option value="">{loadingAdapterConfigs ? "Loading…" : "Select config"}</option>
                      {adapterConfigs.map((item) => (
                        <option key={item.artifact_id} value={item.artifact_id}>
                          {item.title} ({item.slug || item.artifact_id.slice(0, 8)} · v{item.version})
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="inline-actions">
                    <button
                      type="button"
                      className="ghost"
                      disabled={!selectedAdapterConfig}
                      onClick={() =>
                        selectedAdapterConfig &&
                        navigate(`/app/platform/video-adapter-configs/${selectedAdapterConfig.artifact_id}`)
                      }
                    >
                      Open config
                    </button>
                    <button type="button" className="ghost" onClick={() => void createAdapterConfigDraft()} disabled={!activeVideoConfig.adapter_id || loading}>
                      Create config
                    </button>
                    <button type="button" className="ghost" onClick={testConnection} disabled={!selectedAdapterConfig}>
                      Test connection
                    </button>
                  </div>
                </>
              ) : null}
              {renderingMode === "render_via_endpoint" ? (
                <>
                  <label>
                    Endpoint URL
                    <input
                      className="input"
                      placeholder="https://renderer.example.com/render"
                      value={activeVideoConfig.endpoint_url || ""}
                      onChange={(event) => updateVideo({ endpoint_url: event.target.value })}
                    />
                  </label>
                  <label>
                    Authorization credential ref (optional)
                    <input
                      className="input"
                      placeholder="secret_ref:<uuid> or credential name"
                      value={activeVideoConfig.credential_ref || ""}
                      onChange={(event) => updateVideo({ credential_ref: event.target.value })}
                    />
                  </label>
                  <label>
                    Timeout (seconds)
                    <input
                      className="input"
                      type="number"
                      min={5}
                      max={600}
                      value={activeVideoConfig.timeout_seconds ?? 90}
                      onChange={(event) => updateVideo({ timeout_seconds: Number(event.target.value) || 90 })}
                    />
                  </label>
                  <label>
                    Retry count
                    <input
                      className="input"
                      type="number"
                      min={0}
                      max={10}
                      value={activeVideoConfig.retry_count ?? 0}
                      onChange={(event) => updateVideo({ retry_count: Number(event.target.value) || 0 })}
                    />
                  </label>
                </>
              ) : null}
            </div>
            {renderingMode === "export_package_only" ? (
              <p className="muted small">No rendering is performed. Xyn produces a governed render package for export/use elsewhere.</p>
            ) : null}
            {renderingMode === "render_via_adapter" ? (
              <p className="muted small">Xyn produces a render package then invokes the selected adapter + canonical adapter config.</p>
            ) : null}
            {renderingMode === "render_via_endpoint" ? (
              <p className="muted small">
                Endpoint contract: <code>POST {'{endpoint_url}'}/render</code> with <code>{"{ render_package_id, render_package_hash, callback_url, options }"}</code>.
              </p>
            ) : null}
            {renderingMode === "render_via_model_config" ? (
              <InlineMessage
                tone="info"
                title="Feature gated mode"
                body="Direct model rendering mode is enabled by feature flag. Provider-specific execution is intentionally not implemented in this release."
              />
            ) : null}
            {loadingAdapters ? <p className="muted small">Loading adapter registry…</p> : null}
          </section>
        </div>
      ) : null}
    </>
  );
}
