import React from "react";

export type WorkspaceUnavailableReason = "not_found" | "access_denied" | "unknown";

export function classifyWorkspaceUnavailableReason(errorMessage: string): WorkspaceUnavailableReason {
  const message = String(errorMessage || "").toLowerCase();
  if (!message) return "unknown";
  if (
    message.includes("not authenticated") ||
    message.includes("access denied") ||
    message.includes("forbidden") ||
    message.includes("unauthorized") ||
    message.includes("(401)") ||
    message.includes("(403)")
  ) {
    return "access_denied";
  }
  if (
    message.includes("not found") ||
    message.includes("does not exist") ||
    message.includes("(404)")
  ) {
    return "not_found";
  }
  return "unknown";
}

export default function WorkspaceUnavailableState({
  itemLabel,
  workspaceLabel,
  reason,
  onOpenList,
  openListLabel,
}: {
  itemLabel: string;
  workspaceLabel: string;
  reason: WorkspaceUnavailableReason;
  onOpenList?: () => void;
  openListLabel?: string;
}) {
  let detail = `${itemLabel} is unavailable in this workspace.`;
  if (reason === "not_found") {
    detail = `${itemLabel} was not found in workspace ${workspaceLabel}.`;
  } else if (reason === "access_denied") {
    detail = `You do not have access to ${itemLabel.toLowerCase()} in workspace ${workspaceLabel}.`;
  }

  return (
    <section className="card stack" data-testid="workspace-unavailable-state">
      <h3>{itemLabel} unavailable</h3>
      <p className="muted">{detail}</p>
      {onOpenList ? (
        <div className="inline-action-row">
          <button type="button" className="ghost sm" onClick={onOpenList}>
            {openListLabel || "Open list"}
          </button>
        </div>
      ) : null}
    </section>
  );
}
