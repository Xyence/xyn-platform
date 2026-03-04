import type { WebSection } from "../types";

export default function QuoteSection({ section }: { section: WebSection }) {
  const data = (section.data_json as Record<string, any>) || {};
  const quote = data.quote || section.body_md || "";
  const author = data.author || section.title || "";
  const role = data.role || "";

  return (
    <section className="public-section quote">
      <blockquote>
        <p>{quote}</p>
        {(author || role) && (
          <footer>
            <strong>{author}</strong>
            {role && <span>{role}</span>}
          </footer>
        )}
      </blockquote>
    </section>
  );
}
