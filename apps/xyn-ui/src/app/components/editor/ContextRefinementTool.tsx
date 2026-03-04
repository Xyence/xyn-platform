import type { CSSProperties } from "react";

type Surface = "article" | "script" | "storyboard";

type ContextRefinementToolProps = {
  open: boolean;
  mobile: boolean;
  activeSurface: Surface;
  selectedText: string | null;
  videoSpecContext: { intent?: string; audience?: string; tone?: string; duration?: number | null } | null;
  agentOptions: Array<{ id: string; slug: string; name: string }>;
  selectedAgent: string;
  instruction: string;
  busy: boolean;
  anchorStyle?: CSSProperties;
  onSelectAgent: (slug: string) => void;
  onChangeInstruction: (value: string) => void;
  onRewrite: () => void;
  onSuggest: () => void;
  onClose: () => void;
};

function labelForSurface(surface: Surface): string {
  if (surface === "script") return "Video script";
  if (surface === "storyboard") return "Storyboard";
  return "Article";
}

export default function ContextRefinementTool({
  open,
  mobile,
  activeSurface,
  selectedText,
  videoSpecContext,
  agentOptions,
  selectedAgent,
  instruction,
  busy,
  anchorStyle,
  onSelectAgent,
  onChangeInstruction,
  onRewrite,
  onSuggest,
  onClose,
}: ContextRefinementToolProps) {
  if (!open) return null;
  const hasSelection = Boolean(selectedText && selectedText.trim());
  return (
    <div className="refinement-overlay" role="dialog" aria-label="Context refinement tool">
      <div className={`refinement-popover ${mobile ? "sheet" : ""}`} style={mobile ? undefined : anchorStyle}>
        <div className="card-header">
          <h4>{hasSelection ? "Refine Selection" : "Refine Content"}</h4>
          <button className="ghost sm" type="button" onClick={onClose}>
            Close
          </button>
        </div>
        <p className="muted small">Surface: {labelForSurface(activeSurface)}</p>
        <label>
          Refinement agent
          <select value={selectedAgent} onChange={(event) => onSelectAgent(event.target.value)}>
            {!agentOptions.length && <option value="">No refinement agents found</option>}
            {agentOptions.map((agent) => (
              <option key={agent.id} value={agent.slug}>
                {agent.name} ({agent.slug})
              </option>
            ))}
          </select>
        </label>
        <label>
          Refinement instruction (optional)
          <textarea
            className="input"
            rows={3}
            value={instruction}
            placeholder="Example: tighten clarity, simplify wording."
            onChange={(event) => onChangeInstruction(event.target.value)}
          />
        </label>
        {!hasSelection && <p className="muted small">Select text to refine specific content.</p>}
        {videoSpecContext && (
          <p className="muted small">Overall goals are defined in Explainer Video → Intent.</p>
        )}
        <div className="inline-actions">
          <button className="ghost sm" type="button" onClick={onRewrite} disabled={busy || !selectedAgent || !hasSelection}>
            Rewrite
          </button>
          <button className="primary sm" type="button" onClick={onSuggest} disabled={busy || !selectedAgent || !hasSelection}>
            Suggest edits
          </button>
        </div>
      </div>
    </div>
  );
}
