import type { ReactNode } from "react";
import Tooltip from "./Tooltip";

export type CompactPaneTab = {
  key: string;
  label: string;
  icon: ReactNode;
  disabled?: boolean;
  badgeCount?: number;
};

type CompactPaneTabsProps = {
  tabs: CompactPaneTab[];
  activeKey: string;
  onChange: (key: string) => void;
  ariaLabel: string;
  variant?: "iconbar" | "segmented";
};

export default function CompactPaneTabs({
  tabs,
  activeKey,
  onChange,
  ariaLabel,
  variant = "iconbar",
}: CompactPaneTabsProps) {
  const activeTab = tabs.find((tab) => tab.key === activeKey) || tabs[0];

  return (
    <div className={`compact-pane-tabs ${variant === "segmented" ? "segmented" : "iconbar"}`}>
      <div className="compact-pane-tabs-mobile">
        <label>
          <span className="compact-pane-tabs-mobile-label">Pane</span>
          <select value={activeKey} onChange={(event) => onChange(event.target.value)} aria-label={ariaLabel}>
            {tabs.map((tab) => (
              <option key={tab.key} value={tab.key} disabled={tab.disabled}>
                {tab.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="compact-pane-tabs-desktop" aria-label={ariaLabel}>
        {tabs.map((tab) => {
          const selected = tab.key === activeKey;
          return (
            <Tooltip key={tab.key} content={tab.label}>
              <button
                type="button"
                aria-pressed={selected}
                aria-label={tab.label}
                className={`compact-pane-tab-button ${selected ? "active" : ""}`}
                onClick={() => onChange(tab.key)}
                disabled={tab.disabled}
              >
                <span className="compact-pane-tab-icon" aria-hidden="true">
                  {tab.icon}
                </span>
                <span className="sr-only">{tab.label}</span>
                {tab.badgeCount ? (
                  <span className="compact-pane-tab-badge" aria-hidden="true">
                    {tab.badgeCount > 99 ? "99+" : tab.badgeCount}
                  </span>
                ) : null}
              </button>
            </Tooltip>
          );
        })}
      </div>
      <p className="compact-pane-tabs-active-label" aria-live="polite">
        {activeTab?.label}
      </p>
    </div>
  );
}
