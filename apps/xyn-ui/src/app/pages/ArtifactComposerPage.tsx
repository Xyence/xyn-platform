import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { getArtifact } from "../../api/xyn";
import type { UnifiedArtifact } from "../../api/types";

function toIsoDate(value: string): string {
  const raw = String(value || "").trim();
  if (!raw) return "Unknown";
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  return parsed.toLocaleString();
}

export default function ArtifactComposerPage({
  workspaceId,
}: {
  workspaceId: string;
}) {
  const { artifactId } = useParams();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [artifact, setArtifact] = useState<UnifiedArtifact | null>(null);
  const [objective, setObjective] = useState("");

  useEffect(() => {
    const targetId = String(artifactId || "").trim();
    if (!targetId) {
      setError("Missing artifact id.");
      setLoading(false);
      return;
    }
    let mounted = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const payload = await getArtifact(targetId);
        if (!mounted) return;
        setArtifact(payload);
        setObjective(`Refine artifact ${payload.slug || targetId} with a structured implementation plan.`);
      } catch (err) {
        if (!mounted) return;
        setError(err instanceof Error ? err.message : "Failed to load artifact.");
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [artifactId]);

  const artifactSlug = String(artifact?.slug || artifactId || "").trim();
  const artifactTitle = String(artifact?.title || artifact?.name || artifactSlug || "Artifact").trim();
  const legacyDetailPath = useMemo(
    () => `/w/${encodeURIComponent(workspaceId)}/build/artifacts/${encodeURIComponent(String(artifactId || ""))}/detail`,
    [artifactId, workspaceId]
  );

  const openComposer = (prompt: string) => {
    const params = new URLSearchParams();
    params.set("panel", "composer_detail");
    params.set("revise", "1");
    params.set("prompt", prompt);
    params.set("artifact_slug", artifactSlug);
    params.set("artifact_title", artifactTitle);
    params.set("artifact_type", String(artifact?.type || "Artifact"));
    navigate(`/w/${encodeURIComponent(workspaceId)}/workbench?${params.toString()}`);
  };

  if (loading) {
    return (
      <section className="card stack">
        <h2>Loading artifact composer</h2>
        <p className="muted">Preparing composer context…</p>
      </section>
    );
  }

  if (error || !artifact) {
    return (
      <section className="card stack">
        <h2>Artifact composer unavailable</h2>
        <p className="danger">{error || "Artifact record was not found."}</p>
        <div className="inline-action-row">
          <Link className="ghost sm" to={`/w/${encodeURIComponent(workspaceId)}/build/artifacts`}>
            Back to Installed
          </Link>
        </div>
      </section>
    );
  }

  return (
    <section className="stack" data-testid="artifact-composer-page">
      <section className="card stack">
        <header className="stack gap-2">
          <h2>{artifactTitle}</h2>
          <p className="muted">
            Composer-focused artifact workflow. Use this to plan, refine, stage, and hand off changes for <code>{artifactSlug}</code>.
          </p>
        </header>
        <div className="grid two-col">
          <div>
            <div className="field-label">Artifact</div>
            <div className="field-value">{artifactSlug}</div>
          </div>
          <div>
            <div className="field-label">Type</div>
            <div className="field-value">{String(artifact.type || "artifact")}</div>
          </div>
          <div>
            <div className="field-label">Version</div>
            <div className="field-value">{String(artifact.version || artifact.package_version || "n/a")}</div>
          </div>
          <div>
            <div className="field-label">Updated</div>
            <div className="field-value">{toIsoDate(String(artifact.updated_at || artifact.created_at || ""))}</div>
          </div>
        </div>
      </section>

      <section className="card stack">
        <h3>Change Objective</h3>
        <p className="muted">This objective seeds the composer conversation scoped to this artifact.</p>
        <textarea
          value={objective}
          onChange={(event) => setObjective(event.target.value)}
          rows={4}
          placeholder="Describe what should change in this artifact."
        />
        <div className="inline-action-row">
          <button type="button" className="primary" onClick={() => openComposer(objective)}>
            Open Artifact Composer
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() => openComposer(`Generate a structured implementation plan for artifact ${artifactSlug}. ${objective}`)}
          >
            Generate Plan
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() => openComposer(`Refine the current implementation plan for artifact ${artifactSlug}.`)}
          >
            Refine Plan
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() => openComposer(`Stage and apply the approved implementation plan for artifact ${artifactSlug}.`)}
          >
            Stage / Apply
          </button>
        </div>
      </section>

      <section className="card stack">
        <h3>Preview and Handoff</h3>
        <p className="muted">
          This links to the instance surface for preview/sibling workflow handoff. Full promotion automation remains a follow-on.
        </p>
        <div className="inline-action-row">
          <Link className="ghost sm" to={`/w/${encodeURIComponent(workspaceId)}/package/instances`}>
            Open Instances
          </Link>
          <Link className="ghost sm" to={legacyDetailPath}>
            Open Legacy Artifact Details
          </Link>
        </div>
      </section>
    </section>
  );
}

