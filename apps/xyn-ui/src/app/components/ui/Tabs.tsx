import type { ReactNode } from "react";

type TabOption<T extends string> = {
  value: T;
  label: ReactNode;
};

type TabsProps<T extends string> = {
  value: T;
  options: TabOption<T>[];
  onChange: (next: T) => void;
  ariaLabel?: string;
  className?: string;
};

export default function Tabs<T extends string>({
  value,
  options,
  onChange,
  ariaLabel = "Tabs",
  className = "",
}: TabsProps<T>) {
  const rootClass = ["xyn-tabs", className].filter(Boolean).join(" ");
  return (
    <div className={rootClass} role="tablist" aria-label={ariaLabel}>
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={active}
            className={`xyn-tab ${active ? "active" : ""}`}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
