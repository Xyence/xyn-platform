import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  type ReactNode,
} from "react";

const STORAGE_KEY = "xyn.notifications.v1";
const MAX_NOTIFICATIONS = 200;
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

export type NotificationLevel = "info" | "success" | "warning" | "error";
export type NotificationStatus = "queued" | "running" | "succeeded" | "failed";
export type NotificationEntityType =
  | "draft_session"
  | "blueprint"
  | "instance"
  | "run"
  | "release"
  | "release_plan"
  | "registry"
  | "unknown";

export type NotificationItem = {
  id: string;
  ts: number;
  level: NotificationLevel;
  title: string;
  message?: string;
  entityType?: NotificationEntityType;
  entityId?: string;
  action?: string;
  status?: NotificationStatus;
  href?: string;
  ctaLabel?: string;
  ctaAction?: string;
  dedupeKey?: string;
  unread: boolean;
  version: number;
};

export type NotificationInput = Omit<NotificationItem, "id" | "ts" | "unread" | "version"> & {
  id?: string;
  ts?: number;
  unread?: boolean;
  version?: number;
};

type NotificationsState = {
  notifications: NotificationItem[];
};

type NotificationsAction =
  | { type: "PUSH"; payload: NotificationInput }
  | { type: "MARK_READ"; id: string }
  | { type: "MARK_ALL_READ" }
  | { type: "DISMISS"; id: string }
  | { type: "CLEAR_ALL" }
  | { type: "HYDRATE"; items: NotificationItem[] };

function newId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `notif-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function normalizeItems(items: NotificationItem[]): NotificationItem[] {
  const cutoff = Date.now() - MAX_AGE_MS;
  return items
    .filter((item) => Number.isFinite(item.ts) && item.ts >= cutoff)
    .sort((a, b) => b.ts - a.ts)
    .slice(0, MAX_NOTIFICATIONS);
}

export function makeNotification(input: NotificationInput): NotificationItem {
  return {
    id: input.id || newId(),
    ts: input.ts ?? Date.now(),
    level: input.level,
    title: input.title,
    message: input.message,
    entityType: input.entityType,
    entityId: input.entityId,
    action: input.action,
    status: input.status,
    href: input.href,
    ctaLabel: input.ctaLabel,
    ctaAction: input.ctaAction,
    dedupeKey: input.dedupeKey,
    unread: input.unread ?? true,
    version: input.version ?? 1,
  };
}

export function notificationsReducer(state: NotificationsState, action: NotificationsAction): NotificationsState {
  switch (action.type) {
    case "HYDRATE":
      return { notifications: normalizeItems(action.items) };
    case "PUSH": {
      const incoming = makeNotification(action.payload);
      const existingIdx = incoming.dedupeKey
        ? state.notifications.findIndex((item) => item.dedupeKey === incoming.dedupeKey && item.unread)
        : -1;
      if (existingIdx >= 0) {
        const existing = state.notifications[existingIdx];
        const updated: NotificationItem = {
          ...existing,
          ...incoming,
          id: existing.id,
          ts: Date.now(),
          unread: true,
          version: (existing.version || 1) + 1,
        };
        const next = [...state.notifications];
        next.splice(existingIdx, 1);
        return { notifications: normalizeItems([updated, ...next]) };
      }
      return { notifications: normalizeItems([incoming, ...state.notifications]) };
    }
    case "MARK_READ":
      return {
        notifications: state.notifications.map((item) =>
          item.id === action.id
            ? {
                ...item,
                unread: false,
              }
            : item
        ),
      };
    case "MARK_ALL_READ":
      return {
        notifications: state.notifications.map((item) => ({ ...item, unread: false })),
      };
    case "DISMISS":
      return {
        notifications: state.notifications.filter((item) => item.id !== action.id),
      };
    case "CLEAR_ALL":
      return { notifications: [] };
    default:
      return state;
  }
}

function readStorage(): NotificationItem[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return normalizeItems(
      parsed
        .map((item) => {
          if (!item || typeof item !== "object") return null;
          try {
            return makeNotification(item as NotificationInput);
          } catch {
            return null;
          }
        })
        .filter(Boolean) as NotificationItem[]
    );
  } catch {
    return [];
  }
}

function writeStorage(items: NotificationItem[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(normalizeItems(items)));
  } catch {
    // ignore storage write errors
  }
}

type NotificationsContextValue = {
  notifications: NotificationItem[];
  unreadCount: number;
  push: (item: NotificationInput) => string;
  markRead: (id: string) => void;
  markAllRead: () => void;
  dismiss: (id: string) => void;
  clearAll: () => void;
};

const NotificationsContext = createContext<NotificationsContextValue | null>(null);

export function NotificationsProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(notificationsReducer, { notifications: [] });

  useEffect(() => {
    dispatch({ type: "HYDRATE", items: readStorage() });
  }, []);

  useEffect(() => {
    writeStorage(state.notifications);
  }, [state.notifications]);

  const push = useCallback((item: NotificationInput) => {
    const id = item.id || newId();
    dispatch({ type: "PUSH", payload: { ...item, id } });
    return id;
  }, []);

  const markRead = useCallback((id: string) => dispatch({ type: "MARK_READ", id }), []);
  const markAllRead = useCallback(() => dispatch({ type: "MARK_ALL_READ" }), []);
  const dismiss = useCallback((id: string) => dispatch({ type: "DISMISS", id }), []);
  const clearAll = useCallback(() => dispatch({ type: "CLEAR_ALL" }), []);

  const unreadCount = useMemo(
    () => state.notifications.reduce((count, item) => count + (item.unread ? 1 : 0), 0),
    [state.notifications]
  );

  const value = useMemo(
    () => ({
      notifications: state.notifications,
      unreadCount,
      push,
      markRead,
      markAllRead,
      dismiss,
      clearAll,
    }),
    [clearAll, dismiss, markAllRead, markRead, push, state.notifications, unreadCount]
  );

  return <NotificationsContext.Provider value={value}>{children}</NotificationsContext.Provider>;
}

export function useNotifications(): NotificationsContextValue {
  const value = useContext(NotificationsContext);
  if (!value) {
    throw new Error("useNotifications must be used within NotificationsProvider");
  }
  return value;
}
