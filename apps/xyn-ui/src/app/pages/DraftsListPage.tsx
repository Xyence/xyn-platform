import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import InlineMessage from "../../components/InlineMessage";
import { listAppIntentDrafts } from "../../api/xyn";
import type { AppIntentDraft } from "../../api/types";
import WorkspaceContextBar from "../components/common/WorkspaceContextBar";
import { toWorkspacePath } from "../routing/workspaceRouting";

function formatDate(value?: string): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

export default function DraftsListPage({
  workspaceId,
  workspaceName,
  workspaceColor,
}: {
  workspaceId: string;
  workspaceName: string;
  workspaceColor?: string;
}) {
  const navigate = useNavigate();
  const [drafts, setDrafts] = useState<AppIntentDraft[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!workspaceId) {
      setDrafts([]);
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const payload = await listAppIntentDrafts(workspaceId);
      setDrafts(payload);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns = useMemo<ColumnDef<AppIntentDraft>[]>(() => {
    const helper = createColumnHelper<AppIntentDraft>();
    return [
      helper.accessor("title", {
        header: () => "Title",
        cell: (ctx) => <strong>{ctx.getValue() || "Untitled Draft"}</strong>,
      }),
      helper.accessor("type", {
        header: () => "Type",
        cell: (ctx) => ctx.getValue() || "app_intent",
      }),
      helper.accessor("status", {
        header: () => "Status",
        cell: (ctx) => <span className="chip">{ctx.getValue()}</span>,
      }),
      helper.accessor("created_by", {
        header: () => "Created By",
        cell: (ctx) => ctx.getValue() || "user",
      }),
      helper.accessor("updated_at", {
        header: () => "Updated",
        cell: (ctx) => formatDate(ctx.getValue()),
      }),
    ];
  }, []);

  const table = useReactTable({
    data: drafts,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <>
      <WorkspaceContextBar workspaceName={workspaceName} workspaceColor={workspaceColor} />
      <div className="page-header">
        <div>
          <h2>Drafts</h2>
          <p className="muted">App intent drafts in this workspace.</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" onClick={() => void load()} disabled={loading || !workspaceId}>
            Refresh
          </button>
          <button className="primary" onClick={() => navigate(toWorkspacePath(workspaceId, "drafts/new"))} disabled={!workspaceId}>
            New Draft
          </button>
        </div>
      </div>
      {!workspaceId && <InlineMessage tone="error" title="Workspace required" body="Select a workspace first." />}
      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      <section className="card">
        <div className="card-header">
          <h3>Drafts</h3>
        </div>
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
                <tr key={row.id} onClick={() => navigate(toWorkspacePath(workspaceId, `drafts/${row.original.id}`))}>
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                  ))}
                </tr>
              ))}
              {!loading && drafts.length === 0 && (
                <tr>
                  <td colSpan={columns.length} className="muted">
                    No drafts yet.
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
