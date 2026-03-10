export type EntityChangeOperation = "create" | "update" | "delete";

export type EntityChangeDetail = {
  entityKey: string;
  operation: EntityChangeOperation;
  source: "palette" | "agent";
};

export const XYN_ENTITY_CHANGE_EVENT = "xyn:entity-change";

function normalizeEntityKey(value: unknown): string {
  const token = String(value || "").trim().toLowerCase();
  if (!token) return "";
  return token.endsWith("s") ? token : `${token}s`;
}

export function emitEntityChange(detail: EntityChangeDetail) {
  if (typeof window === "undefined") return;
  const entityKey = normalizeEntityKey(detail.entityKey);
  if (!entityKey) return;
  window.dispatchEvent(
    new CustomEvent<EntityChangeDetail>(XYN_ENTITY_CHANGE_EVENT, {
      detail: {
        entityKey,
        operation: detail.operation,
        source: detail.source,
      },
    })
  );
}

export function inferEntityChangeFromPrompt(prompt: string): EntityChangeDetail | null {
  const normalized = String(prompt || "").trim().toLowerCase();
  const createMatch = normalized.match(/^(create|add)\s+([a-z0-9_-]+)/);
  if (createMatch) {
    return { entityKey: normalizeEntityKey(createMatch[2]), operation: "create", source: "palette" };
  }
  const updateMatch = normalized.match(/^(update|rename)\s+([a-z0-9_-]+)/);
  if (updateMatch) {
    return { entityKey: normalizeEntityKey(updateMatch[2]), operation: "update", source: "palette" };
  }
  const deleteMatch = normalized.match(/^(delete|remove)\s+([a-z0-9_-]+)/);
  if (deleteMatch) {
    return { entityKey: normalizeEntityKey(deleteMatch[2]), operation: "delete", source: "palette" };
  }
  return null;
}

export function inferEntityListPrompt(prompt: string): { entityKey: string; prompt: string } | null {
  const normalized = String(prompt || "").trim().toLowerCase();
  const match = normalized.match(/^(show|list)\s+([a-z0-9_-]+)/);
  if (!match) return null;
  const entityKey = normalizeEntityKey(match[2]);
  if (!entityKey) return null;
  return { entityKey, prompt: normalized };
}

export function inferEntityChangeFromDraftPayload(payload: Record<string, unknown> | null | undefined): EntityChangeDetail | null {
  if (!payload || typeof payload !== "object") return null;
  if (String(payload.__operation || "").trim() !== "execute_generated_app_crud") return null;
  const structured = payload.structured_operation;
  if (!structured || typeof structured !== "object") return null;
  const operation = String((structured as Record<string, unknown>).operation || "").trim().toLowerCase();
  const entityKey = normalizeEntityKey((structured as Record<string, unknown>).entity_key);
  if (!entityKey) return null;
  if (operation === "create" || operation === "update" || operation === "delete") {
    return { entityKey, operation, source: "agent" };
  }
  return null;
}
