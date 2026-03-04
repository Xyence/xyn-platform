import type { ReactNode } from "react";

type Props = {
  children: ReactNode;
};

export default function ConsoleResultPanel({ children }: Props) {
  return <section className="xyn-console-result-panel">{children}</section>;
}
