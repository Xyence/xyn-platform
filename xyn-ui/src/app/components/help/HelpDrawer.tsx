import { Link } from "react-router-dom";
import { X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { createDoc, getDocByRoute } from "../../../api/xyn";
import type { DocPage } from "../../../api/types";
import { renderMarkdown } from "../../../public/markdown";
import AtlasFlow from "./AtlasFlow";
import { getRouteHelp } from "../../help/routeHelp";

type HelpDrawerProps = {
  open: boolean;
  onClose: () => void;
  routeId: string;
  workspaceId?: string;
  roles: string[];
  onStartTour?: (slug: string) => void;
};

function defaultSlug(input: string): string {
  return input
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

export default function HelpDrawer({ open, onClose, routeId, workspaceId, roles, onStartTour }: HelpDrawerProps) {
  const [doc, setDoc] = useState<DocPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const help = useMemo(() => getRouteHelp(routeId), [routeId]);
  const canEdit = roles.includes("platform_admin") || roles.includes("platform_architect");

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const result = await getDocByRoute(routeId, workspaceId);
        if (!cancelled) {
          setDoc(result.doc);
        }
      } catch (err) {
        if (!cancelled) {
          setError((err as Error).message);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, routeId, workspaceId]);

  const handleCreateDoc = async () => {
    try {
      setCreating(true);
      setError(null);
      const created = await createDoc({
        title: help.title,
        slug: defaultSlug(help.routeId),
        route_bindings: [help.routeId],
        tags: ["guide"],
        body_markdown: `# ${help.title}\n\nDocument this page intent and operational guardrails.`,
      });
      setDoc(created.doc);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCreating(false);
    }
  };

  return (
    <>
      {open && <button type="button" className="notification-backdrop" aria-label="Close help" onClick={onClose} />}
      <aside className={`help-drawer ${open ? "open" : ""}`} aria-label="Page help">
        <div className="notification-drawer-header">
          <h3>Page Help</h3>
          <button type="button" className="ghost" onClick={onClose} aria-label="Close help drawer">
            <X size={14} />
          </button>
        </div>

        <div className="help-drawer-body">
          <section className="help-section">
            <h4>What you do here</h4>
            <ul>
              {help.whatYouDo.map((bullet) => (
                <li key={bullet}>{bullet}</li>
              ))}
            </ul>
          </section>

          <section className="help-section">
            <h4>Where this sits in the flow</h4>
            <AtlasFlow current={help.atlasNode} />
          </section>

          <section className="help-section">
            <h4>Common next steps</h4>
            <div className="help-next-steps">
              {help.nextSteps.map((step) => (
                <Link key={`${step.to}:${step.label}`} className="link" to={step.to}>
                  {step.label}
                </Link>
              ))}
            </div>
            <button className="ghost small" onClick={() => onStartTour?.("deploy-subscriber-notes")}>Start "Deploy Subscriber Notes" tour</button>
          </section>

          <section className="help-section">
            <h4>Route-bound doc</h4>
            {loading && <p className="muted">Loading doc…</p>}
            {!loading && !doc && <p className="muted">No doc for this page yet.</p>}
            {!loading && !doc && canEdit && (
              <button className="ghost" onClick={handleCreateDoc} disabled={creating}>
                {creating ? "Creating…" : "Create doc draft"}
              </button>
            )}
            {error && <p className="error-text">{error}</p>}
            {doc && (
              <>
                <div className="muted small">
                  Updated {doc.updated_at || "—"}
                  {doc.updated_by_email ? ` by ${doc.updated_by_email}` : ""}
                </div>
                {canEdit && <Link className="link" to={`/app/guides?edit=${encodeURIComponent(doc.slug)}`}>Edit this doc</Link>}
                <div className="markdown-body" dangerouslySetInnerHTML={{ __html: renderMarkdown(doc.body_markdown) }} />
              </>
            )}
          </section>
        </div>
      </aside>
    </>
  );
}
