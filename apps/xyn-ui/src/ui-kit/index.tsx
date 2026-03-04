import type { ButtonHTMLAttributes, InputHTMLAttributes, PropsWithChildren, ReactNode } from "react";
import "./theme.css";

export function ensureXynThemeCss(appKey = "xyn-ui", endpointBase = "https://xyence.io"): string {
  const key = (appKey || "xyn-ui").trim() || "xyn-ui";
  const href = `${endpointBase.replace(/\/$/, "")}/xyn/api/branding/theme.css?app=${encodeURIComponent(key)}`;
  if (typeof document !== "undefined" && !document.querySelector(`link[data-xyn-theme=\"${key}\"]`)) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    link.dataset.xynTheme = key;
    document.head.appendChild(link);
  }
  return href;
}

export function AppShell({ children }: PropsWithChildren) {
  return <div className="xui-shell">{children}</div>;
}

export function Header({ logoUrl, title, actions }: { logoUrl?: string; title: string; actions?: ReactNode }) {
  return (
    <header className="xui-header">
      <div className="xui-header-brand">
        {logoUrl ? <img src={logoUrl} alt="" /> : null}
        <strong>{title}</strong>
      </div>
      {actions ? <div>{actions}</div> : null}
    </header>
  );
}

export function Footer({ children }: PropsWithChildren) {
  return <footer className="xui-footer">{children}</footer>;
}

export function Page({ children }: PropsWithChildren) {
  return <main className="xui-page">{children}</main>;
}

export function Card({ children }: PropsWithChildren) {
  return <section className="xui-card">{children}</section>;
}

export function Button({
  children,
  variant = "primary",
  ...rest
}: PropsWithChildren<{ variant?: "primary" | "secondary" | "ghost" } & ButtonHTMLAttributes<HTMLButtonElement>>) {
  return (
    <button className={`xui-btn xui-btn-${variant}`} {...rest}>
      {children}
    </button>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input className="xui-input" {...props} />;
}

export function TableWrap({ children }: PropsWithChildren) {
  return <div className="xui-table-wrap">{children}</div>;
}
