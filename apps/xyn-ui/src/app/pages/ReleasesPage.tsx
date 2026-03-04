import { useCallback, useEffect, useMemo, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import {
  bulkDeleteReleases,
  deleteRelease,
  getMe,
  getRelease,
  listBlueprints,
  listReleasePlans,
  listReleases,
  updateRelease,
} from "../../api/xyn";
import type {
  BlueprintSummary,
  ReleaseDetail,
  ReleasePlanSummary,
  ReleaseSummary,
} from "../../api/types";

export default function ReleasesPage() {
  const [items, setItems] = useState<ReleaseSummary[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [prevPage, setPrevPage] = useState<number | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<ReleaseDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [blueprints, setBlueprints] = useState<BlueprintSummary[]>([]);
  const [releasePlans, setReleasePlans] = useState<ReleasePlanSummary[]>([]);
  const [canManageControlPlane, setCanManageControlPlane] = useState(false);
  const [bulkSelectedIds, setBulkSelectedIds] = useState<string[]>([]);

  const blueprintNameById = useMemo(() => {
    return blueprints.reduce<Record<string, string>>((acc, blueprint) => {
      acc[blueprint.id] = blueprint.name;
      return acc;
    }, {});
  }, [blueprints]);

  const releasePlanNameById = useMemo(() => {
    return releasePlans.reduce<Record<string, string>>((acc, plan) => {
      acc[plan.id] = plan.name;
      return acc;
    }, {});
  }, [releasePlans]);

  const blueprintById = useMemo(() => {
    return blueprints.reduce<Record<string, BlueprintSummary>>((acc, blueprint) => {
      acc[blueprint.id] = blueprint;
      return acc;
    }, {});
  }, [blueprints]);

  const selectedIsControlPlane = useMemo(() => {
    if (!selected?.blueprint_id) return false;
    const blueprint = blueprintById[selected.blueprint_id];
    if (!blueprint) return false;
    const fqn = `${blueprint.namespace}.${blueprint.name}`;
    return ["xyn-api", "xyn-ui", "core.xyn-api", "core.xyn-ui"].includes(blueprint.name) || ["core.xyn-api", "core.xyn-ui", "xyn-api", "xyn-ui"].includes(fqn);
  }, [blueprintById, selected]);

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await listReleases(undefined, undefined, page, pageSize);
      setItems(data.releases);
      setCount(data.count || 0);
      setNextPage(data.next ?? null);
      setPrevPage(data.prev ?? null);
      if (selectedId && !data.releases.find((release) => release.id === selectedId)) {
        setSelectedId(data.releases[0]?.id ?? null);
      }
      if (!selectedId && data.releases[0]) {
        setSelectedId(data.releases[0].id);
      }
      setBulkSelectedIds((current) => current.filter((id) => data.releases.some((release) => release.id === id)));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [page, pageSize, selectedId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    (async () => {
      try {
        const [blueprintData, releasePlanData] = await Promise.all([
          listBlueprints(),
          listReleasePlans(),
        ]);
        setBlueprints(blueprintData.blueprints);
        setReleasePlans(releasePlanData.release_plans);
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const me = await getMe();
        const roles = me.roles || [];
        setCanManageControlPlane(roles.includes("platform_admin") || roles.includes("platform_architect"));
      } catch {
        setCanManageControlPlane(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      return;
    }
    (async () => {
      try {
        const detail = await getRelease(selectedId);
        setSelected(detail);
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, [selectedId]);

  const normalizedArtifacts = useMemo(() => {
    const raw = selected?.artifacts_json;
    if (!raw) return [] as Array<{ name: string; url: string }>;
    if (Array.isArray(raw)) {
      return raw.filter((item) => Boolean(item?.name && item?.url));
    }
    if (typeof raw === "object") {
      return Object.entries(raw as Record<string, unknown>)
        .map(([name, value]) => {
          if (value && typeof value === "object") {
            const url = String((value as { url?: string }).url || "");
            return { name, url };
          }
          return { name, url: "" };
        })
        .filter((item) => Boolean(item.url));
    }
    return [] as Array<{ name: string; url: string }>;
  }, [selected?.artifacts_json]);

  const handleRefresh = async () => {
    try {
      setLoading(true);
      await load();
      setMessage("Releases refreshed.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handlePublish = async () => {
    if (!selected) return;
    try {
      setLoading(true);
      setError(null);
      await updateRelease(selected.id, { status: "published" });
      const detail = await getRelease(selected.id);
      setSelected(detail);
      await load();
      const buildNote =
        detail.build_state && detail.build_state !== "ready"
          ? ` Build state: ${detail.build_state}.`
          : "";
      setMessage(`Release ${detail.version} published.${buildNote}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const canDelete = useMemo(() => {
    if (!selected) return false;
    if (selected.status === "draft") return true;
    if (selected.status === "published" && !selected.release_plan_id) return true;
    return false;
  }, [selected]);

  const handleDelete = async () => {
    if (!selected) return;
    if (!confirm(`Delete release ${selected.version}? This cannot be undone.`)) return;
    try {
      setLoading(true);
      setError(null);
      const result = await deleteRelease(selected.id);
      setMessage(
        result.image_cleanup
          ? `Release deleted. Image cleanup: ${JSON.stringify(result.image_cleanup)}`
          : "Release deleted."
      );
      setSelected(null);
      setSelectedId(null);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const toggleBulkSelected = (releaseId: string, checked: boolean) => {
    setBulkSelectedIds((current) => {
      if (checked) {
        if (current.includes(releaseId)) return current;
        return [...current, releaseId];
      }
      return current.filter((id) => id !== releaseId);
    });
  };

  const handleBulkDelete = async () => {
    if (bulkSelectedIds.length === 0) return;
    if (!confirm(`Delete ${bulkSelectedIds.length} selected release(s)? Protected releases will be skipped.`)) return;
    try {
      setLoading(true);
      setError(null);
      const result = await bulkDeleteReleases(bulkSelectedIds);
      setMessage(`${result.deleted_count} release(s) deleted, ${result.skipped_count} skipped.`);
      if (selectedId && result.deleted.includes(selectedId)) {
        setSelectedId(null);
        setSelected(null);
      }
      setBulkSelectedIds([]);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Releases</h2>
          <p className="muted">Generated releases and artifacts.</p>
        </div>
        <div className="inline-actions">
          <label>
            Page size
            <select
              value={String(pageSize)}
              onChange={(event) => {
                setPageSize(Number(event.target.value));
                setPage(1);
              }}
            >
              <option value="20">20</option>
              <option value="50">50</option>
              <option value="100">100</option>
            </select>
          </label>
          <button className="ghost" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={!prevPage || loading}>
            Prev
          </button>
          <span className="meta-pill">Page {page}</span>
          <button className="ghost" onClick={() => setPage((current) => current + 1)} disabled={!nextPage || loading}>
            Next
          </button>
          <span className="muted small">{count} total</span>
          <button
            className="danger"
            onClick={handleBulkDelete}
            disabled={loading || bulkSelectedIds.length === 0}
          >
            Delete selected ({bulkSelectedIds.length})
          </button>
          <button className="ghost" onClick={handleRefresh} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <div className="layout">
        <section className="card">
          <div className="card-header">
            <h3>Releases</h3>
            <label className="muted small">
              <input
                type="checkbox"
                checked={items.length > 0 && items.every((item) => bulkSelectedIds.includes(item.id))}
                onChange={(event) => {
                  if (event.target.checked) {
                    setBulkSelectedIds(items.map((item) => item.id));
                  } else {
                    setBulkSelectedIds([]);
                  }
                }}
              />{" "}
              Select page
            </label>
          </div>
          <div className="instance-list">
            {items.map((item) => (
              <div
                key={item.id}
                className={`instance-row ${selectedId === item.id ? "active" : ""}`}
              >
                <div style={{ flex: 1, cursor: "pointer" }} onClick={() => setSelectedId(item.id)}>
                  <strong>{item.version}</strong>
                  <span className="muted small">
                    {item.status}
                    {item.build_state && item.status === "published"
                      ? ` · build ${item.build_state}`
                      : ""}{" "}
                    ·{" "}
                  </span>
                  <span className="muted small">
                    {blueprintNameById[item.blueprint_id ?? ""] ?? item.blueprint_id ?? "—"}
                  </span>
                </div>
                <div className="muted small">
                  <div>
                    {item.release_plan_id
                      ? `Plan: ${releasePlanNameById[item.release_plan_id] ?? item.release_plan_id}`
                      : "No release plan"}
                  </div>
                </div>
                <label className="muted small">
                  <input
                    type="checkbox"
                    checked={bulkSelectedIds.includes(item.id)}
                    onChange={(event) => toggleBulkSelected(item.id, event.target.checked)}
                  />{" "}
                  Select
                </label>
              </div>
            ))}
            {items.length === 0 && <p className="muted">No releases yet.</p>}
          </div>
        </section>

        <section className="card">
          <div className="card-header">
            <h3>Release detail</h3>
          </div>
          {!selected ? (
            <p className="muted">Select a release to inspect.</p>
          ) : (
            <>
              {selected.status === "draft" && (
                <InlineMessage
                  tone="info"
                  title="Draft release"
                  body="This release is in draft state. Drafts are not promoted to targets until published or deployed."
                />
              )}
              {selected.status === "draft" && selectedIsControlPlane && !canManageControlPlane && (
                <InlineMessage
                  tone="warn"
                  title="Role required"
                  body="Publishing control plane releases requires the Platform Architect role."
                />
              )}
              {selected.status === "published" && selected.build_state === "building" && (
                <InlineMessage
                  tone="info"
                  title="Build in progress"
                  body="Release build artifacts are being generated. Deployment will be available once build completes."
                />
              )}
              {selected.status === "published" && selected.build_state === "failed" && (
                <InlineMessage
                  tone="error"
                  title="Build failed"
                  body="Release artifacts failed to build. Re-publish or rerun the build to make this release deployable."
                />
              )}
              <div className="detail-grid">
                <div>
                  <div className="label">Version</div>
                  <strong>{selected.version}</strong>
                </div>
                <div>
                  <div className="label">Status</div>
                  <span className="muted">{selected.status}</span>
                </div>
                <div>
                  <div className="label">Build state</div>
                  <span className="muted">{selected.build_state ?? "—"}</span>
                </div>
                <div>
                  <div className="label">Blueprint</div>
                  <span className="muted">
                    {blueprintNameById[selected.blueprint_id ?? ""] ??
                      selected.blueprint_id ??
                      "—"}
                  </span>
                </div>
                <div>
                  <div className="label">Release plan</div>
                  <span className="muted">
                    {releasePlanNameById[selected.release_plan_id ?? ""] ??
                      selected.release_plan_id ??
                      "—"}
                  </span>
                </div>
                <div>
                  <div className="label">Created from run</div>
                  <span className="muted">{selected.created_from_run_id ?? "—"}</span>
                </div>
                <div>
                  <div className="label">Created</div>
                  <span className="muted">{selected.created_at ?? "—"}</span>
                </div>
                <div>
                  <div className="label">Updated</div>
                  <span className="muted">{selected.updated_at ?? "—"}</span>
                </div>
              </div>
              <div className="stack">
                <div className="inline-actions">
                  <button className="danger" onClick={handleDelete} disabled={loading || !canDelete}>
                    Delete release
                  </button>
                </div>
                {selected.status === "draft" && (
                  <div className="inline-actions">
                    <button
                      className="primary"
                      onClick={handlePublish}
                      disabled={loading || (selectedIsControlPlane && !canManageControlPlane)}
                    >
                      Publish release
                    </button>
                  </div>
                )}
                <strong>Artifacts</strong>
                {normalizedArtifacts.length === 0 ? (
                  <span className="muted">No artifacts attached.</span>
                ) : (
                  normalizedArtifacts.map((artifact) => (
                    <div key={artifact.name} className="item-row">
                      <div>
                        <strong>{artifact.name}</strong>
                      </div>
                      <a className="link small" href={artifact.url} target="_blank" rel="noreferrer">
                        Open
                      </a>
                    </div>
                  ))
                )}
              </div>
            </>
          )}
        </section>
      </div>
    </>
  );
}
