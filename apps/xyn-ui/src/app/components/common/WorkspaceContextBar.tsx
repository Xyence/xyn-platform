type Props = {
  workspaceName: string;
  workspaceColor?: string;
  className?: string;
};

export default function WorkspaceContextBar({ workspaceName, workspaceColor = "#6c7a89", className = "" }: Props) {
  return (
    <section className={`workspace-context-bar ${className}`.trim()} aria-label="Workspace context">
      <div className="workspace-context-accent" style={{ background: workspaceColor }} aria-hidden="true" />
      <strong>Workspace: {workspaceName || "Unknown"}</strong>
      <span className="workspace-dot" style={{ background: workspaceColor }} aria-hidden="true" />
      <span className="workspace-scope-pill">Scope: Workspace</span>
    </section>
  );
}
