import { useEffect, useMemo, useState } from "react";
import { getContextualCapabilities } from "../../../api/xyn";
import type { CapabilityContextAttributes, ContextualCapability } from "../../../api/types";

type Params = {
  context?: string;
  entityId?: string | null;
  workspaceId?: string | null;
  includeUnavailable?: boolean;
};

type Model = {
  loading: boolean;
  error: string | null;
  context: string;
  attributes: CapabilityContextAttributes;
  capabilities: ContextualCapability[];
};

export function useContextualCapabilities(params: Params): Model {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [context, setContext] = useState("unknown");
  const [attributes, setAttributes] = useState<CapabilityContextAttributes>({});
  const [capabilities, setCapabilities] = useState<ContextualCapability[]>([]);

  const requestKey = useMemo(
    () => [
      String(params.context || "").trim().toLowerCase(),
      String(params.entityId || "").trim(),
      String(params.workspaceId || "").trim(),
      params.includeUnavailable ? "with-unavailable" : "available-only",
    ].join("::"),
    [params.context, params.entityId, params.workspaceId, params.includeUnavailable]
  );

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const payload = await getContextualCapabilities({
          context: params.context || undefined,
          entityId: params.entityId || undefined,
          workspaceId: params.workspaceId || undefined,
          includeUnavailable: params.includeUnavailable,
        });
        if (!active) return;
        setContext(String(payload.context || "unknown"));
        setAttributes(payload.attributes || {});
        setCapabilities(Array.isArray(payload.capabilities) ? payload.capabilities : []);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load contextual capabilities");
        setContext(String(params.context || "unknown") || "unknown");
        setAttributes({});
        setCapabilities([]);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [params.context, params.entityId, params.workspaceId, params.includeUnavailable, requestKey]);

  return { loading, error, context, attributes, capabilities };
}
