import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  applyApplicationPlan,
  executeAppPalettePrompt,
  getApplication,
  getApplicationPlan,
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
  getSystemReadiness,
  getWorkItem,
  getWorkQueue,
  dispatchNextWorkQueueItem,
  dispatchWorkItem,
  generateApplicationPlan,
  listGoals,
  listCoordinationThreads,
  listWorkItems,
  listAppBuilderArtifacts,
  listRuntimeRunsCanvasApi,
  listWorkspacesCanvasApi,
  publishDevTask,
  queryArtifactCanvasTable,
  queryEmsDevicesCanvasTable,
  queryEmsRegistrationsCanvasTable,
  requeueDevTask,
  reviewCoordinationThread,
  reviewGoal,
  retryDevTask,
  updateApplication,
  updateApplicationPlan,
  updateWorkItem,
} from "../../../api/xyn";
import type {
  AppBuilderArtifact,
  ApplicationDetail,
  ApplicationFactorySummary,
  ApplicationPlanDetail,
  AppPaletteResult,
  ArtifactCanvasTableResponse,
  ArtifactConsoleDetailResponse,
  ArtifactConsoleFileRow,
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
  SystemReadinessResponse,
  WorkQueueResponse,
  WorkItemDetail,
  WorkItemSummary,
  WorkspaceSummary,
} from "../../../api/types";
import CanvasRenderer from "../../../components/canvas/CanvasRenderer";
import InlineMessage from "../../../components/InlineMessage";
import type { OpenDetailTarget } from "../../../components/canvas/datasetEntityRegistry";
import { XYN_ENTITY_CHANGE_EVENT, inferEntityListPrompt, type EntityChangeDetail } from "../../utils/entityChangeEvents";
import { applyRuntimeEventToRunDetail, applyRuntimeEventToRuns, refreshRuntimeRunDetail, refreshRuntimeRunSummary, subscribeRuntimeEventStream } from "../../utils/runtimeEventStream";
import {
  deriveComposerStageSummary,
  deriveComposerViewModel,
  formatComposerCountLabel,
  formatComposerGoalProgressStatus,
  formatComposerPlanningStatus,
  formatComposerThreadStatus,
  latestTimestamp,
} from "./composerViewModel";
import type { ComposerContainerFilter, ComposerWorkContainer } from "./composerViewModel";
import { clearComposerStoredSelection, readComposerStoredSelection, resolveComposerInitialSelection, writeComposerStoredSelection } from "./composerSelection";
import DraftDetailPage from "../../pages/DraftDetailPage";
import DraftsListPage from "../../pages/DraftsListPage";
import JobDetailPage from "../../pages/JobDetailPage";
import JobsListPage from "../../pages/JobsListPage";
import PlatformSettingsHubPage from "../../pages/PlatformSettingsHubPage";
import { toWorkspacePath } from "../../routing/workspaceRouting";

export type ConsolePanelKey =
  | "platform_settings"
  | "composer_detail"
  | "goal_list"
  | "goal_detail"
  | "application_plan_detail"
  | "application_detail"
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

function readinessTone(readiness: SystemReadinessResponse | null): "ok" | "warning" | "error" {
  if (!readiness) return "warning";
  if (readiness.ready) return "ok";
  return readiness.checks.some((check) => check.status === "error") ? "error" : "warning";
}

function SystemReadinessBanner({ readiness }: { readiness: SystemReadinessResponse | null }) {
  if (!readiness) return null;
  const tone = readinessTone(readiness);
  const title = readiness.summary || (readiness.ready ? "System ready" : "Configuration required");
  return (
    <section className="card system-readiness-banner" style={{ borderColor: tone === "error" ? "#d14343" : tone === "warning" ? "#c18401" : "#2d7a46" }}>
      <div className="card-header">
        <h3>System Readiness</h3>
      </div>
      <p style={{ marginTop: 0 }}>{title}</p>
      <details>
        <summary>Diagnostic checks</summary>
        <div className="detail-grid" style={{ marginTop: 12 }}>
          {readiness.checks.map((check) => (
            <div key={check.component}>
              <div className="field-label">{titleCaseToken(check.component)}</div>
              <div className="field-value">
                {titleCaseToken(check.status)}: {check.message}
              </div>
            </div>
          ))}
        </div>
      </details>
    </section>
  );
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
        const next = await getGoal(goalId);
        if (!active) return;
        setPayload(next);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load goal");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [goalId]);

  useEffect(() => {
    onTitleChange?.(payload?.title || "Goal");
  }, [onTitleChange, payload?.title]);

  if (loading) return <p className="muted">Loading goal…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">Goal not found.</p>;

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
        const detail = await getCoordinationThread(threadId);
        if (!active) return;
        setPayload(detail);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load thread");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [threadId]);

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
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">Thread not found.</p>;

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
      const response = await dispatchWorkItem(workItemId, workspaceId);
      setPayload(response.work_item || (await getWorkItem(workItemId)));
      setActionState({
        status: "idle",
        message: response.status === "dispatched" ? `Dispatched ${String(response.queue_item?.work_item_id || payload?.work_item_id || workItemId)}.` : response.status,
      });
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
  const queue = payload.execution_queue;
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
          {queue.dispatchable && !queue.dispatched ? (
            <div className="inline-action-row" style={{ marginTop: 12 }}>
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

type SettingsSection = "general" | "security" | "integrations" | "deploy" | "workspaces";
const VALID_SETTINGS_SECTIONS: SettingsSection[] = ["general", "security", "integrations", "deploy", "workspaces"];

const PlatformSettingsPanel = React.memo(function PlatformSettingsPanel({
  initialSection,
  onSectionChange,
}: {
  initialSection?: string;
  onSectionChange?: (section: SettingsSection) => void;
}) {
  const parsed = String(initialSection || "").trim().toLowerCase();
  const init: SettingsSection = (VALID_SETTINGS_SECTIONS as string[]).includes(parsed) ? (parsed as SettingsSection) : "security";
  const [section, setSection] = useState<SettingsSection>(init);

  useEffect(() => {
    setSection(init);
  }, [init]);

  const handleChange = (next: SettingsSection) => {
    if (next === section) return;
    setSection(next);
    onSectionChange?.(next);
  };

  return <PlatformSettingsHubPage sectionOverride={section} onSectionChange={handleChange} />;
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
        setError(err instanceof Error ? err.message : "Failed to load artifact detail");
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
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">Artifact not found.</p>;

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

  return (
    <div className="ems-panel-body">
      <p className="muted">
        {payload.artifact.slug} · {payload.artifact.kind} · v{payload.artifact.version}
      </p>
      <p className="muted small">Roles: {(payload.manifest_summary?.roles || []).join(", ") || "none"}</p>
      <div className="inline-actions">
        <button type="button" className="ghost sm" onClick={() => onOpenPanel("artifact_raw_json", { slug: payload.artifact.slug })}>
          Open Raw JSON
        </button>
        <button type="button" className="ghost sm" onClick={() => onOpenPanel("artifact_files", { slug: payload.artifact.slug })}>
          Open Files
        </button>
      </div>
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
  const [message, setMessage] = useState<string | null>(null);

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
  factoryKey,
  applicationPlanId,
  applicationId,
  goalId,
  threadId,
  onOpenPanel,
  onTitleChange,
}: {
  workspaceId: string;
  factoryKey?: string;
  applicationPlanId?: string;
  applicationId?: string;
  goalId?: string;
  threadId?: string;
  onTitleChange?: (title: string) => void;
} & PanelProps) {
  const [payload, setPayload] = useState<ComposerState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [objective, setObjective] = useState("");
  const [effortFilter, setEffortFilter] = useState<ComposerContainerFilter>("active");
  const [hiddenEffortIds, setHiddenEffortIds] = useState<Record<string, true>>(() => {
    if (typeof window === "undefined") return {};
    try {
      const raw = window.localStorage.getItem(`xyn:composer:hidden-efforts:${workspaceId}`);
      return raw ? JSON.parse(raw) as Record<string, true> : {};
    } catch {
      return {};
    }
  });

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(`xyn:composer:hidden-efforts:${workspaceId}`, JSON.stringify(hiddenEffortIds));
  }, [hiddenEffortIds, workspaceId]);

  useEffect(() => {
    writeComposerStoredSelection(workspaceId, {
      application_id: applicationId,
      application_plan_id: applicationPlanId,
    });
  }, [applicationId, applicationPlanId, workspaceId]);

  async function reloadComposerState() {
    const next = await getComposerState({
      workspace_id: workspaceId,
      factory_key: factoryKey,
      application_plan_id: applicationPlanId,
      application_id: applicationId,
      goal_id: goalId,
      thread_id: threadId,
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
  }, [applicationId, applicationPlanId, factoryKey, goalId, threadId, workspaceId]);

  useEffect(() => {
    onTitleChange?.("Composer");
  }, [onTitleChange]);

  const openComposer = (params?: Record<string, unknown>) => {
    const nextParams = {
      workspace_id: workspaceId,
      ...(params || {}),
    };
    writeComposerStoredSelection(workspaceId, nextParams);
    onOpenPanel("composer_detail", nextParams);
  };

  async function handleGeneratePlan(targetFactoryKey?: string) {
    const objectiveText = objective.trim();
    if (!objectiveText) {
      setMessage("Enter an application objective before generating a plan.");
      return;
    }
    try {
      const response = await generateApplicationPlan({
        workspace_id: workspaceId,
        objective: objectiveText,
        factory_key: targetFactoryKey || factoryKey || undefined,
        application_name: payload?.selected_factory?.name ? objectiveText : undefined,
      });
      setMessage(`Generated reviewable plan for ${response.name}.`);
      openComposer({
        application_plan_id: response.id,
        factory_key: response.source_factory_key || targetFactoryKey || factoryKey || undefined,
      });
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to generate application plan");
    }
  }

  async function handleApplyPlan(id: string) {
    try {
      const response = await applyApplicationPlan(id);
      setMessage(
        response.status === "applied"
          ? `Applied ${response.application.name} into durable goals, threads, and work items.`
          : `${response.application.name} was already applied.`
      );
      openComposer({
        application_plan_id: response.application_plan.id,
        application_id: response.application.id,
      });
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to apply application plan");
    }
  }

  async function handleArchiveApplication(application: ComposerWorkContainer | ApplicationDetail) {
    try {
      const result = await updateApplication(application.id, { status: "archived" });
      setMessage(`Archived ${result.name}. It is now hidden from the default active view.`);
      await reloadComposerState();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to archive the application effort");
    }
  }

  async function handleCancelPlan(plan: ComposerWorkContainer | ApplicationPlanDetail) {
    try {
      const result = await updateApplicationPlan(plan.id, { status: "canceled" });
      setMessage(`Canceled ${result.name}. It is now treated as historical plan work.`);
      await reloadComposerState();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to archive the application plan");
    }
  }

  async function handleRestartEffort(container: ComposerWorkContainer) {
    const objectiveText = String(container.requestObjective || "").trim();
    if (!objectiveText) {
      setMessage("This effort does not have a reusable objective, so Xyn cannot restart it automatically.");
      return;
    }
    try {
      const response = await generateApplicationPlan({
        workspace_id: workspaceId,
        objective: objectiveText,
        factory_key: container.sourceFactoryKey || undefined,
        application_name: container.title,
      });
      if (container.kind === "application") {
        await updateApplication(container.id, { status: "archived" });
      } else {
        await updateApplicationPlan(container.id, { status: "canceled" });
      }
      setMessage(`Started a new plan for ${container.title} and retired the older effort from the default active view.`);
      setEffortFilter("active");
      openComposer({
        application_plan_id: response.id,
        factory_key: response.source_factory_key || container.sourceFactoryKey || undefined,
      });
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to start over from this application effort");
    }
  }

  async function handleApproveNextSlice(goal: GoalDetail, recommendationId?: string | null) {
    try {
      const response = await reviewGoal(goal.id, "approve_and_queue", recommendationId);
      const nextRecommendation =
        response.goal?.recommendation && typeof response.goal.recommendation === "object"
          ? response.goal.recommendation
          : null;
      const nextThreadId =
        nextRecommendation?.thread_id
        || nextRecommendation?.queue_suggestion?.thread_id
        || nextRecommendation?.recommended_work_items?.[0]?.thread_id
        || null;
      const nextWorkItemId =
        nextRecommendation?.work_item_id
        || nextRecommendation?.queue_suggestion?.work_item_id
        || nextRecommendation?.recommended_work_items?.[0]?.id
        || null;
      const nextMessage =
        response.status === "approved"
          ? "Approved and queued the next slice."
          : response.status === "already_queued"
            ? "That slice is already queued. Open the thread and dispatch the ready work item."
            : response.status === "no_recommendation"
              ? "No queueable next slice is available right now."
              : response.status === "stale_recommendation"
                ? "That recommendation is no longer current. Refresh the goal and review the latest next slice."
                : response.status.replace(/_/g, " ");
      setMessage(nextMessage);
      openComposer({
        goal_id: goal.id,
        application_id: goal.application_id || undefined,
        thread_id: nextThreadId || undefined,
        work_item_id: nextWorkItemId || undefined,
      });
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to approve the next slice");
    }
  }

  async function handleThreadReview(thread: CoordinationThreadDetail, reviewAction: "resume_thread" | "queue_next_slice" | "mark_thread_completed") {
    try {
      const response = await reviewCoordinationThread(thread.id, reviewAction);
      setMessage(response.summary || response.status.replace(/_/g, " "));
      openComposer({
        thread_id: thread.id,
        goal_id: thread.goal_id || goalId,
        application_id: applicationId || payload?.goal?.application_id || undefined,
      });
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to review thread");
    }
  }

  const selectedFactory = payload?.selected_factory ?? null;
  const selectedGoal = payload?.goal ?? null;
  const selectedThread = payload?.thread ?? null;
  const selectedApplication = payload?.application ?? null;
  const selectedPlan = payload?.application_plan ?? null;
  const portfolioInsights = payload?.portfolio_context?.insights || [];
  const breadcrumbRows = payload?.breadcrumbs || [];
  const actionableBreadcrumbs = breadcrumbRows.filter(
    (crumb) => !(crumb.kind === "composer" && breadcrumbRows.length === 1)
  );
  const composerView = payload ? deriveComposerViewModel(payload) : null;
  const storedSelection = composerView ? readComposerStoredSelection(workspaceId) : null;
  const hasExplicitComposerFocus = Boolean(
    factoryKey
    || applicationPlanId
    || applicationId
    || goalId
    || threadId
  );
  const initialSelection = composerView && !hasExplicitComposerFocus
    ? resolveComposerInitialSelection(composerView.containers, storedSelection)
    : null;
  useEffect(() => {
    if (loading || !payload || !composerView || hasExplicitComposerFocus || !initialSelection) return;
    openComposer(initialSelection);
  }, [composerView, hasExplicitComposerFocus, initialSelection, loading, payload]);
  const currentContainer = composerView?.containers.find((container) =>
    (applicationId && container.kind === "application" && container.id === applicationId)
    || (applicationPlanId && container.kind === "application_plan" && container.id === applicationPlanId)
  ) || null;
  const currentApplication =
    currentContainer?.kind === "application" && selectedApplication?.id === currentContainer.id
      ? selectedApplication
      : null;
  const currentPlan =
    currentContainer?.kind === "application_plan" && selectedPlan?.id === currentContainer.id
      ? selectedPlan
      : null;
  const currentPlanGoals = currentPlan?.generated_goals || currentPlan?.generated_plan?.generated_goals || [];
  const currentGoal =
    currentContainer?.kind === "application" && selectedGoal?.application_id === currentContainer.id
      ? selectedGoal
      : null;
  const currentGoalId = currentGoal?.id || "";
  const selectedContainerGoals = currentContainer?.kind === "application" ? currentContainer.goals : [];
  const selectedContainerGoalIds = new Set(selectedContainerGoals.map((goal) => goal.id));
  const selectedContainerThreads = currentContainer?.kind === "application"
    ? currentContainer.threads
    : [];
  const currentThread =
    currentContainer?.kind === "application" && selectedThread && selectedContainerThreads.some((thread) => thread.id === selectedThread.id)
      ? selectedThread
      : null;
  const currentThreadId = currentThread?.id || "";
  const currentGoalThreads = currentGoal
    ? selectedContainerThreads.filter((thread) => thread.goal_id === currentGoal.id)
    : [];
  const threadDiagnosticSummary = currentThread?.thread_diagnostic
    ? currentThread.thread_diagnostic.observations[0]
      || currentThread.thread_diagnostic.likely_causes[0]
      || currentThread.thread_diagnostic.provenance?.summary
      || null
    : null;
  const threadNeedsBriefReview = Boolean(
    currentThread?.thread_diagnostic && [
      currentThread.thread_diagnostic.suggested_human_review_action,
      ...currentThread.thread_diagnostic.observations,
      ...currentThread.thread_diagnostic.likely_causes,
      threadDiagnosticSummary,
    ].some((entry) => typeof entry === "string" && /brief review/i.test(entry))
  );
  const threadActionGuidance = threadNeedsBriefReview
    ? "Next step: open the thread work items and review the blocking execution brief before queueing more coding work."
    : null;
  const recommendation =
    currentGoal && currentGoal.recommendation && typeof currentGoal.recommendation === "object"
      ? currentGoal.recommendation
      : null;
  useEffect(() => {
    if (!currentContainer) return;
    writeComposerStoredSelection(workspaceId, currentContainer.selectionParams);
  }, [currentContainer, workspaceId]);
  useEffect(() => {
    if (!composerView?.containers.length && !hasExplicitComposerFocus) {
      clearComposerStoredSelection(workspaceId);
    }
  }, [composerView?.containers.length, hasExplicitComposerFocus, workspaceId]);
  const currentWork = currentContainer
    ? {
      ...(composerView?.currentContext || { title: "Choose an application effort", statusLabel: "Awaiting selection", latestResult: "", latestActivityAt: null, container: null }),
      title:
        currentContainer.kind === "application"
          ? (currentThread?.title || currentGoal?.title || currentContainer.title)
          : currentContainer.title,
      statusLabel:
        currentContainer.kind === "application"
          ? (
            currentThread?.status
            || (currentGoal?.goal_progress?.goal_progress_status
              ? formatComposerGoalProgressStatus(currentGoal.goal_progress.goal_progress_status)
              : null)
            || currentContainer.statusLabel
          )
          : currentContainer.statusLabel,
      latestResult:
        currentContainer.kind === "application"
          ? (
            currentThread?.thread_diagnostic?.provenance?.summary
            || currentThread?.thread_diagnostic?.observations?.[0]
            || currentGoal?.recommendation?.summary
            || currentContainer.latestResult
          )
          : currentContainer.latestResult,
      latestActivityAt:
        currentContainer.kind === "application"
          ? latestTimestamp([
            currentThread?.updated_at,
            currentGoal?.updated_at,
            currentContainer.latestActivityAt,
          ])
          : currentContainer.latestActivityAt,
      container: currentContainer,
    }
    : (composerView?.currentContext || {
      title: "Choose an application effort",
      statusLabel: "Awaiting selection",
      latestResult: "Select an application effort to view its goals, threads, and latest workflow state.",
      latestActivityAt: null,
      container: null,
    });
  const stageSummary = payload ? deriveComposerStageSummary(payload, currentWork) : null;

  if (loading) return <p className="muted">Loading composer…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload || !composerView || !stageSummary) return <p className="muted">Composer state unavailable.</p>;
  const effortVisibilityKey = (container: ComposerWorkContainer) => `${container.kind}:${container.id}`;
  const isEffortHidden = (container: ComposerWorkContainer) => Boolean(hiddenEffortIds[effortVisibilityKey(container)]);
  const visibleEffortCount = (filter: ComposerContainerFilter) =>
    composerView.containers.filter((container) => {
      const isHidden = isEffortHidden(container);
      if (filter === "all") return true;
      if (filter === "archived") return container.lifecycleState === "archived";
      if (filter === "failed") return !isHidden && container.lifecycleState === "failed";
      if (isHidden || container.lifecycleState === "archived") return false;
      if (container.lifecycleState === "failed" && !container.isCurrent && !container.isMostRecent) return false;
      if (container.isSuperseded && !container.isCurrent && !container.isMostRecent) return false;
      return true;
    }).length;
  // Active view stays focused on current/recent work and hides locally hidden or stale failed
  // efforts by default. Older failed/archived efforts remain available through the other tabs.
  const filteredContainers = composerView.containers.filter((container) => {
    const isHidden = isEffortHidden(container);
    if (effortFilter === "all") return true;
    if (effortFilter === "archived") return container.lifecycleState === "archived";
    if (effortFilter === "failed") return !isHidden && container.lifecycleState === "failed";
    if (isHidden || container.lifecycleState === "archived") return false;
    if (container.lifecycleState === "failed" && !container.isCurrent && !container.isMostRecent) return false;
    if (container.isSuperseded && !container.isCurrent && !container.isMostRecent) return false;
    return true;
  });
  const latestQuickActionReason = currentThread
    ? threadActionGuidance || "Review the currently focused thread and decide whether it is safe to queue more coding work."
    : recommendation
      ? recommendation.summary
      : currentWork.latestResult;
  const showPlanningTools = payload.stage === "factory_discovery" || payload.stage === "plan_review";

  function renderLifecycleActions(container: ComposerWorkContainer, options?: { compact?: boolean }) {
    const isHidden = isEffortHidden(container);
    const canArchive = container.kind === "application" && container.rawStatus !== "archived";
    const canCancel = container.kind === "application_plan" && container.rawStatus !== "canceled";
    const canRestart = Boolean(String(container.requestObjective || "").trim());
    return (
      <div className="inline-action-row" style={{ marginTop: options?.compact ? 8 : 12, flexWrap: "wrap" }}>
        {canRestart ? (
          <button type="button" className="ghost sm" onClick={() => void handleRestartEffort(container)}>
            Start Over
          </button>
        ) : null}
        {canArchive ? (
          <button type="button" className="ghost sm" onClick={() => void handleArchiveApplication(container)}>
            Archive
          </button>
        ) : null}
        {canCancel ? (
          <button type="button" className="ghost sm" onClick={() => void handleCancelPlan(container)}>
            Mark Obsolete
          </button>
        ) : null}
        <button
          type="button"
          className="ghost sm"
          disabled={container.isCurrent && !isHidden}
          title={container.isCurrent && !isHidden ? "Select another effort before hiding this one from the default active view." : undefined}
          onClick={() => {
            setHiddenEffortIds((current) => {
              const next = { ...current };
              const key = effortVisibilityKey(container);
              if (next[key]) delete next[key];
              else next[key] = true;
              return next;
            });
          }}
        >
          {isHidden ? "Show in Active View" : "Hide from Active View"}
        </button>
      </div>
    );
  }

  return (
    <div className="panel-section-stack">
      <section className="card">
        <div className="card-header">
          <div>
            <div className="field-label">Current application effort</div>
            <div className="field-value">{currentWork.title}</div>
          </div>
        </div>
        <div className="composer-stage-strip" role="status" aria-live="polite">
          <div className="composer-stage-strip__header">
            <span className="field-label">Current workflow step</span>
            <span className="pill ghost">{stageSummary.label}</span>
          </div>
          <p className="composer-stage-strip__explanation">{stageSummary.explanation}</p>
          <p className="composer-stage-strip__next-step">
            <strong>Next:</strong> {stageSummary.nextStep}
          </p>
        </div>
        <div className="detail-grid">
          <div><div className="field-label">Overall state</div><div className="field-value">{titleCaseLabel(currentWork.statusLabel)}</div></div>
          <div><div className="field-label">Selected item</div><div className="field-value">{currentContainer ? `${currentContainer.kind === "application" ? "Application" : "Application plan"} · ${currentContainer.title}` : "No application effort selected"}</div></div>
          <div><div className="field-label">Latest activity</div><div className="field-value">{formatPanelTimestamp(currentWork.latestActivityAt)}</div></div>
        </div>
        <p className="muted" style={{ marginTop: 12 }}>{currentWork.latestResult}</p>
        {actionableBreadcrumbs.length ? (
          <div className="inline-action-row" style={{ flexWrap: "wrap", marginTop: 8 }}>
            {actionableBreadcrumbs.map((crumb, index) => (
              <button
                key={`${crumb.kind}:${crumb.id || index}`}
                type="button"
                className="ghost sm"
                onClick={() => {
                  if (crumb.kind === "factory" && crumb.id) openComposer({ factory_key: crumb.id });
                  else if (crumb.kind === "application_plan" && crumb.id) openComposer({ application_plan_id: crumb.id });
                  else if (crumb.kind === "application" && crumb.id) openComposer({ application_id: crumb.id });
                  else if (crumb.kind === "goal" && crumb.id) openComposer({ goal_id: crumb.id });
                  else if (crumb.kind === "thread" && crumb.id) openComposer({ thread_id: crumb.id });
                }}
              >
                {crumb.label}
              </button>
            ))}
          </div>
        ) : null}
        <div className="inline-action-row" style={{ marginTop: 12, flexWrap: "wrap" }}>
          {currentPlan ? (
            <button type="button" className="ghost sm" disabled={currentPlan.status === "applied"} onClick={() => handleApplyPlan(currentPlan.id)}>
              Apply Plan
            </button>
          ) : null}
          {currentGoal ? (
            <button
              type="button"
              className="ghost sm"
              disabled={!recommendation}
              onClick={() => recommendation && handleApproveNextSlice(currentGoal, String(recommendation.recommendation_id || ""))}
            >
              Approve Next Slice
            </button>
          ) : null}
          {currentThread ? (
            <button type="button" className="ghost sm" onClick={() => onOpenPanel("thread_detail", { thread_id: currentThread.id })}>
              Review Work Items
            </button>
          ) : null}
        </div>
        <p className="muted small" style={{ marginTop: 8 }}>{latestQuickActionReason}</p>
        {!currentContainer ? (
          <p className="muted small" style={{ marginTop: 8 }}>
            Composer is not focused on a single effort yet. Choose one from the list below to see its work goals, execution threads, and next steps.
          </p>
        ) : null}
        {currentContainer ? renderLifecycleActions(currentContainer, { compact: true }) : null}
        {message ? <InlineMessage tone="info" title="Composer" body={message} /> : null}
      </section>

      <section className="card">
        <div className="card-header">
          <div>
            <div className="field-label">Application efforts</div>
            <div className="field-value">Choose the application or plan you want to continue</div>
          </div>
        </div>
        <p className="muted" style={{ marginBottom: 12 }}>
          Composer groups work by application effort first so each work goal and execution thread is shown under the application or plan it belongs to.
        </p>
        <div className="inline-action-row" style={{ marginBottom: 12, flexWrap: "wrap" }}>
          {(["active", "failed", "archived", "all"] as ComposerContainerFilter[]).map((filter) => (
            <button
              key={filter}
              type="button"
              className={effortFilter === filter ? "primary sm" : "ghost sm"}
              aria-pressed={effortFilter === filter}
              onClick={() => setEffortFilter(filter)}
            >
              {filter === "active" ? "Active" : filter === "failed" ? "Failed" : filter === "archived" ? "Archived" : "All"} ({visibleEffortCount(filter)})
            </button>
          ))}
        </div>
        <div className="composer-effort-grid">
          {filteredContainers.map((container) => (
            <article
              key={`${container.kind}:${container.id}`}
              className={`composer-effort-card${container.isCurrent ? " is-current" : ""}`}
            >
              <div className="composer-effort-header">
                <div>
                  <div className="field-label">{container.kind === "application" ? "Application" : "Application plan"}</div>
                  <h3>{container.title}</h3>
                </div>
                <div className="composer-effort-badges">
                  <span className="pill">{container.statusLabel}</span>
                  <span className="pill ghost">{container.recencyLabel}</span>
                  {container.isSuperseded ? <span className="pill ghost">Superseded</span> : null}
                  {isEffortHidden(container) ? <span className="pill ghost">Hidden</span> : null}
                </div>
              </div>
              <p className="composer-effort-summary">{container.promptSummary}</p>
              <div className="composer-effort-meta">
                <span><strong>Updated</strong> {formatPanelTimestamp(container.latestActivityAt)}</span>
                <span><strong>Work goals</strong> {container.goalCount}</span>
                <span><strong>Execution threads</strong> {container.threadCount}</span>
              </div>
              <p className="muted small">{container.latestResult}</p>
              {container.kind === "application" ? (
                <div className="composer-effort-children">
                  <div className="field-label">Work goals for this application</div>
                  {container.goals.length ? (
                    <ul className="detail-list composer-effort-goal-list">
                      {container.goals.slice(0, 4).map((goal) => (
                        <li key={goal.id}>
                          <div className="composer-effort-goal-copy">
                            <strong>{goal.title}</strong> · {formatComposerGoalProgressStatus(goal.goal_progress_status || goal.planning_status || "planned")} · {formatComposerCountLabel(goal.threads.length, "execution thread")}
                          </div>
                          <div className="inline-action-row composer-effort-goal-actions">
                            <button
                              type="button"
                              className="ghost sm"
                              onClick={() => openComposer({ application_id: container.id, goal_id: goal.id })}
                            >
                              Open goal
                            </button>
                          </div>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="muted small">
                      {container.goalCount > 0
                        ? "This application already has work goals, but you need to open the effort to inspect them in detail."
                        : "No work goals are attached yet."}
                    </p>
                  )}
                </div>
              ) : null}
              <div className="inline-action-row" style={{ marginTop: 12 }}>
                <button
                  type="button"
                  className="ghost sm"
                  disabled={container.isCurrent}
                  title={container.isCurrent ? "This application effort is already selected." : undefined}
                  onClick={() => openComposer(container.selectionParams)}
                >
                  {container.isCurrent ? "Current effort" : "Open effort"}
                </button>
              </div>
              {renderLifecycleActions(container)}
            </article>
          ))}
          {!filteredContainers.length ? (
            <p className="muted">
              {effortFilter === "active"
                ? "No current application efforts are visible. Switch filters to inspect archived or older blocked work."
                : effortFilter === "failed"
                  ? "No blocked or failed efforts are currently visible."
                  : effortFilter === "archived"
                    ? "No archived efforts are currently visible."
                    : "No application efforts have been created in this workspace yet."}
            </p>
          ) : null}
        </div>
      </section>

      {composerView.unlinkedGoals.length || composerView.unlinkedThreads.length ? (
        <section className="card">
          <div className="card-header">
            <div>
              <div className="field-label">Unlinked work</div>
              <div className="field-value">Older coordination items that are not attached to a current application effort</div>
            </div>
          </div>
          <p className="muted" style={{ marginBottom: 12 }}>
            These items could not be attached to a durable application effort from the current payload, so Composer keeps them separate instead of implying they belong to the selected application.
          </p>
          {composerView.unlinkedGoals.length ? (
            <>
              <div className="field-label">Work goals</div>
              <div className="canvas-table-wrap">
                <table className="canvas-table">
                  <thead>
                    <tr>
                      <th>Goal</th>
                      <th>Status</th>
                      <th>Updated</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {composerView.unlinkedGoals.map((goal) => (
                      <tr key={goal.id}>
                        <td>{goal.title}</td>
                        <td>{formatComposerGoalProgressStatus(goal.goal_progress_status || goal.planning_status)}</td>
                        <td>{formatPanelTimestamp(goal.updated_at)}</td>
                        <td><button type="button" className="ghost sm" onClick={() => openComposer({ goal_id: goal.id })}>Open goal</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
          {composerView.unlinkedThreads.length ? (
            <>
              <div className="field-label" style={{ marginTop: 12 }}>Execution threads</div>
              <div className="canvas-table-wrap">
                <table className="canvas-table">
                  <thead>
                    <tr>
                      <th>Thread</th>
                      <th>Status</th>
                      <th>Goal</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {composerView.unlinkedThreads.map((thread) => (
                      <tr key={thread.id}>
                        <td>{thread.title}</td>
                        <td>{formatComposerThreadStatus(thread.status)}</td>
                        <td>{thread.goal_title || "—"}</td>
                        <td><button type="button" className="ghost sm" onClick={() => openComposer({ goal_id: thread.goal_id || undefined, thread_id: thread.id })}>Open thread</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
        </section>
      ) : null}

      {showPlanningTools && (
        <section className="card">
          <div className="field-label">Start a new application plan</div>
          <p className="muted small" style={{ marginTop: 8, marginBottom: 12 }}>
            Describe what you want to build. Composer will turn that request into a reviewable implementation plan.
          </p>
          <textarea
            className="input"
            value={objective}
            onChange={(event) => setObjective(event.target.value)}
            placeholder="Describe the application you want Xyn to plan."
            rows={4}
          />
          <div className="inline-action-row" style={{ marginTop: 12 }}>
            <button type="button" className="ghost sm" onClick={() => handleGeneratePlan(selectedFactory?.key)}>
              Build plan
            </button>
          </div>
        </section>
      )}

      {showPlanningTools && (
        <section className="card">
          <div className="field-label">Starting templates</div>
          <p className="muted small" style={{ marginTop: 8, marginBottom: 12 }}>
            Starting templates help Composer choose the right structure for a new application before detailed planning begins.
          </p>
          <div className="canvas-table-wrap">
            <table className="canvas-table">
              <thead>
                <tr>
                  <th>Template</th>
                  <th>Description</th>
                  <th>Best For</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {payload.factory_catalog.map((factory) => (
                  <tr key={factory.key}>
                    <td>{factory.name}</td>
                    <td>{factory.description}</td>
                    <td>{factory.intended_use_case || "—"}</td>
                    <td>
                      <button type="button" className="ghost sm" onClick={() => openComposer({ factory_key: factory.key })}>
                        Use template
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {currentPlan ? (
        <section className="card">
          <div className="card-header"><div><div className="field-label">Selected application plan</div></div></div>
          <p className="muted small" style={{ marginTop: 0, marginBottom: 12 }}>
            This is the reviewable plan for the selected application effort. Review it, then apply it when you are ready to create durable work.
          </p>
          <div className="detail-grid">
            <div><div className="field-label">Plan</div><div className="field-value">{currentPlan.name}</div></div>
            <div><div className="field-label">Starting template</div><div className="field-value">{currentPlan.factory?.name || currentPlan.source_factory_key}</div></div>
            <div><div className="field-label">Status</div><div className="field-value">{formatComposerPlanningStatus(currentPlan.status)}</div></div>
            <div><div className="field-label">Planned work goals</div><div className="field-value">{currentPlanGoals.length}</div></div>
          </div>
          <p className="muted" style={{ marginTop: 12 }}>{currentPlan.summary}</p>
          <div className="inline-action-row" style={{ marginTop: 12 }}>
            <button type="button" className="ghost sm" disabled={currentPlan.status === "applied"} onClick={() => handleApplyPlan(currentPlan.id)}>
              Apply plan
            </button>
          </div>
          {currentContainer?.kind === "application_plan" ? renderLifecycleActions(currentContainer) : null}
        </section>
      ) : null}

      {currentApplication ? (
        <section className="card">
          <div className="card-header"><div><div className="field-label">Selected application overview</div></div></div>
          <p className="muted small" style={{ marginTop: 0, marginBottom: 12 }}>
            This is the currently selected application effort and its overall coordination state.
          </p>
          <div className="detail-grid">
            <div><div className="field-label">Application</div><div className="field-value">{currentApplication.name}</div></div>
            <div><div className="field-label">Starting template</div><div className="field-value">{currentApplication.source_factory_key}</div></div>
            <div><div className="field-label">Status</div><div className="field-value">{titleCaseLabel(currentContainer?.statusLabel || currentApplication.status)}</div></div>
            <div><div className="field-label">Work goals</div><div className="field-value">{currentApplication.goals.length}</div></div>
          </div>
          {currentApplication.portfolio_state?.recommended_goal ? (
            <InlineMessage
              tone="info"
              title={`Recommended work goal: ${currentApplication.portfolio_state.recommended_goal.title}`}
              body={currentApplication.portfolio_state.recommended_goal.summary}
            />
          ) : null}
          {currentApplication.portfolio_state?.recommended_goal?.goal_id ? (
            <div className="inline-action-row" style={{ marginTop: 12, flexWrap: "wrap" }}>
              <button
                type="button"
                className="ghost sm"
                onClick={() =>
                  openComposer({
                    application_id: currentApplication.id,
                    goal_id: currentApplication.portfolio_state?.recommended_goal?.goal_id,
                  })}
              >
                Open recommended goal
              </button>
            </div>
          ) : null}
          {currentContainer?.kind === "application" ? renderLifecycleActions(currentContainer) : null}
        </section>
      ) : null}

      {selectedContainerGoals.length ? (
        <section className="card">
          <div className="field-label">Work goals for this application</div>
          <p className="muted small" style={{ marginTop: 8, marginBottom: 12 }}>
            Work goals break the application effort into meaningful outcomes. Open one to review recommendations and next steps.
          </p>
          <div className="canvas-table-wrap">
            <table className="canvas-table">
              <thead>
                <tr>
                  <th>Work goal</th>
                  <th>Planning</th>
                  <th>Progress</th>
                  <th>Threads</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {selectedContainerGoals.map((goal) => (
                  <tr key={goal.id}>
                    <td>{goal.title}</td>
                    <td>{formatComposerPlanningStatus(goal.planning_status)}</td>
                    <td>{goal.goal_progress_status ? formatComposerGoalProgressStatus(goal.goal_progress_status) : "Not started"}</td>
                    <td>{goal.threads.length || goal.thread_count}</td>
                    <td>
                      <button
                        type="button"
                        className="ghost sm"
                        disabled={currentGoalId === goal.id}
                        title={currentGoalId === goal.id ? "This goal is already focused." : undefined}
                        onClick={() => openComposer({ application_id: currentApplication?.id, goal_id: goal.id })}
                      >
                        {currentGoalId === goal.id ? "Current goal" : "Open goal"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {currentGoal ? (
        <section className="card">
          <div className="card-header"><div><div className="field-label">Selected work goal</div></div></div>
          <p className="muted small" style={{ marginTop: 0, marginBottom: 12 }}>
            This section explains the current goal, how far it has progressed, and the next slice of work Composer recommends.
          </p>
          <div className="detail-grid">
            <div><div className="field-label">Work goal</div><div className="field-value">{currentGoal.title}</div></div>
            <div><div className="field-label">Planning status</div><div className="field-value">{formatComposerPlanningStatus(currentGoal.planning_status)}</div></div>
            <div><div className="field-label">Progress</div><div className="field-value">{currentGoal.goal_progress?.goal_progress_status ? formatComposerGoalProgressStatus(currentGoal.goal_progress.goal_progress_status) : "Not started"}</div></div>
            <div><div className="field-label">Execution threads</div><div className="field-value">{currentGoal.threads.length}</div></div>
          </div>
          {recommendation ? (
            <InlineMessage
              tone="info"
              title={`Recommended next slice${recommendation.thread_title ? `: ${recommendation.thread_title}` : ""}`}
              body={recommendation.reasoning_summary || recommendation.summary || ""}
            />
          ) : null}
          <div className="inline-action-row" style={{ marginTop: 12 }}>
            <button
              type="button"
              className="ghost sm"
              disabled={!recommendation}
              onClick={() => recommendation && handleApproveNextSlice(currentGoal, String(recommendation.recommendation_id || ""))}
            >
              Approve next slice
            </button>
          </div>
        </section>
      ) : null}

      {selectedContainerThreads.length ? (
        <section className="card">
          <div className="field-label">Execution threads for this application</div>
          <p className="muted small" style={{ marginTop: 8, marginBottom: 12 }}>
            Execution threads organize the ongoing implementation work for this application. Open one to inspect work items and dispatch status.
          </p>
          <div className="canvas-table-wrap">
            <table className="canvas-table">
              <thead>
                <tr>
                  <th>Execution thread</th>
                  <th>Status</th>
                  <th>Ready</th>
                  <th>Blocked</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {selectedContainerThreads.map((thread) => (
                  <tr key={thread.id}>
                    <td>{thread.title}</td>
                    <td>{formatComposerThreadStatus(thread.status)}</td>
                    <td>{thread.queued_work_items}</td>
                    <td>{thread.awaiting_review_work_items + thread.failed_work_items}</td>
                    <td>
                      <button
                        type="button"
                        className="ghost sm"
                        disabled={currentThreadId === thread.id}
                        title={currentThreadId === thread.id ? "This thread is already focused." : undefined}
                        onClick={() =>
                          openComposer({
                            application_id: currentApplication?.id || currentGoal?.application_id || undefined,
                            goal_id: currentGoal?.id || thread.goal_id || undefined,
                            thread_id: thread.id,
                          })
                        }
                      >
                        {currentThreadId === thread.id ? "Current thread" : "Open thread"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {currentGoalThreads.length ? (
        <section className="card">
          <div className="field-label">Execution threads for this work goal</div>
          <p className="muted small" style={{ marginTop: 8, marginBottom: 12 }}>
            These are the execution threads contributing to the selected work goal.
          </p>
          <div className="canvas-table-wrap">
            <table className="canvas-table">
              <thead>
                <tr>
                  <th>Execution thread</th>
                  <th>Status</th>
                  <th>Ready</th>
                  <th>Blocked</th>
                </tr>
              </thead>
              <tbody>
                {currentGoalThreads.map((thread) => (
                  <tr key={thread.id}>
                    <td>{thread.title}</td>
                    <td>{formatComposerThreadStatus(thread.status)}</td>
                    <td>{thread.queued_work_items}</td>
                    <td>{thread.awaiting_review_work_items + thread.failed_work_items}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {currentThread ? (
        <section className="card">
          <div className="card-header"><div><div className="field-label">Selected execution thread</div></div></div>
          <p className="muted small" style={{ marginTop: 0, marginBottom: 12 }}>
            This thread shows the current line of implementation work, whether it is moving, and what you can do next.
          </p>
          <div className="detail-grid">
            <div><div className="field-label">Execution thread</div><div className="field-value">{currentThread.title}</div></div>
            <div><div className="field-label">Status</div><div className="field-value">{formatComposerThreadStatus(currentThread.status)}</div></div>
            <div><div className="field-label">Completed</div><div className="field-value">{currentThread.work_items_completed}</div></div>
            <div><div className="field-label">Blocked</div><div className="field-value">{currentThread.work_items_blocked}</div></div>
          </div>
          {threadDiagnosticSummary ? (
            <InlineMessage tone="info" title="Execution thread summary" body={threadDiagnosticSummary} />
          ) : null}
          {threadActionGuidance ? (
            <InlineMessage tone="warn" title="Review Required Before Resuming" body={threadActionGuidance} />
          ) : null}
          <div className="inline-action-row" style={{ marginTop: 12 }}>
            <button
              type="button"
              className="ghost sm"
              disabled={currentThread.status === "active"}
              title={currentThread.status === "active" ? "This thread is already active." : undefined}
              onClick={() => handleThreadReview(currentThread, "resume_thread")}
            >
              Resume thread
            </button>
            <button
              type="button"
              className="ghost sm"
              disabled={currentThread.status !== "active" || threadNeedsBriefReview}
              title={
                threadNeedsBriefReview
                  ? "Review the blocking execution brief before queueing the next slice."
                  : currentThread.status !== "active"
                    ? "Queueing the next slice requires an active thread."
                    : undefined
              }
              onClick={() => handleThreadReview(currentThread, "queue_next_slice")}
            >
              Queue next slice
            </button>
            <button
              type="button"
              className="ghost sm"
              disabled={currentThread.status === "completed"}
              title={currentThread.status === "completed" ? "This thread is already completed." : undefined}
              onClick={() => handleThreadReview(currentThread, "mark_thread_completed")}
            >
              Mark thread completed
            </button>
            <button type="button" className="ghost sm" onClick={() => onOpenPanel("thread_detail", { thread_id: currentThread.id })}>
              Review work items
            </button>
          </div>
        </section>
      ) : null}

      {payload.portfolio_context ? (
        <section className="card">
          <div className="field-label">Other related work</div>
          <p className="muted small" style={{ marginTop: 8, marginBottom: 12 }}>
            This section shows nearby work that may affect the selected application effort, without implying it is the current focus.
          </p>
          <div className="detail-grid">
            <div><div className="field-label">Work goals</div><div className="field-value">{payload.portfolio_context.goals.length}</div></div>
            <div><div className="field-label">Insights</div><div className="field-value">{portfolioInsights.length}</div></div>
            <div><div className="field-label">Recommended work goal</div><div className="field-value">{payload.portfolio_context.recommended_goal?.title || "—"}</div></div>
          </div>
        </section>
      ) : null}
    </div>
  );
}

const PANEL_TITLES: Record<ConsolePanelKey, string> = {
  platform_settings: "Platform Settings",
  composer_detail: "Composer",
  workspaces: "Workspaces",
  goal_list: "Goals",
  goal_detail: "Goal",
  application_plan_detail: "Application Plan",
  application_detail: "Application",
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
  onOpenPanel,
  onClosePanel,
  onContextChange,
}: {
  panel: ConsolePanelSpec | null;
  workspaceId: string;
  workspaceName?: string;
  workspaceColor?: string;
  onOpenPanel: (panel: ConsolePanelSpec) => void;
  onClosePanel?: () => void;
  onContextChange?: ContextEmitter;
}) {
  const [resolvedTitle, setResolvedTitle] = useState("");
  const [systemReadiness, setSystemReadiness] = useState<SystemReadinessResponse | null>(null);
  useEffect(() => {
    setResolvedTitle("");
  }, [panel?.panel_id, panel?.key]);

  useEffect(() => {
    let active = true;
    getSystemReadiness()
      .then((next) => {
        if (active) setSystemReadiness(next);
      })
      .catch(() => {
        if (active) setSystemReadiness(null);
      });
    return () => {
      active = false;
    };
  }, [workspaceId]);

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
          factoryKey={String(panel.params?.factory_key || "") || undefined}
          applicationPlanId={String(panel.params?.application_plan_id || "") || undefined}
          applicationId={String(panel.params?.application_id || "") || undefined}
          goalId={String(panel.params?.goal_id || "") || undefined}
          threadId={String(panel.params?.thread_id || "") || undefined}
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

    if (panel.key === "goal_list") {
      return <GoalListPanel workspaceId={workspaceId} onOpenPanel={openPanel} onTitleChange={setResolvedTitle} />;
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
      <div>
        <div className="card ems-panel-host">
          <PlatformSettingsPanel
            initialSection={String(panel.params?.section || "")}
            onSectionChange={(next) => {
              if (panel.params) panel.params.section = next;
            }}
          />
        </div>
        <SystemReadinessBanner readiness={systemReadiness} />
      </div>
    );
  }

  return (
    <div>
      <div className="card ems-panel-host">{content || <p className="muted">Unknown panel.</p>}</div>
      <SystemReadinessBanner readiness={systemReadiness} />
    </div>
  );
}
