import { useEffect, useMemo, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import { getControlPlaneState, triggerControlPlaneDeploy, triggerControlPlaneRollback } from "../../api/xyn";
import type { ControlPlaneStateItem, ControlPlaneStateResponse } from "../../api/types";

export default function ControlPlanePage() {
  const [data, setData] = useState<ControlPlaneStateResponse | null>(null);
  const [selectedEnvironment, setSelectedEnvironment] = useState("");
  const [selectedApp, setSelectedApp] = useState("xyn-api");
  const [selectedRelease, setSelectedRelease] = useState("");
  const [selectedInstance, setSelectedInstance] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async (environmentId?: string) => {
    try {
      setError(null);
      const payload = await getControlPlaneState(environmentId);
      setData(payload);
      if (!selectedEnvironment) {
        const firstEnv = payload.states[0]?.environment_id;
        if (firstEnv) setSelectedEnvironment(firstEnv);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const stateRows = useMemo(() => {
    if (!data) return [] as ControlPlaneStateItem[];
    return data.states.filter((row) => (!selectedEnvironment || row.environment_id === selectedEnvironment));
  }, [data, selectedEnvironment]);

  const releaseOptions = useMemo(() => {
    if (!data) return [];
    return data.releases.filter((row) => row.app_id === selectedApp);
  }, [data, selectedApp]);

  const instanceOptions = useMemo(() => {
    if (!data) return [];
    return data.instances.filter((row) => row.environment_id === selectedEnvironment);
  }, [data, selectedEnvironment]);

  const handleDeploy = async () => {
    if (!selectedEnvironment || !selectedRelease || !selectedApp) {
      setError("Select environment, app, and release.");
      return;
    }
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      const payload = await triggerControlPlaneDeploy({
        environment_id: selectedEnvironment,
        app_id: selectedApp,
        release_id: selectedRelease,
        instance_id: selectedInstance || undefined,
      });
      setMessage(
        payload.rollback_deployment_id
          ? `Deploy ${payload.deployment_id} failed and rollback ${payload.rollback_deployment_id} started.`
          : `Deploy ${payload.deployment_id} finished with status ${payload.status}.`
      );
      await load(selectedEnvironment);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleRollback = async (deploymentId?: string | null) => {
    if (!deploymentId) {
      setError("No deployment selected for rollback.");
      return;
    }
    if (!confirm("Trigger rollback to last known good release?")) return;
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      const payload = await triggerControlPlaneRollback({ deployment_id: deploymentId });
      setMessage(`Rollback ${payload.rollback_deployment_id} status: ${payload.rollback_status}`);
      await load(selectedEnvironment);
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
          <h2>Control Plane</h2>
          <p className="muted">Track current and last-known-good releases for Xyn core apps.</p>
        </div>
        <button className="ghost" onClick={() => load(selectedEnvironment)} disabled={loading}>
          Refresh
        </button>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <section className="card">
        <div className="card-header">
          <h3>Deploy Control Plane Release</h3>
        </div>
        <div className="form-grid">
          <label>
            Environment
            <select value={selectedEnvironment} onChange={(event) => setSelectedEnvironment(event.target.value)}>
              <option value="">Select environment</option>
              {Array.from(new Set((data?.states || []).map((item) => `${item.environment_id}|${item.environment_name}`))).map(
                (entry) => {
                  const [id, name] = entry.split("|");
                  return (
                    <option key={id} value={id}>
                      {name}
                    </option>
                  );
                }
              )}
            </select>
          </label>
          <label>
            App
            <select value={selectedApp} onChange={(event) => setSelectedApp(event.target.value)}>
              <option value="xyn-api">xyn-api</option>
              <option value="xyn-ui">xyn-ui</option>
            </select>
          </label>
          <label>
            Release
            <select value={selectedRelease} onChange={(event) => setSelectedRelease(event.target.value)}>
              <option value="">Select release</option>
              {releaseOptions.map((release) => (
                <option key={release.id} value={release.id}>
                  {release.version}
                </option>
              ))}
            </select>
          </label>
          <label>
            Instance (optional)
            <select value={selectedInstance} onChange={(event) => setSelectedInstance(event.target.value)}>
              <option value="">Auto-select</option>
              {instanceOptions.map((instance) => (
                <option key={instance.id} value={instance.id}>
                  {instance.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="actions" style={{ marginTop: 12 }}>
          <button className="primary" onClick={handleDeploy} disabled={loading}>
            Deploy release
          </button>
        </div>
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <div className="card-header">
          <h3>App State</h3>
        </div>
        <div className="instance-list">
          {stateRows.map((row) => (
            <div className="instance-row" key={`${row.environment_id}-${row.app_id}`}>
              <div>
                <strong>
                  {row.environment_name} - {row.display_name}
                </strong>
                <span className="muted small">
                  Current: {row.current_release_version || "-"} | Last good: {row.last_good_release_version || "-"} | Last deploy: {row.last_deployment_status || "-"}
                </span>
                {row.last_deployment_error ? <span className="muted small">{row.last_deployment_error}</span> : null}
              </div>
              <button className="ghost" onClick={() => handleRollback(row.last_deployment_id)} disabled={loading}>
                Roll back
              </button>
            </div>
          ))}
          {stateRows.length === 0 ? <p className="muted">No control plane state found yet.</p> : null}
        </div>
      </section>
    </>
  );
}
