import type { ExecutionPlan } from "../../../api/types";

function renderArchitectureValue(value: unknown): string {
  return typeof value === "string" && value.trim() ? value : "—";
}

export default function CapabilityPlanSummary({ plan, title = "Application Plan" }: { plan: ExecutionPlan; title?: string }) {
  const architectureEntries = Object.entries(plan.architecture || {}).filter(([, value]) => value != null && String(value).trim());
  return (
    <section className="card capability-plan-card">
      <h4>{title}</h4>
      {architectureEntries.length ? (
        <>
          <div className="field-label">Architecture</div>
          <div className="detail-grid">
            {architectureEntries.map(([key, value]) => (
              <div key={key}>
                <div className="field-label">{key.replace(/_/g, " ")}</div>
                <div className="field-value">{renderArchitectureValue(value)}</div>
              </div>
            ))}
          </div>
        </>
      ) : null}
      {Object.keys(plan.defaults || {}).length ? (
        <>
          <div className="field-label" style={{ marginTop: 12 }}>Defaults</div>
          <ul className="capability-plan-list">
            {Object.entries(plan.defaults || {}).map(([key, value]) => (
              <li key={key}>
                <strong>{key.replace(/_/g, " ")}:</strong> {renderArchitectureValue(value)}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {plan.dependencies.length ? (
        <>
          <div className="field-label" style={{ marginTop: 12 }}>Dependencies</div>
          <ul className="capability-plan-list">
            {plan.dependencies.map((entry) => <li key={entry}>{entry}</li>)}
          </ul>
        </>
      ) : null}
      {plan.components.length ? (
        <>
          <div className="field-label" style={{ marginTop: 12 }}>Components</div>
          <ul className="capability-plan-list">
            {plan.components.map((entry) => <li key={entry}>{entry}</li>)}
          </ul>
        </>
      ) : null}
      {plan.artifacts.length ? (
        <>
          <div className="field-label" style={{ marginTop: 12 }}>Artifacts</div>
          <ul className="capability-plan-list">
            {plan.artifacts.map((entry) => <li key={entry}>{entry}</li>)}
          </ul>
        </>
      ) : null}
    </section>
  );
}
