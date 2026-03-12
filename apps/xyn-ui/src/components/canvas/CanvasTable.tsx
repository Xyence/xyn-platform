import { useEffect, useMemo, useState } from "react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type ColumnFiltersState,
  type SortingState,
} from "@tanstack/react-table";
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

function swallowHeaderPointerEvent(event: { stopPropagation: () => void }) {
  event.stopPropagation();
}

export default function CanvasTable({ payload, query, onSort, onRowActivate, onOpenDetail }: CanvasTableProps) {
  const { push } = useNotifications();
  const [selectedRowId, setSelectedRowId] = useState<string>("");
  const [activeFilterColumn, setActiveFilterColumn] = useState<string | null>(null);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnSizing, setColumnSizing] = useState<Record<string, number>>({});
  const columns = payload.dataset.columns || [];
  const rows = payload.dataset.rows || [];
  const primaryKey = payload.dataset.primary_key;
  const resolveSortingState = (sortQuery: CanvasQuery["sort"] | undefined): SortingState => {
    const field = sortQuery?.[0]?.field;
    if (!field || !columns.some((column) => column.key === field)) return [];
    return [{ id: field, desc: sortQuery?.[0]?.dir === "desc" }];
  };
  const [sorting, setSorting] = useState<SortingState>(() => resolveSortingState(query.sort));
  const currentSort = sorting[0];

  useEffect(() => {
    setSorting(resolveSortingState(query.sort));
  }, [columns, query.sort]);
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
          <div className="canvas-table-header">
            <button
              type="button"
              className={`ghost sm canvas-table-header-main${activeFilterColumn === column.key ? " is-active" : ""}`}
              onMouseDown={swallowHeaderPointerEvent}
              onPointerDown={swallowHeaderPointerEvent}
              onClick={() => {
                if (!column.filterable) return;
                setActiveFilterColumn((current) => (current === column.key ? null : column.key));
              }}
              disabled={!column.filterable}
              aria-label={column.filterable ? `Filter ${column.label}` : column.label}
            >
              <span className="canvas-table-header-label">{column.label}</span>
            </button>
            {column.sortable ? (
              <button
                type="button"
                className="ghost sm canvas-table-header-sort"
                onMouseDown={swallowHeaderPointerEvent}
                onPointerDown={swallowHeaderPointerEvent}
                onClick={() => {
                  const same = currentSort?.id === column.key;
                  const nextDesc = same ? !currentSort?.desc : false;
                  setSorting([{ id: column.key, desc: nextDesc }]);
                  onSort?.(column.key, true);
                }}
                aria-label={`Sort by ${column.label}`}
              >
                {currentSort?.id === column.key ? (currentSort?.desc ? "↓" : "↑") : "↕"}
              </button>
            ) : null}
            {activeFilterColumn === column.key && column.filterable ? (
              <input
                className="canvas-table-filter-input"
                type="text"
                autoFocus
                placeholder={`Filter ${column.label}`}
                value={String(
                  columnFilters.find((entry) => entry.id === column.key)?.value ?? ""
                )}
                onMouseDown={swallowHeaderPointerEvent}
                onPointerDown={swallowHeaderPointerEvent}
                onClick={(event) => event.stopPropagation()}
                onChange={(event) => {
                  const value = event.target.value;
                  setColumnFilters((current) => {
                    const next = current.filter((entry) => entry.id !== column.key);
                    return value.trim() ? [...next, { id: column.key, value }] : next;
                  });
                }}
              />
            ) : null}
          </div>
        ),
        cell: (context) => renderCellValue(context.getValue(), column.type),
        enableSorting: Boolean(column.sortable),
        enableColumnFilter: Boolean(column.filterable),
        filterFn: (row, id, value) => {
          const raw = row.getValue(id);
          const left = renderCellValue(raw, column.type).toLowerCase();
          const right = String(value || "").trim().toLowerCase();
          if (!right) return true;
          return left.includes(right);
        },
      })
    );
  }, [activeFilterColumn, columnFilters, columns, currentSort?.desc, currentSort?.id, onSort]);

  const table = useReactTable({
    data: rows,
    columns: defs,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    columnResizeMode: "onChange",
    state: {
      columnFilters,
      columnSizing,
      sorting,
    },
    onColumnFiltersChange: setColumnFilters,
    onColumnSizingChange: setColumnSizing,
    onSortingChange: setSorting,
    defaultColumn: {
      minSize: 120,
      size: 180,
      maxSize: 520,
    },
  });

  return (
    <div className="ems-panel-body">
      <p className="muted">
        Rows: {table.getRowModel().rows.length} / Total: {payload.dataset.total_count || 0}
      </p>
      <div className="canvas-table-wrap">
        <table className="canvas-table" role="grid">
          <colgroup>
            {table.getVisibleLeafColumns().map((column) => (
              <col key={column.id} style={{ width: column.getSize() }} />
            ))}
          </colgroup>
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const canResize = header.column.getCanResize();
                  return (
                    <th key={header.id} style={{ width: header.getSize() }}>
                      {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                      {canResize ? (
                        <div
                          role="separator"
                          aria-orientation="vertical"
                          className={`canvas-table-resizer${header.column.getIsResizing() ? " is-resizing" : ""}`}
                          onMouseDown={(event) => {
                            event.stopPropagation();
                            header.getResizeHandler()(event);
                          }}
                          onPointerDown={(event) => event.stopPropagation()}
                          onDoubleClick={() => header.column.resetSize()}
                          onTouchStart={header.getResizeHandler()}
                        />
                      ) : null}
                    </th>
                  );
                })}
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
