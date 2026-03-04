import type { WebSection } from "../types";

export default function CtaBandSection({ section }: { section: WebSection }) {
  const data = (section.data_json as Record<string, any>) || {};
  const headline = data.headline || section.title || "";
  const body = data.body || section.body_md || "";
  const cta = data.cta || null;

  return (
    <section className="public-section cta-band">
      <div>
        {headline && <h2>{headline}</h2>}
        {body && <p>{body}</p>}
      </div>
      {cta?.label && cta?.href && (
        <a className="primary" href={cta.href}>
          {cta.label}
        </a>
      )}
    </section>
  );
}
