import { useEffect, useMemo, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import { getCapabilityGraph } from "../../api/xyn";
import type { CapabilityGraphResponse } from "../../api/types";

export default function CapabilityExplorerPage() {
  const [graph, setGraph] = useState<CapabilityGraphResponse | null>(null);
  const [selectedContextId, setSelectedContextId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const payload = await getCapabilityGraph();
        if (!active) return;
        setGraph(payload);
        setSelectedContextId((current) => current || payload.contexts?.[0]?.id || "");
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load capability graph");
        setGraph(null);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const selectedContext = useMemo(
    () => graph?.contexts.find((entry) => entry.id === selectedContextId) || graph?.contexts?.[0] || null,
    [graph?.contexts, selectedContextId]
  );

  const contextCapabilities = useMemo(
    () => (graph?.capabilities || []).filter((entry) => entry.contexts.includes(selectedContext?.id || "")),
    [graph?.capabilities, selectedContext?.id]
  );

  const contextPaths = useMemo(
    () => (graph?.paths || []).filter((entry) => entry.contexts.includes(selectedContext?.id || "")),
    [graph?.paths, selectedContext?.id]
  );

  const capabilityNameById = useMemo(
    () =>
      new Map((graph?.capabilities || []).map((entry) => [entry.id, entry.name] as const)),
    [graph?.capabilities]
  );

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Capability Explorer</h2>
          <p className="muted">Browse contexts, capabilities, and workflows exposed by the platform capability graph.</p>
        </div>
      </div>
      {error ? <InlineMessage tone="error" title="Request failed" body={error} /> : null}
      <div className="capability-explorer-grid">
        <section className="card">
          <div className="card-header">
            <h3>Contexts</h3>
          </div>
          {loading ? <p className="muted">Loading capability graph…</p> : null}
          {!loading ? (
            <div className="capability-explorer-contexts">
              {(graph?.contexts || []).map((context) => (
                <button
                  key={context.id}
                  type="button"
                  className={`ghost capability-explorer-context ${selectedContext?.id === context.id ? "active" : ""}`}
                  onClick={() => setSelectedContextId(context.id)}
                >
                  <strong>{context.name}</strong>
                  <span className="muted small">{context.description}</span>
                </button>
              ))}
            </div>
          ) : null}
        </section>

        <section className="card">
          <div className="card-header">
            <h3>{selectedContext ? `${selectedContext.name} Capabilities` : "Capabilities"}</h3>
          </div>
          {selectedContext ? <p className="muted small">{selectedContext.description}</p> : null}
          {contextCapabilities.length ? (
            <div className="capability-explorer-list">
              {contextCapabilities.map((capability) => (
                <div key={capability.id} className="capability-explorer-item">
                  <strong>{capability.name}</strong>
                  <p className="muted small">{capability.description}</p>
                  <div className="instance-meta">
                    <span className="meta-pill">{capability.action_type}</span>
                    <span className="muted small">{capability.id}</span>
                  </div>
                  {capability.preconditions?.length ? (
                    <ul className="capability-explorer-preconditions">
                      {capability.preconditions.map((precondition) => (
                        <li key={`${capability.id}:${precondition.guard_type}:${precondition.failure_code || ""}`}>
                          <span className="muted small">
                            {precondition.failure_message || precondition.failure_code || precondition.guard_type}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">No capabilities are mapped to this context.</p>
          )}
        </section>

        <section className="card">
          <div className="card-header">
            <h3>{selectedContext ? `${selectedContext.name} Workflows` : "Workflows"}</h3>
          </div>
          {contextPaths.length ? (
            <div className="capability-explorer-list">
              {contextPaths.map((path) => (
                <div key={path.id} className="capability-explorer-item">
                  <strong>{path.name}</strong>
                  <p className="muted small">{path.description}</p>
                  <ol className="capability-explorer-steps">
                    {path.steps.map((stepId) => (
                      <li key={`${path.id}:${stepId}`}>{capabilityNameById.get(stepId) || stepId}</li>
                    ))}
                  </ol>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">No workflows are mapped to this context.</p>
          )}
        </section>
      </div>
    </>
  );
}
