import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import InlineMessage from "../../components/InlineMessage";
import { listAppJobs } from "../../api/xyn";
import type { AppJob } from "../../api/types";
import WorkspaceContextBar from "../components/common/WorkspaceContextBar";
import { toWorkspacePath } from "../routing/workspaceRouting";

function formatDate(value?: string): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

export default function JobsListPage({
  workspaceId,
  workspaceName,
  workspaceColor,
}: {
  workspaceId: string;
  workspaceName: string;
  workspaceColor?: string;
}) {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<AppJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const columns = useMemo(() => {
    const helper = createColumnHelper<AppJob>();
    return [
      helper.accessor("type", {
        header: () => "Type",
        cell: (ctx) => <strong>{ctx.getValue()}</strong>,
      }),
      helper.accessor("status", {
        header: () => "Status",
        cell: (ctx) => <span className="chip">{ctx.getValue()}</span>,
      }),
      helper.accessor("created_at", {
        header: () => "Created",
        cell: (ctx) => formatDate(ctx.getValue()),
      }),
      helper.accessor("updated_at", {
        header: () => "Updated",
        cell: (ctx) => formatDate(ctx.getValue()),
      }),
    ] as ColumnDef<AppJob>[];
  }, []);

  const table = useReactTable({
    data: jobs,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <>
      <WorkspaceContextBar workspaceName={workspaceName} workspaceColor={workspaceColor} />
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
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <th key={header.id}>{header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}</th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr key={row.id} onClick={() => navigate(toWorkspacePath(workspaceId, `jobs/${row.original.id}`))}>
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                  ))}
                </tr>
              ))}
              {!loading && jobs.length === 0 && (
                <tr>
                  <td colSpan={columns.length} className="muted">
                    No jobs found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
