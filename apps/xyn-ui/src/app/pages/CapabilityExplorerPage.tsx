import { useEffect, useMemo, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import { getCapabilityGraph } from "../../api/xyn";
import type {
  CapabilityGraphCapability,
  CapabilityGraphContext,
  CapabilityGraphPath,
  CapabilityGraphResponse,
} from "../../api/types";

interface CapabilityExplorerLayoutProps {
  selectedContext: CapabilityGraphContext | null;
  contexts: CapabilityGraphContext[];
  capabilities: CapabilityGraphCapability[];
  paths: CapabilityGraphPath[];
  capabilityNameById: Map<string, string>;
  onSelectContext: (contextId: string) => void;
}

function CapabilityPreconditionList({
  capabilityId,
  preconditions,
}: {
  capabilityId: string;
  preconditions: NonNullable<CapabilityGraphCapability["preconditions"]>;
}) {
  if (!preconditions.length) return null;
  return (
    <ul className="capability-explorer-preconditions">
      {preconditions.map((precondition) => (
        <li key={`${capabilityId}:${precondition.guard_type}:${precondition.failure_code || ""}`}>
          <span className="muted small">
            {precondition.failure_message || precondition.failure_code || precondition.guard_type}
          </span>
        </li>
      ))}
    </ul>
  );
}

function CapabilityContextList({
  contexts,
  selectedContextId,
  onSelectContext,
}: {
  contexts: CapabilityGraphContext[];
  selectedContextId: string;
  onSelectContext: (contextId: string) => void;
}) {
  return (
    <section className="card">
      <div className="card-header">
        <h3>Contexts</h3>
      </div>
      <div className="capability-explorer-contexts">
        {contexts.map((context) => (
          <button
            key={context.id}
            type="button"
            className={`ghost capability-explorer-context ${selectedContextId === context.id ? "active" : ""}`}
            onClick={() => onSelectContext(context.id)}
          >
            <strong>{context.name}</strong>
            <span className="muted small">{context.description}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function CapabilityListSection({
  selectedContext,
  capabilities,
}: {
  selectedContext: CapabilityGraphContext | null;
  capabilities: CapabilityGraphCapability[];
}) {
  return (
    <section className="card">
      <div className="card-header">
        <h3>{selectedContext ? `${selectedContext.name} Capabilities` : "Capabilities"}</h3>
      </div>
      {selectedContext ? <p className="muted small">{selectedContext.description}</p> : null}
      {capabilities.length ? (
        <div className="capability-explorer-list">
          {capabilities.map((capability) => (
            <div key={capability.id} className="capability-explorer-item">
              <strong>{capability.name}</strong>
              <p className="muted small">{capability.description}</p>
              <div className="instance-meta">
                <span className="meta-pill">{capability.action_type}</span>
                <span className="muted small">{capability.id}</span>
              </div>
              <CapabilityPreconditionList capabilityId={capability.id} preconditions={capability.preconditions || []} />
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">No capabilities are mapped to this context.</p>
      )}
    </section>
  );
}

function CapabilityWorkflowSection({
  selectedContext,
  paths,
  capabilityNameById,
}: {
  selectedContext: CapabilityGraphContext | null;
  paths: CapabilityGraphPath[];
  capabilityNameById: Map<string, string>;
}) {
  return (
    <section className="card">
      <div className="card-header">
        <h3>{selectedContext ? `${selectedContext.name} Workflows` : "Workflows"}</h3>
      </div>
      {paths.length ? (
        <div className="capability-explorer-list">
          {paths.map((path) => (
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
  );
}

function CapabilityExplorerLayout({
  selectedContext,
  contexts,
  capabilities,
  paths,
  capabilityNameById,
  onSelectContext,
}: CapabilityExplorerLayoutProps) {
  return (
    <div className="capability-explorer-grid" data-testid="capability-explorer">
      <CapabilityContextList
        contexts={contexts}
        selectedContextId={selectedContext?.id || ""}
        onSelectContext={onSelectContext}
      />
      <CapabilityListSection selectedContext={selectedContext} capabilities={capabilities} />
      <CapabilityWorkflowSection selectedContext={selectedContext} paths={paths} capabilityNameById={capabilityNameById} />
    </div>
  );
}

export default function CapabilityExplorerPage() {
  const [graph, setGraph] = useState<CapabilityGraphResponse | null>(null);
  const [selectedContextId, setSelectedContextId] = useState("");
  const [loading, setLoading] = useState(true);
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
      {loading ? <p className="muted">Loading capability graph…</p> : null}
      {!loading ? (
        <CapabilityExplorerLayout
          selectedContext={selectedContext}
          contexts={graph?.contexts || []}
          capabilities={contextCapabilities}
          paths={contextPaths}
          capabilityNameById={capabilityNameById}
          onSelectContext={setSelectedContextId}
        />
      ) : null}
    </>
  );
}
