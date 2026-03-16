import { useEffect, useMemo, useState } from "react";
import { getContextualCapabilities } from "../../../api/xyn";
import type { ContextualCapability } from "../../../api/types";

type Params = {
  context?: string;
  artifactId?: string | null;
  applicationId?: string | null;
};

type Model = {
  loading: boolean;
  error: string | null;
  context: string;
  capabilities: ContextualCapability[];
};

export function useContextualCapabilities(params: Params): Model {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [context, setContext] = useState("unknown");
  const [capabilities, setCapabilities] = useState<ContextualCapability[]>([]);

  const requestKey = useMemo(
    () => [
      String(params.context || "").trim().toLowerCase(),
      String(params.artifactId || "").trim(),
      String(params.applicationId || "").trim(),
    ].join("::"),
    [params.applicationId, params.artifactId, params.context]
  );

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const payload = await getContextualCapabilities({
          context: params.context || undefined,
          artifact_id: params.artifactId || undefined,
          application_id: params.applicationId || undefined,
        });
        if (!active) return;
        setContext(String(payload.context || "unknown"));
        setCapabilities(Array.isArray(payload.capabilities) ? payload.capabilities : []);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load contextual capabilities");
        setContext(String(params.context || "unknown") || "unknown");
        setCapabilities([]);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [params.applicationId, params.artifactId, params.context, requestKey]);

  return { loading, error, context, capabilities };
}
