import { useEffect, useMemo } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { toWorkspacePath } from "../routing/workspaceRouting";

function normalizeVariant(raw: string): string {
  const value = String(raw || "").trim().toLowerCase();
  if (value === "explainer_video" || value === "video_explainer") return "explainer_video";
  return "standard";
}

export default function ArticleSurfaceEditorRedirectPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const params = useParams();
  const workspaceId = String(params.workspaceId || "").trim();

  const search = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const artifactId =
    String(search.get("artifact_instance_id") || "").trim() ||
    String(search.get("draft_id") || "").trim() ||
    String(search.get("id") || "").trim();
  const variant = normalizeVariant(String(search.get("variant") || ""));

  useEffect(() => {
    if (!workspaceId || !artifactId) return;
    const target = `${toWorkspacePath(workspaceId, `build/artifacts/${artifactId}`)}?variant=${encodeURIComponent(variant)}`;
    navigate(target, { replace: true });
  }, [workspaceId, artifactId, variant, navigate]);

  if (!artifactId) {
    return (
      <section className="card">
        <h3>Article Editor Surface</h3>
        <p className="muted">Missing artifact identifier. Expected `id` or `artifact_instance_id` query param.</p>
      </section>
    );
  }

  return (
    <section className="card">
      <h3>Opening Article Editor…</h3>
      <p className="muted">Redirecting to the artifact draft editor.</p>
    </section>
  );
}

