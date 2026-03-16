import { useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import Tabs from "../components/ui/Tabs";

type HubSection = "general" | "security" | "integrations" | "deploy" | "workspaces";

type SurfaceCard = {
  id: string;
  title: string;
  description: string;
  route: string;
  section: HubSection;
};

const SECTIONS: Array<{ value: HubSection; label: string; description: string }> = [
  { value: "general", label: "General", description: "Platform-wide defaults and metadata." },
  { value: "security", label: "Security", description: "Identity, roles, secrets, and governance." },
  { value: "integrations", label: "Integrations", description: "AI and rendering adapter integrations." },
  { value: "deploy", label: "Deploy", description: "Runtime/deploy controls and release entry points." },
  { value: "workspaces", label: "Workspaces", description: "Workspace governance and lifecycle management." },
];

const SURFACES: SurfaceCard[] = [
  {
    id: "access-control",
    title: "Access Control",
    description: "Manage users, roles, and access explorer.",
    route: "/app/platform/access-control",
    section: "security",
  },
  {
    id: "identity-configuration",
    title: "Identity Configuration",
    description: "Configure identity providers and OIDC app clients.",
    route: "/app/platform/identity-configuration",
    section: "security",
  },
  {
    id: "secrets",
    title: "Secrets",
    description: "Manage secret stores and secret references.",
    route: "/app/platform/secrets",
    section: "security",
  },
  {
    id: "activity",
    title: "Activity",
    description: "Review platform governance activity and contributions.",
    route: "/app/platform/activity",
    section: "security",
  },
  {
    id: "ai-agents",
    title: "AI Agents",
    description: "Manage agents, credentials, model configs, and purposes.",
    route: "/app/platform/ai-agents?tab=agents",
    section: "integrations",
  },
  {
    id: "rendering-settings",
    title: "Rendering Settings",
    description: "Configure renderer integrations and video adapter settings.",
    route: "/app/platform/rendering-settings",
    section: "integrations",
  },
  {
    id: "deploy-settings",
    title: "Deploy Settings",
    description: "Configure platform deploy and release-related settings.",
    route: "/app/platform/deploy",
    section: "deploy",
  },
  {
    id: "workspace-governance",
    title: "Workspaces",
    description: "Manage workspace profile/governance across the platform.",
    route: "/app/platform/workspaces",
    section: "workspaces",
  },
  {
    id: "platform-branding",
    title: "Branding",
    description: "Manage global branding defaults and application overrides.",
    route: "/app/platform/branding",
    section: "general",
  },
];

export default function PlatformSettingsHubPage({
  sectionOverride,
  onSectionChange,
}: {
  sectionOverride?: HubSection;
  onSectionChange?: (section: HubSection) => void;
}) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedSection = sectionOverride || String(searchParams.get("section") || "security").trim().toLowerCase();
  const activeSection = (SECTIONS.find((section) => section.value === requestedSection)?.value || "security") as HubSection;
  const cards = useMemo(() => SURFACES.filter((card) => card.section === activeSection), [activeSection]);

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Platform Settings</h2>
          <p className="muted">Global admin hub for security, integrations, deploy, and workspace governance.</p>
        </div>
      </div>

      <div className="page-tabs">
        <Tabs
          ariaLabel="Platform Settings sections"
          value={activeSection}
          options={SECTIONS.map((section) => ({ value: section.value, label: section.label }))}
          onChange={(nextSection) => {
            if (nextSection === activeSection) return;
            if (onSectionChange) {
              onSectionChange(nextSection as HubSection);
            } else {
              const next = new URLSearchParams(searchParams);
              next.set("section", nextSection);
              setSearchParams(next, { replace: true });
            }
          }}
        />
      </div>

      <section className="card" style={{ marginBottom: 12, padding: "12px 16px", gap: 0 }}>
        <p className="muted" style={{ margin: 0 }}>{SECTIONS.find((section) => section.value === activeSection)?.description}</p>
      </section>

      <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
        {cards.map((card) => (
          <section key={card.id} className="card" style={{ marginBottom: 0 }}>
            <div className="card-header">
              <h3>{card.title}</h3>
            </div>
            <p className="muted">{card.description}</p>
            <div className="form-actions">
              <button type="button" className="ghost" onClick={() => navigate(card.route)}>
                Open
              </button>
            </div>
          </section>
        ))}
        {!cards.length ? (
          <section className="card">
            <p className="muted">No surfaces found for this section.</p>
          </section>
        ) : null}
      </div>
    </>
  );
}
