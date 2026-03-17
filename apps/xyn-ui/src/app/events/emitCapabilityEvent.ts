import { emitCapabilityRefreshEvent } from "../../api/xyn";
import type { CapabilityEventPayload, CapabilityRefreshDetail } from "./capabilityEvents";
import { XYN_CAPABILITY_REFRESH_EVENT } from "./capabilityEvents";

const RECENT_EVENT_WINDOW_MS = 800;
let recentEventSignature = "";
let recentEventAt = 0;

function signatureForEvent(payload: CapabilityEventPayload): string {
  return [payload.eventType, String(payload.entityId || "").trim(), String(payload.workspaceId || "").trim()].join("::");
}

export async function emitCapabilityEvent(payload: CapabilityEventPayload): Promise<void> {
  if (typeof window === "undefined") return;
  const eventType = String(payload.eventType || "").trim();
  if (!eventType) return;

  const signature = signatureForEvent(payload);
  const now = Date.now();
  if (signature && signature === recentEventSignature && now - recentEventAt < RECENT_EVENT_WINDOW_MS) {
    return;
  }
  recentEventSignature = signature;
  recentEventAt = now;

  try {
    const response = await emitCapabilityRefreshEvent({
      event_type: eventType,
      entity_id: String(payload.entityId || "").trim() || undefined,
      workspace_id: String(payload.workspaceId || "").trim() || undefined,
    });

    const detail: CapabilityRefreshDetail = {
      eventType: response.event_type,
      entityId: response.entityId || null,
      workspaceId: response.workspaceId || null,
      contexts: Array.isArray(response.contexts) ? response.contexts : [],
    };

    window.dispatchEvent(new CustomEvent<CapabilityRefreshDetail>(XYN_CAPABILITY_REFRESH_EVENT, { detail }));
  } catch {
    // Capability refresh is opportunistic; failed refreshes should not break the active surface.
  }
}
