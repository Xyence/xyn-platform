import { useMemo, useState } from "react";
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import type { ArtifactCanvasTableResponse, ArtifactStructuredQuery, CanvasTableQuery, CanvasTableResponse } from "../../api/types";
import { useNotifications } from "../../app/state/notificationsStore";
import { getOpenDetailTarget, type OpenDetailTarget } from "./datasetEntityRegistry";

type CanvasPayload = CanvasTableResponse | ArtifactCanvasTableResponse;
type CanvasQuery = CanvasTableQuery | ArtifactStructuredQuery;

export type CanvasTableProps = {
  payload: CanvasPayload;
  query: CanvasQuery;
  onSort?: (field: string, sortable: boolean) => void;
  onRowActivate?: (rowId: string, row: Record<string, unknown>) => void;
  onOpenDetail?: (target: OpenDetailTarget, row: Record<string, unknown>) => void;
};

function formatDate(value?: string): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function renderCellValue(value: unknown, type: string): string {
  if (type === "boolean") return value ? "Yes" : "No";
  if (type === "datetime") return formatDate(String(value || ""));
  if (type === "string[]" && Array.isArray(value)) return value.join(", ");
  if (value == null || value === "") return "-";
  return String(value);
}

export default function CanvasTable({ payload, query, onSort, onRowActivate, onOpenDetail }: CanvasTableProps) {
  const { push } = useNotifications();
  const [selectedRowId, setSelectedRowId] = useState<string>("");
  const columns = payload.dataset.columns || [];
  const rows = payload.dataset.rows || [];
  const primaryKey = payload.dataset.primary_key;
  const currentSort = query.sort?.[0];
  const openDetailForRow = (row: Record<string, unknown>) => {
    const target = getOpenDetailTarget(payload.dataset.name, row, primaryKey);
    if (!target) {
      push({
        level: "warning",
        title: "Detail unavailable",
        message: `Cannot open detail: missing primary key '${primaryKey}'.`,
      });
      return;
    }
    onOpenDetail?.(target, row);
  };

  const defs = useMemo<ColumnDef<Record<string, unknown>>[]>(() => {
    const helper = createColumnHelper<Record<string, unknown>>();
    return columns.map((column) =>
      helper.accessor((row) => row[column.key], {
        id: column.key,
        header: () => (
          <button
            type="button"
            className="ghost sm"
            onClick={() => onSort?.(column.key, Boolean(column.sortable))}
            disabled={!column.sortable}
            aria-label={`Sort by ${column.label}`}
          >
            {column.label}
            {currentSort?.field === column.key ? (currentSort?.dir === "asc" ? " ↑" : " ↓") : ""}
          </button>
        ),
        cell: (context) => renderCellValue(context.getValue(), column.type),
      })
    );
  }, [columns, currentSort?.dir, currentSort?.field, onSort]);

  const table = useReactTable({
    data: rows,
    columns: defs,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="ems-panel-body">
      <p className="muted">
        Rows: {rows.length} / Total: {payload.dataset.total_count || 0}
      </p>
      <div className="canvas-table-wrap">
        <table className="canvas-table" role="grid">
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
            {table.getRowModel().rows.map((row) => {
              const rowId = String(row.original[primaryKey] || row.id);
              return (
                <tr
                  key={row.id}
                  className={selectedRowId === rowId ? "is-selected" : ""}
                  onClick={() => {
                    setSelectedRowId(rowId);
                    onRowActivate?.(rowId, row.original);
                    if (onOpenDetail) openDetailForRow(row.original);
                  }}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <details>
        <summary className="muted small">Query metadata</summary>
        <pre className="code-block">{JSON.stringify(payload.query || query, null, 2)}</pre>
      </details>
    </div>
  );
}
