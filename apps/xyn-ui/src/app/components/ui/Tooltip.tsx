import { type ReactNode, useState } from "react";

type TooltipProps = {
  content: string;
  children: ReactNode;
  disabled?: boolean;
};

export default function Tooltip({ content, children, disabled = false }: TooltipProps) {
  const [open, setOpen] = useState(false);

  if (disabled) {
    return <>{children}</>;
  }

  return (
    <span
      className="xyn-tooltip"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      <span title={content} aria-label={content}>
        {children}
      </span>
      {open && (
        <span role="tooltip" className="xyn-tooltip-bubble">
          {content}
        </span>
      )}
    </span>
  );
}
