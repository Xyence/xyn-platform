import { useNavigate } from "react-router-dom";

export default function PlatformRenderingSettingsPage() {
  const navigate = useNavigate();
  return (
    <>
      <div className="page-header">
        <div>
          <h2>Rendering Settings</h2>
          <p className="muted">Manage rendering adapters and video pipeline integration settings.</p>
        </div>
      </div>
      <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
        <section className="card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <h3>Video Adapter Configs</h3>
          </div>
          <p className="muted">Manage canonical adapter config artifacts and rendering endpoints.</p>
          <div className="form-actions">
            <button type="button" className="ghost" onClick={() => navigate("/app/platform/settings/legacy?tab=integrations")}>
              Open Adapter Settings
            </button>
          </div>
        </section>
        <section className="card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <h3>AI + Rendering Integration</h3>
          </div>
          <p className="muted">Open AI agents to manage model config dependencies used by rendering flows.</p>
          <div className="form-actions">
            <button type="button" className="ghost" onClick={() => navigate("/app/platform/ai-agents?tab=model-configs")}>
              Open Model Configs
            </button>
          </div>
        </section>
      </div>
    </>
  );
}

