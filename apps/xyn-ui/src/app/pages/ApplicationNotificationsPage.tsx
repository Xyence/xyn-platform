import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import {
  getApplicationNotificationUnreadCount,
  listApplicationNotifications,
  markAllApplicationNotificationsRead,
  markApplicationNotificationRead,
} from "../../api/xyn";
import type { ApplicationNotification } from "../../api/types";

const PAGE_LIMIT = 100;

function formatTimestamp(value?: string): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function isExternalLink(value: string): boolean {
  return /^https?:\/\//i.test(String(value || "").trim());
}

export default function ApplicationNotificationsPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<ApplicationNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadFeed = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [feed, unread] = await Promise.all([
        listApplicationNotifications({ limit: PAGE_LIMIT, offset: 0 }),
        getApplicationNotificationUnreadCount(),
      ]);
      setItems(feed.notifications || []);
      setUnreadCount(Number(unread.unread_count || 0));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadFeed();
  }, [loadFeed]);

  const unreadIds = useMemo(
    () => new Set(items.filter((item) => item.unread).map((item) => String(item.notification_id))),
    [items]
  );

  const markOneRead = useCallback(
    async (notificationId: string) => {
      if (!unreadIds.has(notificationId)) return;
      try {
        setWorking(true);
        setError(null);
        const response = await markApplicationNotificationRead(notificationId);
        setItems((current) =>
          current.map((item) =>
            item.notification_id === notificationId
              ? { ...item, unread: false, read_at: item.read_at || new Date().toISOString() }
              : item
          )
        );
        setUnreadCount(Number(response.unread_count || 0));
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setWorking(false);
      }
    },
    [unreadIds]
  );

  const markAllRead = useCallback(async () => {
    if (!items.some((item) => item.unread)) return;
    try {
      setWorking(true);
      setError(null);
      const response = await markAllApplicationNotificationsRead();
      setItems((current) => current.map((item) => ({ ...item, unread: false, read_at: item.read_at || new Date().toISOString() })));
      setUnreadCount(Number(response.unread_count || 0));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setWorking(false);
    }
  }, [items]);

  const openNotification = useCallback(
    (item: ApplicationNotification) => {
      if (item.unread) {
        void markOneRead(item.notification_id);
      }
      const target = String(item.deep_link || "").trim();
      if (!target) return;
      if (isExternalLink(target)) {
        window.open(target, "_blank", "noopener,noreferrer");
        return;
      }
      navigate(target);
    },
    [markOneRead, navigate]
  );

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Application Notifications</h2>
          <p className="muted">Durable backend notification feed for application events.</p>
        </div>
        <div className="inline-actions">
          <span className="badge">Unread {unreadCount}</span>
          <Link className="ghost" to="settings">
            Settings
          </Link>
          <button type="button" className="ghost" onClick={() => void loadFeed()} disabled={loading || working}>
            Refresh
          </button>
          <button type="button" className="ghost" onClick={() => void markAllRead()} disabled={working || unreadCount === 0}>
            Mark all read
          </button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}

      <section className="card">
        {loading ? <p className="muted">Loading notifications…</p> : null}
        {!loading && items.length === 0 ? <p className="muted">No application notifications yet.</p> : null}
        {!loading && items.length > 0 ? (
          <div className="notification-list" data-testid="application-notification-list">
            {items.map((item) => (
              <article
                key={item.notification_id}
                className={`notification-item ${item.unread ? "unread" : ""}`}
                data-testid={`application-notification-${item.notification_id}`}
              >
                <div className="notification-text">
                  <div className="notification-title-row">
                    <strong>{item.title}</strong>
                    {item.unread ? <span className="badge">Unread</span> : <span className="muted">Read</span>}
                  </div>
                  {item.summary ? <p>{item.summary}</p> : null}
                  <p className="muted">
                    Source: {item.source_app_key || "unknown"} · {formatTimestamp(item.created_at)}
                  </p>
                </div>
                <div className="inline-actions">
                  {item.unread ? (
                    <button type="button" className="ghost sm" onClick={() => void markOneRead(item.notification_id)} disabled={working}>
                      Mark read
                    </button>
                  ) : null}
                  {item.deep_link ? (
                    <button type="button" className="ghost sm" onClick={() => openNotification(item)}>
                      Open
                    </button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </section>
    </>
  );
}
