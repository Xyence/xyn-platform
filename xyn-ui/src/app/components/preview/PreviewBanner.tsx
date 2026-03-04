import { usePreview } from "../../state/previewStore";

type Props = {
  actorLabel: string;
  onExit: () => Promise<void>;
};

export default function PreviewBanner({ actorLabel, onExit }: Props) {
  const { preview, loading } = usePreview();
  if (!preview.enabled) return null;
  return (
    <div className="preview-banner" role="status" aria-live="polite">
      <div>
        <strong>Previewing as: {preview.roles?.[0] || "role"}</strong>
        <span className="muted"> You are still signed in as {actorLabel || "current user"}.</span>
        {preview.read_only ? <span className="preview-chip">Read-only</span> : null}
      </div>
      <button type="button" className="ghost" onClick={() => void onExit()} disabled={loading}>
        Exit preview
      </button>
    </div>
  );
}
