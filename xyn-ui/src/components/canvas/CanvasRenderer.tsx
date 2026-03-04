import type { ArtifactCanvasTableResponse, ArtifactStructuredQuery, CanvasTableQuery, CanvasTableResponse } from "../../api/types";
import CanvasEmpty from "./CanvasEmpty";
import CanvasJson from "./CanvasJson";
import CanvasTable from "./CanvasTable";
import type { OpenDetailTarget } from "./datasetEntityRegistry";

type CanvasPayload = CanvasTableResponse | ArtifactCanvasTableResponse;
type CanvasQuery = CanvasTableQuery | ArtifactStructuredQuery;

export type CanvasRendererProps = {
  payload: CanvasPayload | null;
  query: CanvasQuery;
  onSort?: (field: string, sortable: boolean) => void;
  onRowActivate?: (rowId: string, row: Record<string, unknown>) => void;
  onOpenDetail?: (target: OpenDetailTarget, row: Record<string, unknown>) => void;
};

export default function CanvasRenderer({ payload, query, onSort, onRowActivate, onOpenDetail }: CanvasRendererProps) {
  if (!payload) return <CanvasEmpty message="No rows." />;
  if (payload.type === "canvas.table") {
    return <CanvasTable payload={payload} query={query} onSort={onSort} onRowActivate={onRowActivate} onOpenDetail={onOpenDetail} />;
  }
  return <CanvasJson value={payload} />;
}
