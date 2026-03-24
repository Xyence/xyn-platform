import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";

type SolutionDetailPageProps = {
  workspaceId: string;
};

export default function SolutionDetailPage({ workspaceId }: SolutionDetailPageProps) {
  const navigate = useNavigate();
  const params = useParams<{ applicationId: string }>();
  const applicationId = String(params.applicationId || "").trim();

  useEffect(() => {
    if (!workspaceId || !applicationId) return;
    // Deprecated compatibility route: keep this page redirect-only.
    // Solution/session business logic belongs in workbench panels.
    const query = new URLSearchParams();
    query.set("panel", "solution_detail");
    query.set("application_id", applicationId);
    navigate(`/w/${encodeURIComponent(workspaceId)}/workbench?${query.toString()}`, { replace: true });
  }, [applicationId, navigate, workspaceId]);

  return (
    <section className="card stack">
      <h2>Redirecting to Solution Panel</h2>
      <p className="muted">Opening solution detail in Workbench.</p>
    </section>
  );
}
