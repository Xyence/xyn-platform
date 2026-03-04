import { Fragment, useEffect, useMemo, useState } from "react";
import { ReactFlow, Background, Controls, Edge, Node, NodeMouseHandler, Panel } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  getAccessRegistry,
  searchAccessUsers,
  getAccessUserRoles,
  getAccessUserEffective,
  getAccessRoleDetail,
} from "../../api/xyn";
import type {
  AccessEffectivePermission,
  AccessPermissionDefinition,
  AccessRegistryResponse,
  AccessRoleDefinition,
  AccessRoleDetailResponse,
  AccessUserSummary,
} from "../../api/types";

type AccessExplorerPageProps = {
  selectedUserId?: string;
  onSelectedUserIdChange?: (userId: string) => void;
  refreshToken?: number;
};

function scopeSummary(scope?: Record<string, unknown> | null): string {
  if (!scope || Object.keys(scope).length === 0) return "global";
  return Object.entries(scope)
    .map(([key, value]) => `${key}:${String(value)}`)
    .join(", ");
}

export default function AccessExplorerPage({
  selectedUserId: controlledSelectedUserId,
  onSelectedUserIdChange,
  refreshToken = 0,
}: AccessExplorerPageProps) {
  const [registry, setRegistry] = useState<AccessRegistryResponse | null>(null);
  const [users, setUsers] = useState<AccessUserSummary[]>([]);
  const [search, setSearch] = useState("");
  const [uncontrolledSelectedUserId, setUncontrolledSelectedUserId] = useState("");
  const [userRoles, setUserRoles] = useState<Array<{ roleId: string; roleName: string; scope?: Record<string, unknown>; assignedAt?: string }>>([]);
  const [effective, setEffective] = useState<AccessEffectivePermission[]>([]);
  const [activeTab, setActiveTab] = useState<"roles" | "effective" | "graph">("effective");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedPermission, setExpandedPermission] = useState<string>("");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [permissionFilter, setPermissionFilter] = useState("");
  const [dangerOnly, setDangerOnly] = useState(true);
  const [diffMode, setDiffMode] = useState(false);
  const [diffRoleId, setDiffRoleId] = useState("");
  const [inspectedNode, setInspectedNode] = useState<Node | null>(null);
  const [roleDrawerOpen, setRoleDrawerOpen] = useState(false);
  const [roleDetail, setRoleDetail] = useState<AccessRoleDetailResponse | null>(null);

  const selectedUserId = controlledSelectedUserId ?? uncontrolledSelectedUserId;
  const selectedUser = useMemo(() => users.find((user) => user.id === selectedUserId) || null, [users, selectedUserId]);

  const setSelectedUserId = (nextUserId: string) => {
    if (controlledSelectedUserId === undefined) {
      setUncontrolledSelectedUserId(nextUserId);
    }
    onSelectedUserIdChange?.(nextUserId);
  };

  const permissionsByKey = useMemo(() => {
    const map = new Map<string, AccessPermissionDefinition>();
    (registry?.permissions || []).forEach((item) => map.set(item.key, item));
    return map;
  }, [registry]);

  const rolesById = useMemo(() => {
    const map = new Map<string, AccessRoleDefinition>();
    (registry?.roles || []).forEach((item) => map.set(item.id, item));
    return map;
  }, [registry]);

  const filteredEffective = useMemo(() => {
    return effective.filter((row) => {
      const def = permissionsByKey.get(row.permissionKey);
      if (!def) return false;
      if (categoryFilter !== "all" && def.category !== categoryFilter) return false;
      if (dangerOnly && !def.isDangerous) return false;
      if (permissionFilter.trim()) {
        const q = permissionFilter.trim().toLowerCase();
        const hay = `${def.key} ${def.name} ${def.description}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [effective, permissionsByKey, categoryFilter, dangerOnly, permissionFilter]);

  const roleOnlyPermissionKeys = useMemo(() => {
    if (!diffMode || !diffRoleId || !registry) return new Set<string>();
    const rows = registry.rolePermissions.filter((rp) => rp.roleId === diffRoleId && rp.effect !== "deny");
    return new Set(rows.map((row) => row.permissionKey));
  }, [diffMode, diffRoleId, registry]);

  const categories = useMemo(() => {
    const set = new Set<string>();
    (registry?.permissions || []).forEach((item) => set.add(item.category));
    return ["all", ...Array.from(set).sort()];
  }, [registry]);

  const loadRegistry = async () => {
    try {
      const reg = await getAccessRegistry();
      setRegistry(reg);
    } catch (err) {
      setError((err as Error).message || "Failed to load registry");
    }
  };

  const loadUsers = async (query = "") => {
    try {
      const response = await searchAccessUsers(query);
      setUsers(response.users || []);
    } catch (err) {
      setError((err as Error).message || "Failed to load users");
    }
  };

  const loadSelectedUser = async (userId: string) => {
    if (!userId) {
      setUserRoles([]);
      setEffective([]);
      return;
    }
    setLoading(true);
    try {
      const [rolesResponse, effectiveResponse] = await Promise.all([
        getAccessUserRoles(userId),
        getAccessUserEffective(userId),
      ]);
      setUserRoles(rolesResponse.roles || []);
      setEffective(effectiveResponse.effective || []);
    } catch (err) {
      setError((err as Error).message || "Failed to load access graph");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadRegistry();
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadUsers(search);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    void loadUsers("");
  }, []);

  useEffect(() => {
    if (!selectedUserId) {
      setUserRoles([]);
      setEffective([]);
      return;
    }
    void loadSelectedUser(selectedUserId);
  }, [selectedUserId]);

  useEffect(() => {
    if (refreshToken === 0) return;
    void (async () => {
      await Promise.all([loadRegistry(), loadUsers(search)]);
      if (selectedUserId) await loadSelectedUser(selectedUserId);
    })();
    // Intentionally keyed to explicit manual refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshToken]);

  const nodesAndEdges = useMemo(() => {
    if (!selectedUser || !registry) return { nodes: [] as Node[], edges: [] as Edge[] };
    const roleNodes: Node[] = userRoles.map((role, idx) => ({
      id: `role:${role.roleId}`,
      type: "default",
      position: { x: 320, y: 80 + idx * 120 },
      data: { label: `${role.roleName}\n${scopeSummary(role.scope)}` },
    }));

    const permissionRows = diffMode && diffRoleId
      ? registry.rolePermissions.filter((row) => row.roleId === diffRoleId)
      : filteredEffective.map((row) => ({ roleId: row.sources[0]?.viaRoleId || "", permissionKey: row.permissionKey, scope: row.scope, effect: row.effect }));

    const uniquePermissions = Array.from(new Set(permissionRows.map((row) => row.permissionKey))).slice(0, 250);

    const permissionNodes: Node[] = uniquePermissions.map((permKey, idx) => {
      const def = permissionsByKey.get(permKey);
      return {
        id: `perm:${permKey}`,
        type: "default",
        position: { x: 680, y: 40 + idx * 70 },
        data: { label: `${permKey}\n${def?.category || "uncategorized"}` },
      };
    });

    const userNode: Node = {
      id: `user:${selectedUser.id}`,
      type: "default",
      position: { x: 40, y: 140 },
      data: { label: `${selectedUser.name}\n${selectedUser.email}` },
    };

    const userRoleEdges: Edge[] = userRoles.map((role) => ({
      id: `edge:user:${selectedUser.id}:role:${role.roleId}`,
      source: `user:${selectedUser.id}`,
      target: `role:${role.roleId}`,
      label: scopeSummary(role.scope),
      animated: false,
    }));

    const rolePermEdges: Edge[] = permissionRows
      .filter((row) => uniquePermissions.includes(row.permissionKey))
      .map((row, idx) => ({
        id: `edge:role:${row.roleId || idx}:perm:${row.permissionKey}:${idx}`,
        source: `role:${row.roleId || userRoles[0]?.roleId || ""}`,
        target: `perm:${row.permissionKey}`,
        label: `${row.effect || "allow"} ${scopeSummary((row as { scope?: Record<string, unknown> }).scope)}`,
      }))
      .filter((edge) => edge.source !== "role:");

    return { nodes: [userNode, ...roleNodes, ...permissionNodes], edges: [...userRoleEdges, ...rolePermEdges] };
  }, [selectedUser, registry, userRoles, filteredEffective, permissionsByKey, diffMode, diffRoleId]);

  const openRoleDetail = async (roleId: string) => {
    try {
      const detail = await getAccessRoleDetail(roleId);
      setRoleDetail(detail);
      setRoleDrawerOpen(true);
    } catch (err) {
      setError((err as Error).message || "Failed to load role detail");
    }
  };

  const exportEffective = () => {
    const payload = {
      user: selectedUser,
      effective: filteredEffective,
      exportedAt: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = `access-effective-${selectedUser?.id || "user"}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(href);
  };

  const handleGraphNodeClick: NodeMouseHandler = (_event, node) => setInspectedNode(node);

  return (
    <div className="layout" style={{ gridTemplateColumns: "320px minmax(0,1fr)", alignItems: "start" }}>
      <section className="card">
        <div className="card-header">
          <h3>Access Explorer</h3>
        </div>
        <label>
          Find user...
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="name, email, subject" />
        </label>
        <div className="instance-list" style={{ maxHeight: 520, overflow: "auto" }}>
          {users.map((user) => (
            <button
              key={user.id}
              className={`app-nav-link ${selectedUser?.id === user.id ? "active" : ""}`}
              onClick={() => setSelectedUserId(user.id)}
              style={{ textAlign: "left" }}
            >
              <strong>{user.name}</strong>
              <div className="muted small">{user.email}</div>
            </button>
          ))}
        </div>
        {selectedUser ? (
          <div className="card" style={{ padding: 12 }}>
            <strong>{selectedUser.name}</strong>
            <div className="muted small">{selectedUser.email}</div>
            <div className="inline-actions">
              {userRoles.map((role) => (
                <span key={`${role.roleId}-${scopeSummary(role.scope)}`} className="meta-pill">
                  {role.roleName}
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </section>

      <section className="card">
        <div className="page-header">
          <div>
            <h2>Access Explorer</h2>
            <p className="muted">Users ↔ Roles ↔ Permissions with effective permission traces.</p>
          </div>
          <div className="inline-actions">
            <button className={activeTab === "roles" ? "primary" : "ghost"} onClick={() => setActiveTab("roles")}>User Roles</button>
            <button className={activeTab === "effective" ? "primary" : "ghost"} onClick={() => setActiveTab("effective")}>Effective Permissions</button>
            <button className={activeTab === "graph" ? "primary" : "ghost"} onClick={() => setActiveTab("graph")}>Graph</button>
          </div>
        </div>

        {error ? <div className="inline-message inline-error"><strong>Request failed</strong><span>{error}</span></div> : null}
        {!selectedUser ? <p className="muted">Select a user to begin.</p> : null}

        {selectedUser && activeTab === "roles" ? (
          <section className="card" style={{ padding: 12 }}>
            <h3>User Roles</h3>
            <div className="table-wrap">
              <table className="table dense">
                <thead>
                  <tr>
                    <th>Role</th>
                    <th>Tier</th>
                    <th>Scope</th>
                    <th>Assigned</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {userRoles.map((role) => (
                    <tr key={`${role.roleId}-${scopeSummary(role.scope)}`}>
                      <td>{role.roleName}</td>
                      <td>{rolesById.get(role.roleId)?.tier ?? "-"}</td>
                      <td className="small muted">{scopeSummary(role.scope)}</td>
                      <td className="small muted">{role.assignedAt ? new Date(role.assignedAt).toLocaleString() : "-"}</td>
                      <td><button className="ghost" onClick={() => void openRoleDetail(role.roleId)}>View role detail</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ) : null}

        {selectedUser && activeTab === "effective" ? (
          <section className="card" style={{ padding: 12 }}>
            <div className="card-header">
              <h3>Effective Permissions</h3>
              <div className="inline-actions">
                <button className="ghost" onClick={exportEffective}>Export JSON</button>
              </div>
            </div>
            <div className="form-grid">
              <label>
                Category
                <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
                  {categories.map((category) => (
                    <option key={category} value={category}>{category}</option>
                  ))}
                </select>
              </label>
              <label>
                Permission key
                <input value={permissionFilter} onChange={(event) => setPermissionFilter(event.target.value)} placeholder="filter permission" />
              </label>
              <label className="checkbox-inline" style={{ marginTop: 28 }}>
                <input type="checkbox" checked={dangerOnly} onChange={(event) => setDangerOnly(event.target.checked)} />
                Dangerous only
              </label>
              <label className="checkbox-inline" style={{ marginTop: 28 }}>
                <input type="checkbox" checked={diffMode} onChange={(event) => setDiffMode(event.target.checked)} />
                Diff mode
              </label>
              {diffMode ? (
                <label>
                  Compare against role
                  <select value={diffRoleId} onChange={(event) => setDiffRoleId(event.target.value)}>
                    <option value="">Select role</option>
                    {(registry?.roles || []).map((role) => (
                      <option key={role.id} value={role.id}>{role.name}</option>
                    ))}
                  </select>
                </label>
              ) : null}
            </div>
            <div className="table-wrap">
              <table className="table dense">
                <thead>
                  <tr>
                    <th>Permission</th>
                    <th>Category</th>
                    <th>Scope</th>
                    <th>Sources</th>
                    {diffMode ? <th>In role-only</th> : null}
                  </tr>
                </thead>
                <tbody>
                  {filteredEffective.map((row) => {
                    const def = permissionsByKey.get(row.permissionKey);
                    const traceOpen = expandedPermission === `${row.permissionKey}:${scopeSummary(row.scope)}`;
                    return (
                      <Fragment key={`${row.permissionKey}:${scopeSummary(row.scope)}`}>
                        <tr
                          onClick={() => setExpandedPermission(traceOpen ? "" : `${row.permissionKey}:${scopeSummary(row.scope)}`)}
                          style={{ cursor: "pointer" }}
                        >
                          <td>
                            <strong>{row.permissionKey}</strong>
                            <div className="muted small">{def?.name || row.permissionKey}</div>
                          </td>
                          <td>{def?.category || "uncategorized"}</td>
                          <td className="small muted">{scopeSummary(row.scope)}</td>
                          <td>{row.sources?.length || 0}</td>
                          {diffMode ? <td>{roleOnlyPermissionKeys.has(row.permissionKey) ? "yes" : "no"}</td> : null}
                        </tr>
                        {traceOpen ? (
                          <tr>
                            <td colSpan={diffMode ? 5 : 4}>
                              <div className="instance-list">
                                {(row.sources || []).map((source, idx) => (
                                  <div key={`${source.ruleId || idx}`} className="instance-row">
                                    <strong>{source.viaRoleName}</strong>
                                    <div className="muted small">Role scope: {scopeSummary(source.roleScope)}</div>
                                    <div className="muted small">Permission scope: {scopeSummary(source.permScope)}</div>
                                    <div className="muted small">Merged scope: {scopeSummary(source.mergedScope)}</div>
                                  </div>
                                ))}
                              </div>
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        ) : null}

        {selectedUser && activeTab === "graph" ? (
          <section className="card" style={{ height: 680, padding: 0, overflow: "hidden" }}>
            <ReactFlow
              className="access-explorer-flow"
              nodes={nodesAndEdges.nodes}
              edges={nodesAndEdges.edges}
              fitView
              onNodeClick={handleGraphNodeClick}
            >
              <Background />
              <Controls />
              <Panel position="top-right">
                <div className="meta-pill">Nodes: {nodesAndEdges.nodes.length} | Edges: {nodesAndEdges.edges.length}</div>
              </Panel>
            </ReactFlow>
            {inspectedNode ? (
              <aside className="overlay-card" style={{ position: "absolute", right: 24, top: 80, width: 320 }}>
                <h4>Inspector</h4>
                <div className="small muted">{inspectedNode.id}</div>
                <pre className="log-box" style={{ whiteSpace: "pre-wrap" }}>{String((inspectedNode.data as { label?: string })?.label || "")}</pre>
                {inspectedNode.id.startsWith("role:") ? (
                  <button className="primary" onClick={() => void openRoleDetail(inspectedNode.id.replace("role:", ""))}>Open role detail</button>
                ) : null}
                {inspectedNode.id.startsWith("perm:") ? (
                  <button
                    className="ghost"
                    onClick={() => {
                      setActiveTab("effective");
                      setPermissionFilter(inspectedNode.id.replace("perm:", ""));
                    }}
                  >
                    Show effective traces
                  </button>
                ) : null}
              </aside>
            ) : null}
          </section>
        ) : null}

        {loading ? <p className="muted">Loading access model...</p> : null}
      </section>

      {roleDrawerOpen && roleDetail ? (
        <div className="modal-backdrop" onClick={() => setRoleDrawerOpen(false)}>
          <section className="modal" onClick={(event) => event.stopPropagation()}>
            <h3>{roleDetail.role.name}</h3>
            <p className="muted">{roleDetail.role.description || ""}</p>
            <div className="table-wrap">
              <table className="table dense">
                <thead>
                  <tr>
                    <th>Permission key</th>
                    <th>Effect</th>
                    <th>Scope</th>
                  </tr>
                </thead>
                <tbody>
                  {(roleDetail.permissions || []).map((permission) => (
                    <tr key={`${permission.permissionKey}:${scopeSummary(permission.scope)}`}>
                      <td>{permission.permissionKey}</td>
                      <td>{permission.effect || "allow"}</td>
                      <td className="small muted">{scopeSummary(permission.scope)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="inline-actions">
              <button className="primary" onClick={() => setRoleDrawerOpen(false)}>Close</button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
