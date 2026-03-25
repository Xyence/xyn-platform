import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

type SolutionsPageProps = {
  workspaceId: string;
};

export default function SolutionsPage({ workspaceId }: SolutionsPageProps) {
  const navigate = useNavigate();
  useEffect(() => {
    if (!workspaceId) return;
    // Deprecated compatibility route: keep this page redirect-only.
    // Solutions business logic belongs in workbench panels.
    const query = new URLSearchParams();
    query.set("panel", "solution_list");
    navigate(`/w/${encodeURIComponent(workspaceId)}/workbench?${query.toString()}`, { replace: true });
  }, [navigate, workspaceId]);

  return (
    <section className="card stack">
      <h2>Redirecting to Solutions Panel</h2>
      <p className="muted">Opening Solutions in Workbench.</p>
    </section>
  );
}
