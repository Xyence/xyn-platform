import type { CapabilityEventContextRefresh, CapabilityEventType } from "../../api/types";

export type CapabilityEvent = CapabilityEventType;

export type CapabilityEventPayload = {
  eventType: CapabilityEvent;
  entityId?: string | null;
  workspaceId?: string | null;
};

export type CapabilityRefreshDetail = {
  eventType: string;
  entityId?: string | null;
  workspaceId?: string | null;
  contexts: CapabilityEventContextRefresh[];
};

export const XYN_CAPABILITY_REFRESH_EVENT = "xyn:capability-refresh";

function normalize(value: unknown): string {
  return String(value || "").trim().toLowerCase();
}

export function capabilityRefreshMatchesRequest(
  detail: CapabilityRefreshDetail,
  request: {
    context?: string;
    entityId?: string | null;
    workspaceId?: string | null;
  },
): boolean {
  const requestedContext = normalize(request.context);
  const requestedEntityId = normalize(request.entityId);
  const requestedWorkspaceId = normalize(request.workspaceId);
  return (detail.contexts || []).some((entry) => {
    const contextMatches = normalize(entry.context) === requestedContext;
    if (!contextMatches) return false;
    const eventWorkspaceId = normalize(entry.workspaceId);
    const eventEntityId = normalize(entry.entityId);
    const workspaceMatches = !requestedWorkspaceId || !eventWorkspaceId || requestedWorkspaceId === eventWorkspaceId;
    const entityMatches = !requestedEntityId || !eventEntityId || requestedEntityId === eventEntityId;
    return workspaceMatches && entityMatches;
  });
}
