import type { ComposerWorkContainer } from "./composerViewModel";

export type ComposerStoredSelection = {
  application_id?: string;
  application_plan_id?: string;
};

function storageKey(workspaceId: string): string {
  return `xyn:composer:selected-effort:${String(workspaceId || "").trim()}`;
}

export function readComposerStoredSelection(workspaceId: string): ComposerStoredSelection | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(storageKey(workspaceId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ComposerStoredSelection;
    const applicationId = String(parsed?.application_id || "").trim();
    const applicationPlanId = String(parsed?.application_plan_id || "").trim();
    if (!applicationId && !applicationPlanId) return null;
    return {
      ...(applicationId ? { application_id: applicationId } : {}),
      ...(applicationPlanId ? { application_plan_id: applicationPlanId } : {}),
    };
  } catch {
    return null;
  }
}

export function writeComposerStoredSelection(workspaceId: string, params?: Record<string, unknown>): void {
  if (typeof window === "undefined") return;
  const applicationId = String(params?.application_id || "").trim();
  const applicationPlanId = String(params?.application_plan_id || "").trim();
  if (!applicationId && !applicationPlanId) return;
  const payload: ComposerStoredSelection = {
    ...(applicationId ? { application_id: applicationId } : {}),
    ...(applicationPlanId ? { application_plan_id: applicationPlanId } : {}),
  };
  window.localStorage.setItem(storageKey(workspaceId), JSON.stringify(payload));
}

export function clearComposerStoredSelection(workspaceId: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(storageKey(workspaceId));
}

export function resolveComposerInitialSelection(
  containers: ComposerWorkContainer[],
  _storedSelection: ComposerStoredSelection | null,
): ComposerStoredSelection | null {
  const viable = containers.filter((container) =>
    container.lifecycleState !== "archived"
    && container.lifecycleState !== "failed"
    && !container.isSuperseded,
  );
  if (viable.length !== 1) return null;
  return viable[0].kind === "application"
    ? { application_id: viable[0].id }
    : { application_plan_id: viable[0].id };
}
