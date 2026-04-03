import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  activateArtifact,
  applyApplicationPlan,
  createCampaign,
  executeAppPalettePrompt,
  getApplication,
  getApplicationPlan,
  getCampaign,
  getComposerState,
  getGoal,
  getArtifactConsoleDetailBySlug,
  getArtifactConsoleFilesBySlug,
  getCoordinationThread,
  getEmsDatasetSchemaTable,
  getEmsRegistrationsTimeseriesCanvasTable,
  getEmsStatusRollupCanvasTable,
  getRuntimeRunArtifactContent,
  getRuntimeRunCanvasApi,
  getAiRoutingStatus,
  listAiAgents,
  getWorkItem,
  getWorkQueue,
  dispatchNextWorkQueueItem,
  dispatchWorkItem,
  generateApplicationPlan,
  listGoals,
  listCoordinationThreads,
  listWorkItems,
  listAppBuilderArtifacts,
  listCampaigns,
  listRuntimeRunsCanvasApi,
  listWorkspacesCanvasApi,
  decideSolutionPlanningCheckpoint,
  finalizeSolutionChangeSession,
  generateSolutionChangePlan,
  prepareSolutionChangePreview,
  promoteSolutionChangeSession,
  publishDevTask,
  queryArtifactCanvasTable,
  queryEmsDevicesCanvasTable,
  queryEmsRegistrationsCanvasTable,
  requeueDevTask,
  regenerateSolutionPlanningOptions,
  replyToSolutionPlanningSession,
  reviewCoordinationThread,
  reviewGoal,
  retryDevTask,
  selectSolutionPlanningOption,
  stageSolutionChangeApply,
  updateApplication,
  updateApplicationPlan,
  updateCampaign,
  validateSolutionChangeSession,
  updateWorkItem,
} from "../../../api/xyn";
import type {
  AppBuilderArtifact,
  ApplicationDetail,
  ApplicationFactorySummary,
  ApplicationPlanDetail,
  CampaignDetail,
  CampaignListResponse,
  AppPaletteResult,
  AiAgent,
  AiAgentResolution,
  AiRoutingStatusResponse,
  ArtifactCanvasTableResponse,
  ArtifactConsoleDetailResponse,
  ArtifactConsoleFileRow,
  ArtifactActivationResponse,
  ArtifactStructuredQuery,
  CanvasTableResponse,
  ComposerState,
  CoordinationThreadDetail,
  CoordinationThreadSummary,
  GoalDetail,
  GoalListResponse,
  GoalSummary,
  LocalProvisionResponse,
  RuntimeRunDetail,
  RuntimeRunArtifactContent,
  RuntimeRunSummary,
  WorkQueueResponse,
  WorkItemDetail,
  WorkItemSummary,
  WorkspaceSummary,
} from "../../../api/types";
import CanvasRenderer from "../../../components/canvas/CanvasRenderer";
import InlineMessage from "../../../components/InlineMessage";
import Avatar from "../common/Avatar";
import { resolveUserProfile } from "../common/userProfile";
import type { OpenDetailTarget } from "../../../components/canvas/datasetEntityRegistry";
import { XYN_ENTITY_CHANGE_EVENT, inferEntityListPrompt, type EntityChangeDetail } from "../../utils/entityChangeEvents";
import { applyRuntimeEventToRunDetail, applyRuntimeEventToRuns, refreshRuntimeRunDetail, refreshRuntimeRunSummary, subscribeRuntimeEventStream } from "../../utils/runtimeEventStream";
import {
  deriveComposerViewModel,
} from "./composerViewModel";
import { readComposerStoredSelection, resolveComposerInitialSelection, writeComposerStoredSelection } from "./composerSelection";
import DraftDetailPage from "../../pages/DraftDetailPage";
import DraftsListPage from "../../pages/DraftsListPage";
import JobDetailPage from "../../pages/JobDetailPage";
import JobsListPage from "../../pages/JobsListPage";
import PlatformSettingsHubPage, { type HubSection } from "../../pages/PlatformSettingsHubPage";
import AccessControlPage from "../../pages/AccessControlPage";
import IdentityConfigurationPage from "../../pages/IdentityConfigurationPage";
import SecretConfigurationPage from "../../pages/SecretConfigurationPage";
import ActivityPage from "../../pages/ActivityPage";
import AIConfigPage from "../../pages/AIConfigPage";
import AIAgentRoutingPage from "../../pages/AIAgentRoutingPage";
import PlatformRenderingSettingsPage from "../../pages/PlatformRenderingSettingsPage";
import PlatformDeploySettingsPage from "../../pages/PlatformDeploySettingsPage";
import PlatformBrandingPage from "../../pages/PlatformBrandingPage";
import WorkspacesPage from "../../pages/WorkspacesPage";
import RulesBrowserPanel from "../rules/RulesBrowserPanel";
import { toWorkspacePath } from "../../routing/workspaceRouting";
import { SolutionDetailPanel, SolutionListPanel } from "../solutions/SolutionPanels";
import WorkspaceUnavailableState, { classifyWorkspaceUnavailableReason } from "../common/WorkspaceUnavailableState";
import { LINKED_SESSION_UPDATED_EVENT } from "../common/linkedChangeSessionRoute";

export type ConsolePanelKey =
  | "platform_settings"
  | "composer_detail"
  | "goal_list"
  | "goal_detail"
  | "application_plan_detail"
  | "application_detail"
  | "solution_list"
  | "solution_detail"
  | "campaign_list"
  | "campaign_detail"
  | "workspaces"
  | "thread_list"
  | "thread_detail"
  | "runs"
  | "drafts_list"
  | "draft_detail"
  | "jobs_list"
  | "job_detail"
  | "work_items"
  | "work_item_detail"
  | "palette_result"
  | "app_builder_artifact_list"
  | "run_detail"
  | "artifact_list"
  | "artifact_detail"
  | "artifact_raw_json"
  | "artifact_files"
  | "rules_browser"
  | "ems_devices"
  | "ems_registrations"
  | "ems_device_status_rollup"
  | "ems_registrations_timeseries"
  | "ems_dataset_schema"
  | "ems_unregistered_devices"
  | "ems_registrations_time"
  | "ems_device_statuses"
  | "record_detail"
  | "local_provision_result";

export type ConsolePanelSpec = {
  panel_id?: string;
  panel_type?: "table" | "detail" | "report";
  instance_key?: string;
  title?: string;
  active_group_id?: string | null;
  open_in?: "current_panel" | "new_panel" | "side_by_side";
  return_to_panel_id?: string;
  key: ConsolePanelKey;
  params?: Record<string, unknown>;
};

type ComposerExecutionPhase = "planned" | "staged" | "preview_ready" | "ready_for_promotion" | "failed";

type ComposerExecutionActionKey = "stage-apply" | "prepare-preview" | "validate" | "promote" | "finalize";

type PanelProps = {
  onOpenPanel: (panelKey: ConsolePanelKey, params?: Record<string, unknown>) => void;
};

function titleCaseLabel(value: string): string {
  return String(value || "")
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatPanelTimestamp(value?: string | null): string {
  const parsed = new Date(String(value || ""));
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString();
}

function deriveComposerExecutionPhase(
  executionStatus: string,
  previewStatus: string,
  validationStatus: string,
): ComposerExecutionPhase {
  const execution = String(executionStatus || "").trim().toLowerCase();
  const preview = String(previewStatus || "").trim().toLowerCase();
  const validation = String(validationStatus || "").trim().toLowerCase();
  if (execution === "failed" || preview === "failed" || validation === "failed") return "failed";
  if (
    execution === "ready_for_promotion"
    || execution === "validated"
    || execution === "completed"
    || execution === "finalized"
    || execution === "archived"
    || validation === "passed"
    || validation === "validated"
    || validation === "ready_for_promotion"
    || validation === "success"
  ) {
    return "ready_for_promotion";
  }
  if (
    execution === "preview_ready"
    || preview === "ready"
    || preview === "prepared"
    || preview === "preview_ready"
  ) {
    return "preview_ready";
  }
  if (
    execution === "staged"
    || execution === "applied"
    || execution === "preview_preparing"
    || execution === "validating"
  ) {
    return "staged";
  }
  return "planned";
}

function executionPhaseLabel(phase: ComposerExecutionPhase): string {
  if (phase === "planned") return "Not Started";
  if (phase === "staged") return "Staged";
  if (phase === "preview_ready") return "Preview Ready";
  if (phase === "ready_for_promotion") return "Validated";
  return "Failed";
}

function executionPhaseNextActionLabel(phase: ComposerExecutionPhase): string {
  if (phase === "planned") return "Apply planned changes";
  if (phase === "staged") return "Prepare preview environment";
  if (phase === "preview_ready") return "Validate changes";
  if (phase === "ready_for_promotion") return "Finalize session";
  return "Retry the failed execution step";
}

function defaultPrimaryActionForPhase(phase: ComposerExecutionPhase): ComposerExecutionActionKey {
  if (phase === "staged") return "prepare-preview";
  if (phase === "preview_ready") return "validate";
  if (phase === "ready_for_promotion") return "promote";
  return "stage-apply";
}

function briefReviewLabel(item: Pick<WorkItemSummary, "execution_brief_review" | "execution_queue">): string {
  const review = item.execution_brief_review;
  const queue = item.execution_queue;
  if (!review?.has_brief) return "No brief";
  const state = titleCaseLabel(review.review_state || "draft");
  if (queue?.dispatched) return `${state} · dispatched`;
  if (queue?.queue_ready) return `${state} · ready for dispatch`;
  return review.blocked || queue?.blocked ? `${state} · blocked` : state;
}

function BriefReviewSummary({ item }: { item: Pick<WorkItemSummary, "execution_brief_review" | "execution_queue"> }) {
  const review = item.execution_brief_review;
  const queue = item.execution_queue;
  if (!review?.has_brief) {
    if (queue?.queue_ready) return <span>Ready for dispatch</span>;
    if (queue?.dispatched) return <span>Dispatched</span>;
    return <span className="muted">No brief</span>;
  }
  return (
    <div>
      <div>{briefReviewLabel(item)}</div>
      <div className="muted small">{queue?.message || review.blocked_message || "—"}</div>
    </div>
  );
}

function executionRunLabel(item: Pick<WorkItemSummary, "execution_run">): string {
  const execution = item.execution_run;
  if (!execution?.has_run) return "Not run";
  return titleCaseLabel(execution.state || execution.raw_status || "unknown");
}

function ExecutionRunSummary({ item }: { item: Pick<WorkItemSummary, "execution_run" | "execution_recovery"> }) {
  const execution = item.execution_run;
  if (!execution?.has_run) {
    if (item.execution_recovery?.last_failure) {
      return (
        <div>
          <div>Not run</div>
          <div className="muted small">{item.execution_recovery.message}</div>
        </div>
      );
    }
    return <span className="muted">Not run</span>;
  }
  const detailParts = [
    execution.validation_status ? titleCaseLabel(execution.validation_status) : "",
    execution.artifact_count ? `${execution.artifact_count} artifact${execution.artifact_count === 1 ? "" : "s"}` : "",
    item.execution_recovery?.retryable ? "Retryable" : "",
  ].filter(Boolean);
  return (
    <div>
      <div>{executionRunLabel(item)}</div>
      <div className="muted small">{detailParts.length ? detailParts.join(" · ") : execution.message}</div>
    </div>
  );
}

function ChangeSetSummary({ item }: { item: Pick<WorkItemSummary, "change_set"> }) {
  const changeSet = item.change_set;
  if (!changeSet?.available) return <span className="muted">Unavailable</span>;
  if (!changeSet.has_changes) return <span className="muted">No changes</span>;
  const fileCount = changeSet.changed_file_count || changeSet.files.length || 0;
  const filePreview = changeSet.files
    .slice(0, 2)
    .map((file) => file.path)
    .filter(Boolean)
    .join(", ");
  return (
    <div>
      <div>{fileCount} file{fileCount === 1 ? "" : "s"} changed</div>
      <div className="muted small">{filePreview || changeSet.message}</div>
    </div>
  );
}

function PublishSummary({ item }: { item: Pick<WorkItemSummary, "publish_state"> }) {
  const publish = item.publish_state;
  if (!publish?.branch && !publish?.commit) return <span className="muted">Not published</span>;
  const label = publish.push_status === "pushed" ? "Pushed" : publish.commit ? "Committed" : titleCaseLabel(publish.status || "idle");
  return (
    <div>
      <div>{label}</div>
      <div className="muted small">{publish.branch || publish.message}</div>
    </div>
  );
}

function routingPurposeRow(routing: AiAgentResolution[], purpose: string): AiAgentResolution | null {
  return routing.find((row) => String(row.purpose || "").trim().toLowerCase() === purpose) || null;
}

function workItemDispatchPurpose(item: Pick<WorkItemDetail, "task_type" | "intent_type" | "context_purpose"> | null): "planning" | "coding" {
  if (!item) return "coding";
  const taskType = String(item.task_type || "").trim().toLowerCase();
  const intentType = String(item.intent_type || "").trim().toLowerCase();
  const contextPurpose = String(item.context_purpose || "").trim().toLowerCase();
  if (
    taskType.includes("plan")
    || intentType.includes("plan")
    || contextPurpose === "planning"
  ) {
    return "planning";
  }
  return "coding";
}

function routingResolutionLabel(row: AiAgentResolution | null, purpose: "planning" | "coding"): string {
  if (!row) return "Unresolved routing";
  if (row.resolution_source === "explicit") return `Explicit ${purpose} assignment`;
  if (row.resolution_source === "default_fallback") return "Default fallback";
  return titleCaseLabel(row.resolution_source || "unresolved");
}

type CanvasQuery = {
  entity: string;
  filters: Array<{ field: string; op: string; value: unknown }>;
  sort: Array<{ field: string; dir: "asc" | "desc" }>;
  limit: number;
  offset: number;
};

type ContextEmitter = (context: Record<string, unknown> | null) => void;

function PaletteResultPanel({
  result,
  prompt,
  error,
  workspaceId,
}: {
  result?: AppPaletteResult;
  prompt?: string;
  error?: string;
  workspaceId: string;
}) {
  const [liveResult, setLiveResult] = useState<AppPaletteResult | undefined>(result);
  const [refreshing, setRefreshing] = useState(false);
  const listPrompt = useMemo(() => inferEntityListPrompt(String(prompt || "")), [prompt]);

  useEffect(() => {
    setLiveResult(result);
  }, [result]);

  useEffect(() => {
    if (!workspaceId || !listPrompt) return;
    let active = true;
    const onEntityChange = async (event: Event) => {
      const detail = (event as CustomEvent<EntityChangeDetail>).detail;
      if (!detail || detail.entityKey !== listPrompt.entityKey) return;
      try {
        setRefreshing(true);
        const refreshed = await executeAppPalettePrompt(workspaceId, { prompt: listPrompt.prompt });
        if (!active || refreshed.kind !== "table") return;
        setLiveResult(refreshed);
      } finally {
        if (active) setRefreshing(false);
      }
    };
    window.addEventListener(XYN_ENTITY_CHANGE_EVENT, onEntityChange as EventListener);
    return () => {
      active = false;
      window.removeEventListener(XYN_ENTITY_CHANGE_EVENT, onEntityChange as EventListener);
    };
  }, [listPrompt, workspaceId]);

  const safeResult = liveResult || { kind: "table", columns: [], rows: [] };
  const columns = Array.isArray(safeResult.columns) ? safeResult.columns : [];
  const rows = Array.isArray(safeResult.rows) ? safeResult.rows : [];
  const labels = Array.isArray(safeResult.labels) ? safeResult.labels : [];
  const values = Array.isArray(safeResult.values) ? safeResult.values : [];
  const meta = safeResult.meta && typeof safeResult.meta === "object" ? safeResult.meta : {};
  const contextPackSlugs = Array.isArray(meta.context_pack_slugs)
    ? meta.context_pack_slugs.map((value) => String(value || "").trim()).filter(Boolean)
    : [];
  const warnings = Array.isArray(meta.context_warnings)
    ? meta.context_warnings.map((value) => String(value || "").trim()).filter(Boolean)
    : [];
  return (
    <>
      <div className="page-header">
        <div>
          <h2>Palette Result</h2>
          <p className="muted">{String(safeResult.text || error || "Command executed.")}</p>
        </div>
      </div>
      <section className="card">
        <div className="detail-grid">
          <div>
            <div className="field-label">Prompt</div>
            <div className="field-value">{String(prompt || "—")}</div>
          </div>
          <div>
            <div className="field-label">Result Kind</div>
            <div className="field-value">{String(safeResult.kind || "—")}</div>
          </div>
          <div>
            <div className="field-label">Resolved Context Packs</div>
            <div className="field-value">{contextPackSlugs.length ? contextPackSlugs.join(", ") : "—"}</div>
          </div>
          {listPrompt ? (
            <div>
              <div className="field-label">Auto Refresh</div>
              <div className="field-value">{refreshing ? "Refreshing…" : "Watching entity changes"}</div>
            </div>
          ) : null}
        </div>
        {error ? <InlineMessage tone="error" title="Palette request failed" body={error} /> : null}
        {warnings.length ? <InlineMessage tone="warn" title="Warnings" body={warnings.join(" ")} /> : null}
        {safeResult.kind === "bar_chart" && labels.length > 0 ? (
          <div className="card" style={{ marginTop: 12, marginBottom: 12 }}>
            <div className="card-header">
              <h3>{String(safeResult.title || "Report")}</h3>
            </div>
            <div className="chart-bars">
              {labels.map((label, index) => {
                const numeric = Number(values[index] ?? 0);
                const maxValue = Math.max(...values.map((value) => Number(value || 0)), 1);
                const width = `${Math.max((numeric / maxValue) * 100, 6)}%`;
                return (
                  <div className="chart-row" key={`${label}-${index}`}>
                    <div className="chart-label">{label}</div>
                    <div className="chart-track">
                      <div className="chart-bar" style={{ width }} />
                    </div>
                    <div className="chart-value">{numeric}</div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={String(row.id || index)}>
                  {columns.map((column) => (
                    <td key={column}>{String(row[column] ?? "")}</td>
                  ))}
                </tr>
              ))}
              {!rows.length ? (
                <tr>
                  <td colSpan={Math.max(columns.length, 1)} className="muted">
                    No rows returned.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function AppBuilderArtifactListPanel({ workspaceId, kind }: { workspaceId: string; kind?: string }) {
  const [items, setItems] = useState<AppBuilderArtifact[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    if (!workspaceId) {
      setItems([]);
      setError("Workspace context is required.");
      return;
    }
    void (async () => {
      try {
        setLoading(true);
        setError(null);
        const payload = await listAppBuilderArtifacts(workspaceId, { kind, limit: 50 });
        if (!active) return;
        setItems(payload);
      } catch (err) {
        if (!active) return;
        setError((err as Error).message);
        setItems([]);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [kind, workspaceId]);

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Artifacts</h2>
          <p className="muted">
            {kind ? `Generated artifacts filtered by kind=${kind}.` : "Generated artifacts from the app-builder runtime."}
          </p>
        </div>
      </div>
      {error ? <InlineMessage tone="error" title="Request failed" body={error} /> : null}
      <section className="card">
        <p className="muted">Rows: {items.length}{loading ? " (loading...)" : ""}</p>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Kind</th>
                <th>Scope</th>
                <th>Sync</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{item.name}</td>
                  <td>{item.kind}</td>
                  <td>{String(item.storage_scope || "")}</td>
                  <td>{String(item.sync_state || "")}</td>
                  <td>{String(item.created_at || "")}</td>
                </tr>
              ))}
              {!loading && !items.length ? (
                <tr>
                  <td colSpan={5} className="muted">
                    No artifacts found.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

const WORKSPACES_DATASET_COLUMNS = [
  { key: "id", label: "ID", type: "string", filterable: true, sortable: true },
  { key: "slug", label: "Slug", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "name", label: "Name", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "org_name", label: "Org Name", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "kind", label: "Kind", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "lifecycle_stage", label: "Stage", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "auth_mode", label: "Auth Mode", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "parent_workspace_id", label: "Parent Workspace", type: "string", filterable: true, sortable: true, searchable: true },
] as const;

const RUNS_DATASET_COLUMNS = [
  { key: "id", label: "Run ID", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "work_item_id", label: "Work Item", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "worker_type", label: "Worker", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "status", label: "Status", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "elapsed_time", label: "Elapsed", type: "string", filterable: true, sortable: true },
  { key: "heartbeat_freshness", label: "Heartbeat", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "summary", label: "Summary", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "started_at", label: "Started", type: "datetime", filterable: true, sortable: true },
  { key: "created_at", label: "Created", type: "datetime", filterable: true, sortable: true },
] as const;

function toIso(value?: string | null): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toISOString();
}

function formatDuration(totalSeconds?: number | null): string {
  if (totalSeconds == null || Number.isNaN(totalSeconds)) return "—";
  if (totalSeconds < 60) return `${Math.max(0, totalSeconds)}s`;
  if (totalSeconds < 3600) return `${Math.floor(totalSeconds / 60)}m ${totalSeconds % 60}s`;
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

function resolveRelativeDate(raw: unknown): Date | null {
  const token = String(raw || "").trim().toLowerCase();
  if (!token) return null;
  const relative = token.match(/^now-(\d+)([mhd])$/);
  if (relative) {
    const amount = Math.max(0, Number(relative[1]) || 0);
    const unit = relative[2];
    const now = Date.now();
    if (unit === "m") return new Date(now - amount * 60_000);
    if (unit === "h") return new Date(now - amount * 3_600_000);
    return new Date(now - amount * 86_400_000);
  }
  const absolute = new Date(token);
  if (Number.isNaN(absolute.getTime())) return null;
  return absolute;
}

function compareValues(left: unknown, right: unknown, type?: string): number {
  if (type === "datetime") {
    const leftDate = resolveRelativeDate(left);
    const rightDate = resolveRelativeDate(right);
    const leftTime = leftDate ? leftDate.getTime() : 0;
    const rightTime = rightDate ? rightDate.getTime() : 0;
    return leftTime - rightTime;
  }
  const leftVal = typeof left === "string" ? left.toLowerCase() : left;
  const rightVal = typeof right === "string" ? right.toLowerCase() : right;
  if (leftVal == null && rightVal == null) return 0;
  if (leftVal == null) return -1;
  if (rightVal == null) return 1;
  if (leftVal < rightVal) return -1;
  if (leftVal > rightVal) return 1;
  return 0;
}

function rowMatches(row: Record<string, unknown>, filter: { field: string; op: string; value: unknown }, columns: ReadonlyArray<{ key: string; type: string }>): boolean {
  const field = String(filter.field || "").trim();
  const op = String(filter.op || "eq").trim().toLowerCase();
  const value = row[field];
  const schema = columns.find((entry) => entry.key === field);
  const type = schema?.type || "string";
  if (type === "datetime") {
    const left = resolveRelativeDate(value);
    const right = resolveRelativeDate(filter.value);
    if (!left || !right) return false;
    const cmp = left.getTime() - right.getTime();
    if (op === "eq") return cmp === 0;
    if (op === "neq") return cmp !== 0;
    if (op === "gte") return cmp >= 0;
    if (op === "lte") return cmp <= 0;
    if (op === "gt") return cmp > 0;
    if (op === "lt") return cmp < 0;
    return false;
  }
  const left = value == null ? "" : String(value).toLowerCase();
  const right = filter.value == null ? "" : String(filter.value).toLowerCase();
  if (op === "eq") return left === right;
  if (op === "neq") return left !== right;
  if (op === "contains") return left.includes(right);
  if (op === "in") {
    if (Array.isArray(filter.value)) return filter.value.map((entry) => String(entry).toLowerCase()).includes(left);
    return left === right;
  }
  if (op === "gte" || op === "lte" || op === "gt" || op === "lt") {
    const cmp = compareValues(value, filter.value, type);
    if (op === "gte") return cmp >= 0;
    if (op === "lte") return cmp <= 0;
    if (op === "gt") return cmp > 0;
    if (op === "lt") return cmp < 0;
  }
  return false;
}

function baseArtifactQuery(): ArtifactStructuredQuery {
  return { entity: "artifacts", filters: [], sort: [{ field: "updated_at", dir: "desc" }], limit: 50, offset: 0 };
}

function emitTableContext({
  onContextChange,
  panel,
  payload,
  query,
  selectedRowIds,
  focusedRowId,
  rowOrderIds,
}: {
  onContextChange?: ContextEmitter;
  panel: ConsolePanelSpec | null;
  payload: CanvasTableResponse | ArtifactCanvasTableResponse | null;
  query: CanvasQuery | ArtifactStructuredQuery;
  selectedRowIds: string[];
  focusedRowId: string | null;
  rowOrderIds: string[];
}) {
  if (!onContextChange || !panel?.panel_id || !payload) return;
  onContextChange({
    view_type: "table",
    dataset: {
      name: payload.dataset.name,
      primary_key: payload.dataset.primary_key,
      columns: payload.dataset.columns,
    },
    query,
    selection: {
      selected_row_ids: selectedRowIds,
      focused_row_id: focusedRowId,
      row_order_ids: rowOrderIds,
    },
    pagination: {
      limit: Number(query.limit || 50),
      offset: Number(query.offset || 0),
      total_count: Number(payload.dataset.total_count || 0),
    },
    ui: {
      active_panel_id: panel.panel_id,
      panel_id: panel.panel_id,
      panel_type: panel.panel_type || "table",
      instance_key: panel.instance_key || payload.dataset.name,
      active_group_id: panel.active_group_id || null,
      layout_engine: "simple",
    },
  });
}

function WorkspacesPanel({
  query,
  queryError,
  panel,
  onContextChange,
  onOpenDetail,
  onTitleChange,
}: {
  query?: CanvasQuery;
  queryError?: string;
  panel: ConsolePanelSpec | null;
  onContextChange?: ContextEmitter;
  onOpenDetail: (target: OpenDetailTarget, row: Record<string, unknown>) => void;
  onTitleChange?: (title: string) => void;
}) {
  const [payload, setPayload] = useState<CanvasTableResponse | null>(null);
  const [runs, setRuns] = useState<RuntimeRunSummary[]>([]);
  const [activeQuery, setActiveQuery] = useState<CanvasQuery>({
    entity: "workspaces",
    filters: [],
    sort: [{ field: "name", dir: "asc" }],
    limit: 50,
    offset: 0,
  });
  const [selectedRowIds, setSelectedRowIds] = useState<string[]>([]);
  const [focusedRowId, setFocusedRowId] = useState<string | null>(null);
  const [rowOrderIds, setRowOrderIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [degradedMode, setDegradedMode] = useState(false);
  const [, setClockTick] = useState(0);

  useEffect(() => {
    if (query) {
      setActiveQuery(query);
      return;
    }
    setActiveQuery({ entity: "workspaces", filters: [], sort: [{ field: "name", dir: "asc" }], limit: 50, offset: 0 });
  }, [query]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const response = await listWorkspacesCanvasApi();
        if (!active) return;
        const baseRows: Array<Record<string, unknown>> = (response.workspaces || []).map((workspace: WorkspaceSummary) => ({
          id: workspace.id,
          slug: workspace.slug,
          name: workspace.name,
          org_name: workspace.org_name || workspace.name,
          kind: workspace.kind || "",
          lifecycle_stage: workspace.lifecycle_stage || "",
          auth_mode: workspace.auth_mode || "",
          parent_workspace_id: workspace.parent_workspace_id || "",
        }));
        let rows = [...baseRows];
        for (const filter of activeQuery.filters || []) {
          rows = rows.filter((row) => rowMatches(row, filter, WORKSPACES_DATASET_COLUMNS as unknown as Array<{ key: string; type: string }>));
        }
        for (const sortRow of [...(activeQuery.sort || [])].reverse()) {
          const field = String(sortRow.field || "");
          const dir = sortRow.dir === "asc" ? "asc" : "desc";
          rows.sort((left, right) => {
            const column = WORKSPACES_DATASET_COLUMNS.find((entry) => entry.key === field);
            const cmp = compareValues(left[field], right[field], column?.type);
            return dir === "asc" ? cmp : -cmp;
          });
        }
        const offset = Math.max(0, Number(activeQuery.offset || 0));
        const limit = Math.max(1, Number(activeQuery.limit || 50));
        const paged = rows.slice(offset, offset + limit);
        const nextPayload: CanvasTableResponse = {
          type: "canvas.table",
          title: "Workspaces",
          dataset: {
            name: "workspaces",
            primary_key: "id",
            columns: [...WORKSPACES_DATASET_COLUMNS],
            rows: paged,
            total_count: rows.length,
          },
          query: activeQuery,
        };
        setPayload(nextPayload);
        setRowOrderIds(paged.map((row) => String(row.id || "")));
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load workspaces");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [activeQuery]);

  useEffect(() => {
    emitTableContext({ onContextChange, panel, payload, query: activeQuery, selectedRowIds, focusedRowId, rowOrderIds });
  }, [activeQuery, focusedRowId, onContextChange, panel, payload, rowOrderIds, selectedRowIds]);

  useEffect(() => {
    if (!onTitleChange) return;
    if (!payload?.title) return;
    onTitleChange(String(payload.title));
  }, [onTitleChange, payload?.title]);

  if (loading) return <p className="muted">Loading workspaces…</p>;
  if (queryError) return <p className="muted">{queryError}</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">No workspaces found.</p>;

  return (
    <CanvasRenderer
      payload={payload}
      query={activeQuery}
      onSort={(field, sortable) => {
        if (!sortable) return;
        const same = activeQuery.sort?.[0]?.field === field;
        const dir = same && activeQuery.sort?.[0]?.dir === "asc" ? "desc" : "asc";
        setActiveQuery((current) => ({ ...current, sort: [{ field, dir }] }));
      }}
      onRowActivate={(rowId) => {
        setSelectedRowIds([rowId]);
        setFocusedRowId(rowId);
      }}
      onOpenDetail={onOpenDetail}
    />
  );
}

function WorkItemsPanel({
  panel,
  workspaceId,
  onContextChange,
  onOpenDetail,
  onTitleChange,
}: {
  panel: ConsolePanelSpec | null;
  workspaceId?: string;
  onContextChange?: ContextEmitter;
  onOpenDetail: (target: OpenDetailTarget, row: Record<string, unknown>) => void;
  onTitleChange?: (title: string) => void;
}) {
  const [items, setItems] = useState<WorkItemSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await listWorkItems(undefined, undefined, undefined, undefined, workspaceId);
        if (!active) return;
        setItems(next.work_items || []);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load work items");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const payload = useMemo<CanvasTableResponse>(() => ({
    type: "canvas.table",
    title: "Work Items",
    dataset: {
      name: "work_items",
      primary_key: "id",
      columns: [
        { key: "title", label: "Title", type: "string", sortable: true, searchable: true, filterable: true },
        { key: "status", label: "Status", type: "string", sortable: true, filterable: true, searchable: true },
        { key: "work_item_id", label: "Work Item", type: "string", sortable: true, searchable: true, filterable: true },
        { key: "target_repo", label: "Repo", type: "string", sortable: true, searchable: true, filterable: true },
        { key: "updated_at", label: "Updated", type: "datetime", sortable: true, filterable: true },
      ],
      rows: items.map((item) => ({
        id: item.id,
        title: item.title,
        status: item.status,
        work_item_id: item.work_item_id || "",
        target_repo: item.target_repo || "",
        updated_at: item.updated_at || "",
      })),
      total_count: items.length,
    },
    query: { entity: "work_items", filters: [], sort: [{ field: "updated_at", dir: "desc" }], limit: 50, offset: 0 },
  }), [items]);

  useEffect(() => {
    if (!onContextChange || !panel?.panel_id) return;
    onContextChange({
      view_type: "table",
      dataset: payload.dataset,
      pagination: { limit: 50, offset: 0, total_count: items.length },
      ui: {
        active_panel_id: panel.panel_id,
        panel_id: panel.panel_id,
        panel_type: panel.panel_type || "table",
        instance_key: panel.instance_key || "work_items",
        active_group_id: panel.active_group_id || null,
        layout_engine: "simple",
      },
    });
  }, [items.length, onContextChange, panel, payload.dataset]);

  useEffect(() => {
    if (!onTitleChange) return;
    onTitleChange("Work Items");
  }, [onTitleChange]);

  if (loading) return <p className="muted">Loading work items…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  return (
    <CanvasRenderer
      payload={payload}
      query={payload.query}
      onOpenDetail={onOpenDetail}
      onRowActivate={() => {
        // selection is informational only for now
      }}
    />
  );
}

function GoalListPanel({
  workspaceId,
  onOpenPanel,
  onTitleChange,
}: {
  workspaceId: string;
  onTitleChange?: (title: string) => void;
} & PanelProps) {
  const [payload, setPayload] = useState<GoalListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await listGoals(workspaceId);
        if (!active) return;
        setPayload(next);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load goals");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [workspaceId]);

  useEffect(() => {
    onTitleChange?.("Goals");
  }, [onTitleChange]);

  if (loading) return <p className="muted">Loading goals…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  const goals = payload?.goals || [];
  const portfolioState = payload?.portfolio_state;
  const recommendedGoal = portfolioState?.recommended_goal;
  const portfolioInsights = portfolioState?.insights || [];
  return (
    <div className="panel-section-stack">
      {portfolioState ? (
        <section className="card">
          <div className="detail-grid">
            <div><div className="field-label">Total Goals</div><div className="field-value">{portfolioState.goals.length}</div></div>
            <div><div className="field-label">Active Goals</div><div className="field-value">{portfolioState.goals.filter((goal) => goal.health_status === "active").length}</div></div>
            <div><div className="field-label">Blocked Goals</div><div className="field-value">{portfolioState.goals.filter((goal) => goal.health_status === "blocked").length}</div></div>
            <div><div className="field-label">Recent Execution</div><div className="field-value">{portfolioState.goals.reduce((sum, goal) => sum + (goal.recent_execution_count || 0), 0)}</div></div>
          </div>
          {recommendedGoal ? (
            <InlineMessage
              tone="info"
              title={`Recommended Goal: ${recommendedGoal.title}`}
              body={`${recommendedGoal.summary}${recommendedGoal.reasoning ? ` ${recommendedGoal.reasoning}` : ""}`}
            />
          ) : null}
          {portfolioInsights.length ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Portfolio Insights</div>
              <ul className="bulleted-list">
                {portfolioInsights.slice(0, 3).map((insight) => (
                  <li key={insight.key}>{insight.summary}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      ) : null}
      <section className="card">
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th>Coordination</th>
                <th>Threads</th>
                <th>Work Items</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {goals.map((goal) => (
                <tr key={goal.id}>
                  <td>{goal.title}</td>
                  <td>{goal.planning_status}</td>
                  <td>{goal.coordination_priority?.value || goal.priority}</td>
                  <td>{goal.thread_count}</td>
                  <td>{goal.work_item_count}</td>
                  <td>
                    <button type="button" className="ghost sm" onClick={() => onOpenPanel("goal_detail", { goal_id: goal.id })}>
                      Open
                    </button>
                  </td>
                </tr>
              ))}
              {!goals.length ? (
                <tr>
                  <td colSpan={6} className="muted">No goals found.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function CampaignListPanel({
  workspaceId,
  onOpenPanel,
  onTitleChange,
  autoCreate,
}: {
  workspaceId: string;
  onTitleChange?: (title: string) => void;
  autoCreate?: boolean;
} & PanelProps) {
  const [payload, setPayload] = useState<CampaignListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(Boolean(autoCreate));
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [campaignType, setCampaignType] = useState("generic");
  const [submitting, setSubmitting] = useState(false);

  async function loadCampaigns() {
    setLoading(true);
    setError(null);
    try {
      const next = await listCampaigns(workspaceId);
      setPayload(next);
      const defaultType =
        next.campaign_types.find((row) => row.key === "generic")?.key ||
        next.campaign_types[0]?.key ||
        "generic";
      setCampaignType(defaultType);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load campaigns");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadCampaigns();
  }, [workspaceId]);

  useEffect(() => {
    if (autoCreate) setCreateOpen(true);
  }, [autoCreate]);

  useEffect(() => {
    onTitleChange?.("Campaigns");
  }, [onTitleChange]);

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await createCampaign({
        workspace_id: workspaceId,
        name: name.trim(),
        campaign_type: campaignType,
        description: description.trim() || undefined,
      });
      setName("");
      setDescription("");
      setCreateOpen(false);
      await loadCampaigns();
      onOpenPanel("campaign_detail", { campaign_id: created.id, workspace_id: workspaceId });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create campaign");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <p className="muted">Loading campaigns…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  const campaigns = payload?.campaigns || [];
  const campaignTypes = payload?.campaign_types || [{ key: "generic", label: "Generic Campaign", description: "" }];
  return (
    <div className="panel-section-stack">
      <section className="card">
        <div className="panel-row-actions">
          <button type="button" className="ghost sm" onClick={() => setCreateOpen((current) => !current)}>
            {createOpen ? "Cancel" : "Create campaign"}
          </button>
        </div>
        {createOpen ? (
          <form className="panel-inline-form" onSubmit={handleCreate}>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Campaign name"
              aria-label="Campaign name"
              required
            />
            <select value={campaignType} onChange={(event) => setCampaignType(event.target.value)} aria-label="Campaign type">
              {campaignTypes.map((type) => (
                <option key={type.key} value={type.key}>
                  {type.label}
                </option>
              ))}
            </select>
            <input
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Description (optional)"
              aria-label="Campaign description"
            />
            <button type="submit" className="primary sm" disabled={submitting || !name.trim()}>
              {submitting ? "Creating…" : "Create"}
            </button>
          </form>
        ) : null}
      </section>
      <section className="card">
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Status</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((campaign) => (
                <tr key={campaign.id}>
                  <td>{campaign.name}</td>
                  <td>{campaign.campaign_type}</td>
                  <td>{campaign.status}</td>
                  <td>{formatPanelTimestamp(campaign.updated_at)}</td>
                  <td>
                    <button type="button" className="ghost sm" onClick={() => onOpenPanel("campaign_detail", { campaign_id: campaign.id, workspace_id: workspaceId })}>
                      Open
                    </button>
                  </td>
                </tr>
              ))}
              {!campaigns.length ? (
                <tr>
                  <td colSpan={5} className="muted">No campaigns found in this workspace.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function CampaignDetailPanel({
  campaignId,
  workspaceId,
  onTitleChange,
}: {
  campaignId: string;
  workspaceId: string;
  onTitleChange?: (title: string) => void;
}) {
  const [payload, setPayload] = useState<CampaignDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState("draft");

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await getCampaign(campaignId, workspaceId);
        if (!active) return;
        setPayload(next);
        setName(next.name || "");
        setDescription(next.description || "");
        setStatus(next.status || "draft");
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load campaign");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [campaignId, workspaceId]);

  useEffect(() => {
    onTitleChange?.(payload?.name || "Campaign");
  }, [onTitleChange, payload?.name]);

  async function handleSave(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!payload || saving) return;
    setSaving(true);
    setError(null);
    try {
      const next = await updateCampaign(payload.id, {
        workspace_id: workspaceId,
        name: name.trim(),
        description: description.trim(),
        status,
      });
      setPayload(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save campaign");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <p className="muted">Loading campaign…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">Campaign not found.</p>;

  return (
    <div className="panel-section-stack">
      <section className="card">
        <form className="panel-inline-form" onSubmit={handleSave}>
          <input value={name} onChange={(event) => setName(event.target.value)} aria-label="Campaign name" required />
          <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Campaign status">
            <option value="draft">Draft</option>
            <option value="active">Active</option>
            <option value="paused">Paused</option>
            <option value="completed">Completed</option>
            <option value="archived">Archived</option>
          </select>
          <input value={description} onChange={(event) => setDescription(event.target.value)} aria-label="Campaign description" placeholder="Description" />
          <button type="submit" className="primary sm" disabled={saving || !name.trim()}>
            {saving ? "Saving…" : "Save"}
          </button>
        </form>
      </section>
      <section className="card">
        <div className="detail-grid">
          <div><div className="field-label">Campaign ID</div><div className="field-value">{payload.id}</div></div>
          <div><div className="field-label">Workspace</div><div className="field-value">{workspaceId}</div></div>
          <div><div className="field-label">Slug</div><div className="field-value">{payload.slug}</div></div>
          <div><div className="field-label">Type</div><div className="field-value">{payload.campaign_type}</div></div>
          <div><div className="field-label">Created</div><div className="field-value">{formatPanelTimestamp(payload.created_at)}</div></div>
          <div><div className="field-label">Updated</div><div className="field-value">{formatPanelTimestamp(payload.updated_at)}</div></div>
        </div>
      </section>
    </div>
  );
}

function GoalDetailPanel({
  goalId,
  workspaceId,
  onOpenPanel,
  onTitleChange,
}: {
  goalId: string;
  workspaceId: string;
  onTitleChange?: (title: string) => void;
} & PanelProps) {
  const [payload, setPayload] = useState<GoalDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [unavailableReason, setUnavailableReason] = useState<"not_found" | "access_denied" | null>(null);
  const [actionState, setActionState] = useState<{ status: "idle" | "submitting"; message: string | null }>({
    status: "idle",
    message: null,
  });
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        setUnavailableReason(null);
        setPayload(null);
        const next = await getGoal(goalId);
        if (!active) return;
        if (next.workspace_id && workspaceId && String(next.workspace_id) !== String(workspaceId)) {
          setUnavailableReason("not_found");
          return;
        }
        setPayload(next);
      } catch (err) {
        if (!active) return;
        const message = err instanceof Error ? err.message : "Failed to load goal";
        const reason = classifyWorkspaceUnavailableReason(message);
        if (reason === "not_found" || reason === "access_denied") {
          setUnavailableReason(reason);
          setError(null);
          return;
        }
        setError(message);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [goalId, workspaceId]);

  useEffect(() => {
    onTitleChange?.(payload?.title || "Goal");
  }, [onTitleChange, payload?.title]);

  if (loading) return <p className="muted">Loading goal…</p>;
  if (unavailableReason || !payload) {
    return (
      <WorkspaceUnavailableState
        itemLabel="Goal"
        workspaceLabel={workspaceId || "this workspace"}
        reason={unavailableReason || "not_found"}
        onOpenList={() => onOpenPanel("goal_list")}
        openListLabel="Open Goals"
      />
    );
  }
  if (error) return <p className="danger-text">{error}</p>;

  const recommendationActions = Array.isArray(payload.recommendation?.actions) ? payload.recommendation?.actions : [];
  const queueableAction = recommendationActions.find((action) => action.type === "approve_and_queue");
  const reviewThreadAction = recommendationActions.find((action) => action.type === "review_thread");
  const recommendationId = payload.recommendation?.recommendation_id || null;
  const reviewWorkItemId =
    payload.recommendation?.work_item_id ||
    payload.recommendation?.recommended_work_items?.[0]?.id ||
    null;

  async function handleApproveAndQueue() {
    try {
      setActionState({ status: "submitting", message: null });
      const response = await reviewGoal(goalId, "approve_and_queue", recommendationId);
      setPayload(response.goal);
      setActionState({
        status: "idle",
        message:
          response.status === "approved"
            ? "Approved and queued the recommended slice."
            : response.status === "already_queued"
              ? "The recommended slice is already queued."
              : response.status === "no_recommendation"
                ? "No queueable recommendation is available right now."
                : response.status === "stale_recommendation"
                  ? "That recommendation is no longer current. Refresh the goal and review the latest next slice."
                  : null,
      });
    } catch (err) {
      setActionState({ status: "idle", message: err instanceof Error ? err.message : "Failed to approve recommendation" });
    }
  }

  return (
    <div className="panel-section-stack">
      <section className="card">
        <div className="detail-grid">
          <div><div className="field-label">Title</div><div className="field-value">{payload.title}</div></div>
          <div><div className="field-label">Status</div><div className="field-value">{payload.planning_status}</div></div>
          <div><div className="field-label">Priority</div><div className="field-value">{payload.priority}</div></div>
          <div><div className="field-label">Workspace</div><div className="field-value">{workspaceId}</div></div>
          <div><div className="field-label">Goal Type</div><div className="field-value">{payload.goal_type}</div></div>
          <div><div className="field-label">Conversation</div><div className="field-value">{payload.source_conversation_id || "—"}</div></div>
        </div>
        {payload.description ? <p className="muted" style={{ marginTop: 12 }}>{payload.description}</p> : null}
        {payload.planning_summary ? <InlineMessage tone="info" title="Planning Summary" body={payload.planning_summary} /> : null}
      </section>
      {payload.development_loop_summary ? (
        <section className="card">
          <div className="card-header"><div><p className="muted">Development Loop</p></div></div>
          <div className="detail-grid">
            <div><div className="field-label">Goal Status</div><div className="field-value">{payload.development_loop_summary.goal_status}</div></div>
            <div><div className="field-label">Active Threads</div><div className="field-value">{payload.metrics?.active_threads ?? payload.goal_progress?.active_threads ?? 0}</div></div>
            <div><div className="field-label">Blocked Threads</div><div className="field-value">{payload.metrics?.blocked_threads ?? payload.goal_progress?.blocked_threads ?? 0}</div></div>
            <div><div className="field-label">Artifacts Produced</div><div className="field-value">{payload.metrics?.artifact_production_count ?? payload.goal_progress?.artifact_production_count ?? 0}</div></div>
          </div>
          {actionState.message ? <p className="muted" style={{ marginTop: 12 }}>{actionState.message}</p> : null}
          <div className="canvas-table-wrap" style={{ marginTop: 12 }}>
            <table className="canvas-table">
              <thead>
                <tr>
                  <th>Thread</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {payload.development_loop_summary.threads.map((thread) => (
                  <tr key={thread.thread_id}>
                    <td>{thread.title}</td>
                    <td>{thread.thread_status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="canvas-table-wrap" style={{ marginTop: 12 }}>
            <table className="canvas-table">
              <thead>
                <tr>
                  <th>Recent Work</th>
                  <th>Status</th>
                  <th>Artifacts</th>
                  <th>Run</th>
                </tr>
              </thead>
              <tbody>
                {payload.development_loop_summary.recent_work_results.map((result) => (
                  <tr key={result.work_item_id}>
                    <td>{result.title}</td>
                    <td>{result.status}</td>
                    <td>{result.artifact_count ? `${result.artifact_count}` : "0"}</td>
                    <td>{result.run_id || "—"}</td>
                  </tr>
                ))}
                {!payload.development_loop_summary.recent_work_results.length ? (
                  <tr><td colSpan={4} className="muted">No recent work results yet.</td></tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
      {payload.goal_health ? (
        <section className="card">
          <div className="card-header"><div><p className="muted">Goal Health</p></div></div>
          <div className="detail-grid">
            <div><div className="field-label">Progress</div><div className="field-value">{payload.goal_health.progress_percent}%</div></div>
            <div><div className="field-label">Active Threads</div><div className="field-value">{payload.goal_health.active_threads}</div></div>
            <div><div className="field-label">Blocked Threads</div><div className="field-value">{payload.goal_health.blocked_threads}</div></div>
            <div><div className="field-label">Recent Artifacts</div><div className="field-value">{payload.goal_health.recent_artifacts}</div></div>
          </div>
        </section>
      ) : null}
      {payload.goal_diagnostic ? (
        <section className="card">
          <div className="card-header"><div><p className="muted">Goal Diagnostic</p></div></div>
          <div className="detail-grid">
            <div><div className="field-label">Status</div><div className="field-value">{payload.goal_diagnostic.status}</div></div>
            <div><div className="field-label">Contributing Threads</div><div className="field-value">{payload.goal_diagnostic.contributing_threads.length}</div></div>
          </div>
          {payload.goal_diagnostic.observations.length ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Observations</div>
              <ul className="detail-list">
                {payload.goal_diagnostic.observations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {payload.goal_diagnostic.evidence.length ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Evidence</div>
              <ul className="detail-list">
                {payload.goal_diagnostic.evidence.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {payload.goal_diagnostic.suggested_human_review_focus ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Suggested Review Focus</div>
              <div className="field-value">{payload.goal_diagnostic.suggested_human_review_focus}</div>
            </div>
          ) : null}
        </section>
      ) : null}
      {payload.development_insights?.length ? (
        <section className="card">
          <div className="card-header"><div><p className="muted">Development Insights</p></div></div>
          <div className="detail-list">
            {payload.development_insights.map((insight) => (
              <div key={insight.key} style={{ marginBottom: 12 }}>
                <div className="field-value">{insight.summary}</div>
                {insight.evidence.length ? (
                  <ul className="detail-list">
                    {insight.evidence.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}
      <section className="card">
        <div className="card-header"><div><p className="muted">Threads</p></div></div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th>Priority</th>
                <th>Queued</th>
                <th>Running</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {payload.threads.map((thread) => (
                <tr key={thread.id}>
                  <td>{thread.title}</td>
                  <td>{thread.status}</td>
                  <td>{thread.priority}</td>
                  <td>{thread.queued_work_items}</td>
                  <td>{thread.running_work_items}</td>
                  <td><button type="button" className="ghost sm" onClick={() => onOpenPanel("thread_detail", { thread_id: thread.id })}>Thread</button></td>
                </tr>
              ))}
              {!payload.threads.length ? <tr><td colSpan={6} className="muted">No threads planned yet.</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card">
        <div className="card-header"><div><p className="muted">Work Items</p></div></div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th>Thread</th>
                <th>Repo</th>
                <th>Execution</th>
                <th>Changes</th>
                <th>Publish</th>
                <th>Brief</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {payload.work_items.map((item) => (
                <tr key={item.id}>
                  <td>{item.title}</td>
                  <td>{item.status}</td>
                  <td>{item.thread_title || "—"}</td>
                  <td>{item.target_repo || "—"}</td>
                  <td><ExecutionRunSummary item={item} /></td>
                  <td><ChangeSetSummary item={item} /></td>
                  <td><PublishSummary item={item} /></td>
                  <td><BriefReviewSummary item={item} /></td>
                  <td><button type="button" className="ghost sm" onClick={() => onOpenPanel("work_item_detail", { work_item_id: item.id })}>Work Item</button></td>
                </tr>
              ))}
              {!payload.work_items.length ? <tr><td colSpan={9} className="muted">No work items planned yet.</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
      {payload.recommendation?.summary ? (
        <section className="card">
          <InlineMessage tone="info" title="Recommended Next Slice" body={payload.recommendation.summary} />
          {payload.recommendation.reasoning_summary ? <p className="muted" style={{ marginTop: 10 }}>{payload.recommendation.reasoning_summary}</p> : null}
          <div className="inline-action-row" style={{ marginTop: 12 }}>
            <button type="button" className="ghost sm" disabled={!queueableAction || actionState.status === "submitting"} onClick={handleApproveAndQueue}>
              Approve and Queue
            </button>
            <button
              type="button"
              className="ghost sm"
              disabled={!reviewThreadAction?.target_thread}
              onClick={() => reviewThreadAction?.target_thread && onOpenPanel("thread_detail", { thread_id: reviewThreadAction.target_thread })}
            >
              View Thread
            </button>
            <button
              type="button"
              className="ghost sm"
              disabled={!reviewWorkItemId}
              onClick={() => reviewWorkItemId && onOpenPanel("work_item_detail", { work_item_id: reviewWorkItemId })}
            >
              Review Work Items
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}

function ThreadListPanel({
  workspaceId,
  onOpenPanel,
  onTitleChange,
}: {
  workspaceId: string;
  onTitleChange?: (title: string) => void;
} & PanelProps) {
  const [threads, setThreads] = useState<CoordinationThreadSummary[]>([]);
  const [queue, setQueue] = useState<WorkQueueResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionState, setActionState] = useState<{ status: "idle" | "submitting"; message: string | null }>({
    status: "idle",
    message: null,
  });

  async function loadThreadState(active = true) {
    try {
      setLoading(true);
      setError(null);
      const [threadRows, queueRows] = await Promise.all([
        listCoordinationThreads(workspaceId),
        getWorkQueue(workspaceId),
      ]);
      if (!active) return;
      setThreads(threadRows.threads || []);
      setQueue(queueRows);
    } catch (err) {
      if (!active) return;
      setError(err instanceof Error ? err.message : "Failed to load threads");
    } finally {
      if (active) setLoading(false);
    }
  }

  useEffect(() => {
    let active = true;
    void loadThreadState(active);
    return () => {
      active = false;
    };
  }, [workspaceId]);

  useEffect(() => {
    onTitleChange?.("Threads");
  }, [onTitleChange]);

  async function handleDispatchNext() {
    try {
      setActionState({ status: "submitting", message: null });
      const response = await dispatchNextWorkQueueItem(workspaceId);
      await loadThreadState(true);
      setActionState({
        status: "idle",
        message:
          response.status === "dispatched"
            ? `Dispatched ${String(response.queue_item?.work_item_id || response.queue_item?.task_id || "next work item")}.`
            : response.status === "idle"
              ? "No approved work items are ready for dispatch."
              : response.status,
      });
    } catch (err) {
      setActionState({ status: "idle", message: err instanceof Error ? err.message : "Failed to dispatch next work item" });
    }
  }

  async function handleDispatchSelected(taskId: string) {
    try {
      setActionState({ status: "submitting", message: null });
      const response = await dispatchWorkItem(taskId, workspaceId);
      await loadThreadState(true);
      setActionState({
        status: "idle",
        message: response.status === "dispatched" ? `Dispatched ${String(response.queue_item?.work_item_id || taskId)}.` : response.status,
      });
    } catch (err) {
      setActionState({ status: "idle", message: err instanceof Error ? err.message : "Failed to dispatch selected work item" });
    }
  }

  if (loading) return <p className="muted">Loading XCO threads…</p>;
  if (error) return <p className="danger-text">{error}</p>;

  return (
    <div className="panel-section-stack">
      <section className="card">
        <div className="card-header">
          <div>
            <h3>Threads</h3>
            <p className="muted">Durable lines of effort coordinated by XCO.</p>
          </div>
        </div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th>Priority</th>
                <th>Queued</th>
                <th>Running</th>
                <th>Review</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {threads.map((thread) => (
                <tr key={thread.id}>
                  <td>{thread.title}</td>
                  <td>{thread.status}</td>
                  <td>{thread.priority}</td>
                  <td>{thread.queued_work_items}</td>
                  <td>{thread.running_work_items}</td>
                  <td>{thread.awaiting_review_work_items}</td>
                  <td>
                    <button type="button" className="ghost sm" onClick={() => onOpenPanel("thread_detail", { thread_id: thread.id })}>
                      Open
                    </button>
                  </td>
                </tr>
              ))}
              {!threads.length ? (
                <tr>
                  <td colSpan={7} className="muted">
                    No XCO threads found.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card">
        <div className="card-header">
          <div>
            <h3>Derived Queue</h3>
            <p className="muted">Next eligible work items in deterministic dispatch order.</p>
          </div>
          <button type="button" className="ghost sm" disabled={actionState.status === "submitting"} onClick={handleDispatchNext}>
            Dispatch Next
          </button>
        </div>
        {actionState.message ? <p className="muted" style={{ marginBottom: 12 }}>{actionState.message}</p> : null}
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Thread</th>
                <th>Priority</th>
                <th>Work Item</th>
                <th>Task ID</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {(queue?.items || []).map((entry) => (
                <tr key={`${entry.thread_id}:${entry.task_id}`}>
                  <td>{entry.thread_title}</td>
                  <td>{entry.thread_priority}</td>
                  <td>{entry.work_item_id}</td>
                  <td>{entry.task_id}</td>
                  <td>{entry.queue_state?.message || "Ready for dispatch"}</td>
                  <td>
                    <div className="inline-action-row">
                      <button type="button" className="ghost sm" disabled={actionState.status === "submitting"} onClick={() => handleDispatchSelected(entry.task_id)}>
                        Dispatch
                      </button>
                      <button type="button" className="ghost sm" onClick={() => onOpenPanel("work_item_detail", { work_item_id: entry.task_id })}>
                        Open
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {!queue?.items?.length ? (
                <tr>
                  <td colSpan={6} className="muted">
                    No eligible work items are currently queued.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function ThreadDetailPanel({
  threadId,
  workspaceId,
  onOpenPanel,
  onTitleChange,
}: {
  threadId: string;
  workspaceId: string;
  onTitleChange?: (title: string) => void;
} & PanelProps) {
  const [payload, setPayload] = useState<CoordinationThreadDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [unavailableReason, setUnavailableReason] = useState<"not_found" | "access_denied" | null>(null);
  const [actionState, setActionState] = useState<{ status: "idle" | "submitting"; message: string | null }>({
    status: "idle",
    message: null,
  });

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        setUnavailableReason(null);
        setPayload(null);
        const detail = await getCoordinationThread(threadId);
        if (!active) return;
        if (detail.workspace_id && workspaceId && String(detail.workspace_id) !== String(workspaceId)) {
          setUnavailableReason("not_found");
          return;
        }
        setPayload(detail);
      } catch (err) {
        if (!active) return;
        const message = err instanceof Error ? err.message : "Failed to load thread";
        const reason = classifyWorkspaceUnavailableReason(message);
        if (reason === "not_found" || reason === "access_denied") {
          setUnavailableReason(reason);
          setError(null);
          return;
        }
        setError(message);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [threadId, workspaceId]);

  useEffect(() => {
    onTitleChange?.(payload?.title || "Thread");
  }, [onTitleChange, payload?.title]);

  async function handleReviewAction(action: "resume_thread" | "queue_next_slice" | "mark_thread_completed") {
    try {
      setActionState({ status: "submitting", message: null });
      const response = await reviewCoordinationThread(threadId, action);
      setPayload(response.thread);
      setActionState({ status: "idle", message: response.summary || null });
    } catch (err) {
      setActionState({ status: "idle", message: err instanceof Error ? err.message : "Failed to update thread review state" });
    }
  }

  if (loading) return <p className="muted">Loading XCO thread…</p>;
  if (unavailableReason || !payload) {
    return (
      <WorkspaceUnavailableState
        itemLabel="Thread"
        workspaceLabel={workspaceId || "this workspace"}
        reason={unavailableReason || "not_found"}
        onOpenList={() => onOpenPanel("thread_list")}
        openListLabel="Open Threads"
      />
    );
  }
  if (error) return <p className="danger-text">{error}</p>;

  return (
    <div className="panel-section-stack">
      <section className="card">
        <div className="detail-grid">
          <div><div className="field-label">Title</div><div className="field-value">{payload.title}</div></div>
          <div><div className="field-label">Status</div><div className="field-value">{payload.status}</div></div>
          <div><div className="field-label">Priority</div><div className="field-value">{payload.priority}</div></div>
          <div><div className="field-label">Workspace</div><div className="field-value">{workspaceId}</div></div>
          <div><div className="field-label">WIP limit</div><div className="field-value">{payload.work_in_progress_limit}</div></div>
          <div><div className="field-label">Owner</div><div className="field-value">{payload.owner || "—"}</div></div>
        </div>
        {payload.description ? <p className="muted" style={{ marginTop: 12 }}>{payload.description}</p> : null}
      </section>
      <section className="card">
        <div className="card-header">
          <div>
            <p className="muted">Thread Review</p>
          </div>
        </div>
        <div className="detail-grid">
          <div><div className="field-label">Progress</div><div className="field-value">{payload.thread_progress_status || payload.status}</div></div>
          <div><div className="field-label">Completed</div><div className="field-value">{payload.work_items_completed ?? payload.completed_work_items}</div></div>
          <div><div className="field-label">Ready</div><div className="field-value">{payload.work_items_ready ?? payload.queued_work_items}</div></div>
          <div><div className="field-label">Blocked</div><div className="field-value">{payload.work_items_blocked ?? payload.awaiting_review_work_items}</div></div>
          <div><div className="field-label">Avg Run Duration</div><div className="field-value">{payload.metrics?.average_run_duration_seconds ? `${payload.metrics.average_run_duration_seconds}s` : "—"}</div></div>
          <div><div className="field-label">Failed Work</div><div className="field-value">{payload.metrics?.failed_work_items ?? 0}</div></div>
        </div>
        {actionState.message ? <p className="muted" style={{ marginTop: 12 }}>{actionState.message}</p> : null}
        <div className="inline-action-row" style={{ marginTop: 12 }}>
          <button
            type="button"
            className="ghost sm"
            disabled={payload.status !== "paused" || actionState.status === "submitting"}
            onClick={() => handleReviewAction("resume_thread")}
          >
            Resume Thread
          </button>
          <button
            type="button"
            className="ghost sm"
            disabled={payload.status !== "active" || actionState.status === "submitting"}
            onClick={() => handleReviewAction("queue_next_slice")}
          >
            Queue Next Slice
          </button>
          <button
            type="button"
            className="ghost sm"
            disabled={payload.status === "completed" || actionState.status === "submitting"}
            onClick={() => handleReviewAction("mark_thread_completed")}
          >
            Mark Thread Completed
          </button>
        </div>
      </section>
      {payload.thread_diagnostic ? (
        <section className="card">
          <div className="card-header">
            <div>
              <p className="muted">Thread Diagnostic</p>
            </div>
          </div>
          <div className="detail-grid">
            <div><div className="field-label">Status</div><div className="field-value">{payload.thread_diagnostic.status}</div></div>
            <div><div className="field-label">Provenance</div><div className="field-value">{payload.thread_diagnostic.provenance?.summary || "—"}</div></div>
          </div>
          {payload.thread_diagnostic.observations.length ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Observations</div>
              <ul className="detail-list">
                {payload.thread_diagnostic.observations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {payload.thread_diagnostic.evidence.length ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Evidence</div>
              <ul className="detail-list">
                {payload.thread_diagnostic.evidence.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {payload.thread_diagnostic.suggested_human_review_action ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Suggested Review Action</div>
              <div className="field-value">{payload.thread_diagnostic.suggested_human_review_action}</div>
            </div>
          ) : null}
        </section>
      ) : null}
      <section className="card">
        <div className="card-header">
          <div>
            <h3>Work Items</h3>
            <p className="muted">Durable work coordinated under this thread.</p>
          </div>
        </div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th>Repo</th>
                <th>Execution</th>
                <th>Changes</th>
                <th>Publish</th>
                <th>Brief</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {payload.work_items.map((item) => (
                <tr key={item.id}>
                  <td>{item.title}</td>
                  <td>{item.status}</td>
                  <td>{item.target_repo || "—"}</td>
                  <td><ExecutionRunSummary item={item} /></td>
                  <td><ChangeSetSummary item={item} /></td>
                  <td><PublishSummary item={item} /></td>
                  <td><BriefReviewSummary item={item} /></td>
                  <td>
                    <div className="inline-action-row">
                      <button type="button" className="ghost sm" onClick={() => onOpenPanel("work_item_detail", { work_item_id: item.id })}>
                        Work Item
                      </button>
                      {item.execution_run?.run_id ? (
                        <button type="button" className="ghost sm" onClick={() => onOpenPanel("run_detail", { run_id: item.execution_run?.run_id })}>
                          Run
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
              {!payload.work_items.length ? (
                <tr>
                  <td colSpan={8} className="muted">
                    No work items are attached to this thread yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card">
        <div className="card-header">
          <div>
            <h3>Recent Runs</h3>
            <p className="muted">Recent runtime results linked to this thread.</p>
          </div>
        </div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Run</th>
                <th>Status</th>
                <th>Summary</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {payload.recent_runs.map((run) => (
                <tr key={run.id}>
                  <td>{run.id}</td>
                  <td>{run.status || "—"}</td>
                  <td>{run.summary || run.error || "—"}</td>
                  <td>
                    <button type="button" className="ghost sm" onClick={() => onOpenPanel("run_detail", { run_id: run.id })}>
                      Run
                    </button>
                  </td>
                </tr>
              ))}
              {!payload.recent_runs.length ? (
                <tr>
                  <td colSpan={4} className="muted">
                    No recent run results are available for this thread yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card">
        <div className="card-header">
          <div>
            <h3>Recent Artifacts</h3>
            <p className="muted">Outputs produced by runs associated with this thread.</p>
          </div>
        </div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Type</th>
                <th>Run</th>
                <th>Work Item</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {payload.recent_artifacts.map((artifact) => (
                <tr key={`${artifact.run_id || "run"}:${artifact.id}`}>
                  <td>{artifact.label || artifact.uri || artifact.id}</td>
                  <td>{artifact.artifact_type}</td>
                  <td>{artifact.run_id || "—"}</td>
                  <td>{(artifact as Record<string, unknown>).work_item_id ? String((artifact as Record<string, unknown>).work_item_id) : "—"}</td>
                  <td>
                    {artifact.run_id && artifact.id ? (
                      <button
                        type="button"
                        className="ghost sm"
                        onClick={() =>
                          onOpenPanel("artifact_detail", {
                            runtime_run_id: artifact.run_id,
                            runtime_artifact_id: artifact.id,
                          })
                        }
                      >
                        Artifact
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
              {!payload.recent_artifacts.length ? (
                <tr>
                  <td colSpan={5} className="muted">
                    No artifacts have been registered for this thread yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card">
        <div className="card-header">
          <div>
            <h3>Activity Timeline</h3>
            <p className="muted">Ordered execution history reconstructed from durable work items, runs, and coordination events.</p>
          </div>
        </div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Event</th>
                <th>Source</th>
                <th>Run</th>
                <th>Work Item</th>
                <th>Summary</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {payload.timeline.map((event) => (
                <tr key={event.id}>
                  <td>{event.event_type}</td>
                  <td>{event.source || "—"}</td>
                  <td>{event.run_id || "—"}</td>
                  <td>{event.work_item_title || event.work_item_id || "—"}</td>
                  <td>{event.summary || event.status || "—"}</td>
                  <td>{String(event.created_at || "")}</td>
                </tr>
              ))}
              {!payload.timeline.length ? (
                <tr>
                  <td colSpan={6} className="muted">
                    No coordination events recorded yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function WorkItemDetailPanel({
  workItemId,
  workspaceId,
  onOpenPanel,
}: {
  workItemId: string;
  workspaceId?: string;
} & PanelProps) {
  const [payload, setPayload] = useState<WorkItemDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionState, setActionState] = useState<{ status: "idle" | "submitting"; message: string | null }>({
    status: "idle",
    message: null,
  });
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [routingStatus, setRoutingStatus] = useState<AiRoutingStatusResponse | null>(null);
  const [compatibleAgents, setCompatibleAgents] = useState<AiAgent[]>([]);
  const [agentSelectionLoading, setAgentSelectionLoading] = useState(false);
  const [agentSelectionError, setAgentSelectionError] = useState<string | null>(null);
  const [selectedAgentOverrideId, setSelectedAgentOverrideId] = useState("routed");

  async function loadWorkItem(active = true) {
    try {
      setLoading(true);
      setError(null);
      const next = await getWorkItem(workItemId);
      if (!active) return;
      setPayload(next);
    } catch (err) {
      if (!active) return;
      setError(err instanceof Error ? err.message : "Failed to load work item");
    } finally {
      if (active) setLoading(false);
    }
  }

  useEffect(() => {
    let active = true;
    void loadWorkItem(active);
    return () => {
      active = false;
    };
  }, [workItemId]);

  const queue = payload?.execution_queue;
  const canDispatchSelectedTask = Boolean(queue?.dispatchable && !queue?.dispatched && (queue?.selected_for_dispatch ?? true));
  const dispatchPurpose = workItemDispatchPurpose(payload);
  const routedResolution = routingPurposeRow(routingStatus?.routing || [], dispatchPurpose);
  const routedAgentId = String(routedResolution?.resolved_agent_id || "").trim();
  const routedAgentName = String(routedResolution?.resolved_agent_name || "").trim() || "No routed agent";
  const routedResolutionText = routingResolutionLabel(routedResolution, dispatchPurpose);
  const overrideAgent = selectedAgentOverrideId === "routed"
    ? null
    : compatibleAgents.find((agent) => agent.id === selectedAgentOverrideId) || null;
  const effectiveAgentName = overrideAgent?.name || routedAgentName;
  const effectiveResolutionText = overrideAgent ? "Action override" : routedResolutionText;
  const canShowOverrideControls = compatibleAgents.length > 1;

  useEffect(() => {
    if (!canDispatchSelectedTask || !workspaceId) {
      setRoutingStatus(null);
      setCompatibleAgents([]);
      setSelectedAgentOverrideId("routed");
      setAdvancedOpen(false);
      setAgentSelectionError(null);
      setAgentSelectionLoading(false);
      return;
    }
    let active = true;
    setAgentSelectionLoading(true);
    setAgentSelectionError(null);
    void Promise.all([
      getAiRoutingStatus(),
      listAiAgents({ purpose: dispatchPurpose, enabled: true }),
    ])
      .then(([nextRouting, agentsResponse]) => {
        if (!active) return;
        setRoutingStatus(nextRouting);
        setCompatibleAgents(agentsResponse.agents || []);
      })
      .catch((err) => {
        if (!active) return;
        setAgentSelectionError(err instanceof Error ? err.message : "Failed to load routed agent context.");
        setRoutingStatus(null);
        setCompatibleAgents([]);
      })
      .finally(() => {
        if (!active) return;
        setAgentSelectionLoading(false);
      });
    return () => {
      active = false;
    };
  }, [canDispatchSelectedTask, dispatchPurpose, workspaceId, workItemId]);

  useEffect(() => {
    if (!canShowOverrideControls && selectedAgentOverrideId !== "routed") {
      setSelectedAgentOverrideId("routed");
      return;
    }
    if (selectedAgentOverrideId === "routed") return;
    if (!compatibleAgents.some((agent) => agent.id === selectedAgentOverrideId)) {
      setSelectedAgentOverrideId("routed");
    }
  }, [canShowOverrideControls, compatibleAgents, selectedAgentOverrideId]);

  async function handleBriefAction(action: "mark_ready" | "approve" | "reject" | "regenerate") {
    try {
      setActionState({ status: "submitting", message: null });
      const next = await updateWorkItem(workItemId, {
        execution_brief_action: action,
        execution_brief_revision_reason: action === "regenerate" ? "review_feedback" : undefined,
      });
      setPayload(next);
      setActionState({ status: "idle", message: action === "regenerate" ? "Execution brief regenerated." : `Execution brief ${titleCaseLabel(action)}.` });
    } catch (err) {
      setActionState({ status: "idle", message: err instanceof Error ? err.message : "Failed to update execution brief" });
    }
  }

  async function handleDispatchTask() {
    if (!workspaceId) return;
    try {
      setActionState({ status: "submitting", message: null });
      const overrideId = selectedAgentOverrideId !== "routed" && selectedAgentOverrideId !== routedAgentId
        ? selectedAgentOverrideId
        : "";
      const response = overrideId
        ? await dispatchWorkItem(workItemId, workspaceId, { agent_override_id: overrideId })
        : await dispatchWorkItem(workItemId, workspaceId);
      setPayload(response.work_item || (await getWorkItem(workItemId)));
      setActionState({
        status: "idle",
        message: response.status === "dispatched" ? `Dispatched ${String(response.queue_item?.work_item_id || payload?.work_item_id || workItemId)}.` : response.status,
      });
      setSelectedAgentOverrideId("routed");
      setAdvancedOpen(false);
    } catch (err) {
      setActionState({ status: "idle", message: err instanceof Error ? err.message : "Failed to dispatch work item" });
    }
  }

  async function handleRetryTask() {
    try {
      setActionState({ status: "submitting", message: null });
      const response = await retryDevTask(workItemId);
      setPayload(response.work_item || (await getWorkItem(workItemId)));
      setActionState({
        status: "idle",
        message: response.run_id
          ? `Retried ${String(payload?.work_item_id || workItemId)} as run ${response.run_id}.`
          : "Retried work item.",
      });
    } catch (err) {
      setActionState({ status: "idle", message: err instanceof Error ? err.message : "Failed to retry work item" });
    }
  }

  async function handleRequeueTask() {
    try {
      setActionState({ status: "submitting", message: null });
      const response = await requeueDevTask(workItemId);
      setPayload(response.work_item || (await getWorkItem(workItemId)));
      setActionState({
        status: "idle",
        message: response.status === "queued" ? `Returned ${String(payload?.work_item_id || workItemId)} to the queue.` : response.status,
      });
    } catch (err) {
      setActionState({ status: "idle", message: err instanceof Error ? err.message : "Failed to requeue work item" });
    }
  }

  async function handlePublishTask(push = false) {
    try {
      setActionState({ status: "submitting", message: null });
      const response = await publishDevTask(workItemId, { push });
      setPayload(response.work_item || (await getWorkItem(workItemId)));
      setActionState({
        status: "idle",
        message: push ? "Published branch to the remote repository." : "Committed workspace changes to the task branch.",
      });
    } catch (err) {
      setActionState({ status: "idle", message: err instanceof Error ? err.message : "Failed to publish work item" });
    }
  }

  if (loading) return <p className="muted">Loading work item…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">Work item not found.</p>;
  const review = payload.execution_brief_review;
  const execution = payload.execution_run;
  const recovery = payload.execution_recovery;
  const changeSet = payload.change_set;
  const publish = payload.publish_state;

  return (
    <div className="ems-panel-body">
      <div className="detail-grid">
        <div><div className="field-label">Title</div><div className="field-value">{payload.title}</div></div>
        <div><div className="field-label">Status</div><div className="field-value">{payload.status}</div></div>
        <div><div className="field-label">Work Item</div><div className="field-value">{payload.work_item_id || payload.id}</div></div>
        <div><div className="field-label">Intent</div><div className="field-value">{payload.intent_type || "—"}</div></div>
        <div><div className="field-label">Repo</div><div className="field-value">{payload.target_repo || "—"}</div></div>
        <div><div className="field-label">Branch</div><div className="field-value">{payload.target_branch || "—"}</div></div>
        <div><div className="field-label">Requested By</div><div className="field-value">{payload.requested_by || "—"}</div></div>
        <div><div className="field-label">Conversation</div><div className="field-value">{payload.source_conversation_id || "—"}</div></div>
      </div>
      {payload.description ? <p>{payload.description}</p> : null}
      {payload.last_error ? <InlineMessage tone="warn" title="Last error" body={payload.last_error} /> : null}
      {queue ? (
        <section className="card" style={{ marginTop: 12 }}>
          <div className="card-header"><h3>Execution Queue</h3></div>
          <div className="detail-grid">
            <div><div className="field-label">Queue Status</div><div className="field-value">{titleCaseLabel(queue.status)}</div></div>
            <div><div className="field-label">Dispatchable</div><div className="field-value">{queue.dispatchable ? "yes" : "no"}</div></div>
            <div><div className="field-label">Blocked</div><div className="field-value">{queue.blocked ? "yes" : "no"}</div></div>
            <div><div className="field-label">In Flight</div><div className="field-value">{queue.dispatched ? "yes" : "no"}</div></div>
          </div>
          <p className="muted" style={{ marginTop: 12 }}>{queue.message}</p>
          {queue.dispatchable && !queue.dispatched && !(queue.selected_for_dispatch ?? true) && queue.next_dispatchable_task_id ? (
            <div className="inline-action-row" style={{ marginTop: 12 }}>
              <button
                type="button"
                className="ghost sm"
                onClick={() => onOpenPanel("work_item_detail", { work_item_id: queue.next_dispatchable_task_id })}
              >
                Open next ready work item
              </button>
            </div>
          ) : null}
          {canDispatchSelectedTask ? (
            <div className="inline-action-row" style={{ marginTop: 12 }}>
              <div style={{ width: "100%" }}>
                <div className="detail-grid" style={{ marginBottom: 10 }}>
                  <div><div className="field-label">Purpose</div><div className="field-value">{titleCaseLabel(dispatchPurpose)}</div></div>
                  <div><div className="field-label">Routed Agent</div><div className="field-value">{routedAgentName}</div></div>
                  <div><div className="field-label">Resolution</div><div className="field-value">{routedResolutionText}</div></div>
                  <div><div className="field-label">Effective Agent</div><div className="field-value">{effectiveAgentName}</div></div>
                  <div><div className="field-label">Source</div><div className="field-value">{effectiveResolutionText}</div></div>
                </div>
                {agentSelectionLoading ? <p className="muted small" style={{ marginTop: 0 }}>Loading routed agent context…</p> : null}
                {agentSelectionError ? <p className="danger-text small" style={{ marginTop: 0 }}>{agentSelectionError}</p> : null}
                {canShowOverrideControls ? (
                  <details open={advancedOpen} onToggle={(event) => setAdvancedOpen((event.currentTarget as HTMLDetailsElement).open)}>
                    <summary><strong>Advanced</strong></summary>
                    <div style={{ marginTop: 8 }}>
                      <label className="field-label" htmlFor={`agent-override-${workItemId}`}>Agent override</label>
                      <select
                        id={`agent-override-${workItemId}`}
                        value={selectedAgentOverrideId}
                        onChange={(event) => setSelectedAgentOverrideId(event.target.value)}
                        style={{ maxWidth: 360 }}
                      >
                        <option value="routed">Use routed agent</option>
                        {compatibleAgents.map((agent) => (
                          <option key={agent.id} value={agent.id}>{agent.name}</option>
                        ))}
                      </select>
                      <p className="muted small" style={{ marginTop: 6 }}>
                        This override applies only to this dispatch and does not change Platform Settings.
                      </p>
                    </div>
                  </details>
                ) : null}
              </div>
              <button type="button" className="ghost sm" disabled={actionState.status === "submitting" || !workspaceId} onClick={handleDispatchTask}>
                Dispatch Task
              </button>
            </div>
          ) : null}
        </section>
      ) : null}
      {review?.has_brief ? (
        <section className="card" style={{ marginTop: 12 }}>
          <div className="card-header"><h3>Execution Brief Review</h3></div>
          <div className="detail-grid">
            <div><div className="field-label">State</div><div className="field-value">{titleCaseLabel(review.review_state)}</div></div>
            <div><div className="field-label">Revision</div><div className="field-value">{review.revision || 0}</div></div>
            <div><div className="field-label">History</div><div className="field-value">{review.history_count || 0}</div></div>
            <div><div className="field-label">Target</div><div className="field-value">{review.target_repository_slug ? `${review.target_repository_slug}${review.target_branch ? ` @ ${review.target_branch}` : ""}` : "—"}</div></div>
          </div>
          {review.summary ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Summary</div>
              <div className="field-value">{review.summary}</div>
            </div>
          ) : null}
          {review.objective ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Objective</div>
              <div className="field-value">{review.objective}</div>
            </div>
          ) : null}
          {review.blocked_message ? (
            <InlineMessage tone={review.blocked ? "warn" : "info"} title={review.blocked ? "Execution Blocked" : "Execution Ready"} body={review.blocked_message} />
          ) : null}
          {review.review_notes ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Review Notes</div>
              <div className="field-value">{review.review_notes}</div>
            </div>
          ) : null}
          {actionState.message ? <p className="muted" style={{ marginTop: 12 }}>{actionState.message}</p> : null}
          <div className="inline-action-row" style={{ marginTop: 12 }}>
            {review.available_actions.includes("mark_ready") ? (
              <button type="button" className="ghost sm" disabled={actionState.status === "submitting"} onClick={() => handleBriefAction("mark_ready")}>
                Mark Ready
              </button>
            ) : null}
            {review.available_actions.includes("approve") ? (
              <button type="button" className="ghost sm" disabled={actionState.status === "submitting"} onClick={() => handleBriefAction("approve")}>
                Approve
              </button>
            ) : null}
            {review.available_actions.includes("reject") ? (
              <button type="button" className="ghost sm" disabled={actionState.status === "submitting"} onClick={() => handleBriefAction("reject")}>
                Reject
              </button>
            ) : null}
            {review.available_actions.includes("regenerate") ? (
              <button type="button" className="ghost sm" disabled={actionState.status === "submitting"} onClick={() => handleBriefAction("regenerate")}>
                Regenerate
              </button>
            ) : null}
          </div>
        </section>
      ) : null}
      <section className="card" style={{ marginTop: 12 }}>
        <div className="card-header"><h3>Execution Run</h3></div>
        <div className="detail-grid">
          <div><div className="field-label">Execution State</div><div className="field-value">{executionRunLabel(payload)}</div></div>
          <div><div className="field-label">Validation</div><div className="field-value">{titleCaseLabel(execution?.validation_status || "not_run")}</div></div>
          <div><div className="field-label">Run ID</div><div className="field-value">{execution?.run_id || "—"}</div></div>
          <div><div className="field-label">Artifacts</div><div className="field-value">{execution?.artifact_count || 0}</div></div>
          <div><div className="field-label">Started</div><div className="field-value">{execution?.started_at || "—"}</div></div>
          <div><div className="field-label">Finished</div><div className="field-value">{execution?.finished_at || "—"}</div></div>
        </div>
        <p className="muted" style={{ marginTop: 12 }}>{execution?.message || "No execution run has been dispatched yet."}</p>
        {execution?.agent_selection ? (
          <div style={{ marginTop: 12 }}>
            <div className="field-label">Agent Selection</div>
            <div className="field-value">
              {execution.agent_selection.effective_agent_name || "—"}
              {execution.agent_selection.override_applied ? (
                <span style={{ marginLeft: 8, fontSize: 12, padding: "2px 8px", borderRadius: 999, background: "#fff3d9", color: "#8a5a00" }}>
                  Override Used
                </span>
              ) : null}
            </div>
            <div className="muted small" style={{ marginTop: 4 }}>
              Purpose: {titleCaseLabel(execution.agent_selection.purpose || "coding")} · Routed: {execution.agent_selection.routed_agent_name || "—"} ({execution.agent_selection.routed_resolution_label || "Unknown"}) · Source: {execution.agent_selection.effective_resolution_label || "Unknown"}
            </div>
          </div>
        ) : null}
        {execution?.summary ? (
          <div style={{ marginTop: 12 }}>
            <div className="field-label">Result Summary</div>
            <div className="field-value">{execution.summary}</div>
          </div>
        ) : null}
        {execution?.error ? (
          <InlineMessage tone={execution.state === "failed" ? "warn" : "info"} title="Execution Notes" body={execution.error} />
        ) : null}
        {execution?.artifact_labels?.length ? (
          <div style={{ marginTop: 12 }}>
            <div className="field-label">Artifact Preview</div>
            <div className="field-value">{execution.artifact_labels.join(", ")}</div>
          </div>
        ) : null}
        {execution?.has_run ? (
          <div className="inline-actions" style={{ marginTop: 8 }}>
            {payload.thread_detail?.id ? (
              <button
                type="button"
                className="ghost sm"
                onClick={() => onOpenPanel("thread_detail", { thread_id: payload.thread_detail?.id })}
              >
                Open Thread
              </button>
            ) : null}
            {execution.run_id ? (
              <button
                type="button"
                className="ghost sm"
                onClick={() => onOpenPanel("run_detail", { run_id: execution.run_id })}
              >
                Open Run
              </button>
            ) : null}
            {execution.run_id ? (
              <span className="muted small">
                Latest execution run: {execution.run_id}{workspaceId ? ` · workspace ${workspaceId}` : ""}
              </span>
            ) : null}
          </div>
        ) : null}
      </section>
      {changeSet ? (
        <section className="card" style={{ marginTop: 12 }}>
          <div className="card-header"><h3>Workspace Changes</h3></div>
          <div className="detail-grid">
            <div><div className="field-label">Change State</div><div className="field-value">{titleCaseLabel(changeSet.status || "unavailable")}</div></div>
            <div><div className="field-label">Source</div><div className="field-value">{changeSet.source ? titleCaseLabel(changeSet.source) : "—"}</div></div>
            <div><div className="field-label">Repository</div><div className="field-value">{changeSet.repository_slug || payload.target_repo || "—"}</div></div>
            <div><div className="field-label">Changed Files</div><div className="field-value">{changeSet.changed_file_count || 0}</div></div>
          </div>
          <p className="muted" style={{ marginTop: 12 }}>{changeSet.message}</p>
          {changeSet.files?.length ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Changed Files</div>
              <div className="field-value">
                {changeSet.files.map((file) => `${titleCaseLabel(file.change_type)}: ${file.path}`).join(", ")}
              </div>
            </div>
          ) : null}
          {changeSet.patch_artifact_name ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Patch Artifact</div>
              <div className="field-value">{changeSet.patch_artifact_name}</div>
            </div>
          ) : null}
          {changeSet.diff_text ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Diff</div>
              <pre className="field-value" style={{ whiteSpace: "pre-wrap", overflowX: "auto", maxHeight: 420 }}>{changeSet.diff_text}</pre>
            </div>
          ) : null}
        </section>
      ) : null}
      {publish ? (
        <section className="card" style={{ marginTop: 12 }}>
          <div className="card-header"><h3>Publish</h3></div>
          <div className="detail-grid">
            <div><div className="field-label">Publish Status</div><div className="field-value">{titleCaseLabel(publish.status || "idle")}</div></div>
            <div><div className="field-label">Repository</div><div className="field-value">{publish.repository_slug || payload.target_repo || "—"}</div></div>
            <div><div className="field-label">Branch</div><div className="field-value">{publish.branch || "—"}</div></div>
            <div><div className="field-label">Push Status</div><div className="field-value">{publish.push_status ? titleCaseLabel(publish.push_status) : "—"}</div></div>
            <div><div className="field-label">Commit</div><div className="field-value">{publish.commit || "—"}</div></div>
            <div><div className="field-label">Published At</div><div className="field-value">{publish.published_at || "—"}</div></div>
          </div>
          <p className="muted" style={{ marginTop: 12 }}>{publish.message}</p>
          {publish.last_error ? <InlineMessage tone="warn" title="Publish Error" body={publish.last_error} /> : null}
          {publish.available_actions.length ? (
            <div className="inline-action-row" style={{ marginTop: 12 }}>
              {publish.available_actions.includes("commit") ? (
                <button type="button" className="ghost sm" disabled={actionState.status === "submitting"} onClick={() => handlePublishTask(false)}>
                  Commit Changes
                </button>
              ) : null}
              {publish.available_actions.includes("push") ? (
                <button type="button" className="ghost sm" disabled={actionState.status === "submitting"} onClick={() => handlePublishTask(true)}>
                  Push Branch
                </button>
              ) : null}
              {publish.available_actions.includes("commit_and_push") ? (
                <button type="button" className="ghost sm" disabled={actionState.status === "submitting"} onClick={() => handlePublishTask(true)}>
                  Commit & Push
                </button>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}
      {recovery ? (
        <section className="card" style={{ marginTop: 12 }}>
          <div className="card-header"><h3>Recovery</h3></div>
          <div className="detail-grid">
            <div><div className="field-label">Recovery Status</div><div className="field-value">{titleCaseLabel(recovery.status)}</div></div>
            <div><div className="field-label">Retryable</div><div className="field-value">{recovery.retryable ? "yes" : "no"}</div></div>
            <div><div className="field-label">Requeueable</div><div className="field-value">{recovery.requeueable ? "yes" : "no"}</div></div>
            <div><div className="field-label">In Flight</div><div className="field-value">{recovery.in_flight ? "yes" : "no"}</div></div>
          </div>
          <p className="muted" style={{ marginTop: 12 }}>{recovery.message}</p>
          {actionState.message ? <p className="muted" style={{ marginTop: 12 }}>{actionState.message}</p> : null}
          {recovery.last_failure ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Last Failure</div>
              <div className="field-value">
                {recovery.last_failure.summary || recovery.last_failure.error || "Failure snapshot available."}
              </div>
              {recovery.last_failure.run_id ? (
                <div className="muted small" style={{ marginTop: 6 }}>
                  Run {recovery.last_failure.run_id}
                  {recovery.last_failure.action ? ` · recorded before ${recovery.last_failure.action}` : ""}
                </div>
              ) : null}
            </div>
          ) : null}
          {(recovery.retryable || recovery.requeueable) ? (
            <div className="inline-action-row" style={{ marginTop: 12 }}>
              {recovery.retryable ? (
                <button type="button" className="ghost sm" disabled={actionState.status === "submitting"} onClick={handleRetryTask}>
                  Retry Now
                </button>
              ) : null}
              {recovery.requeueable ? (
                <button type="button" className="ghost sm" disabled={actionState.status === "submitting"} onClick={handleRequeueTask}>
                  Requeue
                </button>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}
      {payload.result_run_artifacts?.length ? (
        <section className="card" style={{ marginTop: 12 }}>
          <div className="card-header"><h3>Artifacts</h3></div>
          <div className="canvas-table-wrap">
            <table className="canvas-table">
              <thead><tr><th>Label</th><th>Type</th><th>Created</th></tr></thead>
              <tbody>
                {payload.result_run_artifacts.map((artifact) => (
                  <tr key={artifact.id}>
                    <td>
                      <button
                        type="button"
                        className="ghost sm"
                        onClick={() => {
                          if (!payload.runtime_run_id) return;
                          onOpenPanel("artifact_detail", {
                            runtime_run_id: payload.runtime_run_id,
                            runtime_artifact_id: artifact.id,
                          });
                        }}
                      >
                        {artifact.name}
                      </button>
                    </td>
                    <td>{artifact.kind || "artifact"}</td>
                    <td>{artifact.created_at || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}

function RuntimeArtifactDetailPanel({
  runId,
  artifactId,
  workspaceId,
  onOpenPanel,
}: {
  runId: string;
  artifactId: string;
  workspaceId?: string;
} & PanelProps) {
  const [payload, setPayload] = useState<RuntimeRunArtifactContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        if (!workspaceId) {
          setPayload(null);
          setError("Workspace context is required.");
          return;
        }
        setLoading(true);
        setError(null);
        const next = await getRuntimeRunArtifactContent(workspaceId, runId, artifactId);
        if (!active) return;
        setPayload(next);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load runtime artifact");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [artifactId, runId, workspaceId]);

  if (loading) return <p className="muted">Loading run artifact…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">Run artifact not found.</p>;

  const contentType = String(payload.content_type || "").toLowerCase();
  const isJson = contentType.includes("json") || payload.label.endsWith(".json");
  let renderedContent = payload.content;
  if (isJson) {
    try {
      renderedContent = JSON.stringify(JSON.parse(payload.content || "{}"), null, 2);
    } catch {
      renderedContent = payload.content;
    }
  }

  return (
    <div className="ems-panel-body">
      <div className="inline-actions" style={{ marginBottom: 12 }}>
        <button type="button" className="ghost sm" onClick={() => onOpenPanel("run_detail", { run_id: runId })}>
          Open Run
        </button>
        <span className="muted small">Run {runId}</span>
      </div>
      <div className="detail-grid">
        <div><div className="field-label">Label</div><div className="field-value">{payload.label}</div></div>
        <div><div className="field-label">Type</div><div className="field-value">{payload.artifact_type}</div></div>
        <div><div className="field-label">URI</div><div className="field-value">{payload.uri}</div></div>
      </div>
      <section className="card" style={{ marginTop: 12 }}>
        <div className="card-header">
          <div>
            <p className="muted">Artifact Evolution</p>
          </div>
        </div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Run</th>
                <th>Created</th>
                <th>Current</th>
              </tr>
            </thead>
            <tbody>
              {(payload.evolution || []).map((entry) => (
                <tr key={`${entry.run_id}:${entry.artifact_id}`}>
                  <td>{entry.label}</td>
                  <td>{entry.run_id}</td>
                  <td>{String(entry.created_at || "—")}</td>
                  <td>{entry.is_current ? "yes" : "no"}</td>
                </tr>
              ))}
              {!payload.evolution?.length ? (
                <tr>
                  <td colSpan={4} className="muted">
                    No prior artifact versions were found for this logical artifact.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
      {payload.analysis ? (
        <section className="card" style={{ marginTop: 12 }}>
          <div className="card-header">
            <div>
              <p className="muted">Artifact Analysis</p>
            </div>
          </div>
          <div className="detail-grid">
            <div><div className="field-label">Status</div><div className="field-value">{payload.analysis.status}</div></div>
            <div><div className="field-label">Versions</div><div className="field-value">{payload.analysis.version_count}</div></div>
            <div><div className="field-label">Recent Activity</div><div className="field-value">{payload.analysis.recent_activity_count}</div></div>
            <div><div className="field-label">Provenance</div><div className="field-value">{payload.analysis.provenance.summary}</div></div>
          </div>
          {payload.analysis.observations.length ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Observations</div>
              <ul className="detail-list">
                {payload.analysis.observations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {payload.analysis.evidence.length ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Evidence</div>
              <ul className="detail-list">
                {payload.analysis.evidence.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {payload.analysis.suggested_human_review_focus ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Suggested Review Focus</div>
              <div className="field-value">{payload.analysis.suggested_human_review_focus}</div>
            </div>
          ) : null}
        </section>
      ) : null}
      <pre className="code-block">{renderedContent}</pre>
    </div>
  );
}

function RunsPanel({
  query,
  queryError,
  workspaceId,
  panel,
  onContextChange,
  onOpenDetail,
  onTitleChange,
}: {
  query?: CanvasQuery;
  queryError?: string;
  workspaceId?: string;
  panel: ConsolePanelSpec | null;
  onContextChange?: ContextEmitter;
  onOpenDetail: (target: OpenDetailTarget, row: Record<string, unknown>) => void;
  onTitleChange?: (title: string) => void;
}) {
  const [payload, setPayload] = useState<CanvasTableResponse | null>(null);
  const [runs, setRuns] = useState<RuntimeRunSummary[]>([]);
  const [activeQuery, setActiveQuery] = useState<CanvasQuery>({
    entity: "runs",
    filters: [],
    sort: [{ field: "created_at", dir: "desc" }],
    limit: 50,
    offset: 0,
  });
  const [selectedRowIds, setSelectedRowIds] = useState<string[]>([]);
  const [focusedRowId, setFocusedRowId] = useState<string | null>(null);
  const [rowOrderIds, setRowOrderIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [degradedMode, setDegradedMode] = useState(false);

  useEffect(() => {
    if (query) {
      setActiveQuery(query);
      return;
    }
    setActiveQuery({ entity: "runs", filters: [], sort: [{ field: "created_at", dir: "desc" }], limit: 50, offset: 0 });
  }, [query]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        if (!workspaceId) {
          setPayload(null);
          setError("Workspace context is required.");
          return;
        }
        setLoading(true);
        setError(null);
        const statusEq = (activeQuery.filters || []).find((entry) => entry.field === "status" && entry.op === "eq");
        const response = await listRuntimeRunsCanvasApi(workspaceId, statusEq ? String(statusEq.value || "") : undefined);
        if (!active) return;
        setRuns(response.runs || []);
        setDegradedMode(false);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load runs");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [activeQuery, workspaceId]);

  useEffect(() => {
    const searchContains = (activeQuery.filters || []).find((entry) => entry.op === "contains" && ["summary", "work_item_id", "worker_type"].includes(entry.field));
    const baseRows: Array<Record<string, unknown>> = runs.map((run: RuntimeRunSummary) => ({
      id: run.id,
      work_item_id: run.work_item_id || "",
      worker_type: run.worker_type || "",
      status: run.status,
      elapsed_time: formatDuration(run.elapsed_time_seconds),
      elapsed_time_seconds: run.elapsed_time_seconds ?? 0,
      heartbeat_freshness: run.heartbeat_freshness || "missing",
      summary: run.summary || "",
      created_at: toIso(run.created_at),
      started_at: toIso(run.started_at),
      completed_at: toIso(run.completed_at),
    }));
    let rows = [...baseRows];
    for (const filter of activeQuery.filters || []) {
      rows = rows.filter((row) => rowMatches(row, filter, RUNS_DATASET_COLUMNS as unknown as Array<{ key: string; type: string }>));
    }
    if (searchContains) {
      const needle = String(searchContains.value || "").toLowerCase();
      rows = rows.filter((row) =>
        [row.summary, row.work_item_id, row.worker_type, row.id].some((value) => String(value || "").toLowerCase().includes(needle))
      );
    }
    for (const sortRow of [...(activeQuery.sort || [])].reverse()) {
      const field = String(sortRow.field || "");
      const dir = sortRow.dir === "asc" ? "asc" : "desc";
      rows.sort((left, right) => {
        const effectiveField = field === "elapsed_time" ? "elapsed_time_seconds" : field;
        const column = RUNS_DATASET_COLUMNS.find((entry) => entry.key === field);
        const cmp = compareValues(left[effectiveField], right[effectiveField], column?.type);
        return dir === "asc" ? cmp : -cmp;
      });
    }
    const offset = Math.max(0, Number(activeQuery.offset || 0));
    const limit = Math.max(1, Number(activeQuery.limit || 50));
    const paged = rows.slice(offset, offset + limit);
    setPayload({
      type: "canvas.table",
      title: "Runs",
      dataset: {
        name: "runs",
        primary_key: "id",
        columns: [...RUNS_DATASET_COLUMNS],
        rows: paged,
        total_count: rows.length,
      },
      query: activeQuery,
    });
    setRowOrderIds(paged.map((row) => String(row.id || "")));
  }, [activeQuery, runs]);

  useEffect(() => {
    if (!workspaceId) return;
    const subscription = subscribeRuntimeEventStream({
      workspaceId,
      onOpen: () => setDegradedMode(false),
      onError: () => setDegradedMode(true),
      onEvent: (event) => {
        setDegradedMode(false);
        setRuns((current) => applyRuntimeEventToRuns(current, event));
      },
    });
    return () => subscription.close();
  }, [workspaceId]);

  useEffect(() => {
    if (!degradedMode) return;
    const interval = window.setInterval(() => {
      setActiveQuery((current) => ({ ...current }));
    }, 30000);
    return () => window.clearInterval(interval);
  }, [degradedMode]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setRuns((current) => current.map((run) => refreshRuntimeRunSummary(run)));
    }, 5000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    emitTableContext({ onContextChange, panel, payload, query: activeQuery, selectedRowIds, focusedRowId, rowOrderIds });
  }, [activeQuery, focusedRowId, onContextChange, panel, payload, rowOrderIds, selectedRowIds]);

  useEffect(() => {
    if (!onTitleChange) return;
    if (!payload?.title) return;
    onTitleChange(String(payload.title));
  }, [onTitleChange, payload?.title]);

  if (loading) return <p className="muted">Loading runs…</p>;
  if (queryError) return <p className="muted">{queryError}</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">No runs found.</p>;

  return (
    <>
      {degradedMode ? <p className="muted small">Live runtime stream unavailable. Falling back to periodic refresh.</p> : null}
      <CanvasRenderer
        payload={payload}
        query={activeQuery}
        onSort={(field, sortable) => {
          if (!sortable) return;
          const same = activeQuery.sort?.[0]?.field === field;
          const dir = same && activeQuery.sort?.[0]?.dir === "asc" ? "desc" : "asc";
          setActiveQuery((current) => ({ ...current, sort: [{ field, dir }] }));
        }}
        onRowActivate={(rowId) => {
          setSelectedRowIds([rowId]);
          setFocusedRowId(rowId);
        }}
        onOpenDetail={onOpenDetail}
      />
    </>
  );
}

function RunDetailPanel({
  runId,
  workspaceId,
  panel,
  onContextChange,
  onOpenPanel,
}: {
  runId: string;
  workspaceId?: string;
  panel: ConsolePanelSpec | null;
  onContextChange?: ContextEmitter;
} & PanelProps) {
  const [payload, setPayload] = useState<RuntimeRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [degradedMode, setDegradedMode] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        if (!workspaceId) {
          setPayload(null);
          setError("Workspace context is required.");
          return;
        }
        setLoading(true);
        setError(null);
        const next = await getRuntimeRunCanvasApi(workspaceId, runId);
        if (!active) return;
        setPayload(next);
        setDegradedMode(false);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load run detail");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [runId, workspaceId]);

  useEffect(() => {
    if (!workspaceId || !runId) return;
    const subscription = subscribeRuntimeEventStream({
      workspaceId,
      onOpen: () => setDegradedMode(false),
      onError: () => setDegradedMode(true),
      onEvent: (event) => {
        if (event.run_id !== runId) return;
        setDegradedMode(false);
        setPayload((current) => (current ? applyRuntimeEventToRunDetail(current, event) : current));
      },
    });
    return () => subscription.close();
  }, [runId, workspaceId]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setPayload((current) => (current ? refreshRuntimeRunDetail(current) : current));
    }, 5000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!degradedMode || !workspaceId || !runId) return;
    const interval = window.setInterval(async () => {
      try {
        const next = await getRuntimeRunCanvasApi(workspaceId, runId);
        setPayload(next);
      } catch {
        // keep current state
      }
    }, 30000);
    return () => window.clearInterval(interval);
  }, [degradedMode, runId, workspaceId]);

  useEffect(() => {
    if (!onContextChange || !panel?.panel_id || !payload) return;
    onContextChange({
      view_type: "detail",
        entity_type: "run",
        entity_id: payload.id,
        available_tabs: ["overview", "timeline", "artifacts"],
        active_tab: "overview",
        ui: {
        active_panel_id: panel.panel_id,
        panel_id: panel.panel_id,
        panel_type: panel.panel_type || "detail",
        instance_key: panel.instance_key || `run:${payload.id}`,
        active_group_id: panel.active_group_id || null,
        layout_engine: "simple",
      },
    });
  }, [onContextChange, panel, payload]);

  if (loading) return <p className="muted">Loading run detail…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">Run not found.</p>;

  return (
    <div className="ems-panel-body">
      {degradedMode ? <p className="muted small">Live runtime stream unavailable. Falling back to periodic refresh.</p> : null}
      <div className="detail-grid">
        <div>
          <div className="field-label">Run</div>
          <div className="field-value">{payload.id}</div>
        </div>
        <div>
          <div className="field-label">Status</div>
          <div className="field-value">{payload.status}</div>
        </div>
        <div>
          <div className="field-label">Worker</div>
          <div className="field-value">{payload.worker_id || payload.worker_type || "—"}</div>
        </div>
        <div>
          <div className="field-label">Elapsed</div>
          <div className="field-value">{formatDuration(payload.elapsed_time_seconds)}</div>
        </div>
        <div>
          <div className="field-label">Heartbeat</div>
          <div className="field-value">{payload.heartbeat_freshness || "missing"}</div>
        </div>
        <div>
          <div className="field-label">Work Item</div>
          <div className="field-value">{payload.work_item_id || "—"}</div>
        </div>
        <div>
          <div className="field-label">Target Repo</div>
          <div className="field-value">{payload.target.repo || "—"}</div>
        </div>
        <div>
          <div className="field-label">Target Branch</div>
          <div className="field-value">{payload.target.branch || "—"}</div>
        </div>
        <div>
          <div className="field-label">Policy</div>
          <div className="field-value">
            retries {payload.policy.max_retries} · human review {payload.policy.require_human_review_on_failure ? "required" : "optional"}
          </div>
        </div>
      </div>
      {payload.summary ? <p>{payload.summary}</p> : null}
      {payload.failure_reason ? <InlineMessage tone="error" title="Failure reason" body={payload.failure_reason} /> : null}
      {payload.escalation_reason ? <InlineMessage tone="warn" title="Escalation reason" body={payload.escalation_reason} /> : null}
      <section className="card" style={{ marginTop: 12 }}>
        <div className="card-header">
          <h3>Step Timeline</h3>
        </div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Step</th>
                <th>Status</th>
                <th>Started</th>
                <th>Completed</th>
                <th>Summary</th>
              </tr>
            </thead>
            <tbody>
              {payload.steps.map((step) => (
                <tr key={step.id}>
                  <td>{step.label || step.step_key}</td>
                  <td>{step.status}</td>
                  <td>{step.started_at || "—"}</td>
                  <td>{step.completed_at || "—"}</td>
                  <td>{step.summary || "—"}</td>
                </tr>
              ))}
              {!payload.steps.length ? (
                <tr>
                  <td colSpan={5} className="muted">No steps reported.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card" style={{ marginTop: 12 }}>
        <div className="card-header">
          <h3>Artifacts</h3>
        </div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Type</th>
                <th>URI</th>
              </tr>
            </thead>
            <tbody>
              {payload.artifacts.map((artifact) => (
                <tr key={artifact.id}>
                  <td>
                    <button
                      type="button"
                      className="ghost sm"
                      onClick={() =>
                        onOpenPanel("artifact_detail", {
                          runtime_run_id: runId,
                          runtime_artifact_id: artifact.id,
                        })
                      }
                    >
                      {artifact.label}
                    </button>
                  </td>
                  <td>{artifact.artifact_type}</td>
                  <td>{artifact.uri || "—"}</td>
                </tr>
              ))}
              {!payload.artifacts.length ? (
                <tr>
                  <td colSpan={3} className="muted">No artifacts captured.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

const VALID_SETTINGS_SECTIONS: HubSection[] = ["general", "security", "integrations", "deploy", "workspaces"];

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
  | "branding"
  | "workspaces";

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
      return "Deploy Settings";
    case "branding":
      return "Branding";
    case "workspaces":
      return "Workspaces";
    default:
      return "Platform Settings";
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
  if (path.endsWith("/platform/branding")) return "branding";
  if (path.endsWith("/platform/workspaces")) return "workspaces";
  return null;
}

const PlatformSettingsPanel = React.memo(function PlatformSettingsPanel({
  workspaceId,
  workspaceName,
  initialSection,
  onSectionChange,
  initialSurface,
  onSurfaceChange,
}: {
  workspaceId: string;
  workspaceName?: string;
  initialSection?: string;
  onSectionChange?: (section: HubSection) => void;
  initialSurface?: string;
  onSurfaceChange?: (surface: PlatformSettingsSurface) => void;
}) {
  const parsed = String(initialSection || "").trim().toLowerCase();
  const init: HubSection = (VALID_SETTINGS_SECTIONS as string[]).includes(parsed) ? (parsed as HubSection) : "security";
  const [section, setSection] = useState<HubSection>(init);
  const parsedSurface = String(initialSurface || "").trim().toLowerCase();
  const initialPanelSurface = ([
    "access_control",
    "identity_configuration",
    "secrets",
    "activity",
    "ai_routing",
    "ai_agents",
    "rendering_settings",
    "deploy_settings",
    "branding",
    "workspaces",
  ] as string[]).includes(parsedSurface)
    ? (parsedSurface as PlatformSettingsSurface)
    : "hub";
  const [tabs, setTabs] = useState<PlatformSettingsTab[]>(() =>
    initialPanelSurface === "hub"
      ? [DEFAULT_PLATFORM_SETTINGS_TAB]
      : [DEFAULT_PLATFORM_SETTINGS_TAB, { id: `platform-settings-${initialPanelSurface}`, surface: initialPanelSurface, label: platformSettingsSurfaceLabel(initialPanelSurface) }]
  );
  const [activeTabId, setActiveTabId] = useState<string>(
    initialPanelSurface === "hub" ? DEFAULT_PLATFORM_SETTINGS_TAB.id : `platform-settings-${initialPanelSurface}`
  );

  useEffect(() => {
    setSection(init);
  }, [init]);

  useEffect(() => {
    if (initialPanelSurface === "hub") return;
    const tabId = `platform-settings-${initialPanelSurface}`;
    setTabs((current) => {
      if (current.some((item) => item.id === tabId)) return current;
      return [...current, { id: tabId, surface: initialPanelSurface, label: platformSettingsSurfaceLabel(initialPanelSurface) }];
    });
    setActiveTabId(tabId);
  }, [initialPanelSurface]);

  const handleChange = (next: HubSection) => {
    if (next === section) return;
    setSection(next);
    onSectionChange?.(next);
  };

  const openSurfaceTab = (surface: PlatformSettingsSurface) => {
    if (surface === "hub") {
      setActiveTabId(DEFAULT_PLATFORM_SETTINGS_TAB.id);
      onSurfaceChange?.("hub");
      return;
    }
    const tabId = `platform-settings-${surface}`;
    setTabs((current) => {
      if (current.some((item) => item.id === tabId)) return current;
      return [...current, { id: tabId, surface, label: platformSettingsSurfaceLabel(surface) }];
    });
    setActiveTabId(tabId);
    onSurfaceChange?.(surface);
  };

  const closeSurfaceTab = (tabId: string) => {
    if (tabId === DEFAULT_PLATFORM_SETTINGS_TAB.id) return;
    setTabs((current) => {
      const next = current.filter((item) => item.id !== tabId);
      return next.length ? next : [DEFAULT_PLATFORM_SETTINGS_TAB];
    });
    setActiveTabId((current) => (current === tabId ? DEFAULT_PLATFORM_SETTINGS_TAB.id : current));
  };

  const activeSurface =
    tabs.find((item) => item.id === activeTabId)?.surface ||
    tabs[tabs.length - 1]?.surface ||
    DEFAULT_PLATFORM_SETTINGS_TAB.surface;

  return (
    <div style={{ display: "grid", gap: 8 }}>
      <div className="page-tabs" aria-label="Platform settings panel tabs">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {tabs.map((tab) => (
            <div key={tab.id} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <button
                type="button"
                className={activeTabId === tab.id ? "ghost active" : "ghost"}
                onClick={() => {
                  setActiveTabId(tab.id);
                  onSurfaceChange?.(tab.surface);
                }}
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
          sectionOverride={section}
          onSectionChange={handleChange}
          onOpenRoute={(route) => {
            const mapped = mapPlatformSettingsRouteToSurface(route);
            if (mapped) {
              openSurfaceTab(mapped);
            }
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
      {activeSurface === "branding" ? <PlatformBrandingPage /> : null}
      {activeSurface === "workspaces" ? (
        <WorkspacesPage
          activeWorkspaceId={workspaceId}
          activeWorkspaceName={workspaceName || workspaceId}
          canWorkspaceAdmin
          canManageWorkspaces
        />
      ) : null}
    </div>
  );
});

function ArtifactListPanel({
  namespace,
  workspaceId,
  query,
  queryError,
  onOpenArtifactDetail,
  panel,
  onContextChange,
  onTitleChange,
}: {
  namespace?: string;
  workspaceId?: string;
  query?: ArtifactStructuredQuery;
  queryError?: string;
  onOpenArtifactDetail: (slug: string) => void;
  panel: ConsolePanelSpec | null;
  onContextChange?: ContextEmitter;
  onTitleChange?: (title: string) => void;
}) {
  const [payload, setPayload] = useState<ArtifactCanvasTableResponse | null>(null);
  const [activeQuery, setActiveQuery] = useState<ArtifactStructuredQuery>(baseArtifactQuery());
  const [selectedRowIds, setSelectedRowIds] = useState<string[]>([]);
  const [focusedRowId, setFocusedRowId] = useState<string | null>(null);
  const [rowOrderIds, setRowOrderIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (query) {
      setActiveQuery(query);
      return;
    }
    if (namespace) {
      setActiveQuery({
        ...baseArtifactQuery(),
        filters: [{ field: "namespace", op: "eq", value: namespace }],
      });
      return;
    }
    setActiveQuery(baseArtifactQuery());
  }, [namespace, query]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await queryArtifactCanvasTable({ workspaceId: workspaceId || undefined, query: activeQuery });
        if (!active) return;
        setPayload(next);
        setRowOrderIds((next.dataset.rows || []).map((row, index) => String(row[next.dataset.primary_key] || index)));
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load artifacts");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [activeQuery, workspaceId]);

  useEffect(() => {
    emitTableContext({ onContextChange, panel, payload, query: activeQuery, selectedRowIds, focusedRowId, rowOrderIds });
  }, [activeQuery, focusedRowId, onContextChange, panel, payload, rowOrderIds, selectedRowIds]);

  useEffect(() => {
    if (!onTitleChange) return;
    if (!payload?.title) return;
    onTitleChange(String(payload.title));
  }, [onTitleChange, payload?.title]);

  if (loading) return <p className="muted">Loading artifacts…</p>;
  if (queryError) return <p className="muted">{queryError}</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">No artifacts found.</p>;

  return (
    <CanvasRenderer
      payload={payload}
      query={activeQuery}
      onSort={(field, sortable) => {
        if (!sortable) return;
        const same = activeQuery.sort?.[0]?.field === field;
        const dir = same && activeQuery.sort?.[0]?.dir === "asc" ? "desc" : "asc";
        setActiveQuery((current) => ({ ...current, sort: [{ field, dir }] }));
      }}
      onRowActivate={(rowId) => {
        setSelectedRowIds([rowId]);
        setFocusedRowId(rowId);
      }}
      onOpenDetail={(target) => {
        if (target.entity_type === "artifact") {
          onOpenArtifactDetail(target.entity_id);
        }
      }}
    />
  );
}

function EmsCanvasPanel({
  fetcher,
  initialQuery,
  queryError,
  panel,
  onContextChange,
  onOpenDetail,
  onTitleChange,
}: {
  fetcher: (query: CanvasQuery) => Promise<CanvasTableResponse>;
  initialQuery: CanvasQuery;
  queryError?: string;
  panel: ConsolePanelSpec | null;
  onContextChange?: ContextEmitter;
  onOpenDetail: (target: OpenDetailTarget, row: Record<string, unknown>) => void;
  onTitleChange?: (title: string) => void;
}) {
  const [payload, setPayload] = useState<CanvasTableResponse | null>(null);
  const [query, setQuery] = useState<CanvasQuery>(initialQuery);
  const [selectedRowIds, setSelectedRowIds] = useState<string[]>([]);
  const [focusedRowId, setFocusedRowId] = useState<string | null>(null);
  const [rowOrderIds, setRowOrderIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setQuery(initialQuery), [initialQuery]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await fetcher(query);
        if (!active) return;
        setPayload(next);
        setRowOrderIds((next.dataset.rows || []).map((row, index) => String(row[next.dataset.primary_key] || index)));
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load panel");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [fetcher, query]);

  useEffect(() => {
    emitTableContext({ onContextChange, panel, payload, query, selectedRowIds, focusedRowId, rowOrderIds });
  }, [focusedRowId, onContextChange, panel, payload, query, rowOrderIds, selectedRowIds]);

  useEffect(() => {
    if (!onTitleChange) return;
    if (!payload?.title) return;
    onTitleChange(String(payload.title));
  }, [onTitleChange, payload?.title]);

  if (loading) return <p className="muted">Loading…</p>;
  if (queryError) return <p className="muted">{queryError}</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">No rows.</p>;

  return (
    <CanvasRenderer
      payload={payload}
      query={query}
      onSort={(field, sortable) => {
        if (!sortable) return;
        const same = query.sort?.[0]?.field === field;
        const dir = same && query.sort?.[0]?.dir === "asc" ? "desc" : "asc";
        setQuery((current) => ({ ...current, sort: [{ field, dir }] }));
      }}
      onRowActivate={(rowId) => {
        setSelectedRowIds([rowId]);
        setFocusedRowId(rowId);
      }}
      onOpenDetail={onOpenDetail}
    />
  );
}

function ArtifactDetailPanel({
  slug,
  onOpenPanel,
  panel,
  onContextChange,
}: { slug: string; panel: ConsolePanelSpec | null; onContextChange?: ContextEmitter } & PanelProps) {
  const params = useParams();
  const navigate = useNavigate();
  const workspaceId = String(params.workspaceId || "").trim();
  const [payload, setPayload] = useState<ArtifactConsoleDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [unavailableReason, setUnavailableReason] = useState<"not_found" | "access_denied" | null>(null);
  const [activationBusy, setActivationBusy] = useState(false);
  const [activationFeedback, setActivationFeedback] = useState<{ tone: "info" | "warn" | "error"; title: string; body?: string } | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        setUnavailableReason(null);
        setPayload(null);
        const next = await getArtifactConsoleDetailBySlug(slug, { workspaceId: workspaceId || undefined });
        if (!active) return;
        setPayload(next);
      } catch (err) {
        if (!active) return;
        const message = err instanceof Error ? err.message : "Failed to load artifact detail";
        const reason = classifyWorkspaceUnavailableReason(message);
        if (reason === "not_found" || reason === "access_denied") {
          setUnavailableReason(reason);
          setError(null);
          return;
        }
        setError(message);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [slug, workspaceId]);

  useEffect(() => {
    if (!onContextChange || !panel?.panel_id || !payload) return;
    onContextChange({
      view_type: "detail",
      entity_type: "artifact",
      entity_id: payload.artifact.slug,
      available_tabs: ["overview", "raw", "files", "manage", "docs"],
      active_tab: String(panel.params?.tab || "overview"),
      ui: {
        active_panel_id: panel.panel_id,
        panel_id: panel.panel_id,
        panel_type: panel.panel_type || "detail",
        instance_key: panel.instance_key || `artifact:${payload.artifact.slug}`,
        active_group_id: panel.active_group_id || null,
        layout_engine: "simple",
      },
    });
  }, [onContextChange, panel, payload]);

  if (loading) return <p className="muted">Loading artifact detail…</p>;
  if (unavailableReason || !payload) {
    return (
      <WorkspaceUnavailableState
        itemLabel="Artifact"
        workspaceLabel={workspaceId || "this workspace"}
        reason={unavailableReason || "not_found"}
        onOpenList={() => onOpenPanel("artifact_list")}
        openListLabel="Open Artifacts"
      />
    );
  }
  if (error) return <p className="danger-text">{error}</p>;

  const manage = payload.manifest_summary?.surfaces?.manage || [];
  const docs = payload.manifest_summary?.surfaces?.docs || [];

  const resolveSurfacePath = (path: string) => {
    const normalized = String(path || "").trim();
    if (!normalized) return "";
    if (/^https?:\/\//i.test(normalized)) return normalized;
    if (/^\/w\/[^/]+\/.+/.test(normalized)) return normalized;
    if (normalized.startsWith("/")) return workspaceId ? toWorkspacePath(workspaceId, normalized.replace(/^\/+/, "")) : normalized;
    return workspaceId ? toWorkspacePath(workspaceId, normalized) : `/${normalized}`;
  };

  const openSurfacePath = (path: string) => {
    const target = resolveSurfacePath(path);
    if (!target) return;
    if (/^https?:\/\//i.test(target)) {
      window.location.href = target;
      return;
    }
    navigate(target);
  };

  const resolveRuntimeTargetUrl = (response: ArtifactActivationResponse): string => {
    const runtimeTarget = response.runtime_target && typeof response.runtime_target === "object" ? response.runtime_target : {};
    const runtimeInstance = response.runtime_instance && typeof response.runtime_instance === "object" ? response.runtime_instance : {};
    const candidates = [
      String((runtimeTarget as Record<string, unknown>).runtime_url || "").trim(),
      String((runtimeTarget as Record<string, unknown>).app_url || "").trim(),
      String((runtimeTarget as Record<string, unknown>).url || "").trim(),
      String((runtimeTarget as Record<string, unknown>).fqdn || "").trim(),
      String((runtimeInstance as Record<string, unknown>).fqdn || "").trim(),
    ].filter(Boolean);
    const first = candidates[0] || "";
    if (!first) return "";
    if (/^https?:\/\//i.test(first)) return first;
    if (/^[a-z0-9.-]+\.[a-z]{2,}$/i.test(first)) return `https://${first}`;
    return "";
  };

  const handleActivateInSibling = async () => {
    if (!payload?.artifact?.id || activationBusy) return;
    setActivationBusy(true);
    setActivationFeedback(null);
    try {
      const response = await activateArtifact(payload.artifact.id);
      if (response.status === "reused") {
        const target = resolveRuntimeTargetUrl(response);
        if (target) {
          window.open(target, "_blank", "noopener,noreferrer");
          setActivationFeedback({ tone: "info", title: "Opened existing dev sibling runtime.", body: `Target: ${target}` });
        } else {
          setActivationFeedback({
            tone: "info",
            title: "Reused existing dev sibling runtime.",
            body: "Runtime target is active, but no openable URL was returned.",
          });
        }
        return;
      }
      if (response.status === "queued_existing") {
        const draftId = String(response.activation?.draft_id || response.in_flight?.draft_id || "").trim();
        const jobId = String(response.activation?.job_id || response.in_flight?.job_id || "").trim();
        setActivationFeedback({ tone: "info", title: "Activation is already in progress.", body: `Draft ${draftId || "—"} · Job ${jobId || "—"}` });
        return;
      }
      const draftId = String(response.activation?.draft_id || "").trim();
      const jobId = String(response.activation?.job_id || "").trim();
      setActivationFeedback({ tone: "info", title: "Activation queued for dev sibling.", body: `Draft ${draftId || "—"} · Job ${jobId || "—"}` });
    } catch (err) {
      setActivationFeedback({
        tone: "error",
        title: "Failed to activate artifact in dev sibling.",
        body: err instanceof Error ? err.message : "Request failed",
      });
    } finally {
      setActivationBusy(false);
    }
  };

  return (
    <div className="ems-panel-body">
      <p className="muted">
        {payload.artifact.slug} · {payload.artifact.kind} · v{payload.artifact.version}
      </p>
      <p className="muted small">Roles: {(payload.manifest_summary?.roles || []).join(", ") || "none"}</p>
      <div className="inline-actions">
        <button type="button" className="primary sm" onClick={() => void handleActivateInSibling()} disabled={activationBusy}>
          {activationBusy ? "Activating…" : "Open in Dev Sibling"}
        </button>
        <button type="button" className="ghost sm" onClick={() => onOpenPanel("artifact_raw_json", { slug: payload.artifact.slug })}>
          Open Raw JSON
        </button>
        <button type="button" className="ghost sm" onClick={() => onOpenPanel("artifact_files", { slug: payload.artifact.slug })}>
          Open Files
        </button>
        <button type="button" className="ghost sm" onClick={() => onOpenPanel("rules_browser", { artifact_slug: payload.artifact.slug })}>
          Browse Rules
        </button>
      </div>
      {activationFeedback ? <InlineMessage tone={activationFeedback.tone} title={activationFeedback.title} body={activationFeedback.body} /> : null}
      {manage.length ? (
        <div>
          <p className="small muted">Manage surfaces</p>
          <ul className="muted">
            {manage.map((entry) => (
              <li key={`${entry.path}:${entry.label}`}>
                <button type="button" className="ghost sm" onClick={() => openSurfacePath(entry.path)}>
                  {entry.label}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {docs.length ? (
        <div>
          <p className="small muted">Docs surfaces</p>
          <ul className="muted">
            {docs.map((entry) => (
              <li key={`${entry.path}:${entry.label}`}>
                <button type="button" className="ghost sm" onClick={() => openSurfacePath(entry.path)}>
                  {entry.label}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function ArtifactRawJsonPanel({ slug }: { slug: string }) {
  const params = useParams();
  const workspaceId = String(params.workspaceId || "").trim();
  const [payload, setPayload] = useState<ArtifactConsoleDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await getArtifactConsoleDetailBySlug(slug, { workspaceId: workspaceId || undefined });
        if (!active) return;
        setPayload(next);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load raw JSON");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [slug, workspaceId]);

  if (loading) return <p className="muted">Loading raw JSON…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  return <pre className="code-block">{JSON.stringify(payload?.raw_artifact_json || {}, null, 2)}</pre>;
}

function ArtifactFilesPanel({ slug }: { slug: string }) {
  const [rows, setRows] = useState<ArtifactConsoleFileRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await getArtifactConsoleFilesBySlug(slug);
        if (!active) return;
        setRows(next.files || []);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load files");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [slug]);

  if (loading) return <p className="muted">Loading files…</p>;
  if (error) return <p className="danger-text">{error}</p>;

  return (
    <div className="ems-panel-body">
      <table className="canvas-table">
        <thead>
          <tr>
            <th>Path</th>
            <th>Size</th>
            <th>SHA256</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.path}>
              <td>{row.path}</td>
              <td>{row.size_bytes}</td>
              <td className="muted small">{row.sha256}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GenericRecordDetailPanel({
  entityType,
  entityId,
  dataset,
  row,
  panel,
  onContextChange,
}: {
  entityType: string;
  entityId: string;
  dataset?: string;
  row?: Record<string, unknown>;
  panel: ConsolePanelSpec | null;
  onContextChange?: ContextEmitter;
}) {
  useEffect(() => {
    if (!onContextChange || !panel?.panel_id) return;
    onContextChange({
      view_type: "detail",
      entity_type: entityType,
      entity_id: entityId,
      available_tabs: ["overview", "raw"],
      active_tab: "overview",
      ui: {
        active_panel_id: panel.panel_id,
        panel_id: panel.panel_id,
        panel_type: panel.panel_type || "detail",
        instance_key: panel.instance_key || `${entityType}:${entityId}`,
        active_group_id: panel.active_group_id || null,
        layout_engine: "simple",
      },
    });
  }, [entityId, entityType, onContextChange, panel]);

  return (
    <div className="ems-panel-body">
      <p className="muted">
        {entityType} · {entityId}
      </p>
      {dataset ? <p className="muted small">Dataset: {dataset}</p> : null}
      <pre className="code-block">{JSON.stringify(row || {}, null, 2)}</pre>
    </div>
  );
}

function LocalProvisionResultPanel({ payload }: { payload?: LocalProvisionResponse | null }) {
  if (!payload) return <p className="muted">No provisioning result available.</p>;
  return (
    <div className="ems-panel-body">
      <p className="muted">
        {payload.status} · {payload.compose_project}
      </p>
      <div className="inline-actions">
        {payload.ui_url ? (
          <a className="ghost sm" href={payload.ui_url} target="_blank" rel="noreferrer">
            Open UI
          </a>
        ) : null}
        {payload.api_url ? (
          <a className="ghost sm" href={payload.api_url} target="_blank" rel="noreferrer">
            Open API
          </a>
        ) : null}
      </div>
      <pre className="code-block">{JSON.stringify(payload, null, 2)}</pre>
    </div>
  );
}

function ApplicationPlanDetailPanel({
  applicationPlanId,
  onOpenPanel,
  onTitleChange,
}: {
  applicationPlanId: string;
  onTitleChange?: (title: string) => void;
} & PanelProps) {
  const [payload, setPayload] = useState<ApplicationPlanDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<React.ReactNode>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await getApplicationPlan(applicationPlanId);
        if (!active) return;
        setPayload(next);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load application plan");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [applicationPlanId]);

  useEffect(() => {
    onTitleChange?.(payload?.name || "Application Plan");
  }, [onTitleChange, payload?.name]);

  async function handleApply() {
    try {
      const response = await applyApplicationPlan(applicationPlanId);
      setPayload(response.application_plan);
      setMessage(
        response.status === "applied"
          ? "Applied application plan into durable goals, threads, and work items."
          : "Application plan was already applied."
      );
      onOpenPanel("application_detail", { application_id: response.application.id });
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to apply application plan");
    }
  }

  if (loading) return <p className="muted">Loading application plan…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">Application plan not found.</p>;
  const generatedPlan = payload.generated_plan ?? {
    ordering_hints: payload.ordering_hints ?? [],
    dependency_hints: payload.dependency_hints ?? [],
    generated_goals: payload.generated_goals ?? [],
  };

  return (
    <div className="panel-section-stack">
      <section className="card">
        <div className="detail-grid">
          <div><div className="field-label">Application</div><div className="field-value">{payload.name}</div></div>
          <div><div className="field-label">Factory</div><div className="field-value">{payload.factory?.name || payload.source_factory_key}</div></div>
          <div><div className="field-label">Status</div><div className="field-value">{payload.status}</div></div>
          <div><div className="field-label">Generated Goals</div><div className="field-value">{generatedPlan.generated_goals.length}</div></div>
        </div>
        <p className="muted" style={{ marginTop: 12 }}>{payload.summary}</p>
        {message ? <InlineMessage tone="info" title="Plan Apply" body={message} /> : null}
        <div className="inline-action-row" style={{ marginTop: 12 }}>
          <button type="button" className="ghost sm" disabled={payload.status === "applied"} onClick={handleApply}>
            Apply Plan
          </button>
        </div>
      </section>
      <section className="card">
        <div className="field-label">Ordering Hints</div>
        <ul className="detail-list">
          {generatedPlan.ordering_hints.map((item) => <li key={item}>{item}</li>)}
          {!generatedPlan.ordering_hints.length ? <li className="muted">No ordering hints.</li> : null}
        </ul>
        <div className="field-label" style={{ marginTop: 12 }}>Dependency Hints</div>
        <ul className="detail-list">
          {generatedPlan.dependency_hints.map((item) => <li key={item}>{item}</li>)}
          {!generatedPlan.dependency_hints.length ? <li className="muted">No dependency hints.</li> : null}
        </ul>
      </section>
      {generatedPlan.generated_goals.map((goal) => (
        <section className="card" key={goal.title}>
          <div className="card-header"><div><p className="muted">{goal.title}</p></div></div>
          <p className="muted">{goal.planning_summary}</p>
          <div className="canvas-table-wrap" style={{ marginTop: 12 }}>
            <table className="canvas-table">
              <thead>
                <tr>
                  <th>Thread</th>
                  <th>Priority</th>
                  <th>Initial Work</th>
                </tr>
              </thead>
              <tbody>
                {goal.threads.map((thread) => (
                  <tr key={thread.title}>
                    <td>{thread.title}</td>
                    <td>{thread.priority}</td>
                    <td>{goal.work_items.filter((item) => item.thread_title === thread.title).length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}

function ApplicationDetailPanel({
  applicationId,
  onOpenPanel,
  onTitleChange,
}: {
  applicationId: string;
  onTitleChange?: (title: string) => void;
} & PanelProps) {
  const [payload, setPayload] = useState<ApplicationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await getApplication(applicationId);
        if (!active) return;
        setPayload(next);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load application");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [applicationId]);

  useEffect(() => {
    onTitleChange?.(payload?.name || "Application");
  }, [onTitleChange, payload?.name]);

  if (loading) return <p className="muted">Loading application…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">Application not found.</p>;

  return (
    <div className="panel-section-stack">
      <section className="card">
        <div className="detail-grid">
          <div><div className="field-label">Application</div><div className="field-value">{payload.name}</div></div>
          <div><div className="field-label">Factory</div><div className="field-value">{payload.source_factory_key}</div></div>
          <div><div className="field-label">Status</div><div className="field-value">{payload.status}</div></div>
          <div><div className="field-label">Goals</div><div className="field-value">{payload.goal_count}</div></div>
        </div>
        <p className="muted" style={{ marginTop: 12 }}>{payload.summary}</p>
      </section>
      {payload.portfolio_state ? (
        <section className="card">
          <div className="detail-grid">
            <div><div className="field-label">Active Goals</div><div className="field-value">{payload.portfolio_state.goals.filter((goal) => goal.health_status === "active").length}</div></div>
            <div><div className="field-label">Blocked Goals</div><div className="field-value">{payload.portfolio_state.goals.filter((goal) => goal.health_status === "blocked").length}</div></div>
            <div><div className="field-label">Recent Execution</div><div className="field-value">{payload.portfolio_state.goals.reduce((sum, goal) => sum + (goal.recent_execution_count || 0), 0)}</div></div>
          </div>
          {payload.portfolio_state.recommended_goal ? (
            <InlineMessage tone="info" title={`Recommended Goal: ${payload.portfolio_state.recommended_goal.title}`} body={payload.portfolio_state.recommended_goal.summary} />
          ) : null}
        </section>
      ) : null}
      <section className="card">
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Goal</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Threads</th>
                <th>Work Items</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {payload.goals.map((goal) => (
                <tr key={goal.id}>
                  <td>{goal.title}</td>
                  <td>{goal.planning_status}</td>
                  <td>{goal.goal_progress_status || "—"}</td>
                  <td>{goal.thread_count}</td>
                  <td>{goal.work_item_count}</td>
                  <td><button type="button" className="ghost sm" onClick={() => onOpenPanel("goal_detail", { goal_id: goal.id })}>Open Goal</button></td>
                </tr>
              ))}
              {!payload.goals.length ? <tr><td colSpan={6} className="muted">No goals found for this application.</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function ComposerDetailPanel({
  workspaceId,
  currentUser,
  factoryKey,
  applicationPlanId,
  applicationId,
  goalId,
  threadId,
  solutionChangeSessionId,
  onOpenPanel,
  onTitleChange,
}: {
  workspaceId: string;
  currentUser?: Record<string, unknown> | null;
  factoryKey?: string;
  applicationPlanId?: string;
  applicationId?: string;
  goalId?: string;
  threadId?: string;
  solutionChangeSessionId?: string;
  onTitleChange?: (title: string) => void;
} & PanelProps) {
  const [payload, setPayload] = useState<ComposerState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<React.ReactNode>(null);
  const [requestDraft, setRequestDraft] = useState("");
  const [refinementDraft, setRefinementDraft] = useState("");
  const [questionReplyDraft, setQuestionReplyDraft] = useState("");
  const [approvalNotes, setApprovalNotes] = useState<Record<string, string>>({});
  const [showApprovalNoteByCheckpoint, setShowApprovalNoteByCheckpoint] = useState<Record<string, boolean>>({});
  const [selectedOptionByTurn, setSelectedOptionByTurn] = useState<Record<string, string>>({});
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [planningRoutingStatus, setPlanningRoutingStatus] = useState<AiRoutingStatusResponse | null>(null);
  const [availableAgents, setAvailableAgents] = useState<AiAgent[]>([]);
  const latestTurnRef = useRef<HTMLLIElement | null>(null);
  const shouldAutoScrollToLatestTurnRef = useRef(false);
  const currentUserProfile = useMemo(
    () => resolveUserProfile((currentUser as Record<string, unknown>) || {}),
    [currentUser]
  );

  useEffect(() => {
    writeComposerStoredSelection(workspaceId, {
      application_id: applicationId,
      application_plan_id: applicationPlanId,
      solution_change_session_id: solutionChangeSessionId,
    });
  }, [applicationId, applicationPlanId, solutionChangeSessionId, workspaceId]);

  async function reloadComposerState() {
    const next = await getComposerState({
      workspace_id: workspaceId,
      factory_key: factoryKey,
      application_plan_id: applicationPlanId,
      application_id: applicationId,
      goal_id: goalId,
      thread_id: threadId,
      ...(solutionChangeSessionId ? { solution_change_session_id: solutionChangeSessionId } : {}),
    });
      setPayload(next);
      return next;
  }

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await getComposerState({
          workspace_id: workspaceId,
          factory_key: factoryKey,
          application_plan_id: applicationPlanId,
          application_id: applicationId,
          goal_id: goalId,
          thread_id: threadId,
          ...(solutionChangeSessionId ? { solution_change_session_id: solutionChangeSessionId } : {}),
        });
        if (!active) return;
        setPayload(next);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load composer state");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [applicationId, applicationPlanId, factoryKey, goalId, solutionChangeSessionId, threadId, workspaceId]);

  useEffect(() => {
    onTitleChange?.("Composer");
  }, [onTitleChange]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const [routing, agentList] = await Promise.all([getAiRoutingStatus(), listAiAgents({ enabled: true })]);
        if (!active) return;
        setPlanningRoutingStatus(routing);
        setAvailableAgents(agentList.agents || []);
      } catch {
        if (!active) return;
        setPlanningRoutingStatus(null);
        setAvailableAgents([]);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const openComposer = (params?: Record<string, unknown>) => {
    const nextParams = {
      workspace_id: workspaceId,
      ...(params || {}),
    };
    writeComposerStoredSelection(workspaceId, nextParams);
    onOpenPanel("composer_detail", nextParams);
  };

  const mergeUpdatedSession = (updatedSession: any) => {
    setPayload((current) => {
      if (!current) return current;
      const sessions = Array.isArray(current.solution_change_sessions)
        ? current.solution_change_sessions.map((session) =>
            String(session.id) === String(updatedSession?.id) ? updatedSession : session
          )
        : [];
      if (!sessions.find((session) => String(session.id) === String(updatedSession?.id))) {
        sessions.unshift(updatedSession);
      }
      return {
        ...current,
        solution_change_sessions: sessions,
        solution_change_session: updatedSession,
      };
    });
  };

  const selectedSession = payload?.solution_change_session
    || payload?.solution_change_sessions?.find((session) => String(session.id) === String(solutionChangeSessionId || ""))
    || null;
  const selectedSessionId = selectedSession ? String(selectedSession.id) : "";
  const planning = selectedSession?.planning || null;
  const planningTurns = Array.isArray(planning?.turns) ? planning.turns : [];
  const pendingQuestion = planning?.pending_question || null;
  const pendingOptionSet = planning?.pending_option_set || null;
  const pendingCheckpoints = Array.isArray(planning?.pending_checkpoints) ? planning.pending_checkpoints : [];
  const latestDraftPlan = planning?.latest_draft_plan || null;
  const allCheckpoints = Array.isArray(planning?.checkpoints) ? planning.checkpoints : [];
  const hasPendingPrompt = Boolean(pendingQuestion || pendingOptionSet);
  const hasDraftPlan = Boolean(latestDraftPlan || (selectedSession?.plan && Object.keys(selectedSession.plan).length > 0));
  const hasPendingCheckpoint = pendingCheckpoints.length > 0;
  const stageCheckpoint = allCheckpoints.find((entry: any) => String(entry.checkpoint_key || "") === "plan_scope_confirmed") || null;
  const hasApprovedStageCheckpoint = !stageCheckpoint || String(stageCheckpoint.status || "") === "approved";
  const canRunExecution = hasDraftPlan && !hasPendingPrompt && hasApprovedStageCheckpoint && !hasPendingCheckpoint;
  const executionStatusToken = String(selectedSession?.execution_status || "not_started").trim().toLowerCase();
  const previewStatusToken = String(selectedSession?.preview?.status || "").trim().toLowerCase();
  const validationStatusToken = String(selectedSession?.validation?.status || "").trim().toLowerCase();
  const executionPhase = deriveComposerExecutionPhase(executionStatusToken, previewStatusToken, validationStatusToken);
  const currentPhaseLabel = executionPhaseLabel(executionPhase);
  const derivedExecutionNextAction = executionPhaseNextActionLabel(executionPhase);
  const sessionExecutionSummary = selectedSession?.staged_changes?.execution_summary
    && typeof selectedSession.staged_changes.execution_summary === "object"
    ? selectedSession.staged_changes.execution_summary as Record<string, unknown>
    : null;
  const executionQueuedCount = Number(sessionExecutionSummary?.queued_artifacts ?? sessionExecutionSummary?.queued ?? 0);
  const executionFailedCount = Number(sessionExecutionSummary?.failed_artifacts ?? sessionExecutionSummary?.failed ?? 0);
  const executionSkippedCount = Number(sessionExecutionSummary?.skipped_artifacts ?? sessionExecutionSummary?.skipped ?? 0);
  const executionTotalCount = Number(sessionExecutionSummary?.total_artifacts ?? sessionExecutionSummary?.total ?? 0);
  const previewPrimaryUrl = String(selectedSession?.preview?.primary_url || "").trim();
  const previewSessionBuild = selectedSession?.preview?.session_build
    && typeof selectedSession.preview.session_build === "object"
    ? selectedSession.preview.session_build as Record<string, unknown>
    : null;
  const previewBuildStatus = String(previewSessionBuild?.status || "").trim().toLowerCase();
  const previewBuildReason = String(previewSessionBuild?.reason || "").trim();
  const previewSummarySource = String(selectedSession?.preview?.source || selectedSession?.preview?.mode || "").trim().toLowerCase();
  const promotionState = selectedSession?.metadata?.promotion
    && typeof selectedSession.metadata.promotion === "object"
    ? selectedSession.metadata.promotion as Record<string, unknown>
    : null;
  const promotionResult = String(promotionState?.result || "").trim().toLowerCase();
  const promotionSucceeded = promotionResult === "success";
  const promotionTarget = String(promotionState?.target_runtime || "").trim() || "xyn-local";
  const promotionUrl = String(promotionState?.ui_url || "").trim();
  const latestExecutionResult = (() => {
    if (executionPhase === "ready_for_promotion") {
      if (promotionSucceeded) return "Changes promoted to the primary local runtime — ready to finalize.";
      return "Validation complete — ready for promotion.";
    }
    if (executionPhase === "preview_ready") {
      if (previewSummarySource.includes("reused")) return "Preview ready (reused runtime).";
      if (previewPrimaryUrl) return `Preview ready (${previewPrimaryUrl}).`;
      return "Preview ready.";
    }
    if (executionPhase === "staged") {
      if (executionFailedCount > 0) {
        return `Changes staged (${executionQueuedCount} queued, ${executionFailedCount} failed).`;
      }
      if (executionQueuedCount > 0) return `Changes staged (${executionQueuedCount} task${executionQueuedCount === 1 ? "" : "s"} queued).`;
      if (executionTotalCount > 0 || executionSkippedCount > 0) return "Changes staged.";
      return "Stage apply has not queued execution tasks yet.";
    }
    if (executionPhase === "failed") return "Execution failed. Retry the failed step.";
    return "No execution action has run yet.";
  })();
  const primaryExecutionAction = defaultPrimaryActionForPhase(executionPhase);
  const sessionStatusToken = String(selectedSession?.status || "").trim().toLowerCase();
  const isSessionFinalized = ["finalized", "completed", "archived"].includes(sessionStatusToken)
    || ["completed", "finalized", "archived"].includes(executionStatusToken);
  const canStageApply = canRunExecution && executionPhase !== "ready_for_promotion";
  const canPreparePreview = canRunExecution && (executionPhase === "staged" || executionPhase === "failed");
  const canValidate = canRunExecution && (executionPhase === "preview_ready" || executionPhase === "failed");
  const canPromote = canRunExecution && !isSessionFinalized && executionPhase === "ready_for_promotion";
  const canFinalize = canRunExecution && !isSessionFinalized && executionPhase === "ready_for_promotion" && promotionSucceeded;
  const hasExecutionProgress = ["staged", "preview_preparing", "preview_ready", "validating", "ready_for_promotion", "completed", "applied"].includes(
    String(selectedSession?.execution_status || "").toLowerCase()
  );
  const showInitialRequestInput = !hasDraftPlan && !hasPendingPrompt;
  const showIterativeRequestInput = hasExecutionProgress && !hasPendingPrompt && !hasPendingCheckpoint;
  const latestPlannerTurn = [...planningTurns].reverse().find((turn: any) => String(turn.actor || "") === "planner") || null;
  const latestVisibleTurn = [...planningTurns].reverse().find((turn: any) => String(turn.kind || "") !== "checkpoint") || null;
  const latestVisibleTurnId = latestVisibleTurn ? String(latestVisibleTurn.id || "") : "";
  const latestDraftTurn = [...planningTurns]
    .reverse()
    .find((turn: any) => String(turn.actor || "") === "planner" && String(turn.kind || "") === "draft_plan") || null;
  const latestDraftTurnId = latestDraftTurn ? String(latestDraftTurn.id || "") : "";
  const latestActivityAt = planningTurns.length
    ? String(planningTurns[planningTurns.length - 1]?.created_at || selectedSession?.updated_at || "")
    : String(selectedSession?.updated_at || "");

  const planningStatusLabel = !selectedSession
    ? "Session required"
    : hasPendingCheckpoint
      ? "Awaiting approval"
      : hasPendingPrompt
        ? "Awaiting response"
        : hasDraftPlan
          ? "Draft plan ready"
          : titleCaseLabel(String(selectedSession.status || "draft"));

  const hasExplicitComposerFocus = Boolean(
    factoryKey
    || applicationPlanId
    || applicationId
    || goalId
    || threadId
    || solutionChangeSessionId
  );
  const composerView = payload ? deriveComposerViewModel(payload) : null;
  const storedSelection = composerView ? readComposerStoredSelection(workspaceId) : null;
  const initialSelection = composerView && !hasExplicitComposerFocus
    ? resolveComposerInitialSelection(composerView.containers, storedSelection)
    : null;
  useEffect(() => {
    if (loading || !payload || !composerView || hasExplicitComposerFocus || !initialSelection) return;
    openComposer(initialSelection);
  }, [composerView, hasExplicitComposerFocus, initialSelection, loading, payload]);
  useEffect(() => {
    if (!selectedSession) return;
    writeComposerStoredSelection(workspaceId, {
      application_id: selectedSession.application_id,
      solution_change_session_id: selectedSession.id,
    });
  }, [selectedSession, workspaceId]);
  useEffect(() => {
    if (!latestVisibleTurnId || !shouldAutoScrollToLatestTurnRef.current) return;
    const target = latestTurnRef.current as (HTMLLIElement & { scrollIntoView?: (options?: any) => void }) | null;
    if (typeof target?.scrollIntoView === "function") {
      target.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    shouldAutoScrollToLatestTurnRef.current = false;
  }, [latestVisibleTurnId]);

  if (loading) return <p className="muted">Loading composer…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload || !composerView) return <p className="muted">Composer state unavailable.</p>;

  const withSessionGuard = async (action: () => Promise<void>) => {
    if (!selectedSession || !selectedSessionId) {
      setMessage("Open a solution change session to continue planning.");
      return;
    }
    try {
      await action();
      await reloadComposerState();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Composer action failed");
    } finally {
      setBusyAction(null);
    }
  };

  const selectedOptionTurnPayload = (turn: any) =>
    turn && typeof turn.payload === "object" && turn.payload
      ? turn.payload as Record<string, unknown>
      : {};

  const selectedOptionResponseBySourceTurn = planningTurns.reduce<Record<string, string>>((acc, turn: any) => {
    const payloadMap = selectedOptionTurnPayload(turn);
    if (
      String(turn.actor || "") === "user"
      && String(turn.kind || "") === "response"
      && String(payloadMap.response_kind || "") === "option_selection"
    ) {
      const sourceId = String(payloadMap.source_turn_id || "");
      const optionId = String(payloadMap.option_id || "");
      if (sourceId && optionId) acc[sourceId] = optionId;
    }
    return acc;
  }, {});
  const pendingStageCheckpoint = pendingCheckpoints.find((entry: any) => String(entry.checkpoint_key || "") === "plan_scope_confirmed")
    || pendingCheckpoints[0]
    || null;
  const showRefinementFooter = Boolean(selectedSession && hasDraftPlan && hasPendingCheckpoint && !hasPendingPrompt);

  const WORKSTREAM_LABELS: Record<string, string> = {
    ui: "UI / presentation",
    api: "API / service",
    data: "Data / storage",
    workflow: "Workflow / orchestration",
    validation: "Validation / verification",
    behavior: "Behavior / interaction logic",
  };

  const normalizeWorkstreamToken = (value: unknown): string => String(value || "").trim().toLowerCase();
  const dedupeList = (values: string[]): string[] => {
    const output: string[] = [];
    values.forEach((item) => {
      if (item && !output.includes(item)) output.push(item);
    });
    return output;
  };
  const collectWorkstreamFocus = (payloadMap: Record<string, unknown>): string[] => {
    const confirmed = Array.isArray(payloadMap.confirmed_workstreams)
      ? payloadMap.confirmed_workstreams.map(normalizeWorkstreamToken).filter(Boolean)
      : [];
    const suggested = Array.isArray(payloadMap.suggested_workstreams)
      ? payloadMap.suggested_workstreams.map(normalizeWorkstreamToken).filter(Boolean)
      : [];
    const sessionConfirmed = Array.isArray(selectedSession?.confirmed_workstreams)
      ? selectedSession.confirmed_workstreams.map(normalizeWorkstreamToken).filter(Boolean)
      : [];
    return dedupeList([...confirmed, ...suggested, ...sessionConfirmed]);
  };
  const collectProposedWork = (payloadMap: Record<string, unknown>): string[] => {
    const explicit = Array.isArray(payloadMap.proposed_work)
      ? payloadMap.proposed_work.map((value) => String(value || "").trim()).filter(Boolean)
      : [];
    if (explicit.length) return dedupeList(explicit);
    const implementation = Array.isArray(payloadMap.implementation_steps)
      ? payloadMap.implementation_steps.map((value) => String(value || "").trim()).filter(Boolean)
      : [];
    if (implementation.length) return dedupeList(implementation);
    return Array.isArray(payloadMap.selected_artifact_ids)
      ? payloadMap.selected_artifact_ids.map((value) => String(value || "").trim()).filter(Boolean)
      : [];
  };
  const formatWorkstreamLabel = (value: string): string => WORKSTREAM_LABELS[value] || value;

  const renderDraftPlanSummary = (turn: any) => {
    const payloadMap = selectedOptionTurnPayload(turn);
    const objectiveText = String(payloadMap.objective || payloadMap.request_text || selectedSession?.request_text || "—");
    const proposedWork = collectProposedWork(payloadMap);
    const workstreamFocus = collectWorkstreamFocus(payloadMap);
    const keyImpacts = Array.isArray(payloadMap.shared_contracts)
      ? payloadMap.shared_contracts.map((value) => String(value || "")).filter(Boolean)
      : [];
    const planningMode = String(payloadMap.planning_mode || "deterministic").trim().toLowerCase();
    const candidateFiles = Array.isArray(payloadMap.candidate_files)
      ? payloadMap.candidate_files.map((value) => String(value || "").trim()).filter(Boolean)
      : [];
    const validationSteps = Array.isArray(payloadMap.validation_plan)
      ? payloadMap.validation_plan.map((value) => String(value || "")).filter(Boolean)
      : [];
    const nextAction = pendingCheckpoints.length
      ? "Review and approve the pending checkpoint before staging."
      : "Continue to stage apply when ready.";
    return (
      <div className="composer-draft-plan">
        <div><span className="field-label">Objective</span><p>{objectiveText}</p></div>
        <div>
          <span className="field-label">Proposed Work</span>
          {proposedWork.length ? (
            <ul className="detail-list">
              {proposedWork.map((item) => <li key={item}>{item}</li>)}
            </ul>
          ) : workstreamFocus.length ? (
            <ul className="detail-list">
              {workstreamFocus.map((item) => <li key={item}>{formatWorkstreamLabel(item)}</li>)}
            </ul>
          ) : (
            <p className="muted small">No selected artifact set provided yet.</p>
          )}
        </div>
        {planningMode === "code_aware" ? (
          <div>
            <span className="field-label">Planning Mode</span>
            <p>
              This draft used repo context{candidateFiles.length ? ` (${candidateFiles.slice(0, 2).join(", ")})` : ""}.
            </p>
          </div>
        ) : null}
        <div>
          <span className="field-label">Key Impacts</span>
          {keyImpacts.length ? (
            <ul className="detail-list">
              {keyImpacts.map((item, index) => <li key={`${item}:${index}`}>{item}</li>)}
            </ul>
          ) : (
            <p className="muted small">No shared contract impacts were listed.</p>
          )}
        </div>
        <div>
          <span className="field-label">Next Action</span>
          {validationSteps.length ? (
            <p>{validationSteps[0]}</p>
          ) : (
            <p>{nextAction}</p>
          )}
        </div>
      </div>
    );
  };

  const latestDraftPayload = (() => {
    if (latestDraftTurn) return selectedOptionTurnPayload(latestDraftTurn);
    if (latestDraftPlan && typeof latestDraftPlan.payload === "object" && latestDraftPlan.payload) {
      return latestDraftPlan.payload as Record<string, unknown>;
    }
    return {};
  })();
  const draftObjective = String(latestDraftPayload.objective || latestDraftPayload.request_text || selectedSession?.request_text || "—");
  const draftProposedWork = collectProposedWork(latestDraftPayload);
  const draftWorkstreamFocus = collectWorkstreamFocus(latestDraftPayload);
  const draftImpacts = Array.isArray(latestDraftPayload.shared_contracts)
    ? latestDraftPayload.shared_contracts.map((value) => String(value || "")).filter(Boolean)
    : [];
  const draftPlanningMode = String(latestDraftPayload.planning_mode || "deterministic").trim().toLowerCase();
  const draftCandidateFiles = Array.isArray(latestDraftPayload.candidate_files)
    ? latestDraftPayload.candidate_files.map((value) => String(value || "").trim()).filter(Boolean)
    : [];
  const draftOpenQuestions = draftImpacts.filter((item) => /open question/i.test(item));
  const draftRevisionCount = planningTurns.filter(
    (turn: any) => String(turn.actor || "") === "planner" && String(turn.kind || "") === "draft_plan"
  ).length;
  const latestPlannerPayload = latestPlannerTurn ? selectedOptionTurnPayload(latestPlannerTurn) : {};
  const planningRoute = routingPurposeRow(planningRoutingStatus?.routing || [], "planning");
  const plannerAgentId = String(
    latestPlannerPayload.planner_agent_id
    || latestPlannerPayload.agent_id
    || planningRoute?.resolved_agent_id
    || planningRoute?.explicit_agent_id
    || ""
  ).trim();
  const plannerAgentById = plannerAgentId
    ? availableAgents.find((item) => String(item.id || "").trim() === plannerAgentId)
    : null;
  const plannerAgentName = String(
    latestPlannerPayload.planner_agent_name
    || latestPlannerPayload.agent_name
    || latestPlannerPayload.agent
    || plannerAgentById?.name
    || planningRoute?.resolved_agent_name
    || planningRoute?.explicit_agent_name
    || latestPlannerPayload.model
    || "Planning Agent"
  ).trim();
  const plannerAgentAvatarUrl = String(
    latestPlannerPayload.planner_agent_avatar_url
    || latestPlannerPayload.agent_avatar_url
    || plannerAgentById?.avatar_url
    || planningRoute?.resolved_agent_avatar_url
    || planningRoute?.explicit_agent_avatar_url
    || ""
  ).trim();
  const plannerAgentIdentityKey = String(plannerAgentId || plannerAgentName || "planner").trim();
  const interpretationForTurn = (turn: any): Record<string, unknown> => {
    const payloadMap = selectedOptionTurnPayload(turn);
    return payloadMap.interpretation && typeof payloadMap.interpretation === "object"
      ? payloadMap.interpretation as Record<string, unknown>
      : {};
  };
  const interpretationBadgeForTurn = (turn: any): string => {
    const interp = interpretationForTurn(turn);
    const mode = String(interp.mode || "").trim().toLowerCase();
    const resultType = String(interp.result_type || "").trim().toLowerCase();
    if (mode === "agent_fallback" && (resultType === "answer_resolution" || resultType === "plan_revision")) {
      return "Interpreted by planner";
    }
    if (resultType === "clarification_request") return "Planner requested clarification";
    if (resultType === "cannot_interpret") return "Could not safely interpret";
    return "";
  };
  const fallbackQuestionReasonLabel = (turn: any): string => {
    const payloadMap = selectedOptionTurnPayload(turn);
    const reason = String(payloadMap.reason || "").trim().toLowerCase();
    if (reason === "clarification_request") return "Planner requested clarification";
    if (reason === "cannot_interpret") return "Could not safely interpret";
    return "";
  };
  const submitRefinement = async (trimmed: string, usePlannerInterpretation: boolean) => {
    if (!selectedSession || !trimmed) return;
    shouldAutoScrollToLatestTurnRef.current = true;
    setBusyAction(usePlannerInterpretation ? "refine-planner" : "refine");
    await withSessionGuard(async () => {
      const response = await replyToSolutionPlanningSession(
        String(selectedSession.application_id),
        String(selectedSession.id),
        {
          reply_text: trimmed,
          source_turn_id: undefined,
          use_planner_interpretation: usePlannerInterpretation,
        }
      );
      mergeUpdatedSession(response.session);
      setRefinementDraft("");
      setMessage(usePlannerInterpretation ? "Submitted using planner interpretation." : "Plan refinement submitted.");
    });
  };

  return (
    <div className="panel-section-stack composer-cockpit">
      <div className="composer-cockpit-grid">
        <div className="composer-cockpit-main">
        <section className="card composer-planning-card">
          <div className="card-header">
            <div>
              <div className="field-label">Planning Conversation</div>
              <div className="field-value">Structured planning timeline</div>
            </div>
          </div>
            <>
              <div className="composer-planning-scroll">
                <ol className="composer-planning-timeline">
              {planningTurns.map((turn: any) => {
              const payloadMap = selectedOptionTurnPayload(turn);
              const isQuestionTurn = String(turn.kind || "") === "question";
              const isOptionTurn = String(turn.kind || "") === "option_set";
              const isDraftPlanTurn = String(turn.kind || "") === "draft_plan";
              const isCheckpointTurn = String(turn.kind || "") === "checkpoint";
              const isPendingQuestionTurn = String(pendingQuestion?.id || "") === String(turn.id || "");
              const isPendingOptionTurn = String(pendingOptionSet?.id || "") === String(turn.id || "");
              const options = Array.isArray(payloadMap.options) ? payloadMap.options : [];
              const selectedOptionId = selectedOptionByTurn[String(turn.id)] || selectedOptionResponseBySourceTurn[String(turn.id)] || "";
              const isLatestTurn = String(turn.id || "") === latestVisibleTurnId;
              const isLatestDraftTurn = String(turn.id || "") === latestDraftTurnId;
              const associatedCheckpoint = isLatestDraftTurn ? pendingStageCheckpoint : null;
              const actorType = String(turn.actor || "planner") === "planner" ? "planner" : "user";
              const turnPlannerAgentId = String(
                payloadMap.planner_agent_id || payloadMap.agent_id || plannerAgentId || ""
              ).trim();
              const turnPlannerAgent = turnPlannerAgentId
                ? availableAgents.find((item) => String(item.id || "").trim() === turnPlannerAgentId)
                : null;
              const turnPlannerName = String(
                payloadMap.planner_agent_name
                || payloadMap.agent_name
                || payloadMap.agent
                || turnPlannerAgent?.name
                || plannerAgentName
                || payloadMap.model
                || "Planning Agent"
              ).trim();
              const turnPlannerAvatar = String(
                payloadMap.planner_agent_avatar_url
                || payloadMap.agent_avatar_url
                || turnPlannerAgent?.avatar_url
                || plannerAgentAvatarUrl
                || ""
              ).trim();
              const actorLabel = actorType === "planner" ? turnPlannerName : currentUserProfile.displayName || "User";
              const actorAvatar = actorType === "planner" ? turnPlannerAvatar : currentUserProfile.picture;
              const actorEmail = actorType === "planner" ? "" : currentUserProfile.email;
              const actorIdentityKey = actorType === "planner"
                ? String(turnPlannerAgentId || turnPlannerName || plannerAgentIdentityKey || "planner")
                : String(currentUserProfile.subject || currentUserProfile.email || turn.created_by || selectedSession?.created_by || "current-user");

              if (isCheckpointTurn) return null;

              return (
                <li
                  key={String(turn.id)}
                  ref={isLatestTurn ? latestTurnRef : null}
                  className={`composer-planning-turn turn-${String(turn.actor || "unknown")} turn-kind-${String(turn.kind || "unknown")}`}
                >
                  <div className="composer-planning-turn__meta">
                    <span className="composer-turn-actor-chip">
                      <Avatar
                        size="sm"
                        src={actorAvatar || undefined}
                        name={actorLabel}
                        email={actorEmail || undefined}
                        identityKey={actorIdentityKey}
                        className="composer-turn-avatar"
                      />
                      <span className="composer-turn-actor-label">{actorLabel}</span>
                    </span>
                    <span className="pill">{titleCaseLabel(String(turn.kind || "update"))}</span>
                    {interpretationBadgeForTurn(turn) ? (
                      <span className="pill">{interpretationBadgeForTurn(turn)}</span>
                    ) : null}
                    {!interpretationBadgeForTurn(turn) && isQuestionTurn && fallbackQuestionReasonLabel(turn) ? (
                      <span className="pill">{fallbackQuestionReasonLabel(turn)}</span>
                    ) : null}
                    <span className="muted small">{formatPanelTimestamp(String(turn.created_at || ""))}</span>
                  </div>
                  {String(turn.actor || "") === "user" && String(turn.kind || "") !== "approval" ? (
                    <p className="composer-planning-turn__body">{String(payloadMap.reply_text || payloadMap.request_text || "Response recorded.")}</p>
                  ) : null}
                  {isQuestionTurn ? (
                    <>
                      <p className="composer-planning-turn__body">{String(payloadMap.question || "Planner requested clarification.")}</p>
                      {isPendingQuestionTurn ? (
                        <div className="composer-planning-action-block">
                          <textarea
                            className="input"
                            rows={3}
                            value={questionReplyDraft}
                            onChange={(event) => setQuestionReplyDraft(event.target.value)}
                            placeholder="Reply to planner question."
                          />
                          <div className="inline-action-row" style={{ marginTop: 8 }}>
                            <button
                              type="button"
                              className="ghost sm"
                              disabled={busyAction === `reply:${turn.id}` || !questionReplyDraft.trim()}
                              onClick={() => {
                                if (!selectedSession || !questionReplyDraft.trim()) return;
                                shouldAutoScrollToLatestTurnRef.current = true;
                                setBusyAction(`reply:${turn.id}`);
                                void withSessionGuard(async () => {
                                  const response = await replyToSolutionPlanningSession(
                                    String(selectedSession.application_id),
                                    String(selectedSession.id),
                                    { reply_text: questionReplyDraft.trim(), source_turn_id: String(turn.id) }
                                  );
                                  mergeUpdatedSession(response.session);
                                  setQuestionReplyDraft("");
                                  setMessage("Reply recorded.");
                                });
                              }}
                            >
                              Submit Reply
                            </button>
                          </div>
                        </div>
                      ) : null}
                    </>
                  ) : null}
                  {isOptionTurn ? (
                    <div className="composer-planning-action-block">
                      <p className="composer-planning-turn__body">{String(payloadMap.question || payloadMap.prompt || "Select one planning option.")}</p>
                      {options.length ? (
                        <>
                          <div className="composer-option-list">
                            {options.map((option: any, index: number) => {
                              const optionId = String(option?.id || `option-${index}`);
                              const optionLabel = String(option?.label || optionId);
                              const optionDescription = String(option?.description || "");
                              const effectiveSelectedOptionId = selectedOptionId || String(options[0]?.id || "");
                              return (
                                <label key={optionId} className="composer-option-item">
                                  <input
                                    type="radio"
                                    name={`planner-option-${turn.id}`}
                                    checked={effectiveSelectedOptionId === optionId}
                                    onChange={() => setSelectedOptionByTurn((current) => ({ ...current, [String(turn.id)]: optionId }))}
                                  />
                                  <span>
                                    <strong>{optionLabel}</strong>
                                    {optionDescription ? <span className="muted small">{optionDescription}</span> : null}
                                  </span>
                                </label>
                              );
                            })}
                          </div>
                          <div className="inline-action-row" style={{ marginTop: 8 }}>
                            <button
                              type="button"
                              className="ghost sm"
                              disabled={!isPendingOptionTurn || busyAction === `option:${turn.id}` || !(selectedOptionId || String(options[0]?.id || ""))}
                              onClick={() => {
                                const effectiveSelectedOptionId = selectedOptionId || String(options[0]?.id || "");
                                if (!selectedSession || !effectiveSelectedOptionId) return;
                                shouldAutoScrollToLatestTurnRef.current = true;
                                setBusyAction(`option:${turn.id}`);
                                void withSessionGuard(async () => {
                                  const response = await selectSolutionPlanningOption(
                                    String(selectedSession.application_id),
                                    String(selectedSession.id),
                                    {
                                      option_id: effectiveSelectedOptionId,
                                      source_turn_id: String(turn.id),
                                    }
                                  );
                                  mergeUpdatedSession(response.session);
                                  setMessage("Option selected.");
                                });
                              }}
                            >
                              Select Option
                            </button>
                          </div>
                        </>
                      ) : (
                        <>
                          <InlineMessage
                            tone="warn"
                            title="Planner options unavailable"
                            body="This option set has no selectable options. Regenerate options to continue."
                          />
                          <div className="inline-action-row" style={{ marginTop: 8 }}>
                            <button
                              type="button"
                              className="ghost sm"
                              disabled={!isPendingOptionTurn || busyAction === `regen-options:${turn.id}`}
                              onClick={() => {
                                if (!selectedSession) return;
                                shouldAutoScrollToLatestTurnRef.current = true;
                                setBusyAction(`regen-options:${turn.id}`);
                                void withSessionGuard(async () => {
                                  const response = await regenerateSolutionPlanningOptions(
                                    String(selectedSession.application_id),
                                    String(selectedSession.id),
                                  );
                                  mergeUpdatedSession(response.session);
                                  setMessage("Planner options regenerated.");
                                });
                              }}
                            >
                              Regenerate Options
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  ) : null}
                  {isDraftPlanTurn ? (
                    <>
                      {renderDraftPlanSummary(turn)}
                      {associatedCheckpoint ? (
                        <div className="composer-draft-approval-summary">
                          <span className="pill warn">Approval Required</span>
                          <p className="muted small">
                            {String(associatedCheckpoint.label || "Review the draft plan and approve in Approval Gate.")}
                          </p>
                        </div>
                      ) : null}
                    </>
                  ) : null}
                  {String(turn.kind || "") === "approval" ? (
                    <p className="composer-planning-turn__body">
                      Approval decision: {titleCaseLabel(String(payloadMap.decision || "recorded"))}
                    </p>
                  ) : null}
                </li>
              );
            })}
              {!planningTurns.length ? (
                <li className="composer-planning-turn">
                  <p className="muted">
                    {selectedSession
                      ? "No planning interaction history has been recorded yet."
                      : "Select a solution change session from Solution Detail to review and approve planning interactions."}
                  </p>
                </li>
              ) : null}
                </ol>
              </div>
              <div className="composer-planning-footer">
                {showInitialRequestInput || showIterativeRequestInput ? (
                  <>
                    <p className="muted small">
                      {showIterativeRequestInput
                        ? "Describe the next change to continue this planning session."
                        : "Request a change for the selected solution session."}
                    </p>
                    <textarea
                      className="input"
                      rows={3}
                      value={requestDraft}
                      onChange={(event) => setRequestDraft(event.target.value)}
                      placeholder="Describe the change you want planned."
                    />
                    <div className="composer-planning-footer-actions">
                      <button
                        type="button"
                        className="ghost sm"
                        disabled={
                          !selectedSession
                          || busyAction === "request"
                          || !requestDraft.trim()
                        }
                        onClick={() => {
                          const trimmed = requestDraft.trim();
                          if (!trimmed || !selectedSession) return;
                          shouldAutoScrollToLatestTurnRef.current = true;
                          setBusyAction("request");
                          void withSessionGuard(async () => {
                            const response = await replyToSolutionPlanningSession(
                              String(selectedSession.application_id),
                              String(selectedSession.id),
                              { reply_text: trimmed, source_turn_id: undefined }
                            );
                            mergeUpdatedSession(response.session);
                            setRequestDraft("");
                            setMessage(showIterativeRequestInput ? "Recorded iterative change request." : "Recorded change request.");
                          });
                        }}
                      >
                        {showIterativeRequestInput ? "Describe Change" : "Submit Request"}
                      </button>
                    </div>
                  </>
                ) : showRefinementFooter ? (
                  <>
                    <p className="muted small">Refine or respond to this plan (optional)</p>
                    <textarea
                      className="input"
                      rows={3}
                      value={refinementDraft}
                      onChange={(event) => setRefinementDraft(event.target.value)}
                      placeholder="Answer open questions or request plan changes."
                    />
                    <div className="composer-planning-footer-actions">
                      <button
                        type="button"
                        className="ghost sm"
                        disabled={!selectedSession || (busyAction === "refine" || busyAction === "refine-planner") || !refinementDraft.trim()}
                        onClick={() => {
                          const trimmed = refinementDraft.trim();
                          if (!trimmed || !selectedSession) return;
                          void submitRefinement(trimmed, false);
                        }}
                      >
                        Refine Plan
                      </button>
                      <button
                        type="button"
                        className="ghost sm"
                        disabled={!selectedSession || (busyAction === "refine" || busyAction === "refine-planner") || !refinementDraft.trim()}
                        onClick={() => {
                          const trimmed = refinementDraft.trim();
                          if (!trimmed || !selectedSession) return;
                          void submitRefinement(trimmed, true);
                        }}
                      >
                        Use planner interpretation
                      </button>
                    </div>
                  </>
                ) : (
                  <p className="muted small">
                    {hasPendingPrompt
                      ? "Respond to the pending planner prompt above to continue."
                      : hasDraftPlan
                        ? "Approval gate controls are available in the right rail."
                        : "A draft plan is required before refinement is available."}
                  </p>
                )}
              </div>
            </>
        </section>
        <section className="card composer-session-summary">
          <div className="field-label">Planning Session</div>
          <div className="composer-cockpit-header-row">
            <div><div className="field-label">Solution / Session</div><div className="field-value">{selectedSession?.title || "No solution session selected"}</div></div>
            <div><div className="field-label">Planning status</div><div className="field-value">{planningStatusLabel}</div></div>
            <div><div className="field-label">Latest activity</div><div className="field-value">{formatPanelTimestamp(latestActivityAt)}</div></div>
            <div className="composer-cockpit-agent">
              <div className="field-label">Agent</div>
              <div className="composer-cockpit-agent-row">
                <Avatar
                  size="sm"
                  src={plannerAgentAvatarUrl || undefined}
                  name={plannerAgentName}
                  identityKey={plannerAgentIdentityKey}
                />
                <span className="field-value">{plannerAgentName}</span>
              </div>
            </div>
            <div><div className="field-label">Revision</div><div className="field-value">{draftRevisionCount ? `Rev ${draftRevisionCount}` : "—"}</div></div>
          </div>
          {!selectedSession ? (
            <p className="muted small" style={{ marginTop: 8 }}>
              Open a solution change session from Solution Detail.
            </p>
          ) : null}
          {message ? <InlineMessage tone="info" title="Composer" body={message} /> : null}
        </section>
        </div>

        <aside className="composer-cockpit-rail">
          <section className="card composer-draft-card">
            <div className="field-label">Current Draft</div>
            <div className="composer-draft-scroll">
              {hasDraftPlan ? (
                <div className="composer-draft-plan">
                  <div><span className="field-label">Objective</span><p>{draftObjective}</p></div>
                  <div>
                    <span className="field-label">Proposed Work</span>
                    {draftProposedWork.length ? (
                      <ul className="detail-list">
                        {draftProposedWork.map((item) => <li key={item}>{item}</li>)}
                      </ul>
                    ) : draftWorkstreamFocus.length ? (
                      <ul className="detail-list">
                        {draftWorkstreamFocus.map((item) => <li key={item}>{formatWorkstreamLabel(item)}</li>)}
                      </ul>
                    ) : (
                      <p className="muted small">No selected artifact set provided yet.</p>
                    )}
                  </div>
                  {draftPlanningMode === "code_aware" ? (
                    <div>
                      <span className="field-label">Planning Mode</span>
                      <p>
                        Code-aware draft{draftCandidateFiles.length ? ` using ${draftCandidateFiles.slice(0, 2).join(", ")}` : ""}.
                      </p>
                    </div>
                  ) : null}
                  <div>
                    <span className="field-label">Key Impacts / Assumptions</span>
                    {draftImpacts.length ? (
                      <ul className="detail-list">
                        {draftImpacts.map((item, index) => <li key={`${item}:${index}`}>{item}</li>)}
                      </ul>
                    ) : (
                      <p className="muted small">No key impacts were listed.</p>
                    )}
                  </div>
                  <div>
                    <span className="field-label">Open Questions</span>
                    {draftOpenQuestions.length ? (
                      <ul className="detail-list">
                        {draftOpenQuestions.map((item, index) => <li key={`${item}:${index}`}>{item}</li>)}
                      </ul>
                    ) : (
                      <p className="muted small">No open questions captured.</p>
                    )}
                  </div>
                  <div>
                    <span className="field-label">Next Action</span>
                    <p>{derivedExecutionNextAction}</p>
                  </div>
                </div>
              ) : (
                <p className="muted small">No draft available yet.</p>
              )}
            </div>
          </section>

          <section className="card">
            <div className="field-label">Approval Gate</div>
            {!selectedSession ? (
              <p className="muted small">Select a session to manage checkpoint approvals.</p>
            ) : pendingStageCheckpoint ? (
              <div className="composer-planning-action-block">
                <p className="composer-planning-turn__body">
                  {String(pendingStageCheckpoint.label || "Approval checkpoint")}
                  {" · "}
                  Required before {String(pendingStageCheckpoint.required_before || "stage")}
                </p>
                <p className="muted small">
                  Current status: {titleCaseLabel(String(pendingStageCheckpoint.status || "pending"))}
                </p>
                {showApprovalNoteByCheckpoint[String(pendingStageCheckpoint.id)] ? (
                  <textarea
                    className="input"
                    rows={2}
                    value={approvalNotes[String(pendingStageCheckpoint.id)] || ""}
                    onChange={(event) =>
                      setApprovalNotes((current) => ({ ...current, [String(pendingStageCheckpoint.id)]: event.target.value }))
                    }
                    placeholder="Approval note (optional)."
                  />
                ) : null}
                <div className="inline-action-row composer-approval-actions" style={{ marginTop: 8 }}>
                  <button
                    type="button"
                    className="primary sm"
                    disabled={busyAction === `checkpoint-approve:${pendingStageCheckpoint.id}`}
                    onClick={() => {
                      if (!selectedSession) return;
                      shouldAutoScrollToLatestTurnRef.current = true;
                      setBusyAction(`checkpoint-approve:${pendingStageCheckpoint.id}`);
                      void withSessionGuard(async () => {
                        const response = await decideSolutionPlanningCheckpoint(
                          String(selectedSession.application_id),
                          String(selectedSession.id),
                          String(pendingStageCheckpoint.id),
                          {
                            decision: "approved",
                            notes: approvalNotes[String(pendingStageCheckpoint.id)] || "",
                          }
                        );
                        mergeUpdatedSession(response.session);
                        setMessage("Checkpoint approved.");
                      });
                    }}
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    className="ghost sm"
                    aria-label="Approve options"
                    onClick={() =>
                      setShowApprovalNoteByCheckpoint((current) => ({
                        ...current,
                        [String(pendingStageCheckpoint.id)]: !current[String(pendingStageCheckpoint.id)],
                      }))
                    }
                  >
                    ▾
                  </button>
                  <button
                    type="button"
                    className="ghost sm"
                    disabled={busyAction === `checkpoint-reject:${pendingStageCheckpoint.id}`}
                    onClick={() => {
                      if (!selectedSession) return;
                      shouldAutoScrollToLatestTurnRef.current = true;
                      setBusyAction(`checkpoint-reject:${pendingStageCheckpoint.id}`);
                      void withSessionGuard(async () => {
                        const response = await decideSolutionPlanningCheckpoint(
                          String(selectedSession.application_id),
                          String(selectedSession.id),
                          String(pendingStageCheckpoint.id),
                          {
                            decision: "rejected",
                            notes: approvalNotes[String(pendingStageCheckpoint.id)] || "",
                          }
                        );
                        mergeUpdatedSession(response.session);
                        setMessage("Checkpoint rejected.");
                      });
                    }}
                  >
                    Reject
                  </button>
                </div>
              </div>
            ) : (
              <p className="muted small">
                {hasDraftPlan
                  ? "No pending approval checkpoint."
                  : "A draft plan is required before approval can be recorded."}
              </p>
            )}
          </section>

          <section className="card">
            <div className="field-label">Execution Controls</div>
            <div className="field-value">Execution Handoff</div>
            {!selectedSession ? (
              <p className="muted small">Execution actions are available after selecting a solution change session.</p>
            ) : (
              <>
                {previewPrimaryUrl && previewStatusToken === "ready" ? (
                  <div className="inline-action-row" style={{ flexWrap: "wrap" }}>
                    <button
                      type="button"
                      className="ghost sm"
                      onClick={() => window.open(previewPrimaryUrl, "_blank", "noopener,noreferrer")}
                    >
                      {previewSummarySource.includes("reused") ? "Open Preview (existing runtime)" : "Open Preview"}
                    </button>
                  </div>
                ) : null}
                {!hasDraftPlan && !hasPendingPrompt ? (
                  <div className="inline-action-row" style={{ flexWrap: "wrap" }}>
                    <button
                      type="button"
                      className="ghost sm"
                      disabled={busyAction === "generate-plan"}
                      onClick={() => {
                        shouldAutoScrollToLatestTurnRef.current = true;
                        setBusyAction("generate-plan");
                        void withSessionGuard(async () => {
                          const response = await generateSolutionChangePlan(
                            String(selectedSession.application_id),
                            String(selectedSession.id)
                          );
                          mergeUpdatedSession(response.session);
                          setMessage("Draft plan generated.");
                        });
                      }}
                    >
                      Generate Draft Plan
                    </button>
                  </div>
                ) : null}
                {isSessionFinalized ? (
                  <p className="muted small" style={{ marginTop: 8 }}>
                    Session finalized. Execution controls are hidden.
                  </p>
                ) : (
                  <div className="inline-action-row" style={{ flexWrap: "wrap" }}>
                    <button
                      type="button"
                      className={`${primaryExecutionAction === "stage-apply" ? "primary" : "ghost"} sm`}
                      disabled={!canStageApply || busyAction === "stage-apply"}
                      onClick={() => {
                        setBusyAction("stage-apply");
                        void withSessionGuard(async () => {
                          const response = await stageSolutionChangeApply(
                            String(selectedSession.application_id),
                            String(selectedSession.id)
                          );
                          mergeUpdatedSession(response.session);
                          const summary = response.session?.staged_changes?.execution_summary
                            && typeof response.session.staged_changes.execution_summary === "object"
                            ? response.session.staged_changes.execution_summary as Record<string, unknown>
                            : null;
                          const queuedCount = Number(summary?.queued_artifacts ?? summary?.queued ?? 0);
                          const failedCount = Number(summary?.failed_artifacts ?? summary?.failed ?? 0);
                          if (failedCount > 0) {
                            setMessage(`Changes staged (${queuedCount} queued, ${failedCount} failed).`);
                            return;
                          }
                          if (queuedCount > 0) {
                            setMessage(`Changes staged (${queuedCount} task${queuedCount === 1 ? "" : "s"} queued).`);
                            return;
                          }
                          setMessage("Changes staged.");
                        });
                      }}
                    >
                      Stage Apply
                    </button>
                    <button
                      type="button"
                      className={`${primaryExecutionAction === "prepare-preview" ? "primary" : "ghost"} sm`}
                      disabled={!canPreparePreview || busyAction === "prepare-preview"}
                      onClick={() => {
                        setBusyAction("prepare-preview");
                        void withSessionGuard(async () => {
                          const response = await prepareSolutionChangePreview(
                            String(selectedSession.application_id),
                            String(selectedSession.id)
                          );
                          mergeUpdatedSession(response.session);
                          const preview = response.session?.preview;
                          const previewUrl = String(preview?.primary_url || "").trim();
                          const previewSource = String(preview?.source || preview?.mode || "").trim().toLowerCase();
                          if (previewSource.includes("reused")) {
                            setMessage("Preview ready (reused runtime).");
                            return;
                          }
                          if (previewUrl) {
                            setMessage(
                              <>
                                Preview ready (
                                <a href={previewUrl} target="_blank" rel="noreferrer">
                                  {previewUrl}
                                </a>
                                ).
                              </>
                            );
                            return;
                          }
                          setMessage("Preview preparation completed.");
                        });
                      }}
                    >
                      Prepare Preview
                    </button>
                    <button
                      type="button"
                      className={`${primaryExecutionAction === "validate" ? "primary" : "ghost"} sm`}
                      disabled={!canValidate || busyAction === "validate"}
                      onClick={() => {
                        setBusyAction("validate");
                        void withSessionGuard(async () => {
                          const response = await validateSolutionChangeSession(
                            String(selectedSession.application_id),
                            String(selectedSession.id)
                          );
                          mergeUpdatedSession(response.session);
                          if (String(response.session?.execution_status || "").toLowerCase() === "ready_for_promotion") {
                            setMessage("Validation complete — ready for promotion.");
                            return;
                          }
                          setMessage("Validation completed.");
                        });
                      }}
                    >
                      Validate
                    </button>
                    {executionPhase === "ready_for_promotion" ? (
                      <button
                        type="button"
                        className={`${primaryExecutionAction === "promote" ? "primary" : "ghost"} sm`}
                        disabled={!canPromote || busyAction === "promote"}
                        onClick={() => {
                          setBusyAction("promote");
                          void withSessionGuard(async () => {
                            const response = await promoteSolutionChangeSession(
                              String(selectedSession.application_id),
                              String(selectedSession.id)
                            );
                            mergeUpdatedSession(response.session);
                            const promotedState = response.session?.metadata?.promotion;
                            const promotedUiUrl = String(
                              promotedState && typeof promotedState === "object" ? (promotedState as Record<string, unknown>).ui_url || "" : ""
                            ).trim();
                            if (response.already_up_to_date) {
                              setMessage("Primary local runtime is already up to date.");
                              return;
                            }
                            if (promotedUiUrl) {
                              setMessage(
                                <>
                                  Changes applied to running environment (
                                  <a href={promotedUiUrl} target="_blank" rel="noreferrer">
                                    {promotedUiUrl}
                                  </a>
                                  ).
                                </>
                              );
                              return;
                            }
                            setMessage("Changes applied to running environment.");
                          });
                        }}
                      >
                        Promote
                      </button>
                    ) : null}
                    {executionPhase === "ready_for_promotion" ? (
                      <button
                        type="button"
                        className={`${primaryExecutionAction === "finalize" ? "primary" : "ghost"} sm`}
                        disabled={!canFinalize || busyAction === "finalize"}
                        onClick={() => {
                          setBusyAction("finalize");
                          void withSessionGuard(async () => {
                            const response = await finalizeSolutionChangeSession(
                              String(selectedSession.application_id),
                              String(selectedSession.id)
                            );
                            mergeUpdatedSession(response.session);
                            window.dispatchEvent(new Event(LINKED_SESSION_UPDATED_EVENT));
                            setMessage("Session finalized.");
                          });
                        }}
                      >
                        Finalize Session
                      </button>
                    ) : null}
                  </div>
                )}
                <p className="muted small" style={{ marginTop: 8 }}>
                  {hasPendingPrompt
                    ? "Blocked: unresolved planner question or option set."
                    : !hasDraftPlan
                      ? "Blocked: no draft plan yet."
                        : hasPendingCheckpoint
                        ? "Blocked: checkpoint approval pending."
                        : !hasApprovedStageCheckpoint
                          ? "Blocked: required checkpoint is not approved."
                          : executionPhase === "ready_for_promotion" && !promotionSucceeded
                            ? "Blocked: promote validated changes to the primary runtime before finalizing."
                          : isSessionFinalized
                            ? "Session finalized."
                          : `Current phase: ${currentPhaseLabel}. Next step: ${derivedExecutionNextAction}.`}
                </p>
              </>
            )}
          </section>

          <section className="card">
            <div className="field-label">Execution Status</div>
            {!selectedSession ? (
              <p className="muted small">No session selected.</p>
            ) : (
              <div className="composer-execution-status">
                <div><span className="field-label">Current phase</span><p>{currentPhaseLabel}</p></div>
                <div><span className="field-label">Recommended next action</span><p>{derivedExecutionNextAction}</p></div>
                <div><span className="field-label">Latest result</span><p>{latestExecutionResult}</p></div>
                <div><span className="field-label">Session status</span><p>{titleCaseLabel(String(selectedSession.status || "draft"))}</p></div>
                <div><span className="field-label">Execution</span><p>{titleCaseLabel(String(selectedSession.execution_status || "not_started"))}</p></div>
                <div><span className="field-label">Preview</span><p>{selectedSession.preview?.status ? titleCaseLabel(String(selectedSession.preview.status)) : "Not prepared"}</p></div>
                <div><span className="field-label">Validation</span><p>{selectedSession.validation?.status ? titleCaseLabel(String(selectedSession.validation.status)) : "Not run"}</p></div>
                {previewPrimaryUrl ? (
                  <div>
                    <span className="field-label">Preview URL</span>
                    <p>{previewPrimaryUrl}</p>
                  </div>
                ) : null}
                {previewBuildStatus ? (
                  <div>
                    <span className="field-label">Session Build</span>
                    <p>{titleCaseLabel(previewBuildStatus)}</p>
                  </div>
                ) : null}
                {previewBuildReason ? (
                  <div>
                    <span className="field-label">Build Reason</span>
                    <p>{previewBuildReason}</p>
                  </div>
                ) : null}
                {promotionState ? (
                  <div>
                    <span className="field-label">Promotion</span>
                    <p>{titleCaseLabel(promotionResult || "unknown")} · {promotionTarget}</p>
                  </div>
                ) : null}
                {promotionUrl ? (
                  <div>
                    <span className="field-label">Promoted URL</span>
                    <p>{promotionUrl}</p>
                  </div>
                ) : null}
                {sessionExecutionSummary ? (
                  <div>
                    <span className="field-label">Execution Summary</span>
                    <p>
                      {executionQueuedCount} queued
                      {executionFailedCount ? ` · ${executionFailedCount} failed` : ""}
                      {executionSkippedCount ? ` · ${executionSkippedCount} skipped` : ""}
                      {executionTotalCount ? ` · ${executionTotalCount} total` : ""}
                    </p>
                  </div>
                ) : null}
              </div>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}

const PANEL_TITLES: Record<ConsolePanelKey, string> = {
  platform_settings: "Platform Settings",
  composer_detail: "Composer",
  workspaces: "Workspaces",
  goal_list: "Goals",
  goal_detail: "Goal",
  campaign_list: "Campaigns",
  campaign_detail: "Campaign",
  application_plan_detail: "Application Plan",
  application_detail: "Application",
  solution_list: "Solutions",
  solution_detail: "Solution",
  thread_list: "Threads",
  thread_detail: "Thread",
  runs: "Runs",
  drafts_list: "Drafts",
  draft_detail: "Build Draft",
  jobs_list: "Jobs",
  job_detail: "Pipeline Job",
  work_items: "Work Items",
  work_item_detail: "Work Item",
  palette_result: "Palette Result",
  app_builder_artifact_list: "Artifacts",
  run_detail: "Run Detail",
  artifact_list: "Artifact List",
  artifact_detail: "Artifact Detail",
  artifact_raw_json: "Artifact Raw JSON",
  artifact_files: "Artifact Files",
  rules_browser: "Rules Browser",
  ems_devices: "EMS Devices",
  ems_registrations: "EMS Registrations",
  ems_device_status_rollup: "EMS Device Status Rollup",
  ems_registrations_timeseries: "EMS Registrations Timeseries",
  ems_dataset_schema: "Dataset Schema",
  ems_unregistered_devices: "Unregistered Devices",
  ems_registrations_time: "Registrations (Past N Hours)",
  ems_device_statuses: "Device Statuses",
  record_detail: "Record Detail",
  local_provision_result: "Local Provision Result",
};

export function panelTitleFor(key: ConsolePanelKey): string {
  return PANEL_TITLES[key];
}

function titleCaseToken(value: string): string {
  return String(value || "")
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function humanizePanelTitle(panel: ConsolePanelSpec, resolvedTitle: string): string {
  const trimmedResolved = String(resolvedTitle || "").trim();
  if (trimmedResolved) return trimmedResolved;
  const trimmedPanelTitle = String(panel.title || "").trim();
  if (trimmedPanelTitle && trimmedPanelTitle !== panel.key) return trimmedPanelTitle;
  const instanceKey = String(panel.instance_key || "").trim();
  if (instanceKey) {
    const datasetToken = instanceKey.includes(":") ? instanceKey.split(":", 1)[0] : instanceKey;
    const asTitle = titleCaseToken(datasetToken);
    if (asTitle) {
      if (panel.panel_type === "table" && !/\b(List|Table)\b/i.test(asTitle)) return `${asTitle} List`;
      return asTitle;
    }
  }
  return panelTitleFor(panel.key);
}

export default function WorkbenchPanelHost({
  panel,
  workspaceId,
  workspaceName,
  workspaceColor,
  currentUser,
  onOpenPanel,
  onClosePanel,
  onContextChange,
}: {
  panel: ConsolePanelSpec | null;
  workspaceId: string;
  workspaceName?: string;
  workspaceColor?: string;
  currentUser?: Record<string, unknown> | null;
  onOpenPanel: (panel: ConsolePanelSpec) => void;
  onClosePanel?: () => void;
  onContextChange?: ContextEmitter;
}) {
  const [resolvedTitle, setResolvedTitle] = useState("");

  useEffect(() => {
    setResolvedTitle("");
  }, [panel?.panel_id, panel?.key]);

  const content = useMemo(() => {
    if (!panel || panel.key === "platform_settings") return null;
    const openPanel = (
      panelKey: ConsolePanelKey,
      params?: Record<string, unknown>,
      options?: { open_in?: "current_panel" | "new_panel" | "side_by_side"; return_to_panel_id?: string }
    ) =>
      onOpenPanel({
        key: panelKey,
        params: params || {},
        open_in: options?.open_in,
        return_to_panel_id: options?.return_to_panel_id,
      });


    if (panel.key === "composer_detail") {
      return (
        <ComposerDetailPanel
          workspaceId={workspaceId}
          currentUser={currentUser}
          factoryKey={String(panel.params?.factory_key || "") || undefined}
          applicationPlanId={String(panel.params?.application_plan_id || "") || undefined}
          applicationId={String(panel.params?.application_id || "") || undefined}
          goalId={String(panel.params?.goal_id || "") || undefined}
          threadId={String(panel.params?.thread_id || "") || undefined}
          solutionChangeSessionId={String(panel.params?.solution_change_session_id || "") || undefined}
          onOpenPanel={openPanel}
          onTitleChange={setResolvedTitle}
        />
      );
    }

    if (panel.key === "workspaces") {
      return (
        <WorkspacesPanel
          query={(panel.params?.query as CanvasQuery | undefined) || undefined}
          queryError={String(panel.params?.query_error || "")}
          panel={panel}
          onContextChange={onContextChange}
          onTitleChange={setResolvedTitle}
          onOpenDetail={(target) => {
            if (target.entity_type === "workspace") {
              openPanel("record_detail", { ...target }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
              return;
            }
            openPanel("record_detail", { ...target }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
          }}
        />
      );
    }

    if (panel.key === "runs") {
      return (
        <RunsPanel
          workspaceId={workspaceId}
          query={(panel.params?.query as CanvasQuery | undefined) || undefined}
          queryError={String(panel.params?.query_error || "")}
          panel={panel}
          onContextChange={onContextChange}
          onTitleChange={setResolvedTitle}
          onOpenDetail={(target, row) => {
            if (target.entity_type === "run") {
              openPanel("run_detail", { run_id: target.entity_id }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
              return;
            }
            openPanel("record_detail", { ...target, row }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
          }}
        />
      );
    }

    if (panel.key === "drafts_list") {
      return (
        <DraftsListPage
          workspaceId={workspaceId}
          workspaceName={workspaceName || "Unknown"}
          workspaceColor={workspaceColor}
          workspaceBarVariant="compact"
          onSelectDraft={(draftId) => openPanel("draft_detail", { draft_id: draftId }, { open_in: "new_panel", return_to_panel_id: panel.panel_id })}
        />
      );
    }

    if (panel.key === "jobs_list") {
      return (
        <JobsListPage
          workspaceId={workspaceId}
          workspaceName={workspaceName || "Unknown"}
          workspaceColor={workspaceColor}
          workspaceBarVariant="compact"
          onSelectJob={(jobId) => openPanel("job_detail", { job_id: jobId }, { open_in: "new_panel", return_to_panel_id: panel.panel_id })}
        />
      );
    }

    if (panel.key === "work_items") {
      return (
        <WorkItemsPanel
          workspaceId={workspaceId}
          panel={panel}
          onContextChange={onContextChange}
          onTitleChange={setResolvedTitle}
          onOpenDetail={(target, row) => {
            if (target.entity_type === "work_item") {
              openPanel("work_item_detail", { work_item_id: target.entity_id }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
              return;
            }
            openPanel("record_detail", { ...target, row }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
          }}
        />
      );
    }

    if (panel.key === "solution_list") {
      return (
        <SolutionListPanel
          workspaceId={workspaceId}
          workspaceName={String(panel.params?.workspace_name || "")}
          solutionNameQuery={String(panel.params?.solution_name || "") || undefined}
          createSolutionObjective={String(panel.params?.create_solution_objective || "") || undefined}
          createSolutionName={String(panel.params?.create_solution_name || "") || undefined}
          onOpenPanel={openPanel}
        />
      );
    }

    if (panel.key === "solution_detail") {
      return (
        <SolutionDetailPanel
          workspaceId={workspaceId}
          applicationId={String(panel.params?.application_id || "")}
          onOpenPanel={openPanel}
        />
      );
    }

    if (panel.key === "goal_list") {
      return <GoalListPanel workspaceId={workspaceId} onOpenPanel={openPanel} onTitleChange={setResolvedTitle} />;
    }

    if (panel.key === "campaign_list") {
      return (
        <CampaignListPanel
          workspaceId={workspaceId}
          onOpenPanel={openPanel}
          onTitleChange={setResolvedTitle}
          autoCreate={panel.params?.create === true}
        />
      );
    }

    if (panel.key === "campaign_detail") {
      return (
        <CampaignDetailPanel
          campaignId={String(panel.params?.campaign_id || "")}
          workspaceId={workspaceId}
          onTitleChange={setResolvedTitle}
        />
      );
    }

    if (panel.key === "goal_detail") {
      return (
        <GoalDetailPanel
          goalId={String(panel.params?.goal_id || "")}
          workspaceId={workspaceId}
          onOpenPanel={openPanel}
          onTitleChange={setResolvedTitle}
        />
      );
    }

    if (panel.key === "application_plan_detail") {
      return (
        <ApplicationPlanDetailPanel
          applicationPlanId={String(panel.params?.application_plan_id || "")}
          onOpenPanel={openPanel}
          onTitleChange={setResolvedTitle}
        />
      );
    }

    if (panel.key === "application_detail") {
      return (
        <ApplicationDetailPanel
          applicationId={String(panel.params?.application_id || "")}
          onOpenPanel={openPanel}
          onTitleChange={setResolvedTitle}
        />
      );
    }

    if (panel.key === "thread_list") {
      return <ThreadListPanel workspaceId={workspaceId} onOpenPanel={openPanel} onTitleChange={setResolvedTitle} />;
    }

    if (panel.key === "thread_detail") {
      return (
        <ThreadDetailPanel
          threadId={String(panel.params?.thread_id || "")}
          workspaceId={workspaceId}
          onOpenPanel={openPanel}
          onTitleChange={setResolvedTitle}
        />
      );
    }

    if (panel.key === "draft_detail") {
      return (
        <DraftDetailPage
          workspaceId={workspaceId}
          workspaceName={workspaceName || "Unknown"}
          workspaceColor={workspaceColor}
          workspaceBarVariant="compact"
          draftId={String(panel.params?.draft_id || "")}
          linkedJobId={String(panel.params?.job_id || "")}
          onBack={() => {
            if (panel.return_to_panel_id) {
              onClosePanel?.();
            }
          }}
          onOpenJob={(jobId) => openPanel("job_detail", { job_id: jobId }, { open_in: "new_panel", return_to_panel_id: panel.panel_id })}
          onOpenArtifacts={(kind) =>
            openPanel("app_builder_artifact_list", { kind: String(kind || "") }, { open_in: "new_panel", return_to_panel_id: panel.panel_id })
          }
        />
      );
    }

    if (panel.key === "job_detail") {
      return (
        <JobDetailPage
          workspaceId={workspaceId}
          workspaceName={workspaceName || "Unknown"}
          workspaceColor={workspaceColor}
          workspaceBarVariant="compact"
          jobId={String(panel.params?.job_id || "")}
          onBack={() => {
            if (panel.return_to_panel_id) {
              onClosePanel?.();
            }
          }}
        />
      );
    }

    if (panel.key === "work_item_detail") {
      return (
        <WorkItemDetailPanel
          workItemId={String(panel.params?.work_item_id || panel.params?.job_id || "")}
          workspaceId={workspaceId}
          onOpenPanel={openPanel}
        />
      );
    }

    if (panel.key === "palette_result") {
      return (
        <PaletteResultPanel
          result={panel.params?.result as AppPaletteResult | undefined}
          prompt={String(panel.params?.prompt || "")}
          error={String(panel.params?.error || "")}
          workspaceId={workspaceId}
        />
      );
    }

    if (panel.key === "app_builder_artifact_list") {
      return <AppBuilderArtifactListPanel workspaceId={workspaceId} kind={String(panel.params?.kind || "")} />;
    }

    if (panel.key === "run_detail") {
      return (
        <RunDetailPanel
          runId={String(panel.params?.run_id || "")}
          workspaceId={workspaceId}
          panel={panel}
          onContextChange={onContextChange}
          onOpenPanel={openPanel}
        />
      );
    }

    if (panel.key === "artifact_list") {
      return (
        <ArtifactListPanel
          namespace={String(panel.params?.namespace || "")}
          workspaceId={workspaceId}
          query={(panel.params?.query as ArtifactStructuredQuery | undefined) || undefined}
          queryError={String(panel.params?.query_error || "")}
          onOpenArtifactDetail={(slug) => openPanel("artifact_detail", { slug }, { open_in: "new_panel", return_to_panel_id: panel.panel_id })}
          panel={panel}
          onContextChange={onContextChange}
          onTitleChange={setResolvedTitle}
        />
      );
    }

    if (panel.key === "artifact_detail") {
      const runtimeRunId = String(panel.params?.runtime_run_id || "").trim();
      const runtimeArtifactId = String(panel.params?.runtime_artifact_id || "").trim();
      if (runtimeRunId && runtimeArtifactId) {
        return <RuntimeArtifactDetailPanel runId={runtimeRunId} artifactId={runtimeArtifactId} workspaceId={workspaceId} onOpenPanel={openPanel} />;
      }
      return <ArtifactDetailPanel slug={String(panel.params?.slug || "")} panel={panel} onContextChange={onContextChange} onOpenPanel={openPanel} />;
    }
    if (panel.key === "artifact_raw_json") return <ArtifactRawJsonPanel slug={String(panel.params?.slug || "")} />;
    if (panel.key === "artifact_files") return <ArtifactFilesPanel slug={String(panel.params?.slug || "")} />;
    if (panel.key === "rules_browser") {
      return (
        <RulesBrowserPanel
          workspaceId={workspaceId}
          artifactSlug={String(panel.params?.artifact_slug || "") || undefined}
          appSlug={String(panel.params?.app_slug || "") || undefined}
          query={String(panel.params?.q || panel.params?.query || "") || undefined}
          editableOnly={panel.params?.editable === true}
          systemOnly={panel.params?.system === true}
        />
      );
    }
    if (panel.key === "record_detail") {
      return (
        <GenericRecordDetailPanel
          entityType={String(panel.params?.entity_type || "record")}
          entityId={String(panel.params?.entity_id || "")}
          dataset={String(panel.params?.dataset || "") || undefined}
          row={(panel.params?.row as Record<string, unknown> | undefined) || undefined}
          panel={panel}
          onContextChange={onContextChange}
        />
      );
    }
    if (panel.key === "local_provision_result") {
      return <LocalProvisionResultPanel payload={(panel.params?.payload as LocalProvisionResponse | undefined) || null} />;
    }

    if (panel.key === "ems_devices" || panel.key === "ems_unregistered_devices") {
      const query = (panel.params?.query as CanvasQuery) || {
        entity: "ems_devices",
        filters: panel.key === "ems_unregistered_devices" ? [{ field: "state", op: "eq", value: "unregistered" }] : [],
        sort: [{ field: "created_at", dir: "desc" }],
        limit: 50,
        offset: 0,
      };
      return (
        <EmsCanvasPanel
          fetcher={(nextQuery) => queryEmsDevicesCanvasTable({ query: nextQuery as never })}
          initialQuery={query}
          queryError={String(panel.params?.query_error || "")}
          panel={panel}
          onContextChange={onContextChange}
          onTitleChange={setResolvedTitle}
          onOpenDetail={(target, row) => {
            openPanel("record_detail", { ...target, row }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
          }}
        />
      );
    }

    if (panel.key === "ems_registrations" || panel.key === "ems_registrations_time") {
      const hours = Number(panel.params?.hours || 24);
      const query = (panel.params?.query as CanvasQuery) || {
        entity: "ems_registrations",
        filters: [{ field: "registered_at", op: "gte", value: `now-${Math.max(1, Math.min(hours, 168))}h` }],
        sort: [{ field: "registered_at", dir: "desc" }],
        limit: 50,
        offset: 0,
      };
      return (
        <EmsCanvasPanel
          fetcher={(nextQuery) => queryEmsRegistrationsCanvasTable({ query: nextQuery as never })}
          initialQuery={query}
          queryError={String(panel.params?.query_error || "")}
          panel={panel}
          onContextChange={onContextChange}
          onTitleChange={setResolvedTitle}
          onOpenDetail={(target, row) => {
            openPanel("record_detail", { ...target, row }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
          }}
        />
      );
    }

    if (panel.key === "ems_device_status_rollup" || panel.key === "ems_device_statuses") {
      return (
        <EmsCanvasPanel
          fetcher={() => getEmsStatusRollupCanvasTable()}
          initialQuery={{ entity: "ems_device_status_rollup", filters: [], sort: [{ field: "bucket", dir: "asc" }], limit: 50, offset: 0 }}
          panel={panel}
          onContextChange={onContextChange}
          onTitleChange={setResolvedTitle}
          onOpenDetail={(target, row) => {
            openPanel("record_detail", { ...target, row }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
          }}
        />
      );
    }

    if (panel.key === "ems_registrations_timeseries") {
      const hours = Number(panel.params?.hours || 24);
      return (
        <EmsCanvasPanel
          fetcher={() => getEmsRegistrationsTimeseriesCanvasTable({ range: `now-${Math.max(1, Math.min(hours, 168))}h`, bucket: "1h" })}
          initialQuery={{
            entity: "ems_registrations_timeseries",
            filters: [{ field: "bucket_start", op: "gte", value: `now-${Math.max(1, Math.min(hours, 168))}h` }],
            sort: [{ field: "bucket_start", dir: "asc" }],
            limit: 50,
            offset: 0,
          }}
          panel={panel}
          onContextChange={onContextChange}
          onTitleChange={setResolvedTitle}
          onOpenDetail={(target, row) => {
            openPanel("record_detail", { ...target, row }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
          }}
        />
      );
    }

    if (panel.key === "ems_dataset_schema") {
      const dataset = String(panel.params?.dataset || "ems_devices");
      return (
        <EmsCanvasPanel
          fetcher={() => getEmsDatasetSchemaTable(dataset)}
          initialQuery={{ entity: "dataset_schema", filters: [], sort: [{ field: "key", dir: "asc" }], limit: 200, offset: 0 }}
          panel={panel}
          onContextChange={onContextChange}
          onTitleChange={setResolvedTitle}
          onOpenDetail={(target, row) => {
            openPanel("record_detail", { ...target, row }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
          }}
        />
      );
    }

    return null;
  }, [onContextChange, onOpenPanel, panel, workspaceId]);

  if (!panel) {
    return null;
  }

  if (panel.key === "platform_settings") {
    return (
      <div className="card ems-panel-host">
        <PlatformSettingsPanel
          workspaceId={workspaceId}
          workspaceName={workspaceName}
          initialSection={String(panel.params?.section || "")}
          initialSurface={String(panel.params?.surface || "")}
          onSectionChange={(next) => {
            if (panel.params) panel.params.section = next;
          }}
          onSurfaceChange={(next) => {
            if (!panel.params) return;
            panel.params.surface = next;
          }}
        />
      </div>
    );
  }

  return <div className="card ems-panel-host">{content || <p className="muted">Unknown panel.</p>}</div>;
}
