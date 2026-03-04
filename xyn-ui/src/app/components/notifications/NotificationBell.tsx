import { Bell, CircleAlert, CircleCheck, CircleDashed, Info, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useNotifications, type NotificationItem } from "../../state/notificationsStore";

type Filter = "all" | "unread" | "errors";

function iconFor(item: NotificationItem) {
  if (item.level === "error") return <CircleAlert size={16} />;
  if (item.level === "success") return <CircleCheck size={16} />;
  if (item.status === "queued" || item.status === "running") return <CircleDashed size={16} />;
  return <Info size={16} />;
}

function relativeTime(ts: number): string {
  const delta = Math.max(1, Math.floor((Date.now() - ts) / 1000));
  if (delta < 60) return `${delta}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86400)}d ago`;
}

export default function NotificationBell() {
  const navigate = useNavigate();
  const { notifications, unreadCount, markRead, markAllRead, dismiss, clearAll } = useNotifications();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");

  const filtered = useMemo(() => {
    if (filter === "unread") return notifications.filter((item) => item.unread);
    if (filter === "errors") return notifications.filter((item) => item.level === "error" || item.status === "failed");
    return notifications;
  }, [filter, notifications]);

  return (
    <>
      <button
        type="button"
        className="ghost notification-bell"
        aria-label="Notifications"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
      >
        <Bell size={16} />
        {unreadCount > 0 && <span className="notification-badge">{unreadCount > 99 ? "99+" : unreadCount}</span>}
      </button>

      {open && <button type="button" className="notification-backdrop" aria-label="Close notifications" onClick={() => setOpen(false)} />}

      <aside className={`notification-drawer ${open ? "open" : ""}`} aria-label="Notifications">
        <div className="notification-drawer-header">
          <h3>Notifications</h3>
          <button type="button" className="ghost" onClick={() => setOpen(false)} aria-label="Close notifications">
            <X size={14} />
          </button>
        </div>

        <div className="notification-filters">
          <button
            type="button"
            className={`ghost ${filter === "all" ? "active" : ""}`}
            onClick={() => setFilter("all")}
          >
            All
          </button>
          <button
            type="button"
            className={`ghost ${filter === "unread" ? "active" : ""}`}
            onClick={() => setFilter("unread")}
          >
            Unread
          </button>
          <button
            type="button"
            className={`ghost ${filter === "errors" ? "active" : ""}`}
            onClick={() => setFilter("errors")}
          >
            Errors
          </button>
        </div>

        <div className="notification-actions">
          <button type="button" className="ghost small" onClick={markAllRead}>
            Mark all read
          </button>
          <button type="button" className="ghost small" onClick={clearAll}>
            Clear all
          </button>
        </div>

        <div className="notification-list">
          {filtered.length === 0 && <p className="muted">No notifications.</p>}
          {filtered.map((item) => (
            <div key={item.id} className={`notification-item ${item.unread ? "unread" : ""}`}>
              <button
                type="button"
                className="notification-item-main"
                onClick={() => {
                  markRead(item.id);
                  if (item.href) {
                    navigate(item.href);
                    setOpen(false);
                  }
                }}
              >
                <span className={`notification-icon ${item.level}`}>{iconFor(item)}</span>
                <span className="notification-text">
                  <strong>{item.title}</strong>
                  {item.message && <span className="muted small">{item.message}</span>}
                  <span className="muted small">{relativeTime(item.ts)}</span>
                </span>
              </button>
              <button
                type="button"
                className="ghost small"
                aria-label="Dismiss notification"
                onClick={() => dismiss(item.id)}
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      </aside>
    </>
  );
}
