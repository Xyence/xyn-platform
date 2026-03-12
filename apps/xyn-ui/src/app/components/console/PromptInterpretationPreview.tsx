import type { PromptInterpretation, PromptInterpretationClarificationOption } from "../../../api/types";

type Props = {
  inputText: string;
  interpretation?: PromptInterpretation | null;
  resolutionStatus?: string | null;
  resolutionSummary?: string | null;
  loading?: boolean;
  onSelectClarificationOption?: (option: PromptInterpretationClarificationOption) => void;
};

function humanizeExecutionMode(value?: string): string {
  const label = {
    immediate_execution: "Immediate execution",
    queued_run: "Queued run",
    work_item_creation: "Create work item",
    work_item_continuation: "Continue work item",
    awaiting_clarification: "Awaiting clarification",
    awaiting_review: "Awaiting review",
    blocked: "Blocked",
  }[String(value || "").trim()];
  return label || `Unknown (${String(value || "n/a").trim() || "n/a"})`;
}

function capabilityLabel(state?: string): string {
  const label = {
    enabled: "Enabled capability",
    known_but_disabled: "Known but disabled",
    unavailable: "Unavailable",
    unknown: "Unknown",
  }[String(state || "").trim()];
  return label || `Unknown (${String(state || "n/a").trim() || "n/a"})`;
}

export default function PromptInterpretationPreview({
  inputText,
  interpretation,
  resolutionStatus,
  resolutionSummary,
  loading = false,
  onSelectClarificationOption,
}: Props) {
  const hasInput = Boolean(String(inputText || "").trim());
  if (!hasInput && !loading) return null;
  if (!interpretation && !loading && !resolutionStatus) return null;

  const clarification = Boolean(interpretation?.needs_clarification);
  const unsupported = String(interpretation?.intent_type || "") === "unsupported_declared_entity";

  return (
    <section className="xyn-console-card xyn-console-interpretation" aria-label="Prompt interpretation">
      <div className="xyn-console-card-head">
        <strong>Prompt interpretation</strong>
        <span className={`xyn-console-interpretation-mode ${clarification ? "clarify" : unsupported ? "warn" : "ready"}`}>
          {loading ? "Previewing…" : humanizeExecutionMode(interpretation?.execution_mode)}
        </span>
      </div>
      {interpretation ? (
        <>
          <div className="xyn-console-highlight-strip" aria-label="Recognized prompt elements">
            <span className="xyn-console-chip action">{interpretation.action.label}</span>
            {interpretation.target_entity?.label ? <span className={`xyn-console-chip capability-${interpretation.capability_state?.state || "unknown"}`}>{interpretation.target_entity.label}</span> : null}
            {interpretation.target_record?.reference ? <span className="xyn-console-chip record">{interpretation.target_record.reference}</span> : null}
            {interpretation.target_work_item?.label ? <span className="xyn-console-chip work">{interpretation.target_work_item.label}</span> : null}
            {interpretation.target_run?.label ? <span className="xyn-console-chip run">{interpretation.target_run.label}</span> : null}
            {interpretation.recognized_spans.map((span) => (
              <span key={`${span.kind}:${span.start}:${span.end}`} className={`xyn-console-chip span-${span.kind} state-${span.state || "recognized"}`}>
                {span.text}
              </span>
            ))}
          </div>

          <div className="xyn-console-interpretation-grid">
            <div>
              <span className="muted small">Action</span>
              <div>{interpretation.action.label}</div>
            </div>
            <div>
              <span className="muted small">Target</span>
              <div>{interpretation.target_entity?.label || interpretation.target_work_item?.label || interpretation.target_run?.label || "Not resolved"}</div>
            </div>
            <div>
              <span className="muted small">Capability</span>
              <div>{capabilityLabel(interpretation.capability_state?.state)}</div>
            </div>
            <div>
              <span className="muted small">Confidence</span>
              <div>{Math.round((Number(interpretation.confidence || 0) || 0) * 100)}%</div>
            </div>
          </div>

          {interpretation.fields.length ? (
            <div className="xyn-console-interpretation-block">
              <span className="muted small">Fields</span>
              <ul className="xyn-console-list">
                {interpretation.fields.map((field) => (
                  <li key={`${field.name}:${String(field.value)}`}>
                    <strong>{field.name}</strong>: {field.value == null || String(field.value) === "" ? <span className="muted">missing</span> : String(field.value)}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {interpretation.missing_fields.length ? (
            <div className="xyn-console-interpretation-block">
              <span className="muted small">Missing</span>
              <ul className="xyn-console-list">
                {interpretation.missing_fields.map((field) => (
                  <li key={field}>{field}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {interpretation.capability_state?.reason ? (
            <p className="muted small">
              {interpretation.capability_state.reason}
              {interpretation.capability_state.alternative ? ` Try: ${interpretation.capability_state.alternative}` : ""}
            </p>
          ) : null}

          {interpretation.needs_clarification ? (
            <div className="xyn-console-interpretation-block">
              <span className="muted small">Clarification required</span>
              <p>{interpretation.clarification_reason || "Target is ambiguous."}</p>
              {interpretation.clarification_options.length ? (
                <div className="xyn-console-options-list">
                  {interpretation.clarification_options.map((option) => (
                    <button key={option.id} type="button" className="ghost sm" onClick={() => onSelectClarificationOption?.(option)}>
                      {option.label}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </>
      ) : (
        <p className="muted small">
          {loading
            ? "Checking how Xyn would interpret this prompt…"
            : resolutionSummary || "Structured interpretation unavailable for this prompt path."}
        </p>
      )}
    </section>
  );
}
