import type { BlueprintDetail, BlueprintIntent } from "../../api/types";

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item ?? "").trim()).filter(Boolean);
}

export function extractBlueprintIntent(detail: BlueprintDetail | null): BlueprintIntent | null {
  if (!detail) return null;
  const spec = detail.spec_json;
  if (!spec || typeof spec !== "object") return null;
  const intent = (spec as Record<string, unknown>).intent;
  if (!intent || typeof intent !== "object") return null;

  const sourceDraftSessionId = String((intent as Record<string, unknown>).sourceDraftSessionId ?? "").trim();
  const createdFrom = (intent as Record<string, unknown>).createdFrom as Record<string, unknown> | undefined;
  const prompt = (intent as Record<string, unknown>).prompt as Record<string, unknown> | undefined;
  const requirements = (intent as Record<string, unknown>).requirements as Record<string, unknown> | undefined;

  if (!sourceDraftSessionId || !createdFrom || !prompt || !requirements) return null;

  const transcriptsRaw = (intent as Record<string, unknown>).transcripts;
  const transcripts = Array.isArray(transcriptsRaw)
    ? transcriptsRaw
        .map((item) => {
          if (!item || typeof item !== "object") return null;
          const row = item as Record<string, unknown>;
          const id = String(row.id ?? "").trim();
          if (!id) return null;
          return {
            id,
            ref: row.ref ? String(row.ref) : undefined,
            text: row.text ? String(row.text) : undefined,
            sha256: row.sha256 ? String(row.sha256) : undefined,
            createdAt: row.createdAt ? String(row.createdAt) : undefined,
          };
        })
        .filter(Boolean)
    : [];

  return {
    sourceDraftSessionId,
    createdFrom: {
      type: "draft",
      id: String(createdFrom.id ?? sourceDraftSessionId),
    },
    prompt: {
      text: String(prompt.text ?? ""),
      sha256: String(prompt.sha256 ?? ""),
      createdAt: String(prompt.createdAt ?? ""),
    },
    transcripts: transcripts as BlueprintIntent["transcripts"],
    requirements: {
      summary: String(requirements.summary ?? ""),
      functional: toStringArray(requirements.functional),
      ui: toStringArray(requirements.ui),
      dataModel: toStringArray(requirements.dataModel),
      operational: toStringArray(requirements.operational),
      definitionOfDone: toStringArray(requirements.definitionOfDone),
    },
  };
}
