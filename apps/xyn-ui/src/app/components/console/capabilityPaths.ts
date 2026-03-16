import { useEffect, useMemo, useState } from "react";
import { getCapabilityPaths } from "../../../api/xyn";
import type { CapabilityPath } from "../../../api/types";
import { capabilityRefreshMatchesRequest, XYN_CAPABILITY_REFRESH_EVENT, type CapabilityRefreshDetail } from "../../events/capabilityEvents";

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
  selectedPath: CapabilityPath | null;
  selectedPathId: string;
  setSelectedPath: (pathId: string) => void;
};

export function useCapabilityPaths(params: Params): Model {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [context, setContext] = useState("unknown");
  const [paths, setPaths] = useState<CapabilityPath[]>([]);
  const [selectedPathId, setSelectedPathId] = useState("");
  const [refreshToken, setRefreshToken] = useState(0);

  const requestKey = useMemo(
    () => [String(params.context || "").trim().toLowerCase(), String(params.entityId || "").trim(), String(params.workspaceId || "").trim()].join("::"),
    [params.context, params.entityId, params.workspaceId],
  );

  useEffect(() => {
    const onCapabilityRefresh = (event: Event) => {
      const detail = (event as CustomEvent<CapabilityRefreshDetail>).detail;
      if (!detail) return;
      if (!capabilityRefreshMatchesRequest(detail, params)) return;
      setRefreshToken((current) => current + 1);
    };
    window.addEventListener(XYN_CAPABILITY_REFRESH_EVENT, onCapabilityRefresh as EventListener);
    return () => window.removeEventListener(XYN_CAPABILITY_REFRESH_EVENT, onCapabilityRefresh as EventListener);
  }, [params.context, params.entityId, params.workspaceId]);

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
        const nextPaths = Array.isArray(payload.paths) ? payload.paths : [];
        setPaths(nextPaths);
        setSelectedPathId((current) => {
          if (current && nextPaths.some((path) => path.id === current)) return current;
          return nextPaths[0]?.id || "";
        });
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load capability paths");
        setContext(String(params.context || "unknown") || "unknown");
        setPaths([]);
        setSelectedPathId("");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [params.context, params.entityId, params.workspaceId, requestKey, refreshToken]);

  const selectedPath = paths.find((path) => path.id === selectedPathId) || paths[0] || null;

  return {
    loading,
    error,
    context,
    paths,
    selectedPath,
    selectedPathId: selectedPath?.id || "",
    setSelectedPath: setSelectedPathId,
  };
}
