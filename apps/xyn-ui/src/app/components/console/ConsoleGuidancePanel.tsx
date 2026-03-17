import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useContextualCapabilities } from "./contextualCapabilities";
import { useCapabilityPaths } from "./capabilityPaths";
import { useExecutionPlan } from "./useExecutionPlan";
import CapabilityPlanSummary from "./CapabilityPlanSummary";
import { executeCapabilityAction } from "../../navigation/executeCapabilityAction";
import type { ContextualCapability } from "../../../api/types";
import CapabilityPathPanel from "./CapabilityPathPanel";

type Props = {
  onInsertSuggestion: (text: string) => void;
  dimmed?: boolean;
  context?: string;
  entityId?: string | null;
  workspaceId?: string | null;
  artifactId?: string | null;
  applicationId?: string | null;
};

const FALLBACK_PROMPTS = [
  { id: "fallback-build", name: "Build an application", description: "Create a new software application.", prompt_template: "Build an application that...", visibility: "primary", action_type: "prompt" },
  { id: "fallback-article", name: "Write an article", description: "Create a written article artifact.", prompt_template: "Write an article about...", visibility: "primary", action_type: "prompt" },
  { id: "fallback-video", name: "Create an explainer video", description: "Create a narrated explainer video artifact.", prompt_template: "Create an explainer video explaining...", visibility: "primary", action_type: "prompt" },
  { id: "fallback-artifacts", name: "Explore artifacts", description: "View existing artifacts in the workspace.", prompt_template: "Show my artifacts", visibility: "secondary", action_type: "prompt" },
];

export default function ConsoleGuidancePanel({
  onInsertSuggestion,
  dimmed = false,
  context,
  entityId,
  workspaceId,
  artifactId,
  applicationId,
}: Props) {
  const navigate = useNavigate();
  const resolvedEntityId = entityId || artifactId || applicationId || null;
  const { capabilities } = useContextualCapabilities({
    context,
    entityId: resolvedEntityId,
    workspaceId,
    includeUnavailable: true,
  });
  const { paths, selectedPath, selectedPathId, setSelectedPath } = useCapabilityPaths({ context, entityId: resolvedEntityId, workspaceId });
  const [selectedCapabilityId, setSelectedCapabilityId] = useState<string>("");
  const availableCapabilities = useMemo(
    () => capabilities.filter((entry) => entry.available !== false),
    [capabilities]
  );
  const unavailableCapabilities = useMemo(
    () => capabilities.filter((entry) => entry.available === false),
    [capabilities]
  );
  const prompts = useMemo(
    () => ((capabilities.length ? availableCapabilities : FALLBACK_PROMPTS) as ContextualCapability[]).slice(0, 4),
    [availableCapabilities, capabilities.length]
  );
  const { loading, error, plan } = useExecutionPlan(selectedCapabilityId || null);

  return (
    <aside className={`xyn-console-guidance ${dimmed ? "is-dimmed" : ""}`} aria-label="Suggested actions">
      <div className="xyn-console-guidance-card">
        <h4>Suggested Actions</h4>
        <div className="xyn-console-options-list">
          {prompts.map((entry) => (
            <div key={entry.id} className="xyn-console-option-row">
              <button
                type="button"
                className="ghost sm"
                onClick={() => {
                  executeCapabilityAction({
                    capability: entry,
                    navigate,
                    workspaceId,
                    entityId: resolvedEntityId,
                    insertPrompt: onInsertSuggestion,
                  });
                }}
              >
                <span>{entry.name}</span>
                {entry.description ? <span className="muted small">{entry.description}</span> : null}
              </button>
              <button type="button" className="ghost sm" onClick={() => setSelectedCapabilityId(entry.id)}>
                View plan
              </button>
            </div>
          ))}
        </div>
      </div>
      {unavailableCapabilities.length ? (
        <div className="xyn-console-guidance-card">
          <h4>Unavailable Right Now</h4>
          <div className="xyn-console-options-list">
            {unavailableCapabilities.map((entry) => (
              <div key={entry.id} className="xyn-console-option-disabled" aria-disabled="true">
                <strong>{entry.name}</strong>
                {entry.failure_message ? <span className="muted small">{entry.failure_message}</span> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {loading ? <div className="xyn-console-guidance-card"><p className="muted small">Loading plan…</p></div> : null}
      {!loading && error ? <div className="xyn-console-guidance-card"><p className="danger-text">{error}</p></div> : null}
      {!loading && plan ? <CapabilityPlanSummary plan={plan} /> : null}
      {selectedPath ? (
        <CapabilityPathPanel
          paths={paths}
          selectedPath={selectedPath}
          selectedPathId={selectedPathId}
          onSelectPath={setSelectedPath}
          workspaceId={workspaceId}
          entityId={resolvedEntityId}
          onInsertSuggestion={onInsertSuggestion}
        />
      ) : null}
      <div className="xyn-console-guidance-card">
        <h4>Quick start</h4>
        <ol className="xyn-console-steps">
          <li>Pick a suggested action or describe what you want.</li>
          <li>Review any draft or proposal Xyn produces.</li>
          <li>Refine or execute from the structured result.</li>
        </ol>
      </div>
    </aside>
  );
}
