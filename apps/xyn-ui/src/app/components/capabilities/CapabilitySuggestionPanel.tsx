import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useCapabilitiesForContext } from "../../capabilities/useCapabilitiesForContext";
import { executeCapabilityAction } from "../../navigation/executeCapabilityAction";

type Props = {
  context?: string;
  workspaceId?: string | null;
  entityId?: string | null;
  artifactId?: string | null;
  draftId?: string | null;
  executionId?: string | null;
  title?: string;
  limit?: number;
  className?: string;
  onInsertSuggestion: (text: string) => void;
};

export default function CapabilitySuggestionPanel({
  context,
  workspaceId,
  entityId,
  artifactId,
  draftId,
  executionId,
  title = "Suggested Actions",
  limit = 4,
  className = "",
  onInsertSuggestion,
}: Props) {
  const navigate = useNavigate();
  const resolvedEntityId = entityId || artifactId || draftId || executionId || null;
  const { capabilities } = useCapabilitiesForContext({
    context,
    entityId: resolvedEntityId,
    workspaceId,
    includeUnavailable: true,
  });

  const availableCapabilities = useMemo(
    () => capabilities.filter((entry) => entry.available !== false).slice(0, Math.max(limit, 1)),
    [capabilities, limit]
  );
  const unavailableCapabilities = useMemo(
    () => capabilities.filter((entry) => entry.available === false).slice(0, Math.max(limit, 1)),
    [capabilities, limit]
  );

  if (!availableCapabilities.length && !unavailableCapabilities.length) return null;

  return (
    <section className={`card capability-suggestion-panel ${className}`.trim()}>
      <div className="card-header">
        <h3>{title}</h3>
      </div>
      {availableCapabilities.length ? (
        <div className="xyn-console-options-list">
          {availableCapabilities.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className="ghost capability-suggestion-action"
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
          ))}
        </div>
      ) : null}
      {unavailableCapabilities.length ? (
        <div className="capability-suggestion-unavailable">
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
    </section>
  );
}
