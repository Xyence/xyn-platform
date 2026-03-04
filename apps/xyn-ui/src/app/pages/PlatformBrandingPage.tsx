import { useCallback, useEffect, useMemo, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import {
  getAppBrandingOverride,
  getPlatformBranding,
  listOidcAppClients,
  updateAppBrandingOverride,
  updatePlatformBranding,
} from "../../api/xyn";
import type { AppBrandingOverride, PlatformBranding } from "../../api/types";

const emptyGlobal: PlatformBranding = {
  brand_name: "Xyn",
  logo_url: "",
  favicon_url: "",
  primary_color: "#0f4c81",
  background_color: "#f5f7fb",
  background_gradient: "",
  text_color: "#10203a",
  font_family: "",
  button_radius_px: 12,
};

const emptyOverride = (appId: string): AppBrandingOverride => ({
  app_id: appId,
  display_name: "",
  logo_url: "",
  primary_color: "",
  background_color: "",
  background_gradient: "",
  text_color: "",
  font_family: "",
  button_radius_px: null,
});

export default function PlatformBrandingPage() {
  const [globalBranding, setGlobalBranding] = useState<PlatformBranding>(emptyGlobal);
  const [appIds, setAppIds] = useState<string[]>([]);
  const [selectedAppId, setSelectedAppId] = useState<string>("xyn-ui");
  const [override, setOverride] = useState<AppBrandingOverride>(emptyOverride("xyn-ui"));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [globalData, clients] = await Promise.all([getPlatformBranding(), listOidcAppClients()]);
      setGlobalBranding(globalData);
      const ids = Array.from(new Set(["xyn-ui", ...clients.oidc_app_clients.map((item) => item.app_id)])).sort();
      setAppIds(ids);
      const app = ids.includes(selectedAppId) ? selectedAppId : ids[0] || "xyn-ui";
      setSelectedAppId(app);
      const appOverride = await getAppBrandingOverride(app);
      setOverride(appOverride);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [selectedAppId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    (async () => {
      try {
        const appOverride = await getAppBrandingOverride(selectedAppId);
        setOverride(appOverride);
      } catch {
        setOverride(emptyOverride(selectedAppId));
      }
    })();
  }, [selectedAppId]);

  const previewStyle = useMemo(
    () => ({
      background: override.background_gradient || override.background_color || globalBranding.background_color,
      color: override.text_color || globalBranding.text_color,
      fontFamily: override.font_family || globalBranding.font_family || "inherit",
      borderRadius: `${override.button_radius_px ?? globalBranding.button_radius_px}px`,
      border: "1px solid rgba(16,32,58,0.18)",
      padding: "12px",
    }),
    [globalBranding, override]
  );

  const handleSaveGlobal = async () => {
    try {
      setLoading(true);
      setError(null);
      const saved = await updatePlatformBranding(globalBranding);
      setGlobalBranding(saved);
      setMessage("Global branding updated.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleSaveOverride = async () => {
    try {
      setLoading(true);
      setError(null);
      const saved = await updateAppBrandingOverride(selectedAppId, override);
      setOverride(saved);
      setMessage(`Branding override saved for ${selectedAppId}.`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Branding</h2>
          <p className="muted">Configure shared login branding tokens and per-app overrides.</p>
          <p className="muted">
            App overrides are keyed by <code>app_key</code>. Generated web apps default to their component name (for example
            <code> web</code>) unless explicitly overridden in deployment settings.
          </p>
        </div>
        <button className="ghost" onClick={load} disabled={loading}>
          Refresh
        </button>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <div className="layout">
        <section className="card">
          <div className="card-header">
            <h3>Global branding</h3>
          </div>
          <div className="form-grid">
            <label>
              Brand name
              <input className="input" value={globalBranding.brand_name} onChange={(e) => setGlobalBranding({ ...globalBranding, brand_name: e.target.value })} />
            </label>
            <label>
              Logo URL
              <input className="input" value={globalBranding.logo_url || ""} onChange={(e) => setGlobalBranding({ ...globalBranding, logo_url: e.target.value })} />
            </label>
            <label>
              Favicon URL
              <input className="input" value={globalBranding.favicon_url || ""} onChange={(e) => setGlobalBranding({ ...globalBranding, favicon_url: e.target.value })} />
            </label>
            <label>
              Primary color
              <input className="input" type="color" value={globalBranding.primary_color} onChange={(e) => setGlobalBranding({ ...globalBranding, primary_color: e.target.value })} />
            </label>
            <label>
              Background color
              <input className="input" type="color" value={globalBranding.background_color} onChange={(e) => setGlobalBranding({ ...globalBranding, background_color: e.target.value })} />
            </label>
            <label>
              Background gradient
              <input className="input" value={globalBranding.background_gradient || ""} onChange={(e) => setGlobalBranding({ ...globalBranding, background_gradient: e.target.value })} placeholder="linear-gradient(...)" />
            </label>
            <label>
              Text color
              <input className="input" type="color" value={globalBranding.text_color} onChange={(e) => setGlobalBranding({ ...globalBranding, text_color: e.target.value })} />
            </label>
            <label>
              Font family
              <input className="input" value={globalBranding.font_family || ""} onChange={(e) => setGlobalBranding({ ...globalBranding, font_family: e.target.value })} />
            </label>
            <label>
              Button radius (px)
              <input className="input" type="number" min={0} max={32} value={globalBranding.button_radius_px} onChange={(e) => setGlobalBranding({ ...globalBranding, button_radius_px: Number(e.target.value) || 0 })} />
            </label>
          </div>
          <div className="form-actions">
            <button className="primary" onClick={handleSaveGlobal} disabled={loading}>
              Save global branding
            </button>
          </div>
        </section>

        <section className="card">
          <div className="card-header">
            <h3>Per-app overrides</h3>
          </div>
          <div className="form-grid">
            <label>
              App
              <select value={selectedAppId} onChange={(e) => setSelectedAppId(e.target.value)}>
                {appIds.map((appId) => (
                  <option key={appId} value={appId}>
                    {appId}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Display name
              <input className="input" value={override.display_name || ""} onChange={(e) => setOverride({ ...override, app_id: selectedAppId, display_name: e.target.value })} />
            </label>
            <label>
              Logo URL
              <input className="input" value={override.logo_url || ""} onChange={(e) => setOverride({ ...override, app_id: selectedAppId, logo_url: e.target.value })} />
            </label>
            <label>
              Primary color
              <input className="input" type="color" value={override.primary_color || globalBranding.primary_color} onChange={(e) => setOverride({ ...override, app_id: selectedAppId, primary_color: e.target.value })} />
            </label>
            <label>
              Background color
              <input className="input" type="color" value={override.background_color || globalBranding.background_color} onChange={(e) => setOverride({ ...override, app_id: selectedAppId, background_color: e.target.value })} />
            </label>
            <label>
              Background gradient
              <input className="input" value={override.background_gradient || ""} onChange={(e) => setOverride({ ...override, app_id: selectedAppId, background_gradient: e.target.value })} placeholder="linear-gradient(...)" />
            </label>
            <label>
              Text color
              <input className="input" type="color" value={override.text_color || globalBranding.text_color} onChange={(e) => setOverride({ ...override, app_id: selectedAppId, text_color: e.target.value })} />
            </label>
            <label>
              Font family
              <input className="input" value={override.font_family || ""} onChange={(e) => setOverride({ ...override, app_id: selectedAppId, font_family: e.target.value })} />
            </label>
            <label>
              Button radius (px)
              <input className="input" type="number" min={0} max={32} value={override.button_radius_px ?? globalBranding.button_radius_px} onChange={(e) => setOverride({ ...override, app_id: selectedAppId, button_radius_px: Number(e.target.value) })} />
            </label>
          </div>
          <div className="form-actions">
            <button className="primary" onClick={handleSaveOverride} disabled={loading}>
              Save app override
            </button>
          </div>
          <div style={previewStyle}>
            <strong>{override.display_name || globalBranding.brand_name}</strong>
            <p className="muted">Preview of shared login card style.</p>
            <button className="ghost" style={{ borderRadius: `${override.button_radius_px ?? globalBranding.button_radius_px}px` }}>
              Continue
            </button>
          </div>
        </section>
      </div>
    </>
  );
}
