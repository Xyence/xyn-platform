import type { WebSection } from "../types";

export default function ServiceCardsSection({ section }: { section: WebSection }) {
  const data = (section.data_json as Record<string, any>) || {};
  const items = Array.isArray(data.items) ? data.items : [];

  return (
    <section className="public-section">
      {section.title && <h2>{section.title}</h2>}
      <div className="service-grid">
        {items.map((item: any, index: number) => (
          <article key={item.title ?? index} className="service-card">
            <h3>{item.title}</h3>
            {Array.isArray(item.bullets) && (
              <ul>
                {item.bullets.map((bullet: string, idx: number) => (
                  <li key={`${item.title ?? index}-bullet-${idx}`}>{bullet}</li>
                ))}
              </ul>
            )}
            {item.href && item.label && (
              <a className="ghost" href={item.href}>
                {item.label}
              </a>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
