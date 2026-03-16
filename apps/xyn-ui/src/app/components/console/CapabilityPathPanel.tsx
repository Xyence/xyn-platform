import { useNavigate } from "react-router-dom";
import type { CapabilityPath } from "../../../api/types";
import { executeCapabilityAction } from "../../navigation/executeCapabilityAction";

function statusMarker(status?: string): string {
  switch (String(status || "").trim().toLowerCase()) {
    case "completed":
      return "✔";
    case "current":
      return "→";
    default:
      return "";
  }
}

export default function CapabilityPathPanel({
  paths,
  selectedPath,
  selectedPathId,
  onSelectPath,
  workspaceId,
  entityId,
  onInsertSuggestion,
}: {
  paths: CapabilityPath[];
  selectedPath: CapabilityPath;
  selectedPathId: string;
  onSelectPath: (pathId: string) => void;
  workspaceId?: string | null;
  entityId?: string | null;
  onInsertSuggestion: (text: string) => void;
}) {
  const navigate = useNavigate();
  const showSelector = paths.length > 1;

  return (
    <div className="xyn-console-guidance-card" aria-label="Guided workflow">
      <h4>{showSelector ? "Guided Workflows" : "Guided Workflow"}</h4>
      {showSelector ? (
        <label className="muted small" style={{ display: "block", marginBottom: 8 }}>
          Workflow
          <select
            aria-label="Select guided workflow"
            value={selectedPathId}
            onChange={(event) => onSelectPath(event.target.value)}
            style={{ display: "block", width: "100%", marginTop: 6 }}
          >
            {paths.map((path) => (
              <option key={path.id} value={path.id}>
                {path.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <strong>{selectedPath.name}</strong>
      <p className="muted small">{selectedPath.description}</p>
      <ol className="xyn-console-steps">
        {selectedPath.steps.map((step) => (
          <li key={`${selectedPath.id}:${step.capability_id}`}>
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
              <span>
                {statusMarker(step.status) ? `${statusMarker(step.status)} ` : ""}
                {step.name}
              </span>
              <span className="muted small">{step.description}</span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
