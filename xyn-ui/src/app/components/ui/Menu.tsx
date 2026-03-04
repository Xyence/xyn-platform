import { type ReactNode } from "react";

type MenuProps = {
  children: ReactNode;
};

export function Menu({ children }: MenuProps) {
  return <div className="xyn-menu">{children}</div>;
}

type MenuItemProps = {
  children: ReactNode;
  onSelect: () => void;
};

export function MenuItem({ children, onSelect }: MenuItemProps) {
  return (
    <button type="button" className="xyn-menu-item" onClick={onSelect}>
      {children}
    </button>
  );
}
