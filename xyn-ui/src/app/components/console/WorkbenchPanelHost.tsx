import { useEffect, useMemo, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import {
  getAiBootstrapStatus,
  getArtifactConsoleDetailBySlug,
  getArtifactConsoleFilesBySlug,
  getEmsDatasetSchemaTable,
  getEmsRegistrationsTimeseriesCanvasTable,
  getEmsStatusRollupCanvasTable,
  getRunCanvasApi,
  listRunsCanvasApi,
  listWorkspaceArtifacts,
  listWorkspacesCanvasApi,
  queryArtifactCanvasTable,
  queryEmsDevicesCanvasTable,
  queryEmsRegistrationsCanvasTable,
} from "../../../api/xyn";
import { resolveApiBaseUrl } from "../../../api/client";
import type {
  AiBootstrapStatus,
  ArtifactCanvasTableResponse,
  ArtifactConsoleDetailResponse,
  ArtifactConsoleFileRow,
  ArtifactStructuredQuery,
  CanvasTableResponse,
  LocalProvisionResponse,
  RunDetail,
  RunSummary,
  WorkspaceSummary,
} from "../../../api/types";
import CanvasRenderer from "../../../components/canvas/CanvasRenderer";
import type { OpenDetailTarget } from "../../../components/canvas/datasetEntityRegistry";
import { toWorkspacePath } from "../../routing/workspaceRouting";

export type ConsolePanelKey =
  | "platform_settings"
  | "workspaces"
  | "runs"
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

type CanvasQuery = {
  entity: string;
  filters: Array<{ field: string; op: string; value: unknown }>;
  sort: Array<{ field: string; dir: "asc" | "desc" }>;
  limit: number;
  offset: number;
};

type ContextEmitter = (context: Record<string, unknown> | null) => void;

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
  { key: "entity_type", label: "Entity Type", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "entity_id", label: "Entity ID", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "status", label: "Status", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "summary", label: "Summary", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "created_at", label: "Created", type: "datetime", filterable: true, sortable: true },
  { key: "started_at", label: "Started", type: "datetime", filterable: true, sortable: true },
  { key: "finished_at", label: "Finished", type: "datetime", filterable: true, sortable: true },
] as const;

function toIso(value?: string | null): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toISOString();
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

function RunsPanel({
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
        setLoading(true);
        setError(null);
        const statusEq = (activeQuery.filters || []).find((entry) => entry.field === "status" && entry.op === "eq");
        const searchContains = (activeQuery.filters || []).find((entry) => entry.op === "contains" && ["summary", "entity_type", "entity_id"].includes(entry.field));
        const response = await listRunsCanvasApi(
          undefined,
          statusEq ? String(statusEq.value || "") : undefined,
          searchContains ? String(searchContains.value || "") : undefined,
          1,
          500
        );
        if (!active) return;
        const baseRows: Array<Record<string, unknown>> = (response.runs || []).map((run: RunSummary) => ({
          id: run.id,
          entity_type: run.entity_type,
          entity_id: run.entity_id,
          status: run.status,
          summary: run.summary || "",
          created_at: toIso(run.created_at),
          started_at: toIso(run.started_at),
          finished_at: toIso(run.finished_at),
        }));
        let rows = [...baseRows];
        for (const filter of activeQuery.filters || []) {
          rows = rows.filter((row) => rowMatches(row, filter, RUNS_DATASET_COLUMNS as unknown as Array<{ key: string; type: string }>));
        }
        for (const sortRow of [...(activeQuery.sort || [])].reverse()) {
          const field = String(sortRow.field || "");
          const dir = sortRow.dir === "asc" ? "asc" : "desc";
          rows.sort((left, right) => {
            const column = RUNS_DATASET_COLUMNS.find((entry) => entry.key === field);
            const cmp = compareValues(left[field], right[field], column?.type);
            return dir === "asc" ? cmp : -cmp;
          });
        }
        const offset = Math.max(0, Number(activeQuery.offset || 0));
        const limit = Math.max(1, Number(activeQuery.limit || 50));
        const paged = rows.slice(offset, offset + limit);
        const nextPayload: CanvasTableResponse = {
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
        };
        setPayload(nextPayload);
        setRowOrderIds(paged.map((row) => String(row.id || "")));
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
  }, [activeQuery]);

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

function RunDetailPanel({ runId, panel, onContextChange }: { runId: string; panel: ConsolePanelSpec | null; onContextChange?: ContextEmitter }) {
  const [payload, setPayload] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await getRunCanvasApi(runId);
        if (!active) return;
        setPayload(next);
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
  }, [runId]);

  useEffect(() => {
    if (!onContextChange || !panel?.panel_id || !payload) return;
    onContextChange({
      view_type: "detail",
      entity_type: "run",
      entity_id: payload.id,
      available_tabs: ["overview", "raw"],
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
      <p className="muted">
        {payload.id} · {payload.status}
      </p>
      <p className="muted small">
        {payload.entity_type} · {payload.entity_id}
      </p>
      {payload.summary ? <p>{payload.summary}</p> : null}
      <pre className="code-block">{JSON.stringify(payload, null, 2)}</pre>
    </div>
  );
}

function PlatformSettingsPanel({ workspaceId }: { workspaceId: string }) {
  const [workspace, setWorkspace] = useState<WorkspaceSummary | null>(null);
  const [artifacts, setArtifacts] = useState<Array<{ name?: string; slug?: string; installed_state?: string }>>([]);
  const [aiBootstrap, setAiBootstrap] = useState<AiBootstrapStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const workspaceResponse = await listWorkspacesCanvasApi();
        if (!active) return;
        const found = (workspaceResponse.workspaces || []).find((entry) => String(entry.id) === workspaceId) || null;
        setWorkspace(found);
        const aiStatus = await getAiBootstrapStatus();
        if (!active) return;
        setAiBootstrap(aiStatus.default_agent || null);
        if (workspaceId) {
          const installed = await listWorkspaceArtifacts(workspaceId);
          if (!active) return;
          setArtifacts((installed.artifacts || []).map((entry) => ({ name: entry.title || entry.name, slug: entry.slug, installed_state: entry.installed_state })));
        } else {
          setArtifacts([]);
        }
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load platform settings");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [workspaceId]);

  if (loading) return <p className="muted">Loading platform settings…</p>;
  if (error) return <p className="danger-text">{error}</p>;

  return (
    <div className="ems-panel-body">
      <h4>Platform Settings</h4>
      <p className="muted small">Workspace info, installed artifacts, and environment summary.</p>
      <div className="card">
        <p className="muted small">Workspace</p>
        <pre className="code-block">
          {JSON.stringify(
            workspace
              ? {
                  id: workspace.id,
                  slug: workspace.slug,
                  name: workspace.name,
                  org_name: workspace.org_name || workspace.name,
                  kind: workspace.kind,
                  lifecycle_stage: workspace.lifecycle_stage,
                  auth_mode: workspace.auth_mode,
                }
              : { id: workspaceId || "", status: "not found or inaccessible" },
            null,
            2
          )}
        </pre>
      </div>
      <div className="card">
        <p className="muted small">Installed artifacts</p>
        <pre className="code-block">{JSON.stringify(artifacts, null, 2)}</pre>
      </div>
      <div className="card">
        <p className="muted small">AI bootstrap</p>
        <pre className="code-block">
          {JSON.stringify(
            aiBootstrap
              ? {
                  provider: aiBootstrap.provider,
                  model: aiBootstrap.model,
                  key_present: aiBootstrap.key_present,
                  default_agent_slug: aiBootstrap.default_agent_slug,
                  last_updated: aiBootstrap.default_agent_updated_at,
                }
              : { status: "unavailable" },
            null,
            2
          )}
        </pre>
      </div>
      <div className="card">
        <p className="muted small">Environment</p>
        <pre className="code-block">
          {JSON.stringify(
            {
              api_base_url: resolveApiBaseUrl(),
              app_origin: typeof window !== "undefined" ? window.location.origin : "",
              path: typeof window !== "undefined" ? window.location.pathname : "",
              time_utc: new Date().toISOString(),
              auth_mode: import.meta.env.VITE_AUTH_MODE || "unknown",
            },
            null,
            2
          )}
        </pre>
      </div>
    </div>
  );
}

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

const PANEL_TITLES: Record<ConsolePanelKey, string> = {
  platform_settings: "Platform Settings",
  workspaces: "Workspaces",
  runs: "Runs",
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
  onOpenPanel,
  onClosePanel,
  onContextChange,
}: {
  panel: ConsolePanelSpec | null;
  workspaceId: string;
  onOpenPanel: (panel: ConsolePanelSpec) => void;
  onClosePanel?: () => void;
  onContextChange?: ContextEmitter;
}) {
  const [resolvedTitle, setResolvedTitle] = useState("");
  useEffect(() => {
    setResolvedTitle("");
  }, [panel?.panel_id, panel?.key]);

  const content = useMemo(() => {
    if (!panel) return null;
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

    if (panel.key === "platform_settings") {
      return <PlatformSettingsPanel workspaceId={String(panel.params?.workspace_id || workspaceId || "")} />;
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
              openPanel("platform_settings", { workspace_id: target.entity_id });
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

    if (panel.key === "run_detail") {
      return <RunDetailPanel runId={String(panel.params?.run_id || "")} panel={panel} onContextChange={onContextChange} />;
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

  return (
    <div className="card ems-panel-host">
      <div className="ems-panel-head">
        <h3>{humanizePanelTitle(panel, resolvedTitle)}</h3>
        {onClosePanel ? (
          <button type="button" className="ghost sm" onClick={onClosePanel} aria-label={panel.panel_type === "detail" ? "Back" : "Close"} title={panel.panel_type === "detail" ? "Back" : "Close"}>
            {panel.panel_type === "detail" ? <ArrowLeft size={14} /> : "Close"}
          </button>
        ) : null}
      </div>
      {content || <p className="muted">Unknown panel.</p>}
    </div>
  );
}
