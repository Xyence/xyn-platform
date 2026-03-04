import { useMemo } from "react";
import { useLocation } from "react-router-dom";

function normalizeVariant(raw: string): "standard" | "explainer_video" {
  const value = String(raw || "").trim().toLowerCase();
  if (value === "explainer_video" || value === "video_explainer") return "explainer_video";
  return "standard";
}

export default function ArticleSurfaceDocsPage() {
  const location = useLocation();
  const params = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const variant = normalizeVariant(String(params.get("variant") || ""));

  return (
    <section className="card">
      <div className="card-header">
        <h3>Article Artifact Docs</h3>
      </div>
      <p className="muted">Manage surface opens the existing draft editor for the selected Article artifact.</p>
      <p className="muted">
        Variant mode:
        {" "}
        <strong>{variant}</strong>
      </p>
      <ul className="muted">
        <li>`standard` renders the standard article drafting workflow.</li>
        <li>`explainer_video` opens explainer mode (mapped to editor format `video_explainer`).</li>
      </ul>
    </section>
  );
}

