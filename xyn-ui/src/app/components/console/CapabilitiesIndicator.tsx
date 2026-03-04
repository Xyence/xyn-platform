import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toWorkspacePath } from "../../routing/workspaceRouting";
import { useXynConsole } from "../../state/xynConsoleStore";
import { type CapabilityEntry, useCapabilitySuggestions } from "./capabilitySuggestions";

export default function CapabilitiesIndicator({ workspaceId }: { workspaceId: string }) {
  const navigate = useNavigate();
  const { openPanel, setInputText, setOpen, requestSubmit } = useXynConsole();
  const [open, setOpenPopover] = useState(false);
  const [platformOpen, setPlatformOpen] = useState(false);
  const { loading, error, capabilities, platform } = useCapabilitySuggestions(workspaceId);

  const openCapability = (entry: CapabilityEntry) => {
    const target = entry.managePath || entry.docsPath;
    if (target) {
      if (/^https?:\/\//i.test(target)) {
        window.location.href = target;
        return;
      }
      const resolved = target.startsWith("/w/")
        ? target
        : target.startsWith("/")
          ? toWorkspacePath(workspaceId, target.replace(/^\/+/, ""))
          : toWorkspacePath(workspaceId, target);
      navigate(resolved);
      setOpenPopover(false);
      return;
    }
    openPanel({ key: "artifact_detail", params: { slug: entry.artifactSlug }, open_in: "current_panel" });
    setOpenPopover(false);
  };

  const runSuggestion = (prompt: string) => {
    const text = String(prompt || "").trim();
    if (!text) return;
    setInputText(text);
    setOpen(true);
    requestSubmit();
    setOpenPopover(false);
  };

  return (
    <div className="workbench-capabilities">
      <button
        type="button"
        className="ghost workbench-capabilities-button"
        onClick={() => setOpenPopover((value) => !value)}
        aria-expanded={open}
        aria-haspopup="dialog"
      >
        Capabilities
        <span className="workbench-capabilities-count">{capabilities.length}</span>
      </button>
      {open ? (
        <div className="workbench-capabilities-popover" role="dialog" aria-label="Capabilities">
          {loading ? <p className="muted small">Loading…</p> : null}
          {error ? <p className="danger-text small">{error}</p> : null}
          {!loading && !error && capabilities.length === 0 ? <p className="muted small">No app capabilities installed.</p> : null}
          {!loading && !error && capabilities.length > 0 ? (
            <ul className="workbench-capabilities-list">
              {capabilities.map((entry) => (
                <li key={entry.key}>
                  <button type="button" className="instance-row workbench-capability-row" onClick={() => openCapability(entry)}>
                    <span>
                      <strong>{entry.title}</strong>
                      {entry.description ? <span className="muted small">{entry.description}</span> : null}
                    </span>
                    <span className="muted small">v{entry.version}</span>
                  </button>
                  {entry.suggestions.filter((row) => row.visibility.map((item) => item.toLowerCase()).includes("capability")).length ? (
                    <div className="workbench-capability-suggestions">
                      {entry.suggestions
                        .filter((row) => row.visibility.map((item) => item.toLowerCase()).includes("capability"))
                        .map((suggestion) => (
                        <button
                          key={suggestion.key}
                          type="button"
                          className="ghost sm workbench-capability-suggestion"
                          onClick={() => runSuggestion(suggestion.prompt)}
                        >
                          {suggestion.suggestionLabel || suggestion.prompt}
                        </button>
                        ))}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
          {!loading && !error && platform.length > 0 ? (
            <details className="workbench-capabilities-platform" open={platformOpen} onToggle={(event) => setPlatformOpen((event.target as HTMLDetailsElement).open)}>
              <summary className="muted small">Platform ({platform.length})</summary>
              <ul className="workbench-capabilities-list">
                {platform.map((entry) => (
                  <li key={entry.key}>
                    <button type="button" className="instance-row workbench-capability-row" onClick={() => openCapability(entry)}>
                      <span>
                        <strong>{entry.title}</strong>
                        {entry.description ? <span className="muted small">{entry.description}</span> : null}
                      </span>
                      <span className="muted small">v{entry.version}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
