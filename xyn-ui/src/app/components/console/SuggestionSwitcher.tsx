import { useEffect, useMemo, useState } from "react";
import { useCapabilitySuggestions, type CapabilityEntry, type CapabilitySuggestion } from "./capabilitySuggestions";
import { useXynConsole } from "../../state/xynConsoleStore";

function isTypingTarget(target: EventTarget | null): boolean {
  const node = target as HTMLElement | null;
  if (!node) return false;
  if (node.isContentEditable) return true;
  const tag = String(node.tagName || "").toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select";
}

export default function SuggestionSwitcher({ workspaceId }: { workspaceId: string }) {
  const { suggestionSwitcherOpen, openSuggestionSwitcher, closeSuggestionSwitcher, setInputText, setOpen, requestSubmit } = useXynConsole();
  const { capabilities, platform } = useCapabilitySuggestions(workspaceId);
  const capabilityBuckets = useMemo<CapabilityEntry[]>(() => {
    const rows = [...capabilities, ...platform];
    return rows.filter((entry) => entry.suggestions.length > 0);
  }, [capabilities, platform]);
  const [capabilityIndex, setCapabilityIndex] = useState(0);
  const [suggestionIndex, setSuggestionIndex] = useState(0);

  useEffect(() => {
    if (!capabilityBuckets.length) {
      setCapabilityIndex(0);
      setSuggestionIndex(0);
      return;
    }
    setCapabilityIndex((current) => {
      const next = Math.max(0, Math.min(current, capabilityBuckets.length - 1));
      const maxSuggestions = capabilityBuckets[next]?.suggestions.length || 0;
      setSuggestionIndex((inner) => Math.max(0, Math.min(inner, Math.max(0, maxSuggestions - 1))));
      return next;
    });
  }, [capabilityBuckets]);

  const activeCapability = capabilityBuckets[capabilityIndex] || null;
  const activeSuggestions = activeCapability?.suggestions || [];
  const highlighted = activeSuggestions[suggestionIndex] || null;

  const runSuggestion = (entry: CapabilitySuggestion | null) => {
    if (!entry) return;
    const prompt = String(entry.prompt || "").trim();
    if (!prompt) return;
    setInputText(prompt);
    setOpen(true);
    requestSubmit();
    closeSuggestionSwitcher();
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const key = event.key;
      const isMeta = event.metaKey || event.ctrlKey;
      const isNextCapability = isMeta && event.shiftKey && key === "]";
      const isPrevCapability = isMeta && event.shiftKey && key === "[";
      const isNextSuggestion = isMeta && !event.shiftKey && key === ";";
      if (isNextCapability || isPrevCapability || isNextSuggestion) {
        if (isTypingTarget(event.target)) return;
        event.preventDefault();
        if (!capabilityBuckets.length) {
          openSuggestionSwitcher();
          return;
        }
        if (!suggestionSwitcherOpen) openSuggestionSwitcher();
        if (isNextCapability) {
          setCapabilityIndex((current) => (current + 1) % capabilityBuckets.length);
          setSuggestionIndex(0);
          return;
        }
        if (isPrevCapability) {
          setCapabilityIndex((current) => (current - 1 + capabilityBuckets.length) % capabilityBuckets.length);
          setSuggestionIndex(0);
          return;
        }
        if (isNextSuggestion) {
          const count = capabilityBuckets[capabilityIndex]?.suggestions.length || 0;
          if (!count) return;
          setSuggestionIndex((current) => (current + 1) % count);
        }
      }
      if (!suggestionSwitcherOpen) return;
      if (key === "Escape") {
        event.preventDefault();
        closeSuggestionSwitcher();
        return;
      }
      if (key === "Enter") {
        event.preventDefault();
        runSuggestion(highlighted);
        return;
      }
      if (key === "ArrowDown") {
        event.preventDefault();
        const count = activeSuggestions.length;
        if (!count) return;
        setSuggestionIndex((current) => (current + 1) % count);
        return;
      }
      if (key === "ArrowUp") {
        event.preventDefault();
        const count = activeSuggestions.length;
        if (!count) return;
        setSuggestionIndex((current) => (current - 1 + count) % count);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    activeSuggestions.length,
    capabilityBuckets,
    capabilityIndex,
    closeSuggestionSwitcher,
    highlighted,
    openSuggestionSwitcher,
    suggestionSwitcherOpen,
  ]);

  if (!suggestionSwitcherOpen) return null;

  return (
    <div className="suggestion-switcher-overlay" role="dialog" aria-label="Suggestion Switcher">
      <div className="suggestion-switcher-card">
        <header className="suggestion-switcher-head">
          <strong>Suggestion Switcher</strong>
          <button type="button" className="ghost sm" onClick={closeSuggestionSwitcher}>
            Close
          </button>
        </header>
        {!activeCapability ? (
          <p className="muted small">No capability suggestions are available for this workspace.</p>
        ) : (
          <>
            <p className="muted small">
              Capability: <strong>{activeCapability.title}</strong>
            </p>
            <div className="suggestion-switcher-capabilities">
              {capabilityBuckets.map((entry, idx) => (
                <button
                  key={entry.key}
                  type="button"
                  className={`ghost sm ${idx === capabilityIndex ? "active" : ""}`}
                  onClick={() => {
                    setCapabilityIndex(idx);
                    setSuggestionIndex(0);
                  }}
                >
                  {entry.title}
                </button>
              ))}
            </div>
            <ul className="suggestion-switcher-list">
              {activeSuggestions.map((entry, idx) => (
                <li key={entry.key}>
                  <button
                    type="button"
                    className={`instance-row suggestion-switcher-item ${idx === suggestionIndex ? "active" : ""}`}
                    onClick={() => {
                      setSuggestionIndex(idx);
                      runSuggestion(entry);
                    }}
                  >
                    <span>
                      <strong>{entry.suggestionLabel || entry.prompt}</strong>
                      {entry.description ? <span className="muted small">{entry.description}</span> : null}
                    </span>
                    <span className="muted small">{entry.group || "General"}</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
        <footer className="muted small">
          <span>⌘/Ctrl+Shift+[ or ] cycle capabilities</span>
          <span>⌘/Ctrl+; cycle suggestions</span>
          <span>Enter runs highlighted suggestion</span>
        </footer>
      </div>
    </div>
  );
}

