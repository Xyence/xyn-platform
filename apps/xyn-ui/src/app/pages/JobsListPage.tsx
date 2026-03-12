import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import CanvasTable from "../../components/canvas/CanvasTable";
import { listAppJobs } from "../../api/xyn";
import type { AppJob, CanvasTableResponse, CanvasTableQuery } from "../../api/types";
import WorkspaceContextBar from "../components/common/WorkspaceContextBar";
import { toWorkspacePath } from "../routing/workspaceRouting";

export default function JobsListPage({
  workspaceId,
  workspaceName,
  workspaceColor,
  workspaceBarVariant = "default",
  onSelectJob,
}: {
  workspaceId: string;
  workspaceName: string;
  workspaceColor?: string;
  workspaceBarVariant?: "default" | "compact";
  onSelectJob?: (jobId: string) => void;
}) {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<AppJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState<CanvasTableQuery>({
    entity: "jobs",
    filters: [],
    sort: [{ field: "updated_at", dir: "desc" }],
    limit: 50,
    offset: 0,
  });

  const load = useCallback(async () => {
    if (!workspaceId) {
      setJobs([]);
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const payload = await listAppJobs(workspaceId);
      setJobs(payload);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const payload = useMemo<CanvasTableResponse>(
    () => ({
      type: "canvas.table",
      title: "Jobs",
      dataset: {
        name: "jobs",
        primary_key: "id",
        columns: [
          { key: "type", label: "Type", type: "string", sortable: true, filterable: true, searchable: true },
          { key: "status", label: "Status", type: "string", sortable: true, filterable: true, searchable: true },
          { key: "created_at", label: "Created", type: "datetime", sortable: true, filterable: true },
          { key: "updated_at", label: "Updated", type: "datetime", sortable: true, filterable: true },
        ],
        rows: jobs.map((job) => ({
          id: job.id,
          type: job.type,
          status: job.status,
          created_at: job.created_at,
          updated_at: job.updated_at,
        })),
        total_count: jobs.length,
      },
      query,
    }),
    [jobs, query]
  );

  return (
    <>
      <WorkspaceContextBar workspaceName={workspaceName} workspaceColor={workspaceColor} variant={workspaceBarVariant} />
      <div className="page-header">
        <div>
          <h2>Jobs</h2>
          <p className="muted">Queued and running draft jobs.</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" onClick={() => void load()} disabled={loading || !workspaceId}>
            Refresh
          </button>
        </div>
      </div>
      {!workspaceId && <InlineMessage tone="error" title="Workspace required" body="Select a workspace first." />}
      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      <section className="card">
        {!loading && jobs.length === 0 ? <p className="muted">No jobs found.</p> : null}
        <CanvasTable
          payload={payload}
          query={query}
          onSort={(field, sortable) => {
            if (!sortable) return;
            setQuery((current) => {
              const same = current.sort?.[0]?.field === field;
              const dir = same && current.sort?.[0]?.dir === "asc" ? "desc" : "asc";
              return { ...current, sort: [{ field, dir }] };
            });
          }}
          onRowActivate={(rowId) => {
            onSelectJob ? onSelectJob(rowId) : navigate(toWorkspacePath(workspaceId, `jobs/${rowId}`));
          }}
        />
      </section>
    </>
  );
}
