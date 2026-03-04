import { createContext, useCallback, useContext, useMemo, useReducer, type ReactNode } from "react";

export type OperationType = "ai" | "deploy" | "save" | "sync" | "other";
export type OperationStatus = "running" | "succeeded" | "failed";

export type OperationEntityType = "article" | "draft_session" | "release" | "instance" | "unknown";

export type OperationItem = {
  id: string;
  type: OperationType;
  status: OperationStatus;
  label: string;
  entityType?: OperationEntityType;
  entityId?: string;
  startedAt: number;
  finishedAt?: number;
  summary?: string;
};

type OperationState = {
  items: OperationItem[];
};

type StartInput = {
  id: string;
  type: OperationType;
  label: string;
  entityType?: OperationEntityType;
  entityId?: string;
};

type FinishInput = {
  id: string;
  status: Exclude<OperationStatus, "running">;
  summary?: string;
};

type OperationAction = { type: "START"; payload: StartInput } | { type: "FINISH"; payload: FinishInput };

const MAX_ITEMS = 150;

function sortAndTrim(items: OperationItem[]): OperationItem[] {
  return [...items]
    .sort((a, b) => {
      if (a.status === "running" && b.status !== "running") return -1;
      if (b.status === "running" && a.status !== "running") return 1;
      const aTs = a.finishedAt ?? a.startedAt;
      const bTs = b.finishedAt ?? b.startedAt;
      return bTs - aTs;
    })
    .slice(0, MAX_ITEMS);
}

export function operationRegistryReducer(state: OperationState, action: OperationAction): OperationState {
  switch (action.type) {
    case "START": {
      const now = Date.now();
      const existing = state.items.find((entry) => entry.id === action.payload.id);
      const next: OperationItem = existing
        ? {
            ...existing,
            ...action.payload,
            status: "running",
            startedAt: now,
            finishedAt: undefined,
            summary: undefined,
          }
        : {
            ...action.payload,
            status: "running",
            startedAt: now,
          };
      return { items: sortAndTrim([next, ...state.items.filter((entry) => entry.id !== action.payload.id)]) };
    }
    case "FINISH": {
      const now = Date.now();
      const existing = state.items.find((entry) => entry.id === action.payload.id);
      if (!existing) return state;
      const next: OperationItem = {
        ...existing,
        status: action.payload.status,
        summary: action.payload.summary,
        finishedAt: now,
      };
      return { items: sortAndTrim([next, ...state.items.filter((entry) => entry.id !== action.payload.id)]) };
    }
    default:
      return state;
  }
}

type OperationsContextValue = {
  operations: OperationItem[];
  runningCount: number;
  runningAiCount: number;
  startOperation: (input: StartInput) => void;
  finishOperation: (input: FinishInput) => void;
};

const OperationsContext = createContext<OperationsContextValue | null>(null);

export function OperationsProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(operationRegistryReducer, { items: [] });

  const startOperation = useCallback((input: StartInput) => {
    dispatch({ type: "START", payload: input });
  }, []);

  const finishOperation = useCallback((input: FinishInput) => {
    dispatch({ type: "FINISH", payload: input });
  }, []);

  const runningCount = useMemo(() => state.items.filter((entry) => entry.status === "running").length, [state.items]);
  const runningAiCount = useMemo(
    () => state.items.filter((entry) => entry.status === "running" && entry.type === "ai").length,
    [state.items]
  );

  const value = useMemo(
    () => ({
      operations: state.items,
      runningCount,
      runningAiCount,
      startOperation,
      finishOperation,
    }),
    [finishOperation, runningAiCount, runningCount, startOperation, state.items]
  );

  return <OperationsContext.Provider value={value}>{children}</OperationsContext.Provider>;
}

export function useOperations(): OperationsContextValue {
  const value = useContext(OperationsContext);
  if (!value) throw new Error("useOperations must be used within OperationsProvider");
  return value;
}

