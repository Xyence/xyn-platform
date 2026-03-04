export type ArticleDraftSnapshot = {
  title: string | null;
  category: string | null;
  format: string | null;
  intent: string | null;
  duration: number | null;
  scenes: Array<Record<string, unknown>>;
  tags: string[];
  summary: string | null;
  body: string | null;
};

export const ARTICLE_PATCHABLE_FIELDS = ["title", "category", "format", "intent", "duration", "scenes", "tags", "summary", "body"] as const;

type PatchableField = (typeof ARTICLE_PATCHABLE_FIELDS)[number];

type ApplyPatchResult = {
  next: ArticleDraftSnapshot;
  appliedFields: PatchableField[];
  ignoredFields: string[];
};

function normalizeText(value: unknown): string | null {
  if (value == null) return null;
  const text = String(value).trim();
  return text.length ? text : null;
}

function normalizeTags(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((entry) => String(entry || "").trim())
      .filter(Boolean);
  }
  if (typeof value === "string") {
    return value
      .split(",")
      .map((entry) => entry.trim())
      .filter(Boolean);
  }
  return [];
}

function normalizeDuration(value: unknown): number | null {
  if (value == null || value === "") return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return null;
  return Math.round(numeric);
}

function normalizeScenes(value: unknown): ArticleDraftSnapshot["scenes"] {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry, index) => {
      if (!entry || typeof entry !== "object") return null;
      const row = entry as Record<string, unknown>;
      return {
        id: String(row.id || `s${index + 1}`).trim() || `s${index + 1}`,
        name: String(row.name || row.title || `Scene ${index + 1}`).trim() || `Scene ${index + 1}`,
        narration: String(row.narration || row.voiceover || "").trim(),
        on_screen_text: String(row.on_screen_text || row.on_screen || "").trim(),
        visual_prompt: String(row.visual_prompt || row.visual_description || "").trim(),
        duration_seconds: Number(row.duration_seconds) || 8,
        camera_motion: String(row.camera_motion || "").trim(),
        style_constraints: Array.isArray(row.style_constraints)
          ? row.style_constraints.map((value) => String(value || "").trim()).filter(Boolean)
          : [],
      };
    })
    .filter((entry): entry is NonNullable<typeof entry> => Boolean(entry));
}

export function buildArticleDraftSnapshot(input: Partial<ArticleDraftSnapshot>): ArticleDraftSnapshot {
  return {
    title: normalizeText(input.title),
    category: normalizeText(input.category),
    format: normalizeText(input.format),
    intent: normalizeText(input.intent),
    duration: normalizeDuration(input.duration),
    scenes: normalizeScenes(input.scenes),
    tags: normalizeTags(input.tags),
    summary: normalizeText(input.summary),
    body: normalizeText(input.body),
  };
}

export function applyPatchToFormSnapshot(current: ArticleDraftSnapshot, patch: Record<string, unknown>): ApplyPatchResult {
  const next: ArticleDraftSnapshot = { ...current };
  const appliedFields: PatchableField[] = [];
  const ignoredFields: string[] = [];

  for (const [key, rawValue] of Object.entries(patch || {})) {
    if (!ARTICLE_PATCHABLE_FIELDS.includes(key as PatchableField)) {
      ignoredFields.push(key);
      continue;
    }
    const field = key as PatchableField;

    if (field === "tags") {
      const tags = normalizeTags(rawValue);
      if (JSON.stringify(tags) !== JSON.stringify(next.tags)) {
        next.tags = tags;
        appliedFields.push(field);
      }
      continue;
    }
    if (field === "duration") {
      const duration = normalizeDuration(rawValue);
      if (duration !== next.duration) {
        next.duration = duration;
        appliedFields.push(field);
      }
      continue;
    }
    if (field === "scenes") {
      const scenes = normalizeScenes(rawValue);
      if (JSON.stringify(scenes) !== JSON.stringify(next.scenes)) {
        next.scenes = scenes;
        appliedFields.push(field);
      }
      continue;
    }
    const normalized = normalizeText(rawValue);
    if (next[field] !== normalized) {
      next[field] = normalized;
      appliedFields.push(field);
    }
  }

  return {
    next,
    appliedFields,
    ignoredFields,
  };
}
