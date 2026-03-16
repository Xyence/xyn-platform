import { useNavigate } from "react-router-dom";
import type { CapabilityPath } from "../../../api/types";
import { executeCapabilityAction } from "../../navigation/executeCapabilityAction";

export default function CapabilityPathPanel({
  path,
  workspaceId,
  entityId,
  onInsertSuggestion,
}: {
  path: CapabilityPath;
  workspaceId?: string | null;
  entityId?: string | null;
  onInsertSuggestion: (text: string) => void;
}) {
  const navigate = useNavigate();

  return (
    <div className="xyn-console-guidance-card" aria-label="Guided workflow">
      <h4>Guided Workflow</h4>
      <strong>{path.name}</strong>
      <p className="muted small">{path.description}</p>
      <ol className="xyn-console-steps">
        {path.steps.map((step) => (
          <li key={`${path.id}:${step.capability_id}`}>
            <button
              type="button"
              className="ghost sm"
              onClick={() =>
                executeCapabilityAction({
                  capability: {
                    id: step.capability_id,
                    name: step.name,
                    description: step.description,
                    prompt_template: step.prompt_template,
                    visibility: step.visibility,
                    priority: step.priority,
                    action_type: step.action_type,
                    action_target: step.action_target,
                  },
                  navigate,
                  workspaceId,
                  entityId,
                  insertPrompt: onInsertSuggestion,
                })
              }
            >
              <span>{step.name}</span>
              <span className="muted small">{step.description}</span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
