import { useEffect, useMemo, useState } from "react";
import { getCapabilityPaths } from "../../../api/xyn";
import type { CapabilityPath } from "../../../api/types";

type Params = {
  context?: string;
  entityId?: string | null;
  workspaceId?: string | null;
};

type Model = {
  loading: boolean;
  error: string | null;
  context: string;
  paths: CapabilityPath[];
};

export function useCapabilityPaths(params: Params): Model {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [context, setContext] = useState("unknown");
  const [paths, setPaths] = useState<CapabilityPath[]>([]);

  const requestKey = useMemo(
    () => [String(params.context || "").trim().toLowerCase(), String(params.entityId || "").trim(), String(params.workspaceId || "").trim()].join("::"),
    [params.context, params.entityId, params.workspaceId],
  );

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const payload = await getCapabilityPaths({
          context: params.context || undefined,
          entityId: params.entityId || undefined,
          workspaceId: params.workspaceId || undefined,
        });
        if (!active) return;
        setContext(String(payload.context || "unknown"));
        setPaths(Array.isArray(payload.paths) ? payload.paths : []);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load capability paths");
        setContext(String(params.context || "unknown") || "unknown");
        setPaths([]);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [params.context, params.entityId, params.workspaceId, requestKey]);

  return { loading, error, context, paths };
}
