import { useEffect, useState } from "react";
import { getExecutionPlan } from "../../../api/xyn";
import type { ExecutionPlan } from "../../../api/types";

type Model = {
  loading: boolean;
  error: string | null;
  plan: ExecutionPlan | null;
};

export function useExecutionPlan(capabilityId?: string | null): Model {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [plan, setPlan] = useState<ExecutionPlan | null>(null);

  useEffect(() => {
    const normalized = String(capabilityId || "").trim();
    if (!normalized) {
      setLoading(false);
      setError(null);
      setPlan(null);
      return;
    }
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const payload = await getExecutionPlan(normalized);
        if (!active) return;
        setPlan(payload);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load plan summary");
        setPlan(null);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [capabilityId]);

  return { loading, error, plan };
}
