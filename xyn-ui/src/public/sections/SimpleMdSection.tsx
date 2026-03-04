import { renderMarkdown } from "../markdown";
import type { WebSection } from "../types";

export default function SimpleMdSection({ section }: { section: WebSection }) {
  return (
    <section className="public-section">
      {section.title && <h2>{section.title}</h2>}
      {section.body_md && (
        <div
          className="markdown"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(section.body_md) }}
        />
      )}
    </section>
  );
}
