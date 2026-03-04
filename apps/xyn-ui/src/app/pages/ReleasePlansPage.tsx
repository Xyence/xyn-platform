import { useCallback, useEffect, useMemo, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import {
  createDevTask,
  createReleasePlan,
  deleteReleasePlan,
  getMe,
  getReleasePlan,
  getRunArtifacts,
  getRunLogs,
  listEnvironments,
  listReleases,
  listReleasePlans,
  runDevTask,
  updateReleasePlan,
} from "../../api/xyn";
import { listInstances } from "../../api/client";
import type {
  EnvironmentSummary,
  ProvisionedInstance,
  ReleasePlanCreatePayload,
  ReleasePlanDetail,
  ReleasePlanSummary,
  ReleaseSummary,
  RunArtifact,
} from "../../api/types";

const emptyForm: ReleasePlanCreatePayload = {
  name: "",
  target_kind: "module",
  target_fqn: "",
  from_version: "",
  to_version: "",
  blueprint_id: "",
  environment_id: "",
};

const TARGET_KINDS = ["module", "bundle", "release", "blueprint"];

export default function ReleasePlansPage() {
  const [items, setItems] = useState<ReleasePlanSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<ReleasePlanDetail | null>(null);
  const [form, setForm] = useState<ReleasePlanCreatePayload>(emptyForm);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [instances, setInstances] = useState<ProvisionedInstance[]>([]);
  const [activeInstances, setActiveInstances] = useState<ProvisionedInstance[]>([]);
  const [targetInstanceId, setTargetInstanceId] = useState<string>("");
  const [forceDeploy, setForceDeploy] = useState(false);
  const [runLogs, setRunLogs] = useState<string>("");
  const [runArtifacts, setRunArtifacts] = useState<RunArtifact[]>([]);
  const [releases, setReleases] = useState<ReleaseSummary[]>([]);
  const [allReleases, setAllReleases] = useState<ReleaseSummary[]>([]);
  const [selectedReleaseId, setSelectedReleaseId] = useState<string>("");
  const [environments, setEnvironments] = useState<EnvironmentSummary[]>([]);
  const [draftReleaseWarning, setDraftReleaseWarning] = useState<string | null>(null);
  const [canManageControlPlane, setCanManageControlPlane] = useState(false);

  const selectedRelease = useMemo(
    () => allReleases.find((item) => item.id === selectedReleaseId),
    [allReleases, selectedReleaseId]
  );
  const isDraftSelected = Boolean(selectedRelease && selectedRelease.status !== "published");
  const isBuildReady = !selectedRelease || selectedRelease.build_state === "ready";

  const eligibleInstances = useMemo(() => {
    if (!form.environment_id) return activeInstances;
    return activeInstances.filter((instance) => instance.environment_id === form.environment_id);
  }, [activeInstances, form.environment_id]);
  const availableReleases = useMemo(() => {
    if (!selected) return [];
    const byPlan = releases.filter((item) => item.release_plan_id === selected.id);
    const byBlueprint = selected.blueprint_id
      ? releases.filter((item) => item.blueprint_id === selected.blueprint_id)
      : [];
    if (byBlueprint.length === 0) {
      return byPlan.length > 0 ? byPlan : releases;
    }
    const merged = [...byPlan];
    for (const item of byBlueprint) {
      if (!merged.some((existing) => existing.id === item.id)) {
        merged.push(item);
      }
    }
    return merged;
  }, [releases, selected]);
  const selectedIsControlPlane = useMemo(() => {
    const target = (selected?.target_fqn || "").trim();
    return ["xyn-api", "xyn-ui", "core.xyn-api", "core.xyn-ui"].includes(target);
  }, [selected]);

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await listReleasePlans();
      setItems(data.release_plans);
      if (!selectedId && data.release_plans[0]) {
        setSelectedId(data.release_plans[0].id);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }, [selectedId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    (async () => {
      try {
        const data = await listInstances();
        setInstances(data.instances);
        setActiveInstances(
          data.instances.filter((instance) => instance.status !== "terminated" && instance.status !== "error")
        );
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
    (async () => {
      try {
        const [published, all] = await Promise.all([listReleases(undefined, "published"), listReleases()]);
        setReleases(published.releases);
        setAllReleases(all.releases);
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const data = await listEnvironments();
        setEnvironments(data.environments);
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      return;
    }
    setSelectedReleaseId("");
    setDraftReleaseWarning(null);
    (async () => {
      try {
        const detail = await getReleasePlan(selectedId);
        setSelected(detail);
        setTargetInstanceId((prev) => prev || detail.deployments?.[0]?.instance_id || "");
        const matching = releases.filter((item) => item.release_plan_id === detail.id);
        const byBlueprint = detail.blueprint_id
          ? releases.filter((item) => item.blueprint_id === detail.blueprint_id)
          : [];
        const selectedCandidate =
          (detail.current_release_id
            ? releases.find((item) => item.id === detail.current_release_id) || allReleases.find((item) => item.id === detail.current_release_id)
            : null) ||
          matching[0] ||
          byBlueprint[0];
        if (selectedCandidate) setSelectedReleaseId(selectedCandidate.id);
        const legacyDraft = allReleases.find(
          (item) =>
            item.status !== "published" &&
            (item.release_plan_id === detail.id || (detail.blueprint_id && item.blueprint_id === detail.blueprint_id))
        );
        if (legacyDraft && !selectedCandidate) {
          setSelectedReleaseId(legacyDraft.id);
          setDraftReleaseWarning(
            `Draft release ${legacyDraft.version} is attached to this plan. Publish it before deploying or saving.`
          );
        }
        setForm({
          name: detail.name,
          target_kind: detail.target_kind,
          target_fqn: detail.target_fqn,
          from_version: detail.from_version ?? "",
          to_version: detail.to_version ?? "",
          blueprint_id: detail.blueprint_id ?? "",
          environment_id: detail.environment_id ?? "",
        });
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, [selectedId, releases, allReleases]);

  useEffect(() => {
    const lastRun = selected?.last_run;
    if (!lastRun) {
      setRunLogs("");
      setRunArtifacts([]);
      return;
    }
    (async () => {
      try {
        const logs = await getRunLogs(lastRun);
        const artifacts = await getRunArtifacts(lastRun);
        setRunLogs(logs.log || "");
        setRunArtifacts(artifacts);
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, [selected?.last_run]);

  useEffect(() => {
    if (!targetInstanceId) return;
    if (!eligibleInstances.find((instance) => instance.id === targetInstanceId)) {
      setTargetInstanceId("");
    }
  }, [eligibleInstances, targetInstanceId]);

  const handleCreate = async () => {
    if (!form.environment_id) {
      setError("Select an environment before creating a release plan.");
      return;
    }
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      await createReleasePlan(form);
      setForm(emptyForm);
      await load();
      setMessage("Release plan created.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleUpdate = async () => {
    if (!selectedId) return;
    if (!form.environment_id) {
      setError("Select an environment before saving.");
      return;
    }
    if (isDraftSelected) {
      setError("Draft release selected. Publish it before saving.");
      return;
    }
    if (selectedIsControlPlane && !canManageControlPlane) {
      setError("Platform Architect role required to modify control plane plans.");
      return;
    }
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      await updateReleasePlan(selectedId, {
        ...form,
        selected_release_id: selectedReleaseId || null,
      });
      await load();
      setMessage("Release plan updated.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedId) return;
    if (!confirm("Delete this release plan?")) return;
    try {
      setLoading(true);
      setError(null);
      await deleteReleasePlan(selectedId);
      setSelectedId(null);
      setSelected(null);
      setForm(emptyForm);
      await load();
      setMessage("Release plan deleted.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleGenerate = async () => {
    if (!selectedId || !selected) return;
    try {
      setLoading(true);
      setError(null);
      const payload = {
        title: `Generate release plan for ${selected.target_fqn || selected.name}`,
        task_type: "release_plan_generate",
        source_entity_type: "blueprint",
        source_entity_id: selected.blueprint_id ?? selected.id,
        input_artifact_key: "implementation_plan.json",
        context_purpose: "planner",
      };
      const created = await createDevTask(payload);
      const run = await runDevTask(created.id);
      setMessage(`Release plan generation queued. Run: ${run.run_id}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleDeploy = async () => {
    if (!selectedId || !selected) return;
    if (!targetInstanceId) {
      setError("Select a target instance before deploying.");
      return;
    }
    if (selectedIsControlPlane && !canManageControlPlane) {
      setError("Platform Architect role required to deploy control plane plans.");
      return;
    }
    if (isDraftSelected) {
      setError("Draft release selected. Publish it before deploying.");
      return;
    }
    if (!isBuildReady) {
      setError("Release build is not ready. Wait for build completion before deploying.");
      return;
    }
    if (form.environment_id) {
      const target = activeInstances.find((instance) => instance.id === targetInstanceId);
      if (target && target.environment_id && target.environment_id !== form.environment_id) {
        setError("Target instance environment does not match release plan environment.");
        return;
      }
    }
    try {
      setLoading(true);
      setError(null);
      const release =
        releases.find((item) => item.id === selectedReleaseId) ||
        releases.find((item) => item.release_plan_id === selected.id);
      const payload = {
        title: `Deploy ${selected.name}`,
        task_type: "deploy_release_plan",
        source_entity_type: "release_plan",
        source_entity_id: selected.id,
        source_run_id: selected.last_run ?? null,
        input_artifact_key: "release_plan.json",
        context_purpose: "deployer",
        target_instance_id: targetInstanceId,
        force: forceDeploy,
        release_id: release?.id,
      };
      const created = await createDevTask(payload);
      const run = await runDevTask(created.id, forceDeploy);
      setMessage(`Deploy queued. Run: ${run.run_id}`);
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
          <h2>Release Plans</h2>
          <p className="muted">Track planned changes for modules and bundles.</p>
        </div>
        <button className="ghost" onClick={load} disabled={loading}>
          Refresh
        </button>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}
      {draftReleaseWarning && (
        <InlineMessage tone="warn" title="Draft release selected" body={draftReleaseWarning} />
      )}
      {isDraftSelected && !draftReleaseWarning && (
        <InlineMessage
          tone="warn"
          title="Draft release selected"
          body="Publish the selected release before deploying or saving."
        />
      )}
      {!isDraftSelected && selectedRelease && !isBuildReady && (
        <InlineMessage
          tone="warn"
          title="Release build not ready"
          body={`Build state is ${selectedRelease.build_state ?? "unknown"}. Deployment is blocked until build succeeds.`}
        />
      )}

      <div className="layout">
        <section className="card">
          <div className="card-header">
            <h3>Release plans</h3>
          </div>
          <div className="instance-list">
            {items.map((item) => (
              <button
                key={item.id}
                className={`instance-row ${selectedId === item.id ? "active" : ""}`}
                onClick={() => setSelectedId(item.id)}
              >
                <div>
                  <strong>{item.name}</strong>
                  <span className="muted small">{item.target_kind}</span>
                </div>
                <span className="muted small">{item.to_version ?? "—"}</span>
              </button>
            ))}
            {items.length === 0 && <p className="muted">No release plans yet.</p>}
          </div>
        </section>

        <section className="card">
          <div className="card-header">
            <h3>{selected ? "Release plan detail" : "Create release plan"}</h3>
          </div>
          <div className="form-grid">
            <label>
              Name
              <input
                value={form.name ?? ""}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
              />
            </label>
            <label>
              Target kind
              <select
                value={form.target_kind ?? "module"}
                onChange={(event) => setForm({ ...form, target_kind: event.target.value })}
              >
                {TARGET_KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {kind}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Target FQN
              <input
                value={form.target_fqn ?? ""}
                onChange={(event) => setForm({ ...form, target_fqn: event.target.value })}
              />
            </label>
            <label>
              From version
              <input
                value={form.from_version ?? ""}
                onChange={(event) => setForm({ ...form, from_version: event.target.value })}
              />
            </label>
            <label>
              To version
              <input
                value={form.to_version ?? ""}
                onChange={(event) => setForm({ ...form, to_version: event.target.value })}
              />
            </label>
            <label>
              Blueprint ID
              <input
                value={form.blueprint_id ?? ""}
                onChange={(event) => setForm({ ...form, blueprint_id: event.target.value })}
              />
            </label>
            <label>
              Environment
              <select
                className="input"
                value={form.environment_id ?? ""}
                onChange={(event) => setForm({ ...form, environment_id: event.target.value })}
              >
                <option value="">Select environment</option>
                {environments.map((env) => (
                  <option key={env.id} value={env.id}>
                    {env.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="form-actions">
            <button
              className="primary"
              data-tour="release-plan-create"
              data-testid="release-plan-create"
              onClick={selected ? handleUpdate : handleCreate}
              disabled={loading || isDraftSelected || !form.environment_id}
            >
              {selected ? "Save changes" : "Create"}
            </button>
            <button
              className="ghost"
              data-tour="release-plan-deploy"
              data-testid="release-plan-deploy"
              onClick={handleDeploy}
              disabled={loading || !selected || !targetInstanceId || isDraftSelected || !isBuildReady}
            >
              Deploy this plan
            </button>
            {selected && (
              <>
                <button className="ghost" onClick={handleGenerate} disabled={loading}>
                  Generate via DevTask
                </button>
                <button className="danger" onClick={handleDelete} disabled={loading}>
                  Delete
                </button>
              </>
            )}
          </div>
          {selected && (
            <div className="detail-grid">
              <div>
                <div className="label">Target</div>
                <span className="muted">{selected.target_fqn}</span>
              </div>
              <div>
                <div className="label">Updated</div>
                <span className="muted">{selected.updated_at ?? "—"}</span>
              </div>
              <div>
                <div className="label">Last run</div>
                {selected.last_run ? (
                  <a className="link" href={`/app/runs?run=${selected.last_run}`}>
                    {selected.last_run}
                  </a>
                ) : (
                  <span className="muted">—</span>
                )}
              </div>
              <div>
                <div className="label">Target instance</div>
                <select value={targetInstanceId} onChange={(event) => setTargetInstanceId(event.target.value)}>
                  <option value="">Select instance</option>
                  {eligibleInstances.map((instance) => (
                    <option key={instance.id} value={instance.id}>
                      {instance.name} ({instance.aws_region})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <div className="label">Force deploy</div>
                <label className="muted small">
                  <input
                    type="checkbox"
                    checked={forceDeploy}
                    onChange={(event) => setForceDeploy(event.target.checked)}
                  />
                  Run even if already applied
                </label>
              </div>
            </div>
          )}
          {selected && (
            <div className="detail-grid">
              <div>
                <div className="label">Release</div>
                <select
                  value={selectedReleaseId}
                  onChange={(event) => setSelectedReleaseId(event.target.value)}
                >
                  <option value="">Select release</option>
                  {isDraftSelected && selectedRelease && (
                    <option value={selectedRelease.id}>
                      Draft: {selectedRelease.version} (not published)
                    </option>
                  )}
                  {availableReleases.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.version} ({item.status})
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}
          <div className="stack">
            <strong>Deployments</strong>
            {!selected?.deployments || selected.deployments.length === 0 ? (
              <span className="muted">No deployments recorded yet.</span>
            ) : (
              selected.deployments.map((dep) => (
                <div key={dep.instance_id} className="item-row">
                  <div>
                    <strong>{dep.instance_name}</strong>
                    <span className="muted small">{dep.instance_id}</span>
                  </div>
                  <div className="muted small">{dep.last_applied_at ?? "—"}</div>
                </div>
              ))
            )}
          </div>
          {selected?.last_run && (
            <div className="stack" data-tour="run-artifacts" data-testid="run-artifacts">
              <strong>Run artifacts</strong>
              {runArtifacts.length === 0 ? (
                <span className="muted">No artifacts yet.</span>
              ) : (
                runArtifacts.map((artifact) => (
                  <div key={artifact.id} className="item-row">
                    <div>
                      <strong>{artifact.name}</strong>
                      <span className="muted small">{artifact.kind ?? "artifact"}</span>
                    </div>
                    {artifact.url && (
                      <a className="link small" href={artifact.url} target="_blank" rel="noreferrer">
                        Open
                      </a>
                    )}
                  </div>
                ))
              )}
              <strong>Run logs</strong>
              <pre className="code-block">{runLogs || "No logs yet."}</pre>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
