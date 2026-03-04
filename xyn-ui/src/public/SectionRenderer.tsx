import type { WebSection } from "./types";
import HeroSection from "./sections/HeroSection";
import FeatureGridSection from "./sections/FeatureGridSection";
import ServiceCardsSection from "./sections/ServiceCardsSection";
import CtaBandSection from "./sections/CtaBandSection";
import QuoteSection from "./sections/QuoteSection";
import SimpleMdSection from "./sections/SimpleMdSection";

function normalizeSection(section: WebSection): WebSection {
  if (typeof section.data_json === "string") {
    try {
      return { ...section, data_json: JSON.parse(section.data_json) };
    } catch {
      return { ...section, data_json: null };
    }
  }
  return section;
}

export default function SectionRenderer({ sections }: { sections: WebSection[] }) {
  return (
    <>
      {sections.map((rawSection) => {
        const section = normalizeSection(rawSection);
        switch (section.section_type) {
          case "hero":
            return <HeroSection key={section.key} section={section} />;
          case "feature_grid":
            return <FeatureGridSection key={section.key} section={section} />;
          case "service_cards":
            return <ServiceCardsSection key={section.key} section={section} />;
          case "cta_band":
            return <CtaBandSection key={section.key} section={section} />;
          case "quote":
            return <QuoteSection key={section.key} section={section} />;
          case "simple_md":
          default:
            return <SimpleMdSection key={section.key} section={section} />;
        }
      })}
    </>
  );
}
