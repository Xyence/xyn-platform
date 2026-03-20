import { useCallback, useEffect, useMemo, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import Tabs from "../components/ui/Tabs";
import StatusPill from "../../components/StatusPill";
import {
  listSourceConnectors,
  listSourceInspections,
  listSourceMappings,
} from "../../api/xyn";
import type { SourceConnectorSummary, SourceInspectionProfile, SourceMappingRecord } from "../../api/types";

type Props = {
  workspaceId: string;
  workspaceName?: string;
};

type TabKey = "schema" | "sample" | "mapping";

const TAB_OPTIONS = [
  { value: "schema", label: "Schema" },
  { value: "sample", label: "Sample" },
  { value: "mapping", label: "Mapping" },
] as const;

function summaryValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function tableColumnsFromRows(rows: Array<Record<string, unknown>>): string[] {
  const set = new Set<string>();
  rows.forEach((row) => Object.keys(row || {}).forEach((key) => set.add(key)));
  return Array.from(set).slice(0, 12);
}

function SimpleTable({ columns, rows, emptyMessage }: { columns: string[]; rows: Array<Record<string, unknown>>; emptyMessage: string }) {
  return (
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
          {rows.map((row, idx) => (
            <tr key={String((row as { id?: string }).id || idx)}>
              {columns.map((column) => (
                <td key={column}>{summaryValue(row[column])}</td>
              ))}
            </tr>
          ))}
          {!rows.length ? (
            <tr>
              <td colSpan={Math.max(columns.length, 1)} className="muted">
                {emptyMessage}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

export default function SourceInspectionReviewPage({ workspaceId, workspaceName }: Props) {
  const [sources, setSources] = useState<SourceConnectorSummary[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState<string>("");
  const [inspections, setInspections] = useState<SourceInspectionProfile[]>([]);
  const [mappings, setMappings] = useState<SourceMappingRecord[]>([]);
  const [tab, setTab] = useState<TabKey>("schema");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSources = useCallback(async () => {
    if (!workspaceId) {
      setError("Workspace context is required to view sources.");
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const payload = await listSourceConnectors(workspaceId);
      setSources(payload.sources || []);
      if (!selectedSourceId && payload.sources && payload.sources[0]) {
        setSelectedSourceId(payload.sources[0].id);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [workspaceId, selectedSourceId]);

  const loadDetails = useCallback(async () => {
    if (!workspaceId || !selectedSourceId) {
      setInspections([]);
      setMappings([]);
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const [inspectionsPayload, mappingsPayload] = await Promise.all([
        listSourceInspections(selectedSourceId, workspaceId),
        listSourceMappings(selectedSourceId, workspaceId),
      ]);
      setInspections(inspectionsPayload.inspections || []);
      setMappings(mappingsPayload.mappings || []);
    } catch (err) {
      setError((err as Error).message);
      setInspections([]);
      setMappings([]);
    } finally {
      setLoading(false);
    }
  }, [selectedSourceId, workspaceId]);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  useEffect(() => {
    void loadDetails();
  }, [loadDetails]);

  const selectedSource = useMemo(
    () => sources.find((item) => item.id === selectedSourceId) || null,
    [sources, selectedSourceId]
  );
  const latestInspection = inspections[0] || null;
  const sampleMetadata = (latestInspection?.sample_metadata || {}) as Record<string, unknown>;
  const profileSummary = (sampleMetadata.profile_summary || {}) as Record<string, unknown>;
  const sampleRows = (Array.isArray(sampleMetadata.sample_rows) ? sampleMetadata.sample_rows : []) as Array<Record<string, unknown>>;
  const geometrySummary = (sampleMetadata.geometry_summary || null) as Record<string, unknown> | null;

  const discoveredFields = (latestInspection?.discovered_fields || []) as Array<Record<string, unknown>>;
  const schemaRows = discoveredFields.map((field, index) => ({
    name: String(field.name || field.key || field.field || `field_${index}`),
    type: String(field.type || field.kind || ""),
    description: String(field.description || field.label || ""),
  }));

  const sampleColumns = tableColumnsFromRows(sampleRows);
  const mappingCurrent = mappings.find((item) => item.is_current) || mappings[0] || null;
  const mappingRows = mappingCurrent
    ? Object.entries(mappingCurrent.field_mapping || {}).map(([sourceField, targetField]) => ({
        source_field: sourceField,
        target_field: targetField,
      }))
    : [];

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Source Inspection Review</h2>
          <p className="muted">
            {workspaceName ? `${workspaceName} ·` : ""} Review inspection metadata for source configuration.
          </p>
        </div>
        <div className="header-actions">
          <button className="ghost" onClick={() => void loadSources()} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {error ? <InlineMessage tone="error" title="Source inspection load failed" body={error} /> : null}

      <section className="card">
        <div className="detail-grid">
          <div>
            <div className="field-label">Workspace</div>
            <div className="field-value">{workspaceName || "—"}</div>
          </div>
          <div>
            <div className="field-label">Source</div>
            <div className="field-value">
              <select
                className="input"
                value={selectedSourceId}
                onChange={(event) => setSelectedSourceId(event.target.value)}
                disabled={loading || sources.length === 0}
              >
                {sources.length === 0 ? <option value="">No sources</option> : null}
                {sources.map((source) => (
                  <option key={source.id} value={source.id}>
                    {source.name} ({source.key})
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <div className="field-label">Latest Inspection</div>
            <div className="field-value">
              {latestInspection ? (
                <StatusPill status={latestInspection.status} label={latestInspection.status} />
              ) : (
                "—"
              )}
            </div>
          </div>
          <div>
            <div className="field-label">Detected Format</div>
            <div className="field-value">{latestInspection?.detected_format || "—"}</div>
          </div>
        </div>
      </section>

      {!latestInspection ? (
        <section className="card">
          <p className="muted">No inspections captured for this source yet.</p>
        </section>
      ) : (
        <>
          <section className="card" style={{ marginTop: 16 }}>
            <div className="detail-grid">
              <div>
                <div className="field-label">Rows</div>
                <div className="field-value">{summaryValue(profileSummary.row_count)}</div>
              </div>
              <div>
                <div className="field-label">Fields</div>
                <div className="field-value">{summaryValue(profileSummary.discovered_fields_count)}</div>
              </div>
              <div>
                <div className="field-label">Sample Rows</div>
                <div className="field-value">{summaryValue(profileSummary.has_sample_rows)}</div>
              </div>
              <div>
                <div className="field-label">Geometry</div>
                <div className="field-value">{summaryValue(profileSummary.has_geometry)}</div>
              </div>
            </div>
            {geometrySummary?.present ? (
              <div className="detail-grid" style={{ marginTop: 16 }}>
                <div>
                  <div className="field-label">Geometry Types</div>
                  <div className="field-value">{summaryValue((geometrySummary.geometry_types as string[])?.join(", "))}</div>
                </div>
                <div>
                  <div className="field-label">BBox</div>
                  <div className="field-value">{summaryValue(JSON.stringify(geometrySummary.bbox))}</div>
                </div>
                <div>
                  <div className="field-label">Centroid</div>
                  <div className="field-value">{summaryValue(JSON.stringify(geometrySummary.centroid))}</div>
                </div>
              </div>
            ) : null}
            {geometrySummary && geometrySummary.present === false && geometrySummary.errors ? (
              <div style={{ marginTop: 12 }}>
                <InlineMessage tone="warn" title="Geometry metadata unavailable" body={String((geometrySummary.errors as string[]).join(" "))} />
              </div>
            ) : null}
          </section>

          <section className="card" style={{ marginTop: 16 }}>
            <Tabs value={tab} options={TAB_OPTIONS} onChange={(next) => setTab(next)} ariaLabel="Inspection tabs" />
            {tab === "schema" ? (
              <div style={{ marginTop: 12 }}>
                <SimpleTable
                  columns={["name", "type", "description"]}
                  rows={schemaRows}
                  emptyMessage="No detected fields captured."
                />
              </div>
            ) : null}

            {tab === "sample" ? (
              <div style={{ marginTop: 12 }}>
                <SimpleTable
                  columns={sampleColumns.length ? sampleColumns : ["value"]}
                  rows={sampleRows}
                  emptyMessage="No sample rows captured."
                />
              </div>
            ) : null}

            {tab === "mapping" ? (
              <div style={{ marginTop: 12 }}>
                {mappingCurrent ? (
                  <>
                    <div className="detail-grid" style={{ marginBottom: 12 }}>
                      <div>
                        <div className="field-label">Mapping Version</div>
                        <div className="field-value">{mappingCurrent.version}</div>
                      </div>
                      <div>
                        <div className="field-label">Status</div>
                        <div className="field-value">
                          <StatusPill status={mappingCurrent.status} label={mappingCurrent.status} />
                        </div>
                      </div>
                    </div>
                    <SimpleTable
                      columns={["source_field", "target_field"]}
                      rows={mappingRows}
                      emptyMessage="No field mappings captured."
                    />
                    {mappingCurrent.transformation_hints && Object.keys(mappingCurrent.transformation_hints).length > 0 ? (
                      <div style={{ marginTop: 12 }}>
                        <div className="field-label">Transformation Hints</div>
                        <pre className="code-block">{JSON.stringify(mappingCurrent.transformation_hints, null, 2)}</pre>
                      </div>
                    ) : null}
                  </>
                ) : (
                  <p className="muted">No mappings captured for this source.</p>
                )}
              </div>
            ) : null}
          </section>
        </>
      )}
    </>
  );
}
