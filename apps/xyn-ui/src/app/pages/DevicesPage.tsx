import { useCallback, useEffect, useMemo, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import {
  confirmAction,
  createDevice,
  createDeviceAction,
  deleteDevice,
  executeAction,
  getActionReceipts,
  listActions,
  listTenantDevices,
  listVisibleTenants,
  ratifyAction,
  setActiveTenant,
  updateDevice,
} from "../../api/xyn";
import type { Device, DevicePayload, DraftAction, ExecutionReceipt, Tenant } from "../../api/types";

const emptyForm: DevicePayload = {
  name: "",
  device_type: "",
  mgmt_ip: "",
  status: "unknown",
};

export default function DevicesPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [activeTenant, setActiveTenantId] = useState<string>("");
  const [selected, setSelected] = useState<Device | null>(null);
  const [form, setForm] = useState<DevicePayload>(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [actions, setActions] = useState<DraftAction[]>([]);
  const [receiptsByAction, setReceiptsByAction] = useState<Record<string, ExecutionReceipt[]>>({});
  const [busy, setBusy] = useState(false);

  const activeRole = useMemo(() => {
    const match = tenants.find((t) => t.id === activeTenant);
    return (match as Tenant & { membership_role?: string }).membership_role || "";
  }, [tenants, activeTenant]);

  const canEdit =
    activeRole === "tenant_admin" || activeRole === "tenant_operator" || activeRole === "platform_admin";
  const canRequestAction =
    activeRole === "tenant_admin" || activeRole === "tenant_operator" || activeRole === "platform_admin";
  const canAdminAction = activeRole === "tenant_admin" || activeRole === "platform_admin";

  const load = useCallback(async () => {
    try {
      setError(null);
      const tenantData = await listVisibleTenants();
      setTenants(tenantData.tenants);
      if (!activeTenant && tenantData.tenants[0]) {
        const tenantId = tenantData.tenants[0].id;
        setActiveTenantId(tenantId);
        await setActiveTenant(tenantId);
      }
      const data = await listTenantDevices();
      setDevices(data.devices);
      if (selected?.id) {
        const actionData = await listActions(selected.id);
        setActions(actionData.actions);
      } else {
        setActions([]);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }, [activeTenant, selected?.id]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!selected) {
      setForm(emptyForm);
      return;
    }
    setForm({
      name: selected.name,
      device_type: selected.device_type,
      mgmt_ip: selected.mgmt_ip,
      status: selected.status,
      tags: selected.tags,
      metadata_json: selected.metadata_json,
    });
  }, [selected]);

  const loadActions = useCallback(async () => {
    if (!selected?.id) {
      setActions([]);
      return;
    }
    try {
      const data = await listActions(selected.id);
      setActions(data.actions);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [selected?.id]);

  useEffect(() => {
    loadActions();
  }, [loadActions]);

  const handleTenantChange = async (tenantId: string) => {
    setActiveTenantId(tenantId);
    await setActiveTenant(tenantId);
    setSelected(null);
    setActions([]);
    await load();
  };

  const handleSave = async () => {
    try {
      setError(null);
      setMessage(null);
      if (selected) {
        await updateDevice(selected.id, form);
        setMessage("Device updated.");
      } else {
        await createDevice(form);
        setMessage("Device created.");
      }
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleDelete = async () => {
    if (!selected) return;
    if (!confirm("Delete this device?")) return;
    try {
      setError(null);
      setMessage(null);
      await deleteDevice(selected.id);
      setSelected(null);
      await load();
      setMessage("Device deleted.");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleReboot = async () => {
    if (!selected || !canRequestAction) return;
    try {
      setBusy(true);
      setError(null);
      setMessage(null);
      const created = await createDeviceAction(selected.id, {
        action_type: "device.reboot",
        params: { reason: "user_request" },
      });
      let next = created.action;
      if (created.requires_confirmation) {
        const accepted = confirm(`Confirm reboot for device ${selected.name}?`);
        if (!accepted) {
          setMessage("Reboot action created; awaiting confirmation.");
          await loadActions();
          return;
        }
        const confirmed = await confirmAction(created.action.id);
        next = confirmed.action;
      }
      setMessage(`Reboot action ${next.status}.`);
      await loadActions();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleExecute = async (actionId: string) => {
    try {
      setBusy(true);
      setError(null);
      await executeAction(actionId);
      await loadActions();
      setMessage("Action executed.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleRatify = async (actionId: string) => {
    try {
      setBusy(true);
      setError(null);
      await ratifyAction(actionId, { method: "ui_confirm" });
      await loadActions();
      setMessage("Action ratified.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleLoadReceipts = async (actionId: string) => {
    try {
      setBusy(true);
      const result = await getActionReceipts(actionId);
      setReceiptsByAction((prev) => ({ ...prev, [actionId]: result.receipts }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Devices</h2>
          <p className="muted">Manage tenant devices.</p>
        </div>
        <div className="header-actions">
          <select value={activeTenant} onChange={(event) => handleTenantChange(event.target.value)}>
            {tenants.map((tenant) => (
              <option key={tenant.id} value={tenant.id}>
                {tenant.name}
              </option>
            ))}
          </select>
          <button className="ghost" onClick={load}>
            Refresh
          </button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <div className="layout">
        <section className="card">
          <div className="card-header">
            <h3>Device list</h3>
          </div>
          <div className="instance-list">
            {devices.map((device) => (
              <button
                key={device.id}
                className={`instance-row ${selected?.id === device.id ? "active" : ""}`}
                onClick={() => setSelected(device)}
              >
                <div>
                  <strong>{device.name}</strong>
                  <span className="muted small">{device.device_type}</span>
                </div>
                <span className="muted small">{device.status}</span>
              </button>
            ))}
            {devices.length === 0 && <p className="muted">No devices yet.</p>}
          </div>
        </section>

        <section className="card">
          <div className="card-header">
            <h3>{selected ? "Device detail" : "Create device"}</h3>
          </div>
          <div className="form-grid">
            <label>
              Name
              <input
                value={form.name ?? ""}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
                disabled={!canEdit}
              />
            </label>
            <label>
              Type
              <input
                value={form.device_type ?? ""}
                onChange={(event) => setForm({ ...form, device_type: event.target.value })}
                disabled={!canEdit}
              />
            </label>
            <label>
              Mgmt IP
              <input
                value={form.mgmt_ip ?? ""}
                onChange={(event) => setForm({ ...form, mgmt_ip: event.target.value })}
                disabled={!canEdit}
              />
            </label>
            <label>
              Status
              <select
                value={form.status ?? "unknown"}
                onChange={(event) => setForm({ ...form, status: event.target.value })}
                disabled={!canEdit}
              >
                <option value="active">active</option>
                <option value="offline">offline</option>
                <option value="unknown">unknown</option>
              </select>
            </label>
          </div>
          <div className="form-actions">
            <button className="primary" onClick={handleSave} disabled={!canEdit}>
              {selected ? "Save changes" : "Create"}
            </button>
            {selected && (
              <button className="ghost" onClick={handleReboot} disabled={!canRequestAction || busy}>
                Reboot (governed)
              </button>
            )}
            {selected && (
              <button className="danger" onClick={handleDelete} disabled={!canEdit}>
                Delete
              </button>
            )}
          </div>
        </section>

        <section className="card">
          <div className="card-header">
            <h3>Audit</h3>
          </div>
          {!selected ? (
            <p className="muted">Select a device to see governed actions.</p>
          ) : (
            <div className="stack">
              {actions.map((action) => (
                <div key={action.id} className="item-row">
                  <div>
                    <strong>{action.action_type}</strong>
                    <div className="muted small">{action.status}</div>
                  </div>
                  <div className="inline-actions">
                    {action.status === "pending_ratification" && canAdminAction && (
                      <button className="ghost" onClick={() => handleRatify(action.id)} disabled={busy}>
                        Ratify
                      </button>
                    )}
                    {(action.status === "pending_ratification" || action.status === "pending_verification") && canAdminAction && (
                      <button className="ghost" onClick={() => handleExecute(action.id)} disabled={busy}>
                        Execute
                      </button>
                    )}
                    <button className="ghost" onClick={() => handleLoadReceipts(action.id)} disabled={busy}>
                      Receipts
                    </button>
                  </div>
                  {receiptsByAction[action.id]?.length ? (
                    <div className="muted small">
                      Latest receipt: {receiptsByAction[action.id][0].outcome}
                      {receiptsByAction[action.id][0].error_message ? ` · ${receiptsByAction[action.id][0].error_message}` : ""}
                    </div>
                  ) : null}
                </div>
              ))}
              {actions.length === 0 && <p className="muted">No governed actions yet.</p>}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
