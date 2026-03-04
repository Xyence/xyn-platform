import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  MiniMap,
  MarkerType,
  Position,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import InlineMessage from "../../components/InlineMessage";
import { checkDrift, deployLatest, fetchMap, listBlueprints, rollbackLastSuccess } from "../../api/xyn";
import type { XynMapEdge, XynMapNode, XynMapNodeKind, XynMapResponse } from "../../api/types";

type FlowNodeData = {
  label: string;
  kind: XynMapNodeKind;
  status: "ok" | "warn" | "error" | "unknown";
  badges: string[];
};

const KIND_ORDER: XynMapNodeKind[] = ["blueprint", "release_plan", "release", "release_target", "instance", "run"];

type FlowNode = Node<FlowNodeData, "mapNode">;
type FlowEdge = Edge;

function XynMapCardNode({ data, selected }: NodeProps<FlowNode>) {
  return (
    <div className={`map-node map-node-${data.status} ${selected ? "map-node-selected" : ""}`}>
      <Handle type="target" position={Position.Left} className="map-handle" />
      <div className="map-node-kind">{data.kind.replace("_", " ")}</div>
      <strong>{data.label}</strong>
      {data.badges.length > 0 ? (
        <div className="map-node-badges">
          {data.badges.slice(0, 3).map((badge) => (
            <span key={badge} className="meta-pill">
              {badge}
            </span>
          ))}
        </div>
      ) : null}
      <Handle type="source" position={Position.Right} className="map-handle" />
    </div>
  );
}

const nodeTypes = {
  mapNode: XynMapCardNode,
};

function buildLayout(nodes: XynMapNode[], edges: XynMapEdge[]): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const byKind = new Map<XynMapNodeKind, XynMapNode[]>();
  for (const kind of KIND_ORDER) {
    byKind.set(kind, []);
  }
  for (const node of nodes) {
    byKind.get(node.kind)?.push(node);
  }
  for (const list of byKind.values()) {
    list.sort((a, b) => a.label.localeCompare(b.label));
  }
  const flowNodes: FlowNode[] = [];
  for (let column = 0; column < KIND_ORDER.length; column += 1) {
    const kind = KIND_ORDER[column];
    const list = byKind.get(kind) || [];
    for (let row = 0; row < list.length; row += 1) {
      const node = list[row];
      flowNodes.push({
        id: node.id,
        type: "mapNode",
        position: { x: column * 340, y: row * 138 },
        width: 220,
        height: 96,
        style: { width: 220, minHeight: 96 },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        data: {
          label: node.label,
          kind: node.kind,
          status: node.status,
          badges: node.badges || [],
        },
      });
    }
  }
  const flowEdges: FlowEdge[] = edges.map((edge) => ({
    id: edge.id,
    source: edge.from,
    target: edge.to,
    type: "smoothstep",
    markerEnd: { type: MarkerType.ArrowClosed },
    animated: edge.kind.includes("run"),
    label: edge.kind,
    style: { stroke: "#5b6f8f", strokeWidth: 1.6 },
    labelStyle: { fill: "#5b6f8f", fontSize: 11 },
  }));
  return { nodes: flowNodes, edges: flowEdges };
}

function pruneArchivedBlueprints(mapData: XynMapResponse, activeBlueprintIds: Set<string>): XynMapResponse {
  const activeBlueprintNodeIds = new Set(
    mapData.nodes
      .filter((node) => node.kind === "blueprint" && activeBlueprintIds.has(node.ref.id))
      .map((node) => node.id)
  );

  const outgoing = new Map<string, string[]>();
  for (const edge of mapData.edges) {
    const targets = outgoing.get(edge.from);
    if (targets) {
      targets.push(edge.to);
    } else {
      outgoing.set(edge.from, [edge.to]);
    }
  }

  const reachable = new Set<string>(activeBlueprintNodeIds);
  const queue = Array.from(activeBlueprintNodeIds);
  while (queue.length > 0) {
    const current = queue.shift();
    if (!current) continue;
    const targets = outgoing.get(current) || [];
    for (const target of targets) {
      if (!reachable.has(target)) {
        reachable.add(target);
        queue.push(target);
      }
    }
  }

  const nodes = mapData.nodes.filter((node) => {
    if (node.kind === "blueprint") {
      return activeBlueprintNodeIds.has(node.id);
    }
    return reachable.has(node.id);
  });
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = mapData.edges.filter((edge) => nodeIds.has(edge.from) && nodeIds.has(edge.to));

  return {
    ...mapData,
    meta: {
      ...mapData.meta,
      options: {
        ...mapData.meta.options,
        blueprints: (mapData.meta.options?.blueprints || []).filter((item) => activeBlueprintIds.has(item.id)),
      },
    },
    nodes,
    edges,
  };
}

export default function XynMapPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [mapData, setMapData] = useState<XynMapResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [blueprintFilter, setBlueprintFilter] = useState(() => searchParams.get("blueprint_id") || "");
  const [environmentFilter, setEnvironmentFilter] = useState(() => searchParams.get("environment_id") || "");
  const [tenantFilter, setTenantFilter] = useState(() => searchParams.get("tenant_id") || "");
  const [search, setSearch] = useState(() => searchParams.get("q") || "");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const blueprintData = await listBlueprints();
      const activeBlueprintIds = new Set((blueprintData.blueprints || []).map((item) => item.id));
      const effectiveBlueprintFilter =
        blueprintFilter && activeBlueprintIds.has(blueprintFilter) ? blueprintFilter : "";
      if (blueprintFilter && !effectiveBlueprintFilter) {
        setBlueprintFilter("");
      }

      const payload = await fetchMap({
        blueprint_id: effectiveBlueprintFilter || undefined,
        environment_id: environmentFilter || undefined,
        tenant_id: tenantFilter || undefined,
        include_runs: true,
        include_instances: true,
      });
      const prunedPayload = pruneArchivedBlueprints(payload, activeBlueprintIds);
      setMapData(prunedPayload);
      if (selectedNodeId && !prunedPayload.nodes.find((node) => node.id === selectedNodeId)) {
        setSelectedNodeId(null);
      }
    } catch (err) {
      setError((err as Error).message);
      setMapData(null);
    } finally {
      setLoading(false);
    }
  }, [blueprintFilter, environmentFilter, tenantFilter, selectedNodeId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const next = new URLSearchParams();
    if (blueprintFilter) {
      next.set("blueprint_id", blueprintFilter);
    }
    if (environmentFilter) {
      next.set("environment_id", environmentFilter);
    }
    if (tenantFilter) {
      next.set("tenant_id", tenantFilter);
    }
    if (search.trim()) {
      next.set("q", search.trim());
    }
    setSearchParams(next, { replace: true });
  }, [blueprintFilter, environmentFilter, tenantFilter, search, setSearchParams]);

  const selectedNode = useMemo(
    () => mapData?.nodes.find((node) => node.id === selectedNodeId) || null,
    [mapData, selectedNodeId]
  );

  const filteredGraph = useMemo(() => {
    if (!mapData) {
      return { nodes: [] as FlowNode[], edges: [] as FlowEdge[] };
    }
    const lowered = search.trim().toLowerCase();
    const keptNodes = lowered
      ? mapData.nodes.filter((node) => node.label.toLowerCase().includes(lowered))
      : mapData.nodes;
    const nodeIds = new Set(keptNodes.map((node) => node.id));
    const keptEdges = mapData.edges.filter((edge) => nodeIds.has(edge.from) && nodeIds.has(edge.to));
    return buildLayout(keptNodes, keptEdges);
  }, [mapData, search]);

  const edgeKinds = useMemo(
    () => Array.from(new Set((mapData?.edges || []).map((edge) => edge.kind))).sort(),
    [mapData]
  );

  const handleAction = async (action: "deploy" | "rollback" | "drift", releaseTargetId: string) => {
    try {
      setActionLoading(true);
      setError(null);
      setMessage(null);
      if (action === "deploy") {
        const result = await deployLatest(releaseTargetId);
        setMessage(`Deploy requested${result.run_id ? ` (run ${result.run_id})` : ""}.`);
      } else if (action === "rollback") {
        const result = await rollbackLastSuccess(releaseTargetId);
        setMessage(`Rollback requested${result.run_id ? ` (run ${result.run_id})` : ""}.`);
      } else {
        const result = await checkDrift(releaseTargetId);
        setMessage(JSON.stringify(result, null, 2));
      }
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Xyn Map</h2>
          <p className="muted">Live read-only topology across blueprints, releases, targets, instances, and runs.</p>
        </div>
      </div>

      <section className="card">
        <div className="map-toolbar">
          <label>
            Blueprint
            <select value={blueprintFilter} onChange={(event) => setBlueprintFilter(event.target.value)}>
              <option value="">All blueprints</option>
              {(mapData?.meta.options?.blueprints || []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Environment
            <select value={environmentFilter} onChange={(event) => setEnvironmentFilter(event.target.value)}>
              <option value="">All environments</option>
              {(mapData?.meta.options?.environments || []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Tenant
            <select value={tenantFilter} onChange={(event) => setTenantFilter(event.target.value)}>
              <option value="">All tenants</option>
              {(mapData?.meta.options?.tenants || []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Search
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Filter by node label"
            />
          </label>
          <div className="actions">
            <button className="ghost" onClick={load} disabled={loading}>
              Refresh
            </button>
          </div>
        </div>
        <div className="map-legend-row">
          <div className="map-legend">
            <span className="small muted">Status</span>
            <span className="map-status-key"><span className="map-status-dot ok" /> ok</span>
            <span className="map-status-key"><span className="map-status-dot warn" /> warn</span>
            <span className="map-status-key"><span className="map-status-dot error" /> error</span>
            <span className="map-status-key"><span className="map-status-dot unknown" /> unknown</span>
          </div>
          <div className="map-legend">
            <span className="small muted">Edge kinds</span>
            {edgeKinds.length ? (
              edgeKinds.map((kind) => (
                <span key={kind} className="meta-pill">
                  {kind}
                </span>
              ))
            ) : (
              <span className="small muted">none</span>
            )}
          </div>
        </div>
      </section>

      {error ? <InlineMessage tone="error" title="Map request failed" body={error} /> : null}
      {message ? <InlineMessage tone="info" title="Action result" body={message} /> : null}

      <section className="map-layout">
        <div className="card map-canvas-card">
          {loading && !mapData ? (
            <p className="muted">Loading map…</p>
          ) : null}
          {!loading && !mapData ? (
            <div className="stack">
              <p className="muted">Unable to load map data right now.</p>
              <div>
                <button className="ghost" onClick={load}>
                  Retry
                </button>
              </div>
            </div>
          ) : null}
          {mapData ? (
            <div className="map-canvas">
              <ReactFlow
                nodes={filteredGraph.nodes}
                edges={filteredGraph.edges}
                nodeTypes={nodeTypes}
                fitView
                onNodeClick={(_event, node) => setSelectedNodeId(node.id)}
              >
                <MiniMap
                  className="xyn-minimap"
                  pannable
                  zoomable
                  nodeColor="#334155"
                  nodeStrokeColor="#0f172a"
                  nodeStrokeWidth={2}
                  maskColor="rgba(0, 0, 0, 0)"
                  style={{ backgroundColor: "#e2e8f0", border: "1px solid #cbd5e1" }}
                />
                <Controls />
                <Background gap={18} size={1} />
              </ReactFlow>
            </div>
          ) : null}
        </div>

        <aside className="card map-inspector">
          {!selectedNode ? (
            <p className="muted">Select a node to inspect details and actions.</p>
          ) : (
            <>
              <div className="card-header">
                <h3>{selectedNode.label}</h3>
                <span className="meta-pill">{selectedNode.kind}</span>
              </div>
              <div className="stack">
                <div>
                  <strong>Status:</strong> {selectedNode.status}
                </div>
                {selectedNode.badges?.length ? (
                  <div className="map-node-badges">
                    {selectedNode.badges.map((badge) => (
                      <span key={badge} className="meta-pill">
                        {badge}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
              <div>
                <h4>Metrics</h4>
                <div className="stack">
                  {Object.entries(selectedNode.metrics || {}).map(([key, value]) => (
                    <div key={key} className="muted small">
                      <strong>{key}</strong>: {value === null || value === undefined ? "-" : String(value)}
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <h4>Links</h4>
                <div className="stack">
                  {Object.entries(selectedNode.links || {}).map(([key, value]) => (
                    <a key={key} className="link" href={value}>
                      {key}
                    </a>
                  ))}
                </div>
              </div>
              {selectedNode.kind === "release_target" ? (
                <div className="actions">
                  <button
                    className="primary"
                    disabled={actionLoading}
                    onClick={() => handleAction("deploy", selectedNode.ref.id)}
                  >
                    Deploy latest
                  </button>
                  <button
                    className="ghost"
                    disabled={actionLoading}
                    onClick={() => handleAction("rollback", selectedNode.ref.id)}
                  >
                    Rollback last success
                  </button>
                  <button
                    className="ghost"
                    disabled={actionLoading}
                    onClick={() => handleAction("drift", selectedNode.ref.id)}
                  >
                    Check drift
                  </button>
                </div>
              ) : null}
            </>
          )}
        </aside>
      </section>
    </>
  );
}
