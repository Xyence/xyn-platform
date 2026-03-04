export type OpenDetailTarget = {
  entity_type: string;
  entity_id: string;
  dataset?: string;
};

const DATASET_ENTITY_MAP: Record<string, string> = {
  artifacts: "artifact",
  ems_devices: "device",
  ems_registrations: "registration",
  runs: "run",
  workspaces: "workspace",
};

export function getEntityTypeForDataset(datasetName: string): string | null {
  const key = String(datasetName || "").trim();
  if (!key) return null;
  return DATASET_ENTITY_MAP[key] || null;
}

export function getOpenDetailTarget(
  datasetName: string,
  row: Record<string, unknown>,
  primaryKey?: string
): OpenDetailTarget | null {
  const dataset = String(datasetName || "").trim();
  const primary = String(primaryKey || "").trim();
  if (!dataset || !primary) return null;
  const rawId = row?.[primary];
  if (rawId == null || rawId === "") return null;
  const entityType = getEntityTypeForDataset(dataset);
  if (entityType) {
    return {
      entity_type: entityType,
      entity_id: String(rawId),
    };
  }
  return {
    entity_type: "record",
    entity_id: String(rawId),
    dataset,
  };
}
