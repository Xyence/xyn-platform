type Props = {
  onInsertSuggestion: (text: string) => void;
  dimmed?: boolean;
};

const QUICK_PROMPTS = [
  "Create an explainer video about Xyn governance ledger for telecom engineers.",
  "Create a guide about RBAC visualization",
  "Open my latest draft",
  "Add tags governance, ledger, access-control",
];

export default function ConsoleGuidancePanel({ onInsertSuggestion, dimmed = false }: Props) {
  return (
    <aside className={`xyn-console-guidance ${dimmed ? "is-dimmed" : ""}`} aria-label="Try this">
      <div className="xyn-console-guidance-card">
        <h4>Try this</h4>
        <div className="xyn-console-options-list">
          {QUICK_PROMPTS.map((prompt) => (
            <button key={prompt} type="button" className="ghost sm" onClick={() => onInsertSuggestion(prompt)}>
              {prompt}
            </button>
          ))}
        </div>
      </div>
      <div className="xyn-console-guidance-card">
        <h4>Quick start</h4>
        <ol className="xyn-console-steps">
          <li>Describe what you want.</li>
          <li>Create draft from the structured response.</li>
          <li>Refine in editor with Xyn.</li>
        </ol>
      </div>
    </aside>
  );
}
