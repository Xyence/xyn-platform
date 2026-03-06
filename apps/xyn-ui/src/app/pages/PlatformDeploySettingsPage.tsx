import { useNavigate } from "react-router-dom";

export default function PlatformDeploySettingsPage() {
  const navigate = useNavigate();
  return (
    <>
      <div className="page-header">
        <div>
          <h2>Deploy Settings</h2>
          <p className="muted">Global deploy controls and release entry points.</p>
        </div>
      </div>
      <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
        <section className="card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <h3>Seed Packs</h3>
          </div>
          <p className="muted">Manage seed packs and deployment packs used for provisioning.</p>
          <div className="form-actions">
            <button type="button" className="ghost" onClick={() => navigate("/app/platform/seeds")}>
              Open Seed Packs
            </button>
          </div>
        </section>
        <section className="card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <h3>Legacy Deploy Controls</h3>
          </div>
          <p className="muted">Temporary fallback until deploy controls are fully migrated out of legacy settings.</p>
          <div className="form-actions">
            <button type="button" className="ghost" onClick={() => navigate("/app/platform/settings/legacy?tab=deploy")}>
              Open Legacy Deploy Tab
            </button>
          </div>
        </section>
      </div>
    </>
  );
}

