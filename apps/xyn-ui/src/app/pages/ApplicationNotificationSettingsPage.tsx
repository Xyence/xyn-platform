import { FormEvent, useCallback, useEffect, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import {
  createNotificationDeliveryTarget,
  getNotificationDeliveryPreference,
  listNotificationDeliveryTargets,
  removeNotificationDeliveryTarget,
  setNotificationDeliveryPreference,
  setNotificationDeliveryTargetEnabled,
} from "../../api/xyn";
import type { NotificationDeliveryPreference, NotificationDeliveryTarget } from "../../api/types";

function verificationLabel(value: string): string {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized) return "Unknown";
  if (normalized === "verified") return "Verified";
  if (normalized === "pending") return "Pending";
  if (normalized === "unverified") return "Unverified";
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

type ApplicationNotificationSettingsPageProps = {
  workspaceId?: string;
  workspaceRole?: string;
};

export default function ApplicationNotificationSettingsPage({
  workspaceId = "",
  workspaceRole = "",
}: ApplicationNotificationSettingsPageProps) {
  const [targets, setTargets] = useState<NotificationDeliveryTarget[]>([]);
  const [preference, setPreference] = useState<NotificationDeliveryPreference>({
    source_app_key: "",
    in_app_enabled: true,
    email_enabled: true,
  });
  const [newEmail, setNewEmail] = useState("");
  const [newIsPrimary, setNewIsPrimary] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const normalizedRole = workspaceRole.trim().toLowerCase();
  const hasWorkspace = workspaceId.trim().length > 0;
  const canManage = hasWorkspace && (normalizedRole ? normalizedRole !== "reader" : true);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const resolvedWorkspaceId = workspaceId.trim();
      if (!resolvedWorkspaceId) {
        setError("Workspace context is required to manage notification settings.");
        return;
      }
      const [targetsResponse, preferenceResponse] = await Promise.all([
        listNotificationDeliveryTargets(resolvedWorkspaceId),
        getNotificationDeliveryPreference("", resolvedWorkspaceId),
      ]);
      setTargets(targetsResponse.targets || []);
      setPreference(
        preferenceResponse.preference || {
          source_app_key: "",
          in_app_enabled: true,
          email_enabled: true,
        }
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const onAddTarget = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const address = newEmail.trim();
      if (!address) return;
      try {
        setSaving(true);
        setError(null);
        await createNotificationDeliveryTarget({
          address,
          enabled: true,
          is_primary: newIsPrimary,
          workspace_id: workspaceId,
        });
        setNewEmail("");
        setNewIsPrimary(false);
        await load();
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setSaving(false);
      }
    },
    [load, newEmail, newIsPrimary, workspaceId]
  );

  const onToggleTarget = useCallback(
    async (target: NotificationDeliveryTarget) => {
      try {
        setSaving(true);
        setError(null);
        await setNotificationDeliveryTargetEnabled(target.id, !target.enabled, workspaceId);
        await load();
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setSaving(false);
      }
    },
    [load]
  );

  const onRemoveTarget = useCallback(
    async (target: NotificationDeliveryTarget) => {
      try {
        setSaving(true);
        setError(null);
        await removeNotificationDeliveryTarget(target.id, workspaceId);
        await load();
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setSaving(false);
      }
    },
    [load]
  );

  const onUpdatePreference = useCallback(
    async (next: Partial<NotificationDeliveryPreference>) => {
      const candidate = {
        ...preference,
        ...next,
      };
      try {
        setSaving(true);
        setError(null);
        const response = await setNotificationDeliveryPreference({
          source_app_key: candidate.source_app_key || "",
          in_app_enabled: !!candidate.in_app_enabled,
          email_enabled: !!candidate.email_enabled,
          workspace_id: workspaceId,
        });
        setPreference(response.preference || candidate);
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setSaving(false);
      }
    },
    [preference, workspaceId]
  );

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Notification Settings</h2>
          <p className="muted">Manage your application notification email targets and delivery preferences.</p>
        </div>
        <div className="inline-actions">
          <button type="button" className="ghost" onClick={() => void load()} disabled={loading || saving}>
            Refresh
          </button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {!error && !canManage ? (
        <InlineMessage
          tone="info"
          title="Read-only access"
          body="You can view notification settings, but you do not have permission to make changes in this workspace."
        />
      ) : null}

      <section className="card">
        <h3>Notification targets (Email)</h3>
        <p className="muted">Add or disable email delivery targets for application notifications.</p>
        <form className="inline-actions" onSubmit={onAddTarget}>
          <input
            className="input"
            aria-label="Email address"
            type="email"
            value={newEmail}
            placeholder="name@example.com"
            onChange={(event) => setNewEmail(event.target.value)}
            disabled={saving || !canManage}
          />
          <label className="inline-actions">
            <input
              type="checkbox"
              checked={newIsPrimary}
              onChange={(event) => setNewIsPrimary(event.target.checked)}
              disabled={saving || !canManage}
            />
            Primary
          </label>
          <button type="submit" className="ghost" disabled={saving || !newEmail.trim() || !canManage}>
            Add target
          </button>
        </form>

        {loading ? <p className="muted">Loading targets…</p> : null}
        {!loading && targets.length === 0 ? <p className="muted">No notification targets configured yet.</p> : null}
        {!loading && targets.length > 0 ? (
          <div className="notification-list" data-testid="delivery-target-list">
            {targets.map((target) => (
              <article key={target.id} className="notification-item" data-testid={`delivery-target-${target.id}`}>
                <div className="notification-text">
                  <div className="notification-title-row">
                    <strong>{target.address}</strong>
                    {target.is_primary ? <span className="badge">Primary</span> : null}
                    <span className={`badge ${target.enabled ? "" : "muted"}`}>{target.enabled ? "Enabled" : "Disabled"}</span>
                  </div>
                  <p className="muted">Verification: {verificationLabel(target.verification_status)}</p>
                </div>
                <div className="inline-actions">
                  <button type="button" className="ghost sm" onClick={() => void onToggleTarget(target)} disabled={saving || !canManage}>
                    {target.enabled ? "Disable" : "Enable"}
                  </button>
                  <button type="button" className="ghost sm" onClick={() => void onRemoveTarget(target)} disabled={saving || !canManage}>
                    Remove
                  </button>
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </section>

      <section className="card">
        <h3>Delivery preferences</h3>
        <p className="muted">These settings control whether in-app and email delivery are enabled for your account.</p>
        <div className="form-grid compact">
          <label>
            <input
              type="checkbox"
              checked={!!preference.in_app_enabled}
              onChange={(event) => void onUpdatePreference({ in_app_enabled: event.target.checked })}
              disabled={saving || !canManage}
            />{" "}
            In-app notifications enabled
          </label>
          <label>
            <input
              type="checkbox"
              checked={!!preference.email_enabled}
              onChange={(event) => void onUpdatePreference({ email_enabled: event.target.checked })}
              disabled={saving || !canManage}
            />{" "}
            Email notifications enabled
          </label>
        </div>
        <p className="muted">Verification is managed separately. Unverified targets may not receive email until verified.</p>
      </section>
    </>
  );
}
