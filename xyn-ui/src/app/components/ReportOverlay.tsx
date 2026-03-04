import { useEffect, useMemo, useState } from "react";
import { createReport } from "../../api/xyn";
import type { ReportContext, ReportPayload, ReportType } from "../../api/types";
import AttachmentDropzone from "./AttachmentDropzone";

type Props = {
  open: boolean;
  onClose: () => void;
  user?: { id?: string; email?: string };
  onSubmitted?: (reportId: string) => void;
};

function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function contextFromWindow(user?: { id?: string; email?: string }): ReportContext {
  const params = new URLSearchParams(window.location.search);
  const route = `${window.location.pathname}${window.location.search || ""}`;
  const blueprintIds = [params.get("blueprint"), params.get("blueprint_id")].filter(Boolean) as string[];
  const releaseIds = [params.get("release"), params.get("release_id")].filter(Boolean) as string[];
  const instanceIds = [params.get("instance"), params.get("instance_id")].filter(Boolean) as string[];
  return {
    url: window.location.href,
    route,
    build: {
      version: (import.meta.env.VITE_BUILD_VERSION as string | undefined) || "",
      commit: (import.meta.env.VITE_BUILD_COMMIT as string | undefined) || "",
    },
    user,
    blueprint_ids: blueprintIds,
    release_ids: releaseIds,
    instance_ids: instanceIds,
    client: {
      user_agent: navigator.userAgent,
      viewport: { w: window.innerWidth, h: window.innerHeight },
    },
    occurred_at_iso: new Date().toISOString(),
  };
}

export default function ReportOverlay({ open, onClose, user, onSubmitted }: Props) {
  const [type, setType] = useState<ReportType>("bug");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<"p0" | "p1" | "p2" | "p3">("p2");
  const [tagsText, setTagsText] = useState("");
  const [includeContext, setIncludeContext] = useState(true);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const context = useMemo(() => contextFromWindow(user), [user]);

  useEffect(() => {
    if (!open) return;
    const onEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onEsc);
    return () => window.removeEventListener("keydown", onEsc);
  }, [open, onClose]);

  if (!open) return null;

  const reset = () => {
    setType("bug");
    setTitle("");
    setDescription("");
    setPriority("p2");
    setTagsText("");
    setIncludeContext(true);
    setFiles([]);
    setError(null);
  };

  const handleSubmit = async () => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const payload: ReportPayload = {
        type,
        title: title.trim(),
        description: description.trim(),
        priority,
        tags: splitCsv(tagsText),
        context: includeContext ? context : undefined,
      };
      const result = await createReport(payload, files);
      setMessage(`Report submitted: ${result.id}`);
      onSubmitted?.(result.id);
      reset();
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="overlay-backdrop" onClick={onClose}>
      <section className="overlay-card" onClick={(event) => event.stopPropagation()}>
        <div className="card-header">
          <h3>Bug / Feature Report</h3>
          <button className="ghost" type="button" onClick={onClose}>
            Close
          </button>
        </div>

        {error && <div className="inline-message inline-error">{error}</div>}
        {message && <div className="inline-message inline-info">{message}</div>}

        <div className="form-grid">
          <label>
            Type
            <select value={type} onChange={(event) => setType(event.target.value as ReportType)}>
              <option value="bug">Bug</option>
              <option value="feature">Feature</option>
            </select>
          </label>
          <label>
            Priority
            <select value={priority} onChange={(event) => setPriority(event.target.value as "p0" | "p1" | "p2" | "p3") }>
              <option value="p0">p0</option>
              <option value="p1">p1</option>
              <option value="p2">p2</option>
              <option value="p3">p3</option>
            </select>
          </label>
          <label className="span-full">
            Title
            <input className="input" value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label className="span-full">
            Description
            <textarea value={description} onChange={(event) => setDescription(event.target.value)} />
          </label>
          <label className="span-full">
            Tags (comma)
            <input className="input" value={tagsText} onChange={(event) => setTagsText(event.target.value)} />
          </label>
          <label>
            Include context
            <select
              value={includeContext ? "yes" : "no"}
              onChange={(event) => setIncludeContext(event.target.value === "yes")}
            >
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </select>
          </label>
          <label>
            Debug bundle
            <button
              className="ghost"
              type="button"
              onClick={async () => {
                await navigator.clipboard.writeText(JSON.stringify(context, null, 2));
                setMessage("Debug bundle copied.");
              }}
            >
              Copy debug bundle
            </button>
          </label>
          {includeContext && (
            <label className="span-full">
              Context preview
              <textarea readOnly value={JSON.stringify(context, null, 2)} />
            </label>
          )}
        </div>

        <AttachmentDropzone files={files} onChange={setFiles} />

        <div className="form-actions">
          <button
            className="primary"
            type="button"
            disabled={busy || !title.trim() || !description.trim()}
            onClick={handleSubmit}
          >
            {busy ? "Submitting..." : "Submit report"}
          </button>
          <button className="ghost" type="button" onClick={reset} disabled={busy}>
            Reset
          </button>
        </div>
      </section>
    </div>
  );
}
