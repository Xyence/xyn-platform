import { renderMarkdown } from "../markdown";
import type { WebSection } from "../types";

export default function HeroSection({ section }: { section: WebSection }) {
  const data = (section.data_json as Record<string, any>) || {};
  const kicker = data.kicker || "";
  const headline = data.headline || section.title || "";
  const subheadline = data.subheadline || "";
  const body = section.body_md || "";
  const primaryCta = data.primaryCta || null;
  const secondaryCta = data.secondaryCta || null;
  const imageUrl = data.imageUrl || null;

  return (
    <section className="public-section hero">
      <div className="hero-content">
        {kicker && <p className="eyebrow">{kicker}</p>}
        {headline && <h1>{headline}</h1>}
        {subheadline && <p className="lead">{subheadline}</p>}
        {body && (
          <div
            className="hero-body"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(body) }}
          />
        )}
        <div className="hero-actions">
          {primaryCta?.label && primaryCta?.href && (
            <a className="primary" href={primaryCta.href}>
              {primaryCta.label}
            </a>
          )}
          {secondaryCta?.label && secondaryCta?.href && (
            <a className="ghost" href={secondaryCta.href}>
              {secondaryCta.label}
            </a>
          )}
        </div>
      </div>
      {imageUrl && (
        <div className="hero-visual">
          <img src={imageUrl} alt="" />
        </div>
      )}
    </section>
  );
}
