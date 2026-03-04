import type { KeyboardEvent as ReactKeyboardEvent } from "react";

type Props = {
  contextLine: string;
  statusLine: string;
  processing: boolean;
  inputText: string;
  onInputChange: (value: string) => void;
  onInputKeyDown: (event: ReactKeyboardEvent<HTMLTextAreaElement>) => void;
  onSubmit: () => void;
  onClear: () => void;
  canSubmit: boolean;
  textareaRef: React.RefObject<HTMLTextAreaElement>;
  pendingCloseBlock: boolean;
};

export default function ConsolePromptCard({
  contextLine,
  statusLine,
  processing,
  inputText,
  onInputChange,
  onInputKeyDown,
  onSubmit,
  onClear,
  canSubmit,
  textareaRef,
  pendingCloseBlock,
}: Props) {
  return (
    <section className="xyn-console-prompt-card" aria-label="Xyn prompt">
      <header className="xyn-console-prompt-head">
        <div>
          <h3>Xyn</h3>
          <p className="muted small">{contextLine}</p>
        </div>
        <div className="xyn-console-prompt-status muted small" aria-live="polite">
          {processing ? statusLine : "Ready"}
        </div>
      </header>

      <div className="xyn-console-prompt-body">
        <textarea
          ref={textareaRef}
          rows={5}
          value={inputText}
          onChange={(event) => onInputChange(event.target.value)}
          onKeyDown={onInputKeyDown}
          placeholder="Describe what you want to create or change..."
          disabled={processing}
        />
        <div className="xyn-console-prompt-actions">
          <button type="button" className="ghost sm" onClick={onClear} disabled={processing || (!inputText.trim() && !pendingCloseBlock)}>
            Clear
          </button>
          <button type="button" className="primary sm" onClick={onSubmit} disabled={!canSubmit}>
            Submit
          </button>
        </div>
      </div>

      {processing ? (
        <div className="xyn-console-prompt-glass" role="status" aria-live="assertive">
          <div className="xyn-console-prompt-glass-card">
            <span className="spinner sm" aria-hidden="true" />
            <strong>{statusLine}</strong>
            <p className="muted small">Please wait. Input is temporarily locked.</p>
          </div>
        </div>
      ) : null}
    </section>
  );
}
