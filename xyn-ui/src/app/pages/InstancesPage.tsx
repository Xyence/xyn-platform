import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createInstance,
  destroyInstance,
  fetchBootstrapLog,
  fetchInstanceContainers,
  getInstance,
  listInstances,
  retryProvisionInstance,
  updateInstance,
} from "../../api/client";
import { createDevTask, getRelease, listEnvironments, listReleases } from "../../api/xyn";
import type {
  BootstrapLogResponse,
  ContainerInfo,
  CreateInstancePayload,
  EnvironmentSummary,
  ProvisionedInstance,
  ReleaseSummary,
} from "../../api/types";
import StatusPill from "../../components/StatusPill";
import InlineMessage from "../../components/InlineMessage";
import { useNotifications } from "../state/notificationsStore";
import { notifyQueued, notifySucceeded } from "../../lib/notifyFromJob";

const POLL_INTERVAL_MS = 5000;

const emptyPayload: CreateInstancePayload = {
  name: "",
  region: "",
  ami_id: "",
  instance_type: "t3.small",
  subnet_id: "",
  vpc_id: "",
  repo_url: "",
  iam_instance_profile_arn: "",
  iam_instance_profile_name: "",
  environment_id: "",
};

export default function InstancesPage() {
  const [instances, setInstances] = useState<ProvisionedInstance[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<ProvisionedInstance | null>(null);
  const [payload, setPayload] = useState<CreateInstancePayload>(emptyPayload);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logTail, setLogTail] = useState(200);
  const [bootstrapLog, setBootstrapLog] = useState<BootstrapLogResponse | null>(null);
  const [containers, setContainers] = useState<ContainerInfo[]>([]);
  const [containersError, setContainersError] = useState<string | null>(null);
  const [containersLoading, setContainersLoading] = useState(false);
  const [releaseMap, setReleaseMap] = useState<Record<string, ReleaseSummary>>({});
  const [environments, setEnvironments] = useState<EnvironmentSummary[]>([]);
  const [environmentId, setEnvironmentId] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("running");
  const [pendingEnvironmentId, setPendingEnvironmentId] = useState<string>("");
  const [showEnvConfirm, setShowEnvConfirm] = useState(false);
  const [forceEnvChange, setForceEnvChange] = useState(false);
  const { push } = useNotifications();

  const environmentNameById = useMemo(() => {
    return environments.reduce<Record<string, string>>((acc, env) => {
      acc[env.id] = env.name;
      return acc;
    }, {});
  }, [environments]);

  const selectedInstance = useMemo(
    () => instances.find((item) => item.id === selectedId) ?? selected,
    [instances, selected, selectedId]
  );

  const loadInstances = useCallback(async () => {
    try {
      setError(null);
      const data = await listInstances(environmentId || undefined);
      const filtered =
        statusFilter === "all"
          ? data.instances
          : data.instances.filter((instance) =>
              statusFilter === "running"
                ? instance.status === "running" || instance.status === "ready"
                : instance.status === statusFilter
            );
      setInstances(filtered);
      if (!selectedId && data.instances[0]) {
        setSelectedId(data.instances[0].id);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }, [environmentId, selectedId, statusFilter]);

  const refreshSelected = useCallback(async () => {
    if (!selectedId) return;
    try {
      const instance = await getInstance(selectedId, true);
      setSelected(instance);
      setInstances((prev) => prev.map((item) => (item.id === instance.id ? instance : item)));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [selectedId]);

  useEffect(() => {
    loadInstances();
  }, [loadInstances]);

  useEffect(() => {
    (async () => {
      try {
        const data = await listReleases();
        const map: Record<string, ReleaseSummary> = {};
        data.releases.forEach((item) => {
          map[item.id] = item;
        });
        setReleaseMap(map);
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
    if (!selectedId) return;
    setContainers([]);
    setContainersError(null);
    refreshSelected();
    const interval = window.setInterval(refreshSelected, POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [refreshSelected, selectedId]);

  useEffect(() => {
    if (!selectedId) return;
    handleFetchContainers();
  }, [selectedId]);

  useEffect(() => {
    if (!selectedInstance) return;
    setPendingEnvironmentId(selectedInstance.environment_id ?? "");
  }, [selectedInstance?.id, selectedInstance?.environment_id]);

  const handleEnvironmentChange = (nextId: string) => {
    if (!selectedInstance) return;
    if (!nextId) {
      setError("Instances must belong to an environment.");
      return;
    }
    if (nextId === (selectedInstance.environment_id ?? "")) {
      setPendingEnvironmentId(nextId);
      return;
    }
    setPendingEnvironmentId(nextId);
    setShowEnvConfirm(true);
  };

  const confirmEnvironmentChange = async () => {
    if (!selectedInstance || !pendingEnvironmentId) return;
    try {
      setLoading(true);
      setError(null);
      const updated = await updateInstance(selectedInstance.id, {
        environment_id: pendingEnvironmentId,
        force: forceEnvChange,
      });
      setInstances((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      setSelected(updated);
      await loadInstances();
      setShowEnvConfirm(false);
      setForceEnvChange(false);
      notifySucceeded(push, {
        action: "instance.environment.update",
        entityType: "instance",
        entityId: updated.id,
        title: "Instance environment updated",
        dedupeKey: `instance.environment.update:${updated.id}`,
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const cancelEnvironmentChange = () => {
    if (selectedInstance) {
      setPendingEnvironmentId(selectedInstance.environment_id ?? "");
    }
    setShowEnvConfirm(false);
    setForceEnvChange(false);
  };

  const handleCreate = async () => {
    try {
      setLoading(true);
      setError(null);
      const trimmed: CreateInstancePayload = {};
      (Object.entries(payload) as [keyof CreateInstancePayload, string | undefined][]).forEach(
        ([key, value]) => {
          if (value && String(value).trim().length > 0) {
            trimmed[key] = String(value).trim();
          }
        }
      );
      const created = await createInstance(trimmed);
      setInstances((prev) => [created, ...prev]);
      setSelectedId(created.id);
      setBootstrapLog(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleDestroy = async () => {
    if (!selectedId) return;
    if (!confirm("Destroy this instance?")) return;
    try {
      setLoading(true);
      setError(null);
      const updated = await destroyInstance(selectedId);
      setInstances((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      setSelected(updated);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleRetryProvision = async () => {
    if (!selectedId) return;
    try {
      setLoading(true);
      setError(null);
      const updated = await retryProvisionInstance(selectedId);
      setInstances((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      setSelected(updated);
      setBootstrapLog(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleLogFetch = async () => {
    if (!selectedId) return;
    try {
      setError(null);
      const log = await fetchBootstrapLog(selectedId, logTail);
      setBootstrapLog(log);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleFetchContainers = async () => {
    if (!selectedId) return;
    try {
      setContainersLoading(true);
      setContainersError(null);
      const data = await fetchInstanceContainers(selectedId);
      setContainers(data.containers || []);
    } catch (err) {
      setContainersError((err as Error).message);
    } finally {
      setContainersLoading(false);
    }
  };

  const handleDeployDesired = async () => {
    if (!selectedInstance) return;
    if (!selectedInstance.desired_release_id) {
      setError("No desired release set for this instance.");
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const release = await getRelease(selectedInstance.desired_release_id);
      if (!release.release_plan_id) {
        setError("Release has no release plan attached.");
        return;
      }
      const result = await createDevTask({
        title: `Deploy ${release.version}`,
        task_type: "deploy_release_plan",
        source_entity_type: "release_plan",
        source_entity_id: release.release_plan_id,
        source_run_id: release.created_from_run_id ?? null,
        input_artifact_key: "release_plan.json",
        context_purpose: "deployer",
        target_instance_id: selectedInstance.id,
        release_id: release.id,
      });
      notifyQueued(push, {
        action: "instance.deploy",
        entityType: "instance",
        entityId: selectedInstance.id,
        title: "Deploy queued",
        message: result.id,
        href: "/app/dev-tasks",
        dedupeKey: `instance.deploy:${selectedInstance.id}`,
      });
      await refreshSelected();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {showEnvConfirm && selectedInstance && (
        <div className="modal-backdrop">
          <div className="modal">
            <h3>Change instance environment?</h3>
            <p className="muted">
              This updates the instance's environment association. Deployments are only valid when the
              release plan environment matches the instance environment.
            </p>
            <div className="detail-grid">
              <div>
                <div className="label">Instance</div>
                <strong>{selectedInstance.name}</strong>
              </div>
              <div>
                <div className="label">Current environment</div>
                <span className="muted">
                  {environmentNameById[selectedInstance.environment_id ?? ""] ?? "None"}
                </span>
              </div>
              <div>
                <div className="label">New environment</div>
                <span className="muted">{environmentNameById[pendingEnvironmentId] ?? "None"}</span>
              </div>
            </div>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={forceEnvChange}
                onChange={(event) => setForceEnvChange(event.target.checked)}
              />
              Force change even if deployments are active
            </label>
            <div className="inline-actions">
              <button className="ghost" onClick={cancelEnvironmentChange} disabled={loading}>
                Cancel
              </button>
              <button className="primary" onClick={confirmEnvironmentChange} disabled={loading}>
                Confirm change
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="page-header">
        <div>
          <h2>Instances</h2>
          <p className="muted">Provision and monitor Xyn Seed instances.</p>
        </div>
        <div className="inline-actions">
          <select
            className="input"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="running">running</option>
            <option value="provisioning">provisioning</option>
            <option value="requested">requested</option>
            <option value="ready">ready</option>
            <option value="error">error</option>
            <option value="terminating">terminating</option>
            <option value="terminated">terminated</option>
            <option value="all">all</option>
          </select>
          <select
            className="input"
            value={environmentId}
            onChange={(event) => setEnvironmentId(event.target.value)}
          >
            <option value="">All environments</option>
            {environments.map((env) => (
              <option key={env.id} value={env.id}>
                {env.name}
              </option>
            ))}
          </select>
          <span className="meta-pill">Polling: {POLL_INTERVAL_MS / 1000}s</span>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}

      <div className="layout">
        <section className="card">
          <div className="card-header">
            <h3>Instances</h3>
            <button className="ghost" onClick={loadInstances} disabled={loading}>
              Refresh list
            </button>
          </div>

          <div className="instance-list" data-tour="instance-select" data-testid="instance-select">
            {instances.length === 0 && <p className="muted">No instances found.</p>}
            {instances.map((instance) => (
              <button
                key={instance.id}
                className={`instance-row ${selectedId === instance.id ? "active" : ""}`}
                onClick={() => setSelectedId(instance.id)}
              >
                <div>
                  <strong>{instance.name}</strong>
                  <span className="muted small">{instance.id}</span>
                  <span className="muted small">
                    Desired: {releaseMap[instance.desired_release_id ?? ""]?.version ?? "—"}
                  </span>
                  <span className="muted small">
                    Observed: {releaseMap[instance.observed_release_id ?? ""]?.version ?? "—"}
                  </span>
                </div>
                <StatusPill
                  status={
                    instance.health_status && instance.health_status !== "unknown"
                      ? instance.health_status
                      : instance.status
                  }
                />
              </button>
            ))}
          </div>
        </section>

        <section className="card">
          <div className="card-header">
            <h3>Provision</h3>
          </div>
          <div className="form-grid">
            <label>
              Name
              <input
                value={payload.name ?? ""}
                onChange={(event) => setPayload({ ...payload, name: event.target.value })}
                placeholder="xyn-seed-dev-1"
              />
            </label>
            <label>
              Region
              <input
                value={payload.region ?? ""}
                onChange={(event) => setPayload({ ...payload, region: event.target.value })}
                placeholder="us-west-2"
              />
            </label>
            <label>
              AMI ID
              <input
                value={payload.ami_id ?? ""}
                onChange={(event) => setPayload({ ...payload, ami_id: event.target.value })}
                placeholder="ami-xxxxxxxx"
              />
            </label>
            <label>
              Instance type
              <input
                value={payload.instance_type ?? ""}
                onChange={(event) => setPayload({ ...payload, instance_type: event.target.value })}
                placeholder="t3.small"
              />
            </label>
            <label>
              Subnet ID
              <input
                value={payload.subnet_id ?? ""}
                onChange={(event) => setPayload({ ...payload, subnet_id: event.target.value })}
                placeholder="subnet-xxxx"
              />
            </label>
            <label>
              VPC ID
              <input
                value={payload.vpc_id ?? ""}
                onChange={(event) => setPayload({ ...payload, vpc_id: event.target.value })}
                placeholder="vpc-xxxx"
              />
            </label>
            <label>
              Repo URL
              <input
                value={payload.repo_url ?? ""}
                onChange={(event) => setPayload({ ...payload, repo_url: event.target.value })}
                placeholder="https://github.com/xyence/xyn-seed"
              />
            </label>
            <label>
              IAM Instance Profile ARN
              <input
                value={payload.iam_instance_profile_arn ?? ""}
                onChange={(event) =>
                  setPayload({ ...payload, iam_instance_profile_arn: event.target.value })
                }
                placeholder="arn:aws:iam::123:instance-profile/..."
              />
            </label>
            <label>
              IAM Instance Profile Name
              <input
                value={payload.iam_instance_profile_name ?? ""}
                onChange={(event) =>
                  setPayload({ ...payload, iam_instance_profile_name: event.target.value })
                }
                placeholder="instance-profile-name"
              />
            </label>
            <label>
              Environment
              <select
                className="input"
                value={payload.environment_id ?? ""}
                onChange={(event) =>
                  setPayload((prev) => ({ ...prev, environment_id: event.target.value }))
                }
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
            <button className="primary" onClick={handleCreate} disabled={loading}>
              Create instance
            </button>
            <button className="danger" onClick={handleDestroy} disabled={!selectedId || loading}>
              Destroy instance
            </button>
          </div>
        </section>

        <section className="card">
          <div className="card-header">
            <h3>Release state</h3>
          </div>
          {!selectedInstance ? (
            <p className="muted">Select an instance to view release state.</p>
          ) : (
            <>
              <div className="detail-grid">
                <div>
                  <div className="label">Desired release</div>
                  <span className="muted">
                    {releaseMap[selectedInstance.desired_release_id ?? ""]?.version ??
                      selectedInstance.desired_release_id ??
                      "—"}
                  </span>
                </div>
                <div>
                  <div className="label">Observed release</div>
                  <span className="muted">
                    {releaseMap[selectedInstance.observed_release_id ?? ""]?.version ??
                      selectedInstance.observed_release_id ??
                      "—"}
                  </span>
                </div>
                <div>
                  <div className="label">Observed at</div>
                  <span className="muted">{selectedInstance.observed_at ?? "—"}</span>
                </div>
                <div>
                  <div className="label">Last deploy run</div>
                  {selectedInstance.last_deploy_run_id ? (
                    <a className="link" href={`/app/runs?run=${selectedInstance.last_deploy_run_id}`}>
                      {selectedInstance.last_deploy_run_id}
                    </a>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </div>
              </div>
              {selectedInstance.desired_release_id &&
                selectedInstance.desired_release_id !== selectedInstance.observed_release_id && (
                  <button className="primary" onClick={handleDeployDesired} disabled={loading}>
                    Deploy desired
                  </button>
                )}
            </>
          )}
        </section>

        <section className="card">
          <div className="card-header">
            <h3>Selected instance</h3>
          </div>
          {!selectedInstance ? (
            <p className="muted">Select an instance to see details.</p>
          ) : (
            <>
              <div className="detail-grid">
                <div>
                  <div className="label">Name</div>
                  <strong>{selectedInstance.name}</strong>
                </div>
                <div>
                  <div className="label">Status</div>
                  <StatusPill status={selectedInstance.status} />
                </div>
                <div>
                  <div className="label">Environment</div>
                  <select
                    className="input"
                    value={pendingEnvironmentId}
                    onChange={(event) => handleEnvironmentChange(event.target.value)}
                  >
                    <option value="">Select environment</option>
                    {environments.map((env) => (
                      <option key={env.id} value={env.id}>
                        {env.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <div className="label">Instance ID</div>
                  <span className="muted">{selectedInstance.instance_id || "—"}</span>
                </div>
                <div>
                  <div className="label">Region</div>
                  <span className="muted">{selectedInstance.aws_region || "—"}</span>
                </div>
                <div>
                  <div className="label">Public IP</div>
                  <span className="muted">{selectedInstance.public_ip || "—"}</span>
                </div>
                <div>
                  <div className="label">Private IP</div>
                  <span className="muted">{selectedInstance.private_ip || "—"}</span>
                </div>
              </div>
              {selectedInstance.last_error && (
                <InlineMessage tone="error" title="Instance error" body={selectedInstance.last_error} />
              )}
              {(selectedInstance.status === "error" || !selectedInstance.instance_id) && (
                <button className="ghost" onClick={handleRetryProvision} disabled={loading}>
                  Retry provisioning
                </button>
              )}
            </>
          )}
        </section>

        <section className="card">
          <div className="card-header">
            <h3>Bootstrap log</h3>
            <div className="inline-actions">
              <div className="inline-field">
                <label className="muted small">Tail</label>
                <input
                  type="number"
                  value={logTail}
                  onChange={(event) => setLogTail(Number(event.target.value))}
                />
              </div>
              <button className="ghost" onClick={handleLogFetch}>
                Fetch
              </button>
            </div>
          </div>
          {bootstrapLog ? (
            <div className="log-box">
              <div className="log-meta">
                <span>Status: {bootstrapLog.status}</span>
                <span>Instance: {bootstrapLog.instance_id}</span>
              </div>
              <pre>{bootstrapLog.stdout || "No output."}</pre>
              {bootstrapLog.stderr && (
                <div className="stderr">
                  <strong>stderr</strong>
                  <pre>{bootstrapLog.stderr}</pre>
                </div>
              )}
            </div>
          ) : (
            <p className="muted">Fetch the bootstrap log to view output.</p>
          )}
        </section>

        <section className="card">
          <div className="card-header">
            <h3>Containers</h3>
            <button
              className="ghost"
              onClick={handleFetchContainers}
              disabled={!selectedId || containersLoading}
            >
              {containersLoading ? "Loading..." : "Refresh"}
            </button>
          </div>
          {!selectedInstance ? (
            <p className="muted">Select an instance to view containers.</p>
          ) : (
            <>
              {containersError && (
                <InlineMessage tone="error" title="Container query failed" body={containersError} />
              )}
              {containers.length === 0 && !containersLoading ? (
                <p className="muted">No containers reported.</p>
              ) : (
                <div className="table">
                  <div className="table-row table-head">
                    <span>ID</span>
                    <span>Name</span>
                    <span>Image</span>
                    <span>Status</span>
                    <span>Ports</span>
                    <span></span>
                  </div>
                  {containers.map((container) => (
                    <div className="table-row" key={container.id}>
                      <span className="muted">{container.id.slice(0, 12)}</span>
                      <strong>{container.name}</strong>
                      <span className="muted">{container.image}</span>
                      <span className="muted">{container.status}</span>
                      <span className="muted">{container.ports || "—"}</span>
                      <span></span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </>
  );
}
