import { useCallback, useEffect, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import {
  createRoleBinding,
  deleteRoleBinding,
  listIdentities,
  listRoleBindings,
} from "../../api/xyn";
import type { IdentitySummary, RoleBindingSummary } from "../../api/types";

const ROLE_OPTIONS = ["platform_owner", "platform_admin", "platform_architect", "platform_operator", "app_user"];

export default function PlatformRolesPage() {
  const [identities, setIdentities] = useState<IdentitySummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [bindings, setBindings] = useState<RoleBindingSummary[]>([]);
  const [role, setRole] = useState("platform_operator");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const selectedIdentity = identities.find((item) => item.id === selectedId) || null;

  const loadIdentities = useCallback(async () => {
    try {
      setError(null);
      const data = await listIdentities();
      setIdentities(data.identities);
      if (!selectedId && data.identities[0]) {
        setSelectedId(data.identities[0].id);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }, [selectedId]);

  const loadBindings = useCallback(async () => {
    if (!selectedId) return;
    try {
      setError(null);
      const data = await listRoleBindings(selectedId);
      setBindings(data.role_bindings);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [selectedId]);

  useEffect(() => {
    loadIdentities();
  }, [loadIdentities]);

  useEffect(() => {
    loadBindings();
  }, [loadBindings]);

  const handleAddRole = async () => {
    if (!selectedId) return;
    try {
      setError(null);
      setMessage(null);
      await createRoleBinding({ user_identity_id: selectedId, role });
      await loadBindings();
      setMessage("Role added.");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleRemoveRole = async (bindingId: string) => {
    if (!confirm("Remove this role binding?")) return;
    try {
      setError(null);
      setMessage(null);
      await deleteRoleBinding(bindingId);
      await loadBindings();
      setMessage("Role removed.");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Roles</h2>
          <p className="muted">Assign platform roles to identities.</p>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <div className="layout">
        <section className="card">
          <div className="card-header">
            <h3>Identities</h3>
          </div>
          <div className="instance-list">
            {identities.map((item) => (
              <button
                key={item.id}
                className={`instance-row ${selectedId === item.id ? "active" : ""}`}
                onClick={() => setSelectedId(item.id)}
              >
                <div>
                  <strong>{item.display_name || item.email || item.subject}</strong>
                  <span className="muted small">{item.email || item.subject}</span>
                </div>
              </button>
            ))}
            {identities.length === 0 && <p className="muted">No identities yet.</p>}
          </div>
        </section>

        <section className="card">
          <div className="card-header">
            <h3>Role bindings</h3>
          </div>
          {selectedIdentity && (
            <div className="stack">
              <span className="muted small">
                User: {selectedIdentity.display_name || selectedIdentity.email || selectedIdentity.subject}
              </span>
              <span className="muted small">
                Identity provider:{" "}
                {selectedIdentity.provider_display_name
                  ? `${selectedIdentity.provider_display_name}${
                      selectedIdentity.provider_id ? ` (${selectedIdentity.provider_id})` : ""
                    }`
                  : selectedIdentity.provider_id || selectedIdentity.provider || selectedIdentity.issuer}
              </span>
            </div>
          )}
          <div className="form-grid">
            <label>
              Role
              <select value={role} onChange={(event) => setRole(event.target.value)}>
                {ROLE_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <button className="primary" onClick={handleAddRole} disabled={!selectedId}>
              Add role
            </button>
          </div>
          <div className="instance-list">
            {bindings.map((binding) => (
              <div key={binding.id} className="instance-row">
                <div>
                  <strong>{binding.role}</strong>
                  <span className="muted small">{binding.scope_kind}</span>
                </div>
                <button className="ghost" onClick={() => handleRemoveRole(binding.id)}>
                  Remove
                </button>
              </div>
            ))}
            {bindings.length === 0 && <p className="muted">No roles assigned.</p>}
          </div>
        </section>
      </div>
    </>
  );
}
