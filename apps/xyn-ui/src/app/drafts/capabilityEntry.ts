import type { AppJob } from "../../api/types";
import { toWorkspacePath } from "../routing/workspaceRouting";

export type CapabilityOpenPreference = {
  mode: string;
  runtimeBaseUrl: string;
  runtimePublicUrl: string;
};

export type CapabilityInstalledArtifact = {
  artifactId: string;
  artifactSlug: string;
  workspaceId: string;
  workspaceSlug: string;
  artifactRevisionId: string;
};

export type CapabilityEntry = {
  sourceOfTruth: string;
  state: string;
  installedArtifact: CapabilityInstalledArtifact;
  openPreference: CapabilityOpenPreference;
};

function normalizeCapabilityEntry(value: unknown): CapabilityEntry | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const installedRaw =
    record.installed_artifact && typeof record.installed_artifact === "object"
      ? (record.installed_artifact as Record<string, unknown>)
      : {};
  const openPrefRaw =
    record.open_preference && typeof record.open_preference === "object"
      ? (record.open_preference as Record<string, unknown>)
      : {};

  return {
    sourceOfTruth: String(record.source_of_truth || "").trim(),
    state: String(record.state || "").trim(),
    installedArtifact: {
      artifactId: String(installedRaw.artifact_id || "").trim(),
      artifactSlug: String(installedRaw.artifact_slug || "").trim(),
      workspaceId: String(installedRaw.workspace_id || "").trim(),
      workspaceSlug: String(installedRaw.workspace_slug || "").trim(),
      artifactRevisionId: String(installedRaw.artifact_revision_id || "").trim(),
    },
    openPreference: {
      mode: String(openPrefRaw.mode || "").trim(),
      runtimeBaseUrl: String(openPrefRaw.runtime_base_url || "").trim(),
      runtimePublicUrl: String(openPrefRaw.runtime_public_url || "").trim(),
    },
  };
}

export function extractCapabilityEntry(allJobs: AppJob[]): CapabilityEntry | null {
  for (let index = allJobs.length - 1; index >= 0; index -= 1) {
    const job = allJobs[index];
    const payloads = [job.output_json, job.input_json];
    for (const payload of payloads) {
      if (!payload || typeof payload !== "object") continue;
      const record = payload as Record<string, unknown>;
      const direct = normalizeCapabilityEntry(record.capability_entry);
      if (direct) return direct;

      const sibling = record.sibling_xyn && typeof record.sibling_xyn === "object" ? (record.sibling_xyn as Record<string, unknown>) : {};
      const siblingEntry = normalizeCapabilityEntry(sibling.capability_entry);
      if (siblingEntry) return siblingEntry;

      const plumbing =
        record.platform_plumbing && typeof record.platform_plumbing === "object"
          ? (record.platform_plumbing as Record<string, unknown>)
          : {};
      const plumbingEntry = normalizeCapabilityEntry(plumbing.capability_entry);
      if (plumbingEntry) return plumbingEntry;
    }
  }
  return null;
}

export function resolveCapabilityOpenTarget(args: {
  workspaceId: string;
  capabilityEntry: CapabilityEntry | null;
  deploymentUrls: {
    appUrl: string;
    siblingUiUrl: string;
  };
}): string {
  const { workspaceId, capabilityEntry, deploymentUrls } = args;
  const preferredMode = String(capabilityEntry?.openPreference.mode || "").trim().toLowerCase();

  if (preferredMode === "artifact_shell") {
    const artifactSlug = String(capabilityEntry?.installedArtifact.artifactSlug || "").trim();
    const artifactWorkspaceId = String(capabilityEntry?.installedArtifact.workspaceId || "").trim() || workspaceId;
    if (artifactSlug && artifactWorkspaceId) {
      const query = new URLSearchParams();
      query.set("artifact_slug", artifactSlug);
      return `${toWorkspacePath(artifactWorkspaceId, "workbench")}?${query.toString()}`;
    }
  }

  const runtimePublicUrl = String(capabilityEntry?.openPreference.runtimePublicUrl || "").trim();
  return runtimePublicUrl || deploymentUrls.siblingUiUrl || deploymentUrls.appUrl || "";
}
