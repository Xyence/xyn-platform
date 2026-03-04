import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import Tabs from "../components/ui/Tabs";
import {
  createContact,
  createMembership,
  createTenant,
  deleteContact,
  deleteMembership,
  deleteTenant,
  getTenantBranding,
  listContacts,
  listIdentities,
  listMemberships,
  listTenants,
  updateContact,
  updateMembership,
  updateTenant,
  updateTenantBranding,
} from "../../api/xyn";
import type { BrandingPayload, Contact, ContactCreatePayload, IdentitySummary, MembershipSummary, Tenant, TenantCreatePayload } from "../../api/types";

type TenantDetailTab = "overview" | "contacts" | "members" | "branding";
const TENANT_TABS: Array<{ value: TenantDetailTab; label: string }> = [
  { value: "overview", label: "Overview" },
  { value: "contacts", label: "Contacts" },
  { value: "members", label: "Members" },
  { value: "branding", label: "Branding" },
];

const emptyTenantForm: TenantCreatePayload = {
  name: "",
  slug: "",
  status: "active",
};

const emptyContactForm: ContactCreatePayload = {
  name: "",
  email: "",
  phone: "",
  role_title: "",
  status: "active",
};

export default function PlatformTenantsPage() {
  const navigate = useNavigate();
  const { tenantId } = useParams<{ tenantId?: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const searchString = searchParams.toString();

  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [selectedContactId, setSelectedContactId] = useState<string>("");
  const [contactForm, setContactForm] = useState<ContactCreatePayload>(emptyContactForm);
  const [memberships, setMemberships] = useState<MembershipSummary[]>([]);
  const [identities, setIdentities] = useState<IdentitySummary[]>([]);
  const [selectedIdentity, setSelectedIdentity] = useState<string>("");
  const [membershipRole, setMembershipRole] = useState("tenant_viewer");
  const [branding, setBranding] = useState<BrandingPayload>({});
  const [themeText, setThemeText] = useState("{}");
  const [tenantForm, setTenantForm] = useState<TenantCreatePayload>(emptyTenantForm);
  const [createTenantOpen, setCreateTenantOpen] = useState(false);
  const [createContactOpen, setCreateContactOpen] = useState(false);
  const [newTenantForm, setNewTenantForm] = useState<TenantCreatePayload>(emptyTenantForm);
  const [newContactForm, setNewContactForm] = useState<ContactCreatePayload>(emptyContactForm);
  const [highlightedContactId, setHighlightedContactId] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const view = String(searchParams.get("view") || "all").trim().toLowerCase() === "my" ? "my" : "all";
  const detailTab = (TENANT_TABS.find((item) => item.value === searchParams.get("tab"))?.value || "overview") as TenantDetailTab;

  const visibleTenants = useMemo(
    () => (view === "my" ? tenants.filter((tenant) => Boolean(tenant.membership_role)) : tenants),
    [tenants, view]
  );

  const selectedTenant = useMemo(
    () => tenants.find((tenant) => tenant.id === tenantId) || null,
    [tenantId, tenants]
  );

  const selectedContact = useMemo(
    () => contacts.find((contact) => contact.id === selectedContactId) || null,
    [contacts, selectedContactId]
  );

  const setView = (nextView: "all" | "my") => {
    const params = new URLSearchParams(searchParams);
    if (nextView === "my") params.set("view", "my");
    else params.delete("view");
    setSearchParams(params, { replace: true });
  };

  const setTab = (next: string) => {
    const params = new URLSearchParams(searchParams);
    params.set("tab", next);
    setSearchParams(params, { replace: true });
  };

  const loadTenants = useCallback(async () => {
    const data = await listTenants();
    setTenants(data.tenants || []);
  }, []);

  const loadTenantDetail = useCallback(async (nextTenantId: string) => {
    const [contactsData, membershipsData, identitiesData] = await Promise.all([
      listContacts(nextTenantId),
      listMemberships(nextTenantId),
      listIdentities(),
    ]);
    setContacts(contactsData.contacts || []);
    setSelectedContactId((current) => {
      if (current && contactsData.contacts.some((contact) => contact.id === current)) return current;
      return contactsData.contacts[0]?.id || "";
    });
    setMemberships(membershipsData.memberships || []);
    setIdentities(identitiesData.identities || []);
    setSelectedIdentity((current) => current || identitiesData.identities?.[0]?.id || "");
    try {
      const tenantBranding = await getTenantBranding(nextTenantId);
      setBranding({
        display_name: tenantBranding.display_name,
        logo_url: tenantBranding.logo_url,
        theme_json: tenantBranding.theme,
      });
      setThemeText(JSON.stringify(tenantBranding.theme || {}, null, 2));
    } catch {
      setBranding({});
      setThemeText("{}");
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      await loadTenants();
      if (tenantId) {
        await loadTenantDetail(tenantId);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [loadTenantDetail, loadTenants, tenantId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!tenantId) {
      const fallback = visibleTenants[0]?.id;
      if (fallback) navigate(`/app/platform/tenants/${fallback}${searchString ? `?${searchString}` : ""}`, { replace: true });
      return;
    }
    void (async () => {
      try {
        setError(null);
        await loadTenantDetail(tenantId);
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, [loadTenantDetail, navigate, searchString, tenantId, visibleTenants]);

  useEffect(() => {
    if (!selectedTenant) {
      setTenantForm(emptyTenantForm);
      return;
    }
    setTenantForm({
      name: selectedTenant.name,
      slug: selectedTenant.slug,
      status: selectedTenant.status,
    });
  }, [selectedTenant]);

  useEffect(() => {
    if (!selectedContact) {
      setContactForm(emptyContactForm);
      return;
    }
    setContactForm({
      name: selectedContact.name,
      email: selectedContact.email ?? "",
      phone: selectedContact.phone ?? "",
      role_title: selectedContact.role_title ?? "",
      status: selectedContact.status,
    });
  }, [selectedContact]);

  const saveTenant = async () => {
    if (!selectedTenant) return;
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      await updateTenant(selectedTenant.id, tenantForm);
      await loadTenants();
      setMessage("Tenant updated.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const suspendTenant = async () => {
    if (!selectedTenant || !window.confirm("Suspend this tenant?")) return;
    try {
      setLoading(true);
      setError(null);
      await deleteTenant(selectedTenant.id);
      await loadTenants();
      setMessage("Tenant suspended.");
      const next = visibleTenants.find((item) => item.id !== selectedTenant.id);
      navigate(next ? `/app/platform/tenants/${next.id}` : "/app/platform/tenants", { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const createTenantHandler = async () => {
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      const created = await createTenant(newTenantForm);
      setCreateTenantOpen(false);
      setNewTenantForm(emptyTenantForm);
      await loadTenants();
      if (created.id) {
        navigate(`/app/platform/tenants/${created.id}`);
      }
      setMessage("Tenant created.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const createContactHandler = async () => {
    if (!selectedTenant) return;
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      const created = await createContact(selectedTenant.id, newContactForm);
      setCreateContactOpen(false);
      setNewContactForm(emptyContactForm);
      await loadTenantDetail(selectedTenant.id);
      if (created?.id) {
        setSelectedContactId(created.id);
        setHighlightedContactId(created.id);
        window.setTimeout(() => setHighlightedContactId(""), 1800);
      }
      setMessage("Contact created.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const saveContact = async () => {
    if (!selectedContactId) return;
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      await updateContact(selectedContactId, contactForm);
      if (selectedTenant) await loadTenantDetail(selectedTenant.id);
      setMessage("Contact updated.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const deactivateContact = async () => {
    if (!selectedContactId || !window.confirm("Deactivate this contact?")) return;
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      await deleteContact(selectedContactId);
      setSelectedContactId("");
      if (selectedTenant) await loadTenantDetail(selectedTenant.id);
      setMessage("Contact deactivated.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const addMember = async () => {
    if (!selectedTenant || !selectedIdentity) return;
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      await createMembership(selectedTenant.id, { user_identity_id: selectedIdentity, role: membershipRole });
      await loadTenantDetail(selectedTenant.id);
      setMessage("Member added.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const updateMember = async (membershipId: string, role: string) => {
    try {
      setError(null);
      setMessage(null);
      await updateMembership(membershipId, { role });
      if (selectedTenant) await loadTenantDetail(selectedTenant.id);
      setMessage("Membership updated.");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const deactivateMember = async (membershipId: string) => {
    if (!window.confirm("Deactivate this membership?")) return;
    try {
      setError(null);
      setMessage(null);
      await deleteMembership(membershipId);
      if (selectedTenant) await loadTenantDetail(selectedTenant.id);
      setMessage("Membership deactivated.");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const saveBranding = async () => {
    if (!selectedTenant) return;
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      let parsedTheme: Record<string, string> | undefined;
      if (themeText.trim()) parsedTheme = JSON.parse(themeText);
      await updateTenantBranding(selectedTenant.id, {
        ...branding,
        theme_json: parsedTheme,
      });
      setMessage("Branding updated.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Tenants</h2>
          <p className="muted">Manage customer organizations.</p>
        </div>
        <div className="inline-actions">
          <Tabs
            ariaLabel="Tenant view"
            value={view}
            onChange={(next) => setView(next as "all" | "my")}
            options={[
              { value: "all", label: "All" },
              { value: "my", label: "Mine" },
            ]}
          />
          <button className="primary" onClick={() => setCreateTenantOpen(true)}>New tenant</button>
          <button className="ghost" onClick={() => void refresh()} disabled={loading}>{loading ? "Refreshing..." : "Refresh"}</button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <div className="layout">
        <section className="card">
          <div className="card-header">
            <h3>{view === "my" ? "My tenants" : "Tenants"}</h3>
          </div>
          <div className="instance-list">
            {visibleTenants.map((tenant) => (
              <button
                key={tenant.id}
                className={`instance-row ${tenantId === tenant.id ? "active" : ""}`}
                onClick={() => navigate(`/app/platform/tenants/${tenant.id}${searchString ? `?${searchString}` : ""}`)}
              >
                <div>
                  <strong>{tenant.name}</strong>
                  <span className="muted small">{tenant.slug}</span>
                  {tenant.membership_role ? <span className="muted small">Role: {tenant.membership_role}</span> : null}
                </div>
                <span className="muted small">{tenant.status}</span>
              </button>
            ))}
            {visibleTenants.length === 0 && <p className="muted">No tenants found for this view.</p>}
          </div>
        </section>

        <section className="card">
          <div className="card-header">
            <h3>Tenant detail</h3>
          </div>
          {selectedTenant ? (
            <>
              <Tabs
                ariaLabel="Tenant detail tabs"
                value={detailTab}
                onChange={setTab}
                options={TENANT_TABS.map((tab) => ({ value: tab.value, label: tab.label }))}
              />

              {detailTab === "overview" ? (
                <>
                  <div className="form-grid" style={{ marginTop: 12 }}>
                    <label>
                      Name
                      <input value={tenantForm.name ?? ""} onChange={(event) => setTenantForm({ ...tenantForm, name: event.target.value })} />
                    </label>
                    <label>
                      Slug
                      <input value={tenantForm.slug ?? ""} onChange={(event) => setTenantForm({ ...tenantForm, slug: event.target.value })} />
                    </label>
                    <label>
                      Status
                      <select value={tenantForm.status ?? "active"} onChange={(event) => setTenantForm({ ...tenantForm, status: event.target.value })}>
                        <option value="active">active</option>
                        <option value="suspended">suspended</option>
                      </select>
                    </label>
                  </div>
                  <div className="inline-actions">
                    <button className="primary" onClick={() => void saveTenant()} disabled={loading}>Save changes</button>
                    <button className="danger" onClick={() => void suspendTenant()} disabled={loading}>Suspend</button>
                  </div>
                </>
              ) : null}

              {detailTab === "contacts" ? (
                <div className="stack" style={{ marginTop: 12 }}>
                  <div className="inline-actions" style={{ justifyContent: "space-between" }}>
                    <h4 style={{ margin: 0 }}>Contacts</h4>
                    <button className="primary sm" onClick={() => setCreateContactOpen(true)}>New contact</button>
                  </div>
                  <div className="layout" style={{ gridTemplateColumns: "minmax(280px, 0.9fr) minmax(320px, 1.1fr)" }}>
                    <section className="card">
                      <div className="instance-list">
                        {contacts.map((contact) => (
                          <button
                            key={contact.id}
                            className={`instance-row ${selectedContactId === contact.id || highlightedContactId === contact.id ? "active" : ""}`}
                            onClick={() => setSelectedContactId(contact.id)}
                          >
                            <div>
                              <strong>{contact.name}</strong>
                              <span className="muted small">{contact.email || "—"}</span>
                            </div>
                            <span className="muted small">{contact.status}</span>
                          </button>
                        ))}
                        {contacts.length === 0 && <p className="muted">No contacts yet.</p>}
                      </div>
                    </section>
                    <section className="card">
                      <div className="card-header"><h4>{selectedContactId ? "Contact detail" : "Select a contact"}</h4></div>
                      {selectedContactId ? (
                        <>
                          <div className="form-grid">
                            <label>Name<input value={contactForm.name ?? ""} onChange={(event) => setContactForm({ ...contactForm, name: event.target.value })} /></label>
                            <label>Email<input value={contactForm.email ?? ""} onChange={(event) => setContactForm({ ...contactForm, email: event.target.value })} /></label>
                            <label>Phone<input value={contactForm.phone ?? ""} onChange={(event) => setContactForm({ ...contactForm, phone: event.target.value })} /></label>
                            <label>Title<input value={contactForm.role_title ?? ""} onChange={(event) => setContactForm({ ...contactForm, role_title: event.target.value })} /></label>
                            <label>Status
                              <select value={contactForm.status ?? "active"} onChange={(event) => setContactForm({ ...contactForm, status: event.target.value })}>
                                <option value="active">active</option>
                                <option value="inactive">inactive</option>
                              </select>
                            </label>
                          </div>
                          <div className="inline-actions">
                            <button className="primary" onClick={() => void saveContact()} disabled={loading}>Save changes</button>
                            <button className="danger" onClick={() => void deactivateContact()} disabled={loading}>Deactivate</button>
                          </div>
                        </>
                      ) : (
                        <p className="muted">Choose a contact from the list.</p>
                      )}
                    </section>
                  </div>
                </div>
              ) : null}

              {detailTab === "members" ? (
                <div className="stack" style={{ marginTop: 12 }}>
                  <div className="form-grid">
                    <label>
                      Identity
                      <select value={selectedIdentity} onChange={(event) => setSelectedIdentity(event.target.value)}>
                        {identities.map((identity) => (
                          <option key={identity.id} value={identity.id}>{identity.display_name || identity.email || identity.subject}</option>
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
                    <button className="primary" onClick={() => void addMember()} disabled={!selectedIdentity}>Add member</button>
                  </div>
                  <div className="instance-list">
                    {memberships.map((membership) => (
                      <div key={membership.id} className="instance-row">
                        <div>
                          <strong>{membership.user_display_name || membership.user_email || membership.user_identity_id}</strong>
                          <span className="muted small">{membership.user_email || ""}</span>
                        </div>
                        <select value={membership.role} onChange={(event) => void updateMember(membership.id, event.target.value)}>
                          <option value="tenant_viewer">tenant_viewer</option>
                          <option value="tenant_operator">tenant_operator</option>
                          <option value="tenant_admin">tenant_admin</option>
                        </select>
                        <button className="ghost" onClick={() => void deactivateMember(membership.id)}>Deactivate</button>
                      </div>
                    ))}
                    {memberships.length === 0 && <p className="muted">No memberships yet.</p>}
                  </div>
                </div>
              ) : null}

              {detailTab === "branding" ? (
                <div className="stack" style={{ marginTop: 12 }}>
                  <div className="form-grid">
                    <label>Display name<input value={branding.display_name ?? ""} onChange={(event) => setBranding({ ...branding, display_name: event.target.value })} /></label>
                    <label>Logo URL<input value={branding.logo_url ?? ""} onChange={(event) => setBranding({ ...branding, logo_url: event.target.value })} /></label>
                    <label>Primary color<input value={branding.primary_color ?? ""} onChange={(event) => setBranding({ ...branding, primary_color: event.target.value })} /></label>
                    <label>Secondary color<input value={branding.secondary_color ?? ""} onChange={(event) => setBranding({ ...branding, secondary_color: event.target.value })} /></label>
                    <label className="form-full">Theme JSON<textarea rows={6} value={themeText} onChange={(event) => setThemeText(event.target.value)} /></label>
                  </div>
                  <div className="inline-actions"><button className="primary" onClick={() => void saveBranding()}>Save branding</button></div>
                </div>
              ) : null}
            </>
          ) : (
            <p className="muted">Select a tenant to view details.</p>
          )}
        </section>
      </div>

      {createTenantOpen && (
        <div className="modal-backdrop" onClick={loading ? undefined : () => setCreateTenantOpen(false)}>
          <section className="modal" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <h3>New tenant</h3>
            <div className="form-grid">
              <label>Name<input value={newTenantForm.name ?? ""} onChange={(event) => setNewTenantForm({ ...newTenantForm, name: event.target.value })} /></label>
              <label>Slug<input value={newTenantForm.slug ?? ""} onChange={(event) => setNewTenantForm({ ...newTenantForm, slug: event.target.value })} /></label>
              <label>Status
                <select value={newTenantForm.status ?? "active"} onChange={(event) => setNewTenantForm({ ...newTenantForm, status: event.target.value })}>
                  <option value="active">active</option>
                  <option value="suspended">suspended</option>
                </select>
              </label>
            </div>
            <div className="inline-actions" style={{ marginTop: 12 }}>
              <button className="primary" onClick={() => void createTenantHandler()} disabled={loading || !newTenantForm.name || !newTenantForm.slug}>{loading ? "Creating..." : "Create tenant"}</button>
              <button className="ghost" onClick={() => setCreateTenantOpen(false)} disabled={loading}>Cancel</button>
            </div>
          </section>
        </div>
      )}

      {createContactOpen && (
        <div className="modal-backdrop" onClick={loading ? undefined : () => setCreateContactOpen(false)}>
          <section className="modal" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <h3>New contact</h3>
            <div className="form-grid">
              <label>Name<input value={newContactForm.name ?? ""} onChange={(event) => setNewContactForm({ ...newContactForm, name: event.target.value })} /></label>
              <label>Email<input value={newContactForm.email ?? ""} onChange={(event) => setNewContactForm({ ...newContactForm, email: event.target.value })} /></label>
              <label>Phone<input value={newContactForm.phone ?? ""} onChange={(event) => setNewContactForm({ ...newContactForm, phone: event.target.value })} /></label>
              <label>Title<input value={newContactForm.role_title ?? ""} onChange={(event) => setNewContactForm({ ...newContactForm, role_title: event.target.value })} /></label>
              <label>Status
                <select value={newContactForm.status ?? "active"} onChange={(event) => setNewContactForm({ ...newContactForm, status: event.target.value })}>
                  <option value="active">active</option>
                  <option value="inactive">inactive</option>
                </select>
              </label>
            </div>
            <div className="inline-actions">
              <button className="primary" onClick={() => void createContactHandler()} disabled={loading || !newContactForm.name}>{loading ? "Creating..." : "Create contact"}</button>
              <button className="ghost" onClick={() => setCreateContactOpen(false)} disabled={loading}>Cancel</button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
