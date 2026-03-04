import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import {
  createContact,
  deleteContact,
  listContacts,
  listMemberships,
  createMembership,
  updateMembership,
  deleteMembership,
  listIdentities,
  getTenantBranding,
  updateTenantBranding,
  updateContact,
} from "../../api/xyn";
import type {
  Contact,
  ContactCreatePayload,
  IdentitySummary,
  MembershipSummary,
  BrandingPayload,
} from "../../api/types";

const emptyForm: ContactCreatePayload = {
  name: "",
  email: "",
  phone: "",
  role_title: "",
  status: "active",
};

export default function PlatformTenantContactsPage() {
  const { tenantId } = useParams<{ tenantId: string }>();
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form, setForm] = useState<ContactCreatePayload>(emptyForm);
  const [memberships, setMemberships] = useState<MembershipSummary[]>([]);
  const [identities, setIdentities] = useState<IdentitySummary[]>([]);
  const [selectedIdentity, setSelectedIdentity] = useState<string>("");
  const [membershipRole, setMembershipRole] = useState("tenant_viewer");
  const [branding, setBranding] = useState<BrandingPayload>({});
  const [themeText, setThemeText] = useState("{}");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!tenantId) return;
    try {
      setError(null);
      const data = await listContacts(tenantId);
      setContacts(data.contacts);
      const membershipData = await listMemberships(tenantId);
      setMemberships(membershipData.memberships);
      const identitiesData = await listIdentities();
      setIdentities(identitiesData.identities);
      try {
        const brandingData = await getTenantBranding(tenantId);
        setBranding({
          display_name: brandingData.display_name,
          logo_url: brandingData.logo_url,
          theme_json: brandingData.theme,
        });
        setThemeText(JSON.stringify(brandingData.theme || {}, null, 2));
      } catch {
        setBranding({});
        setThemeText("{}");
      }
      if (!selectedIdentity && identitiesData.identities[0]) {
        setSelectedIdentity(identitiesData.identities[0].id);
      }
      if (!selectedId && data.contacts[0]) {
        setSelectedId(data.contacts[0].id);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }, [tenantId, selectedId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const selected = contacts.find((item) => item.id === selectedId);
    if (!selected) {
      setForm(emptyForm);
      return;
    }
    setForm({
      name: selected.name,
      email: selected.email ?? "",
      phone: selected.phone ?? "",
      role_title: selected.role_title ?? "",
      status: selected.status,
    });
  }, [contacts, selectedId]);

  const handleCreate = async () => {
    if (!tenantId) return;
    try {
      setLoading(true);
      setMessage(null);
      setError(null);
      await createContact(tenantId, form);
      setForm(emptyForm);
      await load();
      setMessage("Contact created.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleUpdate = async () => {
    if (!selectedId) return;
    try {
      setLoading(true);
      setMessage(null);
      setError(null);
      await updateContact(selectedId, form);
      await load();
      setMessage("Contact updated.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedId) return;
    if (!confirm("Deactivate this contact?")) return;
    try {
      setLoading(true);
      setError(null);
      await deleteContact(selectedId);
      setSelectedId(null);
      await load();
      setMessage("Contact deactivated.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleAddMember = async () => {
    if (!tenantId || !selectedIdentity) return;
    try {
      setError(null);
      setMessage(null);
      await createMembership(tenantId, { user_identity_id: selectedIdentity, role: membershipRole });
      await load();
      setMessage("Member added.");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleUpdateMembership = async (membershipId: string, role: string) => {
    try {
      setError(null);
      setMessage(null);
      await updateMembership(membershipId, { role });
      await load();
      setMessage("Membership updated.");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleRemoveMembership = async (membershipId: string) => {
    if (!confirm("Deactivate this membership?")) return;
    try {
      setError(null);
      setMessage(null);
      await deleteMembership(membershipId);
      await load();
      setMessage("Membership deactivated.");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleSaveBranding = async () => {
    if (!tenantId) return;
    try {
      setError(null);
      setMessage(null);
      let parsedTheme: Record<string, string> | undefined;
      if (themeText.trim()) {
        parsedTheme = JSON.parse(themeText);
      }
      await updateTenantBranding(tenantId, {
        ...branding,
        theme_json: parsedTheme,
      });
      setMessage("Branding updated.");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Contacts</h2>
          <p className="muted">Manage tenant contacts.</p>
        </div>
        <div className="header-actions">
          <button className="ghost" onClick={load} disabled={loading}>
            Refresh
          </button>
          <Link className="ghost" to="/app/platform/tenants">
            Back to tenants
          </Link>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <div className="layout">
        <section className="card">
          <div className="card-header">
            <h3>Contacts</h3>
          </div>
          <div className="instance-list">
            {contacts.map((item) => (
              <button
                key={item.id}
                className={`instance-row ${selectedId === item.id ? "active" : ""}`}
                onClick={() => setSelectedId(item.id)}
              >
                <div>
                  <strong>{item.name}</strong>
                  <span className="muted small">{item.email}</span>
                </div>
                <span className="muted small">{item.status}</span>
              </button>
            ))}
            {contacts.length === 0 && <p className="muted">No contacts yet.</p>}
          </div>
        </section>

        <section className="card">
          <div className="card-header">
            <h3>{selectedId ? "Contact detail" : "Create contact"}</h3>
          </div>
          <div className="form-grid">
            <label>
              Name
              <input
                value={form.name ?? ""}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
              />
            </label>
            <label>
              Email
              <input
                value={form.email ?? ""}
                onChange={(event) => setForm({ ...form, email: event.target.value })}
              />
            </label>
            <label>
              Phone
              <input
                value={form.phone ?? ""}
                onChange={(event) => setForm({ ...form, phone: event.target.value })}
              />
            </label>
            <label>
              Title
              <input
                value={form.role_title ?? ""}
                onChange={(event) => setForm({ ...form, role_title: event.target.value })}
              />
            </label>
            <label>
              Status
              <select
                value={form.status ?? "active"}
                onChange={(event) => setForm({ ...form, status: event.target.value })}
              >
                <option value="active">active</option>
                <option value="inactive">inactive</option>
              </select>
            </label>
          </div>
          <div className="form-actions">
            <button className="primary" onClick={selectedId ? handleUpdate : handleCreate} disabled={loading}>
              {selectedId ? "Save changes" : "Create"}
            </button>
            {selectedId && (
              <button className="danger" onClick={handleDelete} disabled={loading}>
                Deactivate
              </button>
            )}
          </div>
        </section>
      </div>

      <section className="card">
        <div className="card-header">
          <h3>Memberships</h3>
        </div>
        <div className="form-grid">
          <label>
            Identity
            <select value={selectedIdentity} onChange={(event) => setSelectedIdentity(event.target.value)}>
              {identities.map((identity) => (
                <option key={identity.id} value={identity.id}>
                  {identity.display_name || identity.email || identity.subject}
                </option>
              ))}
            </select>
          </label>
          <label>
            Role
            <select value={membershipRole} onChange={(event) => setMembershipRole(event.target.value)}>
              <option value="tenant_viewer">tenant_viewer</option>
              <option value="tenant_operator">tenant_operator</option>
              <option value="tenant_admin">tenant_admin</option>
            </select>
          </label>
          <button className="primary" onClick={handleAddMember} disabled={!selectedIdentity}>
            Add member
          </button>
        </div>
        <div className="instance-list">
          {memberships.map((membership) => (
            <div key={membership.id} className="instance-row">
              <div>
                <strong>{membership.user_display_name || membership.user_email || membership.user_identity_id}</strong>
                <span className="muted small">{membership.user_email}</span>
              </div>
              <select
                value={membership.role}
                onChange={(event) => handleUpdateMembership(membership.id, event.target.value)}
              >
                <option value="tenant_viewer">tenant_viewer</option>
                <option value="tenant_operator">tenant_operator</option>
                <option value="tenant_admin">tenant_admin</option>
              </select>
              <button className="ghost" onClick={() => handleRemoveMembership(membership.id)}>
                Deactivate
              </button>
            </div>
          ))}
          {memberships.length === 0 && <p className="muted">No memberships yet.</p>}
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <h3>Branding</h3>
        </div>
        <div className="form-grid">
          <label>
            Display name
            <input
              value={branding.display_name ?? ""}
              onChange={(event) => setBranding({ ...branding, display_name: event.target.value })}
            />
          </label>
          <label>
            Logo URL
            <input
              value={branding.logo_url ?? ""}
              onChange={(event) => setBranding({ ...branding, logo_url: event.target.value })}
            />
          </label>
          <label>
            Primary color
            <input
              value={branding.primary_color ?? ""}
              onChange={(event) => setBranding({ ...branding, primary_color: event.target.value })}
            />
          </label>
          <label>
            Secondary color
            <input
              value={branding.secondary_color ?? ""}
              onChange={(event) => setBranding({ ...branding, secondary_color: event.target.value })}
            />
          </label>
          <label className="form-full">
            Theme JSON
            <textarea
              rows={6}
              value={themeText}
              onChange={(event) => setThemeText(event.target.value)}
            />
          </label>
        </div>
        <div className="form-actions">
          <button className="primary" onClick={handleSaveBranding}>
            Save branding
          </button>
        </div>
      </section>
    </>
  );
}
