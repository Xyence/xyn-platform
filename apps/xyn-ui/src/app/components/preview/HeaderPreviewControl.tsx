import { useEffect, useMemo, useRef, useState } from "react";
import { Eye } from "lucide-react";
import { usePreview } from "../../state/previewStore";

type Props = {
  actorRoles: string[];
  actorLabel: string;
  onMessage: (payload: { level: "success" | "error"; title: string; message?: string }) => void;
};

function allowedTargets(actorRoles: string[]): string[] {
  const set = new Set<string>();
  if (actorRoles.includes("platform_owner")) {
    ["platform_owner", "platform_admin", "platform_architect", "platform_operator", "app_user"].forEach((role) => set.add(role));
  }
  if (actorRoles.includes("platform_admin")) {
    ["platform_architect", "platform_operator", "app_user"].forEach((role) => set.add(role));
  }
  if (actorRoles.includes("platform_architect")) {
    ["platform_operator", "app_user"].forEach((role) => set.add(role));
  }
  return Array.from(set);
}

export default function HeaderPreviewControl({ actorRoles, actorLabel, onMessage }: Props) {
  const { preview, loading, enablePreviewMode, disablePreviewMode } = usePreview();
  const [open, setOpen] = useState(false);
  const [selectedRole, setSelectedRole] = useState<string>(preview.roles?.[0] || "");
  const containerRef = useRef<HTMLDivElement | null>(null);
  const options = useMemo(() => allowedTargets(actorRoles), [actorRoles]);

  useEffect(() => {
    if (preview.roles?.[0]) setSelectedRole(preview.roles[0]);
    else if (!selectedRole && options[0]) setSelectedRole(options[0]);
  }, [preview.roles, options, selectedRole]);

  useEffect(() => {
    const onDocClick = (event: MouseEvent) => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  if (options.length === 0) return null;

  const handleEnable = async () => {
    if (!selectedRole) return;
    try {
      await enablePreviewMode([selectedRole], true);
      onMessage({ level: "success", title: "Preview enabled", message: `Now previewing as ${selectedRole}.` });
      setOpen(false);
    } catch (err) {
      onMessage({ level: "error", title: "Preview rejected", message: (err as Error).message || "Request failed." });
    }
  };

  const handleDisable = async () => {
    try {
      await disablePreviewMode();
      onMessage({ level: "success", title: "Preview ended" });
      setOpen(false);
    } catch (err) {
      onMessage({ level: "error", title: "Exit preview failed", message: (err as Error).message || "Request failed." });
    }
  };

  return (
    <div className="preview-control" ref={containerRef}>
      <button
        type="button"
        className={`ghost notification-bell ${preview.enabled ? "preview-active" : ""}`}
        aria-label={preview.enabled ? `Preview active as ${preview.roles?.[0] || "role"}` : "Preview as role"}
        onClick={() => setOpen((value) => !value)}
      >
        <Eye size={16} />
      </button>
      {open ? (
        <section className="preview-popover" role="dialog" aria-label="Preview as role">
          <h4>Preview as role</h4>
          <p className="muted small">Signed in as {actorLabel || "current user"}</p>
          <label>
            Preview as
            <select value={selectedRole} onChange={(event) => setSelectedRole(event.target.value)}>
              {options.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </label>
          <label className="preview-readonly-row">
            <input type="checkbox" checked readOnly />
            <span>Read-only preview</span>
          </label>
          <div className="inline-actions">
            {!preview.enabled ? (
              <button type="button" className="primary" onClick={() => void handleEnable()} disabled={loading || !selectedRole}>
                Enable preview
              </button>
            ) : (
              <>
                <button type="button" className="ghost" onClick={() => void handleEnable()} disabled={loading || !selectedRole}>
                  Switch
                </button>
                <button type="button" className="primary" onClick={() => void handleDisable()} disabled={loading}>
                  Exit preview
                </button>
              </>
            )}
          </div>
        </section>
      ) : null}
    </div>
  );
}
