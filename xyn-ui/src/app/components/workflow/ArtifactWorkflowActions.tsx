import { useMemo, useState } from "react";
import Popover from "../ui/Popover";
import type { ArtifactWorkflowView, WorkflowAction, WorkflowActionId } from "../../workflows/artifactWorkflow";

type Props = {
  workflow: ArtifactWorkflowView;
  busyActionId?: WorkflowActionId | null;
  onRunAction: (action: WorkflowAction) => void;
};

function groupLabel(group: WorkflowAction["group"]): string {
  if (group === "workflow") return "Workflow";
  if (group === "revision") return "Revision";
  if (group === "position") return "Position / Vote";
  return "Danger zone";
}

export default function ArtifactWorkflowActions({ workflow, busyActionId = null, onRunAction }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const groups = useMemo(() => {
    const orderedGroups: WorkflowAction["group"][] = ["workflow", "revision", "position", "danger"];
    return orderedGroups
      .map((group) => ({
        group,
        label: groupLabel(group),
        actions: workflow.secondaryActions.filter((item) => item.group === group),
      }))
      .filter((entry) => entry.actions.length > 0);
  }, [workflow.secondaryActions]);

  return (
    <section className="card artifact-workflow-card">
      <div className="artifact-workflow-strip">
        <div className="artifact-workflow-summary">
          <span className={`status-pill status-${workflow.statusTone}`}>{workflow.statusLabel}</span>
          <div className="artifact-workflow-next-step">
            <strong>Next step</strong>
            <span>{workflow.nextStepLabel}</span>
          </div>
        </div>
        <div className="artifact-workflow-controls">
          {workflow.primaryAction ? (
            <button
              className={workflow.primaryAction.intent === "danger" ? "danger" : "primary"}
              onClick={() => onRunAction(workflow.primaryAction as WorkflowAction)}
              disabled={!workflow.primaryAction.enabled || busyActionId === workflow.primaryAction.id}
              title={workflow.primaryAction.disabledReason || undefined}
              aria-label={`Primary action: ${workflow.primaryAction.label}`}
            >
              {workflow.primaryAction.label}
            </button>
          ) : (
            <button className="ghost" disabled aria-label="No required action">
              No required action
            </button>
          )}
          <div className="artifact-workflow-actions-menu">
            <button
              type="button"
              className="ghost"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              aria-label="More artifact actions"
              onClick={() => setMenuOpen((value) => !value)}
            >
              Actions
            </button>
            <Popover open={menuOpen} onClose={() => setMenuOpen(false)} className="artifact-workflow-popover">
              <div className="artifact-workflow-menu" role="menu" aria-label="Artifact actions">
                {groups.map((entry, index) => (
                  <div key={entry.group}>
                    {index > 0 && <div className="xyn-menu-divider" />}
                    <div className="artifact-workflow-menu-group-label">{entry.label}</div>
                    {entry.actions.map((action) => (
                      <button
                        key={action.id}
                        type="button"
                        role="menuitem"
                        className={`xyn-menu-item ${!action.enabled ? "disabled" : ""}`}
                        disabled={!action.enabled || busyActionId === action.id}
                        title={action.disabledReason || undefined}
                        onClick={() => {
                          onRunAction(action);
                          setMenuOpen(false);
                        }}
                      >
                        <span>{action.label}</span>
                        {!action.enabled && action.disabledReason && (
                          <span className="muted small artifact-workflow-action-reason">{action.disabledReason}</span>
                        )}
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            </Popover>
          </div>
        </div>
      </div>
      {workflow.blockers.length > 0 && (
        <div className="artifact-workflow-blockers">
          <strong>Blocking requirements</strong>
          <ul>
            {workflow.blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
