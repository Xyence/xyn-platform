import { useEffect, useState } from "react";
import type { IntentScript } from "../../../api/types";

type Props = {
  open: boolean;
  script: IntentScript | null;
  saving?: boolean;
  generationError?: string | null;
  onGoToBody?: () => void;
  onClose: () => void;
  onSave: (next: IntentScript) => Promise<void> | void;
};

function stripLegacyRouteLines(value: string): string {
  return String(value || "")
    .split("\n")
    .filter((line) => !line.trim().toLowerCase().startsWith("route:"))
    .join("\n");
}

function stripLegacyRouteFields(value: Record<string, unknown>): Record<string, unknown> {
  const copy = { ...value };
  const scenes = Array.isArray(copy.scenes) ? copy.scenes : [];
  copy.scenes = scenes.map((scene) => {
    if (!scene || typeof scene !== "object") return scene;
    const row = { ...(scene as Record<string, unknown>) };
    delete row.ui_route;
    delete row.route;
    delete row.highlights;
    delete row.assets;
    delete row.notes;
    delete row.duration_hint;
    return row;
  });
  return copy;
}

export default function IntentScriptModal({ open, script, saving = false, generationError = null, onGoToBody, onClose, onSave }: Props) {
  const [title, setTitle] = useState("");
  const [scriptText, setScriptText] = useState("");
  const [jsonText, setJsonText] = useState("{}");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !script) return;
    setTitle(script.title || "");
    setScriptText(stripLegacyRouteLines(script.script_text || ""));
    setJsonText(JSON.stringify(stripLegacyRouteFields((script.script_json || {}) as Record<string, unknown>), null, 2));
    setError(null);
  }, [open, script]);

  if (!open) return null;

  return (
    <div className="modal-backdrop" role="presentation" onClick={() => !saving && onClose()}>
      <div className="modal-card" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
        <h3>Intent Script</h3>
        <p className="muted small">Generated from article content (title/summary/body).</p>
        {generationError && (
          <div className="inline-message warn" style={{ marginTop: 8 }}>
            <span>{generationError}</span>
            {onGoToBody ? (
              <button type="button" className="ghost sm" onClick={onGoToBody}>
                Go to Body
              </button>
            ) : null}
          </div>
        )}
        {!script ? (
          <div className="inline-actions" style={{ marginTop: 12 }}>
            <button className="ghost" disabled={saving} onClick={onClose}>
              Close
            </button>
          </div>
        ) : (
          <>
        <div className="form-grid">
          <label>
            Title
            <input className="input" value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label>
            Script text
            <textarea className="input" rows={12} value={scriptText} onChange={(event) => setScriptText(event.target.value)} />
          </label>
          <label>
            Script JSON
            <textarea className="input" rows={12} value={jsonText} onChange={(event) => setJsonText(event.target.value)} />
          </label>
        </div>
        {error && <p className="error-text">{error}</p>}
        <div className="inline-actions" style={{ marginTop: 12 }}>
          <button
            className="primary"
            disabled={saving}
            onClick={async () => {
              setError(null);
              let parsed: Record<string, unknown> = {};
              try {
                parsed = JSON.parse(jsonText || "{}");
              } catch {
                setError("Script JSON is invalid.");
                return;
              }
              const next: IntentScript = {
                ...script,
                title: title.trim() || script.title,
                script_text: scriptText,
                script_json: parsed,
              };
              await onSave(next);
            }}
          >
            Save
          </button>
          <button className="ghost" disabled={saving} onClick={onClose}>
            Close
          </button>
        </div>
          </>
        )}
      </div>
    </div>
  );
}
