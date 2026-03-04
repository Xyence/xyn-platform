export default function WorkspaceHomePage({ workspaceName }: { workspaceName: string }) {
  return (
    <section className="card">
      <div className="card-header">
        <h3>Home</h3>
      </div>
      <p className="muted">Workspace: {workspaceName}</p>
      <p>Legible artifacts, provenance, and explicit promotion rules govern this workspace.</p>
    </section>
  );
}
