import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { applyXynIntent, getXynIntentOptions, resolveXynIntent } from "../../api/xyn";
import type { XynIntentOptionsResponse, XynIntentResolutionResult, XynIntentStatus } from "../../api/types";

const STORAGE_KEY = "xyn.console.v1.sessions";
const HINT_STORAGE_KEY = "xyn.console.v1.lastArtifactHint";

export type XynConsoleContextRef = {
  artifact_id?: string | null;
  artifact_type?: string | null;
};

type SupportedConsoleArtifactType = "ArticleDraft" | "ContextPack" | "Workspace";

type PendingProposal = {
  patch_object: Record<string, unknown>;
  changes: Array<{ field: string; from?: unknown; to?: unknown }>;
};

type ConsoleSessionState = {
  inputText: string;
  lastMessage: string;
  lastResolution: XynIntentResolutionResult | null;
  pendingProposal: PendingProposal | null;
  pendingMissingFields: Array<{ field: string; reason: string; options_available: boolean }>;
  optionsByField: Partial<Record<"category" | "format" | "duration", XynIntentOptionsResponse>>;
  localMessage: string;
  localDirty: boolean;
  ignoredFields: string[];
};

type PersistedSessions = Record<string, ConsoleSessionState>;

type ProcessingStep = "resolving" | "classifying" | "validating";

export type ConsolePanelType = "table" | "detail" | "report";

export type ConsolePanelState = {
  panel_id: string;
  panel_type: ConsolePanelType;
  instance_key: string;
  title: string;
  key: string;
  params?: Record<string, unknown>;
  active_group_id?: string | null;
};

type ActivePanelState = ConsolePanelState | null;

type CanvasContext = {
  view_type: "table" | "detail";
  dataset?: {
    name: string;
    primary_key: string;
    columns: Array<Record<string, unknown>>;
  };
  query?: Record<string, unknown>;
  selection?: {
    selected_row_ids: string[];
    focused_row_id: string | null;
    row_order_ids?: string[];
  };
  pagination?: {
    limit: number;
    offset: number;
    total_count: number;
  };
  entity_type?: string;
  entity_id?: string;
  available_tabs?: string[];
  active_tab?: string;
  ui: {
    active_panel_id: string;
    panel_id: string;
    panel_type: "table" | "detail" | "report";
    instance_key: string;
    active_group_id: string | null;
    layout_engine: "simple" | "dockview";
  };
};

type NavigationEntry = {
  panel_id: string;
  panel_type: ConsolePanelType;
  view_type: "table" | "detail";
  instance_key: string;
  query?: Record<string, unknown>;
  selection?: { selected_row_ids: string[]; focused_row_id: string | null };
  ts: number;
};

export type ConsoleArtifactHint = {
  artifact_id: string;
  artifact_type: string;
  artifact_state?: string | null;
  title?: string;
  route?: string;
  updated_at?: string;
};

type ConsoleEditorBridge = {
  getFormSnapshot: () => Record<string, unknown>;
  applyPatchToForm: (patch: Record<string, unknown>) => { appliedFields: string[]; ignoredFields: string[] };
  focusField: (field: string) => boolean;
  applyFieldValue?: (field: string, value: unknown) => boolean;
};

const DEFAULT_SESSION: ConsoleSessionState = {
  inputText: "",
  lastMessage: "",
  lastResolution: null,
  pendingProposal: null,
  pendingMissingFields: [],
  optionsByField: {},
  localMessage: "",
  localDirty: false,
  ignoredFields: [],
};

function cloneDefaultSession(): ConsoleSessionState {
  return {
    inputText: "",
    lastMessage: "",
    lastResolution: null,
    pendingProposal: null,
    pendingMissingFields: [],
    optionsByField: {},
    localMessage: "",
    localDirty: false,
    ignoredFields: [],
  };
}

function toContextKey(context: XynConsoleContextRef): string {
  const artifactId = String(context.artifact_id || "").trim();
  return artifactId || "global";
}

function normalizeConsoleArtifactType(value: unknown): SupportedConsoleArtifactType {
  const raw = String(value || "").trim().toLowerCase();
  if (raw === "contextpack" || raw === "context_pack") return "ContextPack";
  if (raw === "workspace") return "Workspace";
  return "ArticleDraft";
}

function workspaceIdFromPathname(pathname: string): string {
  const match = String(pathname || "").match(/^\/w\/([^/]+)(?:\/|$)/);
  return match?.[1] ? decodeURIComponent(match[1]) : "";
}

function readSessionsFromStorage(): PersistedSessions {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as PersistedSessions;
    if (!parsed || typeof parsed !== "object") return {};
    return parsed;
  } catch {
    return {};
  }
}

function writeSessionsToStorage(value: PersistedSessions) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
}

function resolutionNeedsBadge(status?: XynIntentStatus): boolean {
  return status === "MissingFields" || status === "ProposedPatch" || status === "ValidationError" || status === "UnsupportedIntent";
}

function readArtifactHint(): ConsoleArtifactHint | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(HINT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ConsoleArtifactHint;
    if (!parsed?.artifact_id || !parsed?.artifact_type) return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeArtifactHint(hint: ConsoleArtifactHint | null) {
  if (typeof window === "undefined") return;
  if (!hint) {
    window.localStorage.removeItem(HINT_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(HINT_STORAGE_KEY, JSON.stringify(hint));
}

function extractOptionValue(field: "category" | "format" | "duration", option: unknown): string {
  if (typeof option === "string" || typeof option === "number") return String(option);
  if (typeof option === "object" && option) {
    const data = option as Record<string, unknown>;
    if (field === "category" && typeof data.slug === "string") return data.slug;
    if (typeof data.value === "string" || typeof data.value === "number") return String(data.value);
    if (typeof data.id === "string") return data.id;
    if (typeof data.slug === "string") return data.slug;
  }
  return "";
}

type XynConsoleContextValue = {
  open: boolean;
  setOpen: (open: boolean) => void;
  context: XynConsoleContextRef;
  setContext: (context: XynConsoleContextRef) => void;
  clearContext: () => void;
  contextKey: string;
  inputText: string;
  setInputText: (value: string) => void;
  processing: boolean;
  processingStep: ProcessingStep | null;
  session: ConsoleSessionState;
  badgeActive: boolean;
  pendingCloseBlock: boolean;
  hasEditorBridge: boolean;
  submitResolve: () => Promise<void>;
  applyPendingProposal: () => Promise<void>;
  applyPendingProposalToForm: () => void;
  applyPendingProposalAndSave: () => Promise<void>;
  applyDraftPayload: () => Promise<void>;
  cancelPendingProposal: () => void;
  fetchOptions: (field: "category" | "format" | "duration") => Promise<void>;
  injectSuggestion: (snippet: string) => void;
  applyOptionValue: (field: "category" | "format" | "duration", option: unknown) => void;
  focusMissingField: (field: string) => boolean;
  registerEditorBridge: (context: XynConsoleContextRef, bridge: ConsoleEditorBridge) => void;
  unregisterEditorBridge: (context: XynConsoleContextRef) => void;
  clearSessionResolution: () => void;
  handleRouteChange: (pathname: string) => void;
  lastArtifactHint: ConsoleArtifactHint | null;
  setLastArtifactHint: (hint: ConsoleArtifactHint | null) => void;
  panels: ConsolePanelState[];
  activePanelId: string | null;
  activePanel: ActivePanelState;
  setActivePanel: (panel: ActivePanelState) => void;
  openPanel: (panel: {
    key: string;
    params?: Record<string, unknown>;
    open_in?: "current_panel" | "new_panel" | "side_by_side";
    return_to_panel_id?: string;
  }) => void;
  closePanel: (panelId: string) => void;
  setActivePanelId: (panelId: string | null) => void;
  updateActivePanelParams: (params: Record<string, unknown>) => void;
  canvasContext: CanvasContext | null;
  setCanvasContext: (context: CanvasContext | null) => void;
  navigateBack: () => void;
  navigateForward: () => void;
  submitToken: number;
  requestSubmit: () => void;
  suggestionSwitcherOpen: boolean;
  openSuggestionSwitcher: () => void;
  closeSuggestionSwitcher: () => void;
};

const XynConsoleContext = createContext<XynConsoleContextValue | null>(null);
const INITIATE_PATHS = new Set(["/app/console", "/app/initiate"]);

function isInitiatePath(pathname: string): boolean {
  const normalized = String(pathname || "").trim().replace(/\/+$/, "") || "/";
  return INITIATE_PATHS.has(normalized);
}

export function XynConsoleProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [context, setContextState] = useState<XynConsoleContextRef>({ artifact_id: null, artifact_type: null });
  const [sessions, setSessions] = useState<PersistedSessions>(() => readSessionsFromStorage());
  const [processing, setProcessing] = useState(false);
  const [processingStep, setProcessingStep] = useState<ProcessingStep | null>(null);
  const [pendingCloseBlock, setPendingCloseBlock] = useState(false);
  const [lastArtifactHint, setLastArtifactHintState] = useState<ConsoleArtifactHint | null>(() => readArtifactHint());
  const [panels, setPanels] = useState<ConsolePanelState[]>([]);
  const [activePanelId, setActivePanelIdState] = useState<string | null>(null);
  const [canvasContext, setCanvasContextState] = useState<CanvasContext | null>(null);
  const [navBack, setNavBack] = useState<NavigationEntry[]>([]);
  const [navForward, setNavForward] = useState<NavigationEntry[]>([]);
  const [panelReturnTargets, setPanelReturnTargets] = useState<Record<string, string>>({});
  const [submitToken, setSubmitToken] = useState(0);
  const [suggestionSwitcherOpen, setSuggestionSwitcherOpen] = useState(false);
  const editorBridgesRef = useRef<Record<string, ConsoleEditorBridge>>({});
  const navigationGuardRef = useRef(false);

  const contextKey = useMemo(() => toContextKey(context), [context]);
  const session = useMemo(() => sessions[contextKey] || DEFAULT_SESSION, [sessions, contextKey]);
  const activeEditorBridge = editorBridgesRef.current[contextKey];

  useEffect(() => {
    writeSessionsToStorage(sessions);
  }, [sessions]);

  useEffect(() => {
    writeArtifactHint(lastArtifactHint);
  }, [lastArtifactHint]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typingTarget = target?.isContentEditable || ["input", "textarea", "select"].includes((target?.tagName || "").toLowerCase());
      if (!typingTarget && (event.metaKey || event.ctrlKey) && !event.shiftKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
      }
      if (event.key === "Escape" && open) {
        if (session.pendingProposal) {
          event.preventDefault();
          setPendingCloseBlock(true);
          return;
        }
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, session.pendingProposal]);

  const updateSession = useCallback(
    (updater: (current: ConsoleSessionState) => ConsoleSessionState) => {
      setSessions((current) => {
        const active = current[contextKey] || cloneDefaultSession();
        return {
          ...current,
          [contextKey]: updater(active),
        };
      });
    },
    [contextKey]
  );

  const setInputText = useCallback(
    (value: string) => {
      updateSession((current) => ({ ...current, inputText: value }));
    },
    [updateSession]
  );

  const storeResolution = useCallback(
    (result: XynIntentResolutionResult, message: string) => {
      updateSession((current) => ({
        ...current,
        lastMessage: message,
        lastResolution: result,
        pendingProposal:
          result.status === "ProposedPatch" && result.proposed_patch
            ? {
                patch_object: result.proposed_patch.patch_object || {},
                changes: (result.proposed_patch.changes || []).map((entry) => ({
                  field: String(entry.field || ""),
                  from: entry.from,
                  to: entry.to,
                })),
              }
            : null,
        pendingMissingFields: result.status === "MissingFields" ? result.missing_fields || [] : [],
        localMessage: "",
        localDirty: false,
        ignoredFields: [],
      }));
    },
    [updateSession]
  );

  const submitResolve = useCallback(async () => {
    const message = String(session.inputText || "").trim();
    if (!message || processing) return;
    setProcessing(true);
    setProcessingStep("resolving");
    setPendingCloseBlock(false);
    try {
      setProcessingStep("classifying");
      const result = await resolveXynIntent({
        message,
        context: {
          artifact_id: context.artifact_id || null,
          artifact_type: context.artifact_type || null,
          workspace_id: workspaceIdFromPathname(typeof window !== "undefined" ? window.location.pathname : ""),
        },
        snapshot: activeEditorBridge?.getFormSnapshot ? activeEditorBridge.getFormSnapshot() : undefined,
      });
      setProcessingStep("validating");
      storeResolution(result, message);
      setOpen(true);
    } catch (error) {
      const failure: XynIntentResolutionResult = {
        status: "ValidationError",
        action_type: "ValidateDraft",
        artifact_type: "ArticleDraft",
        artifact_id: context.artifact_id || null,
        summary: "Resolve failed.",
        validation_errors: [error instanceof Error ? error.message : "Unknown resolve failure"],
      };
      storeResolution(failure, message);
      setOpen(true);
    } finally {
      setProcessingStep(null);
      setProcessing(false);
    }
  }, [session.inputText, processing, context.artifact_id, context.artifact_type, storeResolution, activeEditorBridge]);

  const applyPendingProposalToForm = useCallback(() => {
    if (!session.pendingProposal || !activeEditorBridge) return;
    const localResult = activeEditorBridge.applyPatchToForm(session.pendingProposal.patch_object || {});
    updateSession((current) => ({
      ...current,
      localDirty: Boolean(localResult.appliedFields.length) || current.localDirty,
      ignoredFields: localResult.ignoredFields,
      localMessage: localResult.appliedFields.length
        ? "Applied locally (unsaved)."
        : localResult.ignoredFields.length
          ? "No applicable local fields in patch."
          : current.localMessage,
    }));
  }, [session.pendingProposal, activeEditorBridge, updateSession]);

  const applyPendingProposalAndSave = useCallback(async () => {
    if (!session.pendingProposal || processing) return;
    const targetArtifactId = context.artifact_id || session.lastResolution?.artifact_id || null;
    if (!targetArtifactId) return;

    if (activeEditorBridge) {
      const localResult = activeEditorBridge.applyPatchToForm(session.pendingProposal.patch_object || {});
      updateSession((current) => ({
        ...current,
        localDirty: Boolean(localResult.appliedFields.length) || current.localDirty,
        ignoredFields: localResult.ignoredFields,
        localMessage: localResult.appliedFields.length ? "Applied locally (unsaved)." : current.localMessage,
      }));
    }

    setProcessing(true);
    setProcessingStep("validating");
    try {
      const applyArtifactType = normalizeConsoleArtifactType(context.artifact_type || session.lastResolution?.artifact_type);
      const result = await applyXynIntent({
        action_type: "ApplyPatch",
        artifact_type: applyArtifactType,
        artifact_id: targetArtifactId,
        payload: session.pendingProposal.patch_object,
      });
      storeResolution(result, session.lastMessage || "");
      updateSession((current) => ({
        ...current,
        localDirty: false,
        localMessage: "Applied and saved.",
      }));
      setPendingCloseBlock(false);
    } catch (error) {
      const failure: XynIntentResolutionResult = {
        status: "ValidationError",
        action_type: "ApplyPatch",
        artifact_type: "ArticleDraft",
        artifact_id: targetArtifactId,
        summary: "Apply failed.",
        validation_errors: [error instanceof Error ? error.message : "Unknown apply failure"],
      };
      storeResolution(failure, session.lastMessage || "");
    } finally {
      setProcessingStep(null);
      setProcessing(false);
    }
  }, [
    session.pendingProposal,
    session.lastResolution?.artifact_id,
    session.lastResolution?.artifact_type,
    session.lastMessage,
    processing,
    context.artifact_id,
    context.artifact_type,
    activeEditorBridge,
    updateSession,
    storeResolution,
  ]);

  const applyPendingProposal = useCallback(async () => {
    await applyPendingProposalAndSave();
  }, [applyPendingProposalAndSave]);

  const applyDraftPayload = useCallback(async () => {
    if (processing) return;
    const payload = session.lastResolution?.draft_payload;
    if (!payload || typeof payload !== "object") return;
    setProcessing(true);
    setProcessingStep("validating");
    try {
      const result = await applyXynIntent({
        action_type: "CreateDraft",
        artifact_type: normalizeConsoleArtifactType(session.lastResolution?.artifact_type),
        payload,
      });
      storeResolution(result, session.lastMessage || "");
      setPendingCloseBlock(false);
    } catch (error) {
      const failure: XynIntentResolutionResult = {
        status: "ValidationError",
        action_type: "CreateDraft",
        artifact_type: "ArticleDraft",
        artifact_id: null,
        summary: "Create draft failed.",
        validation_errors: [error instanceof Error ? error.message : "Unknown create failure"],
      };
      storeResolution(failure, session.lastMessage || "");
    } finally {
      setProcessingStep(null);
      setProcessing(false);
    }
  }, [processing, session.lastResolution?.draft_payload, session.lastMessage, storeResolution]);

  const cancelPendingProposal = useCallback(() => {
    updateSession((current) => ({
      ...current,
      pendingProposal: null,
      localMessage: current.localDirty ? "Proposal canceled. Local edits retained (unsaved)." : "Proposal canceled.",
    }));
    setPendingCloseBlock(false);
  }, [updateSession]);

  const fetchOptions = useCallback(
    async (field: "category" | "format" | "duration") => {
      if (processing) return;
      try {
        const response = await getXynIntentOptions({ artifact_type: "ArticleDraft", field });
        updateSession((current) => ({
          ...current,
          optionsByField: {
            ...current.optionsByField,
            [field]: response,
          },
        }));
      } catch {
        // Keep panel deterministic; no-op on options fetch errors.
      }
    },
    [processing, updateSession]
  );

  const injectSuggestion = useCallback(
    (snippet: string) => {
      const text = String(snippet || "").trim();
      if (!text) return;
      updateSession((current) => {
        const prefix = current.inputText?.trim() ? `${current.inputText.trim()}; ` : "";
        return {
          ...current,
          inputText: `${prefix}${text}`,
        };
      });
    },
    [updateSession]
  );

  const applyOptionValue = useCallback(
    (field: "category" | "format" | "duration", option: unknown) => {
      const value = extractOptionValue(field, option);
      if (!value) return;
      if (activeEditorBridge?.applyFieldValue?.(field, value)) {
        updateSession((current) => ({
          ...current,
          localDirty: true,
          localMessage: `Applied locally (unsaved): ${field}.`,
        }));
        return;
      }
      injectSuggestion(`${field}: ${value}`);
    },
    [activeEditorBridge, updateSession, injectSuggestion]
  );

  const focusMissingField = useCallback(
    (field: string) => {
      const targetField = String(field || "").trim();
      if (!targetField) return false;
      if (activeEditorBridge?.focusField(targetField)) {
        updateSession((current) => ({
          ...current,
          localMessage: `Focused field: ${targetField}.`,
        }));
        return true;
      }
      updateSession((current) => {
        const prefix = current.inputText?.trim() ? `${current.inputText.trim()}; ` : "";
        return {
          ...current,
          inputText: `${prefix}${targetField}: `,
          localMessage: `Added field prompt: ${targetField}.`,
        };
      });
      return false;
    },
    [activeEditorBridge, updateSession]
  );

  const setContext = useCallback((next: XynConsoleContextRef) => {
    const artifactId = next.artifact_id || null;
    const artifactType = next.artifact_type || null;
    setContextState({
      artifact_id: artifactId,
      artifact_type: artifactType,
    });
    if (artifactId && artifactType) {
      setLastArtifactHintState((current) => ({
        artifact_id: artifactId,
        artifact_type: artifactType,
        artifact_state: current?.artifact_state || null,
        title: current?.artifact_id === artifactId ? current.title : current?.title,
        route: current?.artifact_id === artifactId ? current.route : current?.route,
        updated_at: current?.artifact_id === artifactId ? current.updated_at : current?.updated_at,
      }));
    }
  }, []);

  const clearContext = useCallback(() => {
    setContextState({ artifact_id: null, artifact_type: null });
  }, []);

  const registerEditorBridge = useCallback((bridgeContext: XynConsoleContextRef, bridge: ConsoleEditorBridge) => {
    editorBridgesRef.current[toContextKey(bridgeContext)] = bridge;
  }, []);

  const unregisterEditorBridge = useCallback((bridgeContext: XynConsoleContextRef) => {
    delete editorBridgesRef.current[toContextKey(bridgeContext)];
  }, []);

  const clearSessionResolution = useCallback(() => {
    updateSession((current) => ({
      ...current,
      lastResolution: null,
      pendingProposal: null,
      pendingMissingFields: [],
      optionsByField: {},
      localMessage: "",
      ignoredFields: [],
    }));
    setPendingCloseBlock(false);
  }, [updateSession]);

  const handleRouteChange = useCallback(
    (pathname: string) => {
      if (isInitiatePath(pathname)) return;
      setSessions((current) => {
        const active = current[contextKey];
        if (!active || active.pendingProposal) return current;
        const resolution = active.lastResolution;
      const shouldReset =
        resolution?.status === "DraftReady" &&
        resolution?.action_type === "CreateDraft" &&
        Boolean(resolution?.artifact_id);
      if (!shouldReset) return current;
      setLastArtifactHintState(null);
      return {
        ...current,
        [contextKey]: cloneDefaultSession(),
      };
      });
      setPendingCloseBlock(false);
    },
    [contextKey]
  );

  const setLastArtifactHint = useCallback((hint: ConsoleArtifactHint | null) => {
    setLastArtifactHintState(hint);
  }, []);

  const badgeActive = useMemo(() => {
    if (session.pendingProposal) return true;
    return resolutionNeedsBadge(session.lastResolution?.status);
  }, [session.pendingProposal, session.lastResolution?.status]);

  const activePanel = useMemo<ActivePanelState>(() => {
    if (!activePanelId) return null;
    return panels.find((item) => item.panel_id === activePanelId) || null;
  }, [activePanelId, panels]);

  const inferPanelType = useCallback((key: string): ConsolePanelType => {
    if (key.includes("detail") || key.includes("raw_json") || key.includes("files")) return "detail";
    if (key.includes("rollup") || key.includes("timeseries") || key.includes("status")) return "report";
    return "table";
  }, []);

  const inferInstanceKey = useCallback((key: string, params?: Record<string, unknown>): string => {
    if (key === "artifact_detail" || key === "artifact_raw_json" || key === "artifact_files") {
      return `artifact:${String(params?.slug || "")}`;
    }
    if (key === "record_detail") {
      return `${String(params?.entity_type || "record")}:${String(params?.entity_id || "")}`;
    }
    if (key === "artifact_list") return "artifacts";
    if (key.startsWith("ems_")) {
      if (key === "ems_dataset_schema") return `dataset_schema:${String(params?.dataset || "ems_devices")}`;
      if (key === "ems_registrations_timeseries") return "ems_registrations_timeseries";
      if (key === "ems_device_status_rollup" || key === "ems_device_statuses") return "ems_device_status_rollup";
      if (key === "ems_registrations" || key === "ems_registrations_time") return "ems_registrations";
      return "ems_devices";
    }
    return key;
  }, []);

  const openPanel = useCallback(
    (input: { key: string; params?: Record<string, unknown>; open_in?: "current_panel" | "new_panel" | "side_by_side"; return_to_panel_id?: string }) => {
      const panelType = inferPanelType(input.key);
      const instanceKey = inferInstanceKey(input.key, input.params);
      const openIn = input.open_in || "current_panel";
      setPanels((current) => {
        const existing = current.find((item) => item.panel_type === panelType && item.instance_key === instanceKey);
        if (existing) {
          if (input.return_to_panel_id) {
            setPanelReturnTargets((targets) => ({ ...targets, [existing.panel_id]: input.return_to_panel_id as string }));
          }
          setActivePanelIdState(existing.panel_id);
          return current.map((item) =>
            item.panel_id === existing.panel_id ? { ...item, key: input.key, params: input.params || {}, title: item.title || input.key } : item
          );
        }
        const next: ConsolePanelState = {
          panel_id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          panel_type: panelType,
          instance_key: instanceKey,
          title: input.key,
          key: input.key,
          params: input.params || {},
          active_group_id: null,
        };
        if (input.return_to_panel_id) {
          setPanelReturnTargets((targets) => ({ ...targets, [next.panel_id]: input.return_to_panel_id as string }));
        }
        if (openIn === "current_panel" && activePanelId) {
          const replaced = current.map((item) => (item.panel_id === activePanelId ? next : item));
          setPanelReturnTargets((targets) => {
            const copy = { ...targets };
            delete copy[activePanelId];
            if (input.return_to_panel_id) {
              copy[next.panel_id] = input.return_to_panel_id as string;
            }
            return copy;
          });
          setActivePanelIdState(next.panel_id);
          return replaced;
        }
        setActivePanelIdState(next.panel_id);
        return [...current, next];
      });
    },
    [activePanelId, inferInstanceKey, inferPanelType]
  );

  const closePanel = useCallback(
    (panelId: string) => {
      setPanels((current) => {
        const next = current.filter((item) => item.panel_id !== panelId);
        const isClosingActive = activePanelId === panelId;
        if (isClosingActive) {
          const explicitTarget = panelReturnTargets[panelId];
          const hasExplicitTarget = explicitTarget && next.some((item) => item.panel_id === explicitTarget);
          if (hasExplicitTarget) {
            setActivePanelIdState(explicitTarget);
          } else {
            const nextPanelIdSet = new Set(next.map((item) => item.panel_id));
            const historyTarget = [...navBack].reverse().find((entry) => entry.panel_id !== panelId && nextPanelIdSet.has(entry.panel_id));
            if (historyTarget?.panel_id) {
              setActivePanelIdState(historyTarget.panel_id);
            } else {
              setActivePanelIdState(next.length ? next[next.length - 1].panel_id : null);
            }
          }
        }
        setPanelReturnTargets((targets) => {
          const copy: Record<string, string> = {};
          Object.entries(targets).forEach(([key, value]) => {
            if (key === panelId) return;
            if (value === panelId) return;
            copy[key] = value;
          });
          return copy;
        });
        return next;
      });
    },
    [activePanelId, navBack, panelReturnTargets]
  );

  const setActivePanelId = useCallback((panelId: string | null) => {
    setActivePanelIdState(panelId);
  }, []);

  const setActivePanel = useCallback(
    (panel: ActivePanelState) => {
      if (!panel) {
        if (activePanelId) closePanel(activePanelId);
        return;
      }
      if (panel.panel_id) {
        setPanels((current) => {
          const exists = current.some((item) => item.panel_id === panel.panel_id);
          if (!exists) return [...current, panel];
          return current.map((item) => (item.panel_id === panel.panel_id ? panel : item));
        });
        setActivePanelIdState(panel.panel_id);
        return;
      }
      openPanel({ key: panel.key, params: panel.params || {} });
    },
    [activePanelId, closePanel, openPanel]
  );

  const updateActivePanelParams = useCallback(
    (params: Record<string, unknown>) => {
      if (!activePanelId) return;
      setPanels((current) => current.map((item) => (item.panel_id === activePanelId ? { ...item, params: { ...(item.params || {}), ...params } } : item)));
    },
    [activePanelId]
  );

  const setCanvasContext = useCallback((context: CanvasContext | null) => {
    setCanvasContextState(context);
  }, []);

  const toNavEntry = useCallback((context: CanvasContext): NavigationEntry => {
    return {
      panel_id: context.ui.panel_id,
      panel_type: context.ui.panel_type,
      view_type: context.view_type,
      instance_key: context.ui.instance_key,
      query: (context.query || undefined) as Record<string, unknown> | undefined,
      selection: context.selection || undefined,
      ts: Date.now(),
    };
  }, []);

  useEffect(() => {
    if (!canvasContext?.ui?.panel_id) return;
    if (navigationGuardRef.current) return;
    setNavBack((current) => {
      const next = [...current];
      const entry = toNavEntry(canvasContext);
      const last = next[next.length - 1];
      if (
        !last ||
        last.panel_id !== entry.panel_id ||
        JSON.stringify(last.query || {}) !== JSON.stringify(entry.query || {}) ||
        JSON.stringify(last.selection || {}) !== JSON.stringify(entry.selection || {})
      ) {
        next.push(entry);
      }
      return next.slice(-30);
    });
    setNavForward([]);
  }, [canvasContext, toNavEntry]);

  const navigateBack = useCallback(() => {
    setNavBack((current) => {
      if (current.length <= 1) return current;
      const next = [...current];
      const currentEntry = next.pop();
      const prev = next[next.length - 1];
      if (currentEntry) setNavForward((forward) => [currentEntry, ...forward].slice(0, 30));
      if (prev) {
        navigationGuardRef.current = true;
        setActivePanelIdState(prev.panel_id);
        setPanels((items) =>
          items.map((panel) => (panel.panel_id === prev.panel_id ? { ...panel, params: { ...(panel.params || {}), query: prev.query || panel.params?.query } } : panel))
        );
        setTimeout(() => {
          navigationGuardRef.current = false;
        }, 0);
      }
      return next;
    });
  }, []);

  const navigateForward = useCallback(() => {
    setNavForward((current) => {
      if (!current.length) return current;
      const [next, ...rest] = current;
      navigationGuardRef.current = true;
      setActivePanelIdState(next.panel_id);
      setPanels((items) =>
        items.map((panel) => (panel.panel_id === next.panel_id ? { ...panel, params: { ...(panel.params || {}), query: next.query || panel.params?.query } } : panel))
      );
      setNavBack((back) => [...back, next].slice(-30));
      setTimeout(() => {
        navigationGuardRef.current = false;
      }, 0);
      return rest;
    });
  }, []);

  const requestSubmit = useCallback(() => {
    setSubmitToken((current) => current + 1);
  }, []);

  const openSuggestionSwitcher = useCallback(() => {
    setSuggestionSwitcherOpen(true);
  }, []);

  const closeSuggestionSwitcher = useCallback(() => {
    setSuggestionSwitcherOpen(false);
  }, []);

  const value = useMemo<XynConsoleContextValue>(
    () => ({
      open,
      setOpen,
      context,
      setContext,
      clearContext,
      contextKey,
      inputText: session.inputText,
      setInputText,
      processing,
      processingStep,
      session,
      badgeActive,
      pendingCloseBlock,
      hasEditorBridge: Boolean(activeEditorBridge),
      submitResolve,
      applyPendingProposal,
      applyPendingProposalToForm,
      applyPendingProposalAndSave,
      applyDraftPayload,
      cancelPendingProposal,
      fetchOptions,
      injectSuggestion,
      applyOptionValue,
      focusMissingField,
      registerEditorBridge,
      unregisterEditorBridge,
      clearSessionResolution,
      handleRouteChange,
      lastArtifactHint,
      setLastArtifactHint,
      panels,
      activePanelId,
      activePanel,
      setActivePanel,
      openPanel,
      closePanel,
      setActivePanelId,
      updateActivePanelParams,
      canvasContext,
      setCanvasContext,
      navigateBack,
      navigateForward,
      submitToken,
      requestSubmit,
      suggestionSwitcherOpen,
      openSuggestionSwitcher,
      closeSuggestionSwitcher,
    }),
    [
      open,
      context,
      setContext,
      clearContext,
      contextKey,
      session,
      setInputText,
      processing,
      processingStep,
      badgeActive,
      pendingCloseBlock,
      activeEditorBridge,
      submitResolve,
      applyPendingProposal,
      applyPendingProposalToForm,
      applyPendingProposalAndSave,
      applyDraftPayload,
      cancelPendingProposal,
      fetchOptions,
      injectSuggestion,
      applyOptionValue,
      focusMissingField,
      registerEditorBridge,
      unregisterEditorBridge,
      clearSessionResolution,
      handleRouteChange,
      lastArtifactHint,
      setLastArtifactHint,
      panels,
      activePanelId,
      activePanel,
      setActivePanel,
      openPanel,
      closePanel,
      setActivePanelId,
      updateActivePanelParams,
      canvasContext,
      setCanvasContext,
      navigateBack,
      navigateForward,
      submitToken,
      requestSubmit,
      suggestionSwitcherOpen,
      openSuggestionSwitcher,
      closeSuggestionSwitcher,
    ]
  );

  return <XynConsoleContext.Provider value={value}>{children}</XynConsoleContext.Provider>;
}

export function useXynConsole(): XynConsoleContextValue {
  const value = useContext(XynConsoleContext);
  if (!value) throw new Error("useXynConsole must be used within XynConsoleProvider");
  return value;
}
