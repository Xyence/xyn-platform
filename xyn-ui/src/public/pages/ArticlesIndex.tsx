import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchPublicArticles } from "../../api/public";
import { useMenuItems } from "../PublicShell";
import type { PublicArticleSummary } from "../types";

type ArticlesIndexProps = {
  surfacePathOverride?: string;
};

export default function ArticlesIndex({ surfacePathOverride }: ArticlesIndexProps) {
  const { category } = useParams();
  const [articles, setArticles] = useState<PublicArticleSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { items: menuItems } = useMenuItems();
  const surfacePath = surfacePathOverride || (category ? `/${category}` : "/articles");

  const menuLabel = useMemo(() => {
    const label = menuItems.find((item) => item.path === surfacePath)?.label;
    if (label) return label;
    if (!category) return "Articles";
    return category
      .split("-")
      .filter(Boolean)
      .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
      .join(" ");
  }, [menuItems, surfacePath, category]);

  const articleBasePath = useMemo(() => {
    const trimmed = surfacePath.replace(/\/+$/, "");
    return trimmed || "/articles";
  }, [surfacePath]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    fetchPublicArticles(1, surfacePath)
      .then((data) => {
        if (!active) return;
        setArticles(data.items || []);
        setError(null);
      })
      .catch((err) => {
        if (!active) return;
        setError((err as Error).message);
      })
      .finally(() => {
        if (!active) return;
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [surfacePath]);

  if (loading) {
    return <p className="muted">Loading articles...</p>;
  }

  if (error) {
    return <p className="muted">{error}</p>;
  }

  if (!articles.length) {
    return <p className="muted">No articles published yet.</p>;
  }

  return (
    <div className="public-articles">
      <h1 className="page-title">{menuLabel}</h1>
      <div className="article-list">
        {articles.map((article) => (
          <article key={article.slug} className="article-card">
            <h2>{article.title}</h2>
            {article.summary && <p className="muted">{article.summary}</p>}
            <Link className="ghost" to={`${articleBasePath}/${article.slug}`}>
              Read article →
            </Link>
          </article>
        ))}
      </div>
    </div>
  );
}
