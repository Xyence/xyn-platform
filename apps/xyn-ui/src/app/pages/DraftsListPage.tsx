import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import CanvasTable from "../../components/canvas/CanvasTable";
import { listAppIntentDrafts } from "../../api/xyn";
import type { AppIntentDraft, CanvasTableQuery, CanvasTableResponse } from "../../api/types";
import WorkspaceContextBar from "../components/common/WorkspaceContextBar";
import { toWorkspacePath } from "../routing/workspaceRouting";

export default function DraftsListPage({
  workspaceId,
  workspaceName,
  workspaceColor,
  workspaceBarVariant = "default",
  onSelectDraft,
}: {
  workspaceId: string;
  workspaceName: string;
  workspaceColor?: string;
  workspaceBarVariant?: "default" | "compact";
  onSelectDraft?: (draftId: string) => void;
}) {
  const navigate = useNavigate();
  const [drafts, setDrafts] = useState<AppIntentDraft[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState<CanvasTableQuery>({
    entity: "drafts",
    filters: [],
    sort: [{ field: "updated_at", dir: "desc" }],
    limit: 50,
    offset: 0,
  });

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

  const payload = useMemo<CanvasTableResponse>(
    () => ({
      type: "canvas.table",
      title: "Drafts",
      dataset: {
        name: "drafts",
        primary_key: "id",
        columns: [
          { key: "title", label: "Title", type: "string", sortable: true, filterable: true, searchable: true },
          { key: "type", label: "Type", type: "string", sortable: true, filterable: true, searchable: true },
          { key: "status", label: "Status", type: "string", sortable: true, filterable: true, searchable: true },
          { key: "created_by", label: "Created By", type: "string", sortable: true, filterable: true, searchable: true },
          { key: "updated_at", label: "Updated", type: "datetime", sortable: true, filterable: true },
        ],
        rows: drafts.map((draft) => ({
          id: draft.id,
          title: draft.title || "Untitled Draft",
          type: draft.type || "app_intent",
          status: draft.status,
          created_by: draft.created_by || "user",
          updated_at: draft.updated_at,
        })),
        total_count: drafts.length,
      },
      query,
    }),
    [drafts, query]
  );

  return (
    <>
      <WorkspaceContextBar workspaceName={workspaceName} workspaceColor={workspaceColor} variant={workspaceBarVariant} />
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
        {!loading && drafts.length === 0 ? <p className="muted">No drafts yet.</p> : null}
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
            onSelectDraft ? onSelectDraft(rowId) : navigate(toWorkspacePath(workspaceId, `drafts/${rowId}`));
          }}
        />
      </section>
    </>
  );
}
