export default function WorkspaceSettingsPage({ workspaceName }: { workspaceName: string }) {
  return (
    <section className="card">
      <div className="card-header">
        <h3>Settings</h3>
      </div>
      <p className="muted">Workspace settings for {workspaceName}.</p>
      <p>Lifecycle policy and verifier rules are represented in artifact metadata for this slice.</p>
    </section>
  );
}
