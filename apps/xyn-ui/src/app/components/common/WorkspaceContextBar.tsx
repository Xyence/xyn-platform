type Props = {
  workspaceName: string;
  workspaceColor?: string;
  className?: string;
  variant?: "default" | "compact";
};

export default function WorkspaceContextBar({
  workspaceName,
  workspaceColor = "#6c7a89",
  className = "",
  variant = "default",
}: Props) {
  return (
    <section className={`workspace-context-bar ${variant === "compact" ? "is-compact" : ""} ${className}`.trim()} aria-label="Workspace context">
      <div className="workspace-context-accent" style={{ background: workspaceColor }} aria-hidden="true" />
      <strong>{workspaceName || "Unknown"}</strong>
      <span className="workspace-dot" style={{ background: workspaceColor }} aria-hidden="true" />
      <span className="workspace-scope-pill">Workspace</span>
    </section>
  );
}
