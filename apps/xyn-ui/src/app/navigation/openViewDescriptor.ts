import type { NavigateFunction } from "react-router-dom";
import type { ViewDescriptor } from "./viewDescriptors";

export function openViewDescriptor(descriptor: ViewDescriptor, navigate: NavigateFunction): void {
  if (!String(descriptor.route || "").trim()) return;
  navigate(descriptor.route);
}
