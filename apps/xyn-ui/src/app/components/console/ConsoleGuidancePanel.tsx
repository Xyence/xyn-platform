import { useMemo, useState } from "react";
import { useContextualCapabilities } from "./contextualCapabilities";
import { useExecutionPlan } from "./useExecutionPlan";
import CapabilityPlanSummary from "./CapabilityPlanSummary";

type Props = {
  onInsertSuggestion: (text: string) => void;
  dimmed?: boolean;
  context?: string;
  artifactId?: string | null;
  applicationId?: string | null;
};

const FALLBACK_PROMPTS = [
  { id: "fallback-build", name: "Build an application", description: "Create a new software application.", prompt_template: "Build an application that..." },
  { id: "fallback-article", name: "Write an article", description: "Create a written article artifact.", prompt_template: "Write an article about..." },
  { id: "fallback-video", name: "Create an explainer video", description: "Create a narrated explainer video artifact.", prompt_template: "Create an explainer video explaining..." },
  { id: "fallback-artifacts", name: "Explore artifacts", description: "View existing artifacts in the workspace.", prompt_template: "Show my artifacts" },
];

export default function ConsoleGuidancePanel({ onInsertSuggestion, dimmed = false, context, artifactId, applicationId }: Props) {
  const { capabilities } = useContextualCapabilities({ context, artifactId, applicationId });
  const [selectedCapabilityId, setSelectedCapabilityId] = useState<string>("");
  const prompts = useMemo(
    () => (capabilities.length ? capabilities : FALLBACK_PROMPTS).slice(0, 4),
    [capabilities]
  );
  const { loading, error, plan } = useExecutionPlan(selectedCapabilityId || null);

  return (
    <aside className={`xyn-console-guidance ${dimmed ? "is-dimmed" : ""}`} aria-label="Suggested actions">
      <div className="xyn-console-guidance-card">
        <h4>Suggested Actions</h4>
        <div className="xyn-console-options-list">
          {prompts.map((entry) => (
            <div key={entry.id} className="xyn-console-option-row">
              <button
                type="button"
                className="ghost sm"
                onClick={() => {
                  setSelectedCapabilityId(entry.id);
                  onInsertSuggestion(String(entry.prompt_template || entry.name || "").trim());
                }}
              >
                <span>{entry.name}</span>
                {entry.description ? <span className="muted small">{entry.description}</span> : null}
              </button>
              <button type="button" className="ghost sm" onClick={() => setSelectedCapabilityId(entry.id)}>
                View plan
              </button>
            </div>
          ))}
        </div>
      </div>
      {loading ? <div className="xyn-console-guidance-card"><p className="muted small">Loading plan…</p></div> : null}
      {!loading && error ? <div className="xyn-console-guidance-card"><p className="danger-text">{error}</p></div> : null}
      {!loading && plan ? <CapabilityPlanSummary plan={plan} /> : null}
      <div className="xyn-console-guidance-card">
        <h4>Quick start</h4>
        <ol className="xyn-console-steps">
          <li>Pick a suggested action or describe what you want.</li>
          <li>Review any draft or proposal Xyn produces.</li>
          <li>Refine or execute from the structured result.</li>
        </ol>
      </div>
    </aside>
  );
}
