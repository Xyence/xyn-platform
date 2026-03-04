import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { disablePreview, enablePreview, getPreviewStatus, type PreviewStatus } from "../../api/xyn";

const DEFAULT_PREVIEW: PreviewStatus = {
  enabled: false,
  roles: [],
  read_only: true,
  started_at: null,
  expires_at: null,
  actor_roles: [],
  effective_roles: [],
};

type PreviewContextValue = {
  preview: PreviewStatus;
  loading: boolean;
  refreshPreviewStatus: () => Promise<void>;
  enablePreviewMode: (roles: string[], readOnly: boolean) => Promise<void>;
  disablePreviewMode: () => Promise<void>;
};

const PreviewContext = createContext<PreviewContextValue | null>(null);

export function PreviewProvider({ children }: { children: ReactNode }) {
  const [preview, setPreview] = useState<PreviewStatus>(DEFAULT_PREVIEW);
  const [loading, setLoading] = useState(false);

  const refreshPreviewStatus = useCallback(async () => {
    try {
      const response = await getPreviewStatus();
      setPreview(response.preview || DEFAULT_PREVIEW);
    } catch {
      setPreview(DEFAULT_PREVIEW);
    }
  }, []);

  useEffect(() => {
    void refreshPreviewStatus();
  }, [refreshPreviewStatus]);

  useEffect(() => {
    const onFocus = () => {
      void refreshPreviewStatus();
    };
    window.addEventListener("focus", onFocus);
    const interval = window.setInterval(() => {
      void refreshPreviewStatus();
    }, 3 * 60 * 1000);
    return () => {
      window.removeEventListener("focus", onFocus);
      window.clearInterval(interval);
    };
  }, [refreshPreviewStatus]);

  const enablePreviewMode = useCallback(async (roles: string[], readOnly: boolean) => {
    setLoading(true);
    try {
      const response = await enablePreview({ roles, readOnly });
      setPreview(response.preview || DEFAULT_PREVIEW);
    } finally {
      setLoading(false);
    }
  }, []);

  const disablePreviewMode = useCallback(async () => {
    setLoading(true);
    try {
      const response = await disablePreview();
      setPreview(response.preview || DEFAULT_PREVIEW);
    } finally {
      setLoading(false);
    }
  }, []);

  const value = useMemo(
    () => ({
      preview,
      loading,
      refreshPreviewStatus,
      enablePreviewMode,
      disablePreviewMode,
    }),
    [preview, loading, refreshPreviewStatus, enablePreviewMode, disablePreviewMode]
  );

  return <PreviewContext.Provider value={value}>{children}</PreviewContext.Provider>;
}

export function usePreview(): PreviewContextValue {
  const value = useContext(PreviewContext);
  if (!value) {
    throw new Error("usePreview must be used within PreviewProvider");
  }
  return value;
}
