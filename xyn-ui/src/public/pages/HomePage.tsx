import { useEffect, useState } from "react";
import { fetchPublicHome } from "../../api/public";
import SectionRenderer from "../SectionRenderer";
import type { WebSection } from "../types";

export default function HomePage() {
  const [sections, setSections] = useState<WebSection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPublicHome()
      .then((data) => {
        setSections(data.sections || []);
        setError(null);
      })
      .catch((err) => {
        setError((err as Error).message);
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <p className="muted">Loading...</p>;
  }

  if (error) {
    return <p className="muted">{error}</p>;
  }

  if (!sections.length) {
    return <p className="muted">No content published yet.</p>;
  }

  return <SectionRenderer sections={sections} />;
}
