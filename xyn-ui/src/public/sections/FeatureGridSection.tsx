import type { WebSection } from "../types";

export default function FeatureGridSection({ section }: { section: WebSection }) {
  const data = (section.data_json as Record<string, any>) || {};
  const items = Array.isArray(data.items) ? data.items : [];

  return (
    <section className="public-section">
      {section.title && <h2>{section.title}</h2>}
      <div className="feature-grid">
        {items.map((item: any, index: number) => (
          <article key={item.title ?? index} className="feature-card">
            {item.icon && <div className="feature-icon">{item.icon}</div>}
            <h3>{item.title}</h3>
            {item.body && <p>{item.body}</p>}
          </article>
        ))}
      </div>
    </section>
  );
}
