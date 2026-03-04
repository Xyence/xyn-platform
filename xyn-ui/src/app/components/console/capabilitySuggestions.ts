import { useEffect, useMemo, useState } from "react";
import { getMe, listWorkspaceArtifacts } from "../../../api/xyn";
import type { ArtifactCapability, ArtifactSuggestion, WorkspaceInstalledArtifactSummary } from "../../../api/types";

export type CapabilitySuggestion = {
  key: string;
  artifactId: string;
  artifactSlug: string;
  capabilityVisibility: string;
  capabilityLabel: string;
  suggestionId: string;
  suggestionLabel: string;
  prompt: string;
  description: string;
  order: number;
  group: string;
  visibility: string[];
};

export type CapabilityEntry = {
  key: string;
  artifactId: string;
  artifactSlug: string;
  title: string;
  description?: string;
  version: string;
  visibility: string;
  order: number;
  managePath: string;
  docsPath: string;
  suggestions: CapabilitySuggestion[];
};

export type CapabilitySuggestionModel = {
  loading: boolean;
  error: string | null;
  capabilities: CapabilityEntry[];
  platform: CapabilityEntry[];
  landingSuggestions: CapabilitySuggestion[];
  paletteSuggestions: CapabilitySuggestion[];
};

function normalizeCapability(raw?: ArtifactCapability): ArtifactCapability {
  const visibility = String(raw?.visibility || "hidden").trim().toLowerCase();
  return {
    visibility: visibility || "hidden",
    label: String(raw?.label || "").trim() || undefined,
    description: String(raw?.description || "").trim() || undefined,
    category: raw?.category,
    order: Number(raw?.order ?? 1000),
    icon: String(raw?.icon || "").trim() || undefined,
    tags: Array.isArray(raw?.tags) ? raw?.tags.map((entry) => String(entry).trim()).filter(Boolean) : undefined,
    permission:
      raw?.permission && String(raw.permission.resource || "").trim() && String(raw.permission.action || "").trim()
        ? { resource: String(raw.permission.resource).trim(), action: String(raw.permission.action).trim() }
        : undefined,
  };
}

function normalizeSuggestion(raw: ArtifactSuggestion): ArtifactSuggestion {
  const visibilityRaw = Array.isArray(raw.visibility) ? raw.visibility : ["capability", "palette"];
  const visibility = visibilityRaw.map((entry) => String(entry).trim().toLowerCase()).filter(Boolean);
  return {
    id: String(raw.id || "").trim(),
    name: String(raw.name || "").trim() || undefined,
    prompt: String(raw.prompt || "").trim(),
    description: String(raw.description || "").trim() || undefined,
    visibility: visibility.length ? visibility : ["capability", "palette"],
    order: Number(raw.order ?? 1000),
    group: String(raw.group || "").trim() || undefined,
    capability_ref: String(raw.capability_ref || "").trim() || undefined,
    permission:
      raw.permission && String(raw.permission.resource || "").trim() && String(raw.permission.action || "").trim()
        ? { resource: String(raw.permission.resource).trim(), action: String(raw.permission.action).trim() }
        : undefined,
    ui: raw.ui,
  };
}

function hasPermission(
  requirement: { resource: string; action: string } | undefined,
  roles: string[],
  permissions: string[]
): boolean {
  if (!requirement) return true;
  const normalizedRoles = new Set((roles || []).map((entry) => String(entry).trim().toLowerCase()));
  if (normalizedRoles.has("platform_admin") || normalizedRoles.has("platform_owner")) return true;
  const resource = String(requirement.resource || "").trim().toLowerCase();
  const action = String(requirement.action || "").trim().toLowerCase();
  if (!resource || !action) return true;
  const permissionSet = new Set((permissions || []).map((entry) => String(entry).trim().toLowerCase()));
  const candidates = [
    `${resource}:${action}`,
    `${resource}:*`,
    `*:${action}`,
    "*:*",
    `${resource}.${action}`,
    `${resource}.*`,
    `*.${action}`,
    "*.*",
  ];
  return candidates.some((token) => permissionSet.has(token));
}

function suggestionVisibleIn(suggestion: CapabilitySuggestion, bucket: "landing" | "palette" | "capability"): boolean {
  const set = new Set(suggestion.visibility.map((entry) => String(entry).toLowerCase()));
  return set.has(bucket);
}

export function useCapabilitySuggestions(workspaceId: string): CapabilitySuggestionModel {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<WorkspaceInstalledArtifactSummary[]>([]);
  const [roles, setRoles] = useState<string[]>([]);
  const [permissions, setPermissions] = useState<string[]>([]);

  useEffect(() => {
    if (!workspaceId) {
      setRows([]);
      setRoles([]);
      setPermissions([]);
      return;
    }
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const [artifactsResponse, me] = await Promise.all([listWorkspaceArtifacts(workspaceId), getMe()]);
        if (!active) return;
        setRows(artifactsResponse.artifacts || []);
        setRoles((me.roles || []).map((entry) => String(entry)));
        setPermissions((me.permissions || []).map((entry) => String(entry)));
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load capability suggestions");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [workspaceId]);

  const model = useMemo<CapabilitySuggestionModel>(() => {
    const entries: CapabilityEntry[] = [];
    for (const artifact of rows || []) {
        const capability = normalizeCapability(artifact.capability || artifact.manifest_summary?.capability);
        if (!hasPermission(capability.permission, roles, permissions)) continue;
        const rawSuggestions = Array.isArray(artifact.suggestions)
          ? artifact.suggestions
          : Array.isArray(artifact.manifest_summary?.suggestions)
            ? artifact.manifest_summary?.suggestions || []
            : [];
        const suggestions: CapabilitySuggestion[] = rawSuggestions
          .map((row) => normalizeSuggestion(row))
          .filter((row) => row.id && row.prompt)
          .filter((row) => hasPermission(row.permission, roles, permissions))
          .map((row) => ({
            key: `${artifact.artifact_id}:${row.id}`,
            artifactId: artifact.artifact_id,
            artifactSlug: artifact.slug || artifact.artifact_id,
            capabilityVisibility: String(capability.visibility || "hidden"),
            capabilityLabel:
              String(capability.label || "").trim() ||
              String(artifact.title || artifact.name || artifact.slug || artifact.artifact_id).trim(),
            suggestionId: row.id,
            suggestionLabel: String(row.name || row.prompt || "").trim() || String(row.prompt),
            prompt: String(row.prompt || "").trim(),
            description: String(row.description || "").trim(),
            order: Number(row.order ?? 1000) || 1000,
            group: String(row.group || "").trim(),
            visibility: Array.isArray(row.visibility) ? row.visibility.map((entry) => String(entry)) : ["capability", "palette"],
          }))
          .sort((a, b) => (a.order - b.order) || a.suggestionLabel.localeCompare(b.suggestionLabel));
        entries.push({
          key: artifact.binding_id || artifact.artifact_id,
          artifactId: artifact.artifact_id,
          artifactSlug: artifact.slug || artifact.artifact_id,
          title:
            String(capability.label || "").trim() ||
            String(artifact.title || artifact.name || artifact.slug || artifact.artifact_id).trim(),
          description: capability.description,
          version: artifact.version == null ? "-" : String(artifact.version),
          visibility: String(capability.visibility || "hidden").toLowerCase() || "hidden",
          order: Number(capability.order ?? 1000) || 1000,
          managePath: artifact.manifest_summary?.surfaces?.manage?.[0]?.path || "",
          docsPath: artifact.manifest_summary?.surfaces?.docs?.[0]?.path || "",
          suggestions,
        } satisfies CapabilityEntry);
    }
    entries.sort((a, b) => (a.order - b.order) || a.title.localeCompare(b.title));

    const capabilities = entries.filter((entry) => entry.visibility === "capabilities");
    const platform = entries.filter((entry) => entry.visibility === "platform");
    const landingSuggestions = [...capabilities, ...platform]
      .flatMap((entry) => entry.suggestions.filter((row) => suggestionVisibleIn(row, "landing")))
      .sort((a, b) => (a.order - b.order) || a.suggestionLabel.localeCompare(b.suggestionLabel));
    const paletteSuggestions = [...capabilities, ...platform]
      .flatMap((entry) => entry.suggestions.filter((row) => suggestionVisibleIn(row, "palette")))
      .sort((a, b) => (a.order - b.order) || a.suggestionLabel.localeCompare(b.suggestionLabel));

    const dedupeSuggestions = (suggestions: CapabilitySuggestion[]) => {
      const seen = new Set<string>();
      return suggestions.filter((entry) => {
        const key = `${entry.prompt}::${entry.artifactSlug}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
    };

    return {
      loading,
      error,
      capabilities,
      platform,
      landingSuggestions: dedupeSuggestions(landingSuggestions),
      paletteSuggestions: dedupeSuggestions(paletteSuggestions),
    };
  }, [error, loading, permissions, roles, rows]);

  return model;
}
