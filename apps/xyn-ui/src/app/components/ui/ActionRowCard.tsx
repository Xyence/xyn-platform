import type { ReactNode } from "react";

type Props = {
  title: string;
  description?: string;
  badge?: ReactNode;
  icon?: ReactNode;
  disabled?: boolean;
  disabledReason?: string;
  onClick?: () => void;
};

export default function ActionRowCard({
  title,
  description,
  badge,
  icon,
  disabled = false,
  disabledReason,
  onClick,
}: Props) {
  const interactive = Boolean(onClick) && !disabled;
  const className = `action-row-card${interactive ? " is-interactive" : ""}${disabled ? " is-disabled" : ""}`;

  const content = (
    <>
      <div className="action-row-card__icon" aria-hidden="true">
        {icon}
      </div>
      <div className="action-row-card__body">
        <div className="action-row-card__header">
          <div className="action-row-card__copy">
            <strong className="action-row-card__title">{title}</strong>
            {description ? <p className="action-row-card__description">{description}</p> : null}
          </div>
          {badge ? <div className="action-row-card__badge">{badge}</div> : null}
        </div>
        {disabled && disabledReason ? <p className="action-row-card__reason">{disabledReason}</p> : null}
      </div>
    </>
  );

  if (interactive) {
    return (
      <button type="button" className={className} onClick={onClick}>
        {content}
      </button>
    );
  }

  return (
    <div className={className} aria-disabled={disabled ? "true" : undefined}>
      {content}
    </div>
  );
}
